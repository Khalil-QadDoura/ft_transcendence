import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { accessToken, backendMode, post } from "../api/client";
export type SocketEvent = { type: string; payload?: Record<string, unknown> };
export async function socketURL(gameRoom?: string) {
  const path = gameRoom
    ? backendMode === "team"
      ? "/ws/game"
      : "/game/ws"
    : "/ws";
  const url = new URL(path, window.location.href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  if (backendMode === "team") {
    const result = await post<{ ticket: string }>("/ws/ticket");
    url.searchParams.set("ticket", result.ticket);
  } else {
    const token = await accessToken();
    if (!token) throw new Error("Sign in required");
    url.searchParams.set("token", token);
  }
  if (gameRoom) url.searchParams.set("room_id", gameRoom);
  return url.toString();
}
export function useLiveEvents(enabled: boolean) {
  const [state, setState] = useState("connecting");
  const client = useQueryClient();
  const navigate = useNavigate();
  useEffect(() => {
    if (!enabled) return;
    let stopped = false;
    let socket: WebSocket | undefined;
    let timer: ReturnType<typeof setTimeout>;
    let heartbeat: ReturnType<typeof setInterval>;
    let attempts = 0;
    async function connect() {
      try {
        const url = await socketURL();
        if (stopped) return;
        socket = new WebSocket(url);
        socket.onopen = () => {
          attempts = 0;
          setState("connected");
          for (const key of [
            "conversations",
            "messages",
            "friends",
            "unread",
            "videos",
            "room",
          ])
            void client.invalidateQueries({ queryKey: [key] });
          heartbeat = setInterval(
            () =>
              socket?.readyState === WebSocket.OPEN &&
              socket.send(JSON.stringify({ type: "ping" })),
            25000,
          );
        };
        socket.onmessage = (e) => {
          let event: SocketEvent;
          try {
            event = JSON.parse(e.data) as SocketEvent;
          } catch {
            return;
          }
          if (
            event.type === "game_room_formed" &&
            typeof event.payload?.room_id === "number"
          ) {
            sessionStorage.setItem("wozu.room", String(event.payload.room_id));
            sessionStorage.removeItem("wozu.queued");
            navigate(`/game/rooms/${event.payload.room_id}`);
          }
          if (
            [
              "message",
              "message_status",
              "message_updated",
              "message_deleted",
              "conversation_updated",
            ].includes(event.type)
          )
            for (const key of ["conversations", "messages", "unread"])
              void client.invalidateQueries({ queryKey: [key] });
          if (event.type === "presence")
            void client.invalidateQueries({ queryKey: ["friends"] });
          if (event.type === "video_moderated")
            void client.invalidateQueries({ queryKey: ["videos"] });
        };
        socket.onclose = () => {
          clearInterval(heartbeat);
          if (!stopped) {
            setState("reconnecting");
            timer = setTimeout(
              () => void connect(),
              [1000, 2000, 5000, 10000][Math.min(attempts++, 3)],
            );
          }
        };
        socket.onerror = () => socket?.close();
      } catch {
        if (!stopped) {
          setState("reconnecting");
          timer = setTimeout(() => void connect(), 10000);
        }
      }
    }
    void connect();
    return () => {
      stopped = true;
      clearTimeout(timer);
      clearInterval(heartbeat);
      socket?.close();
    };
  }, [enabled, client, navigate]);
  return state;
}
