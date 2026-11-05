import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import {
  ArrowRight,
  ArrowUpRight,
  Bot,
  Check,
  Gamepad2,
  Send,
  Sparkles,
  Trophy,
  UserRound,
  Users,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { api, post, remove, type Schema } from "../../api/client";
import { socketURL, type SocketEvent } from "../../app/live";
import {
  Badge,
  Button,
  ErrorNotice,
  Loading,
  PageTitle,
  useAction,
} from "../../components/ui";

export function GameLobby() {
  const { t } = useTranslation();
  const [queued, setQueued] = useState(
    sessionStorage.getItem("wozu.queued") === "yes",
  );
  const previous = sessionStorage.getItem("wozu.room");
  const queue = useAction(async () => {
    if (queued) {
      await remove("/game/queue/leave");
      sessionStorage.removeItem("wozu.queued");
      setQueued(false);
    } else {
      await post("/game/queue/join");
      sessionStorage.setItem("wozu.queued", "yes");
      setQueued(true);
    }
  });
  return (
    <>
      <PageTitle
        eyebrow="A CURIOUS LITTLE BREAK"
        title="Can you spot the human?"
        description="Meet strangers. Follow your instincts. Question everything."
      />
      <section className="game-hero">
        <div className="game-hero-copy">
          <Badge tone="game">
            <Sparkles size={14} />
            {t("THE SOCIAL DEDUCTION GAME")}
          </Badge>
          <h1>
            Turing
            <br />
            <em>
              Duel<span>✳</span>
            </em>
          </h1>
          <p>
            {t(
              "Some of us are human. Some of us aren’t. A conversation is all you have to tell the difference.",
            )}
          </p>
          <Button
            busy={queue.isPending}
            onClick={() => queue.mutate()}
            className="game-start"
          >
            {queued ? (
              <>
                <span className="pulse-dot" />
                {t("Leave matchmaking")}
              </>
            ) : (
              <>
                {t("Find a room")}
                <ArrowUpRight size={19} />
              </>
            )}
          </Button>
          {queued && (
            <p className="queue-note" role="status">
              {t(
                "Finding your people (and perhaps a bot). Keep this page open.",
              )}
            </p>
          )}
          <ErrorNotice error={queue.error} />
          <div className="game-specs">
            <span>
              <Users size={16} />
              2–5 {t("players")}
            </span>
            <span>
              <Gamepad2 size={16} />
              {t("Real-time conversations")}
            </span>
          </div>
        </div>
        <div className="game-art" aria-hidden="true">
          <div className="game-art-ring" />
          <span className="game-floating-star">✦</span>
          <div className="game-face face-human">
            <span className="face-eyes">• •</span>
            <span className="face-smile">⌣</span>
            <span className="face-label">HUMAN?</span>
          </div>
          <div className="game-face face-bot">
            <span className="face-antenna" />
            <span className="bot-eyes">
              <i />
              <i />
            </span>
            <span className="bot-mouth" />
            <span className="face-label">OR NOT?</span>
          </div>
          <div className="game-chat-pill">
            “That sounds very human.” <span>…</span>
          </div>
        </div>
      </section>
      <div className="game-steps">
        {[
          {
            n: "01",
            title: "Join the conversation.",
            body: "Get matched into a room. Everyone gets an anonymous identity.",
          },
          {
            n: "02",
            title: "Ask the unexpected.",
            body: "Chat, listen, and look for clues. Bots are trying to blend in.",
          },
          {
            n: "03",
            title: "Trust your instincts.",
            body: "Vote human or bot. Correct guesses earn points. Then comes the reveal.",
          },
        ].map((s) => (
          <article key={s.n}>
            <span>{s.n}</span>
            <h3>{t(s.title)}</h3>
            <p>{t(s.body)}</p>
          </article>
        ))}
      </div>
      <div className="game-bottom">
        <Link className="text-link" to="/game/rules">
          {t("Read the full rules")}
          <ArrowRight size={16} />
        </Link>
        {previous && (
          <Link className="button secondary" to={`/game/rooms/${previous}`}>
            {t("Return to last room")}
            <ArrowUpRight size={16} />
          </Link>
        )}
      </div>
    </>
  );
}
type Room = Schema["RoomOut"] & {
  self_participant_id?: number;
  phase_ends_at?: string | null;
  messages?: GameMessage[];
  my_votes?: Record<number, string>;
};
type GameMessage = {
  id: number;
  room_id?: number;
  participant_id: number;
  display_label: string;
  text: string;
};
export function GameRoom() {
  const { id } = useParams();
  const { t } = useTranslation();
  const [text, setText] = useState("");
  const [messages, setMessages] = useState<GameMessage[]>([]);
  const [connected, setConnected] = useState(false);
  const [reconnected, setReconnected] = useState(false);
  const [now, setNow] = useState(Date.now());
  const [votes, setVotes] = useState<Record<number, string>>({});
  const socket = useRef<WebSocket | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const room = useQuery({
    queryKey: ["room", id],
    queryFn: () => api<Room>(`/game/rooms/${id}`),
    refetchInterval: (q) => (q.state.data?.state === "finished" ? false : 3000),
  });
  const results = useQuery({
    queryKey: ["results", id],
    queryFn: () => api<Schema["RoomResultsOut"]>(`/game/rooms/${id}/results`),
    enabled: room.data?.state === "finished",
  });
  const vote = useAction(
    async ({ target, guess }: { target: number; guess: string }) => {
      await post(`/game/rooms/${id}/votes`, {
        target_participant_id: target,
        guess,
      });
      setVotes((v) => ({ ...v, [target]: guess }));
    },
  );
  const [sendError, setSendError] = useState<unknown>(null);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    let stopped = false;
    let retry: ReturnType<typeof setTimeout>;
    let attempt = 0;
    setMessages([]);
    setVotes({});
    async function connect() {
      try {
        const url = await socketURL(id);
        if (stopped) return;
        const ws = new WebSocket(url);
        socket.current = ws;
        ws.onopen = () => {
          setConnected(true);
          if (attempt > 0) setReconnected(true);
          attempt = 0;
        };
        ws.onmessage = (e) => {
          let event: SocketEvent;
          try {
            event = JSON.parse(e.data) as SocketEvent;
          } catch {
            return;
          }
          if (event.type === "game_message") {
            const msg = event.payload as GameMessage;
            if (msg.room_id !== undefined && String(msg.room_id) !== id) return;
            setMessages((prev) =>
              prev.some((p) => p.id === msg.id) ? prev : [...prev, msg],
            );
          }
        };
        ws.onclose = () => {
          if (stopped) return;
          setConnected(false);
          retry = setTimeout(
            () => void connect(),
            Math.min(1000 * 2 ** attempt++, 10000),
          );
        };
        ws.onerror = () => ws.close();
      } catch {
        if (!stopped) retry = setTimeout(() => void connect(), 5000);
      }
    }
    void connect();
    return () => {
      stopped = true;
      clearTimeout(retry);
      socket.current?.close();
    };
  }, [id]);
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "nearest" });
  }, [messages.length]);
  if (room.isPending) return <Loading />;
  if (!room.data) return <ErrorNotice error={room.error} />;
  const r = room.data;
  const visibleMessages = [
    ...new Map(
      [...(r.messages || []), ...messages].map((m) => [m.id, m]),
    ).values(),
  ].sort((a, b) => a.id - b.id);
  const recordedVotes = { ...r.my_votes, ...votes };
  const remaining = r.phase_ends_at
    ? Math.max(0, Math.ceil((new Date(r.phase_ends_at).getTime() - now) / 1000))
    : null;
  return (
    <>
      <PageTitle
        eyebrow={`TURING DUEL / ROOM ${id}`}
        title={
          r.state === "finished"
            ? "The masks come off."
            : r.state === "voting"
              ? "Time to trust your instincts."
              : "Everyone has a story. Who’s human?"
        }
        action={
          <Badge tone={connected ? "" : "orange"}>
            {t(connected ? "Connected" : "Reconnecting")}
          </Badge>
        }
      />
      <div className="room-layout">
        <section className="panel room-conversation">
          <div className="section-heading">
            <h2>{t("The conversation")}</h2>
            <Badge>{t(r.state)}</Badge>
            {remaining !== null && (
              <span className="phase-timer" aria-label={t("Time remaining")}>
                {Math.floor(remaining / 60)}:
                {String(remaining % 60).padStart(2, "0")}
              </span>
            )}
          </div>
          {reconnected && !r.messages && (
            <p className="notice">
              {t("You reconnected. Earlier messages may be missing.")}
            </p>
          )}
          <div className="game-messages">
            {visibleMessages.length === 0 && (
              <div className="empty">
                <Sparkles size={30} />
                <h3>{t("Ask a question nobody expects.")}</h3>
                <p>
                  {t("Stay curious. Everyone is anonymous until the reveal.")}
                </p>
              </div>
            )}
            {visibleMessages.map((m) => (
              <article className="game-message" key={m.id}>
                <span
                  className={`participant-dot color-${m.participant_id % 5}`}
                >
                  <UserRound size={16} />
                </span>
                <div>
                  <strong>{m.display_label}</strong>
                  <p dir="auto">{m.text}</p>
                </div>
              </article>
            ))}
            <div ref={bottom} />
          </div>
          <ErrorNotice error={sendError} />
          <form
            className="message-composer"
            onSubmit={(e) => {
              e.preventDefault();
              if (socket.current?.readyState !== WebSocket.OPEN) {
                setSendError(
                  new Error(t("Wait for the connection to recover.")),
                );
                return;
              }
              socket.current.send(
                JSON.stringify({ type: "chat_message", text: text.trim() }),
              );
              setText("");
              setSendError(null);
            }}
          >
            <input
              aria-label={t("Room message")}
              placeholder={t("Ask something unexpected…")}
              maxLength={4000}
              value={text}
              onChange={(e) => setText(e.target.value)}
              disabled={r.state !== "discussion" || !connected}
            />
            <Button
              type="submit"
              aria-label={t("Send message")}
              disabled={!text.trim() || r.state !== "discussion" || !connected}
            >
              <Send size={18} />
            </Button>
          </form>
        </section>
        <aside className="panel participants">
          <h2>{t("The usual suspects")}</h2>
          <p className="muted small-text">
            {t(
              r.state === "voting"
                ? "Choose human or bot for each other player."
                : "Look for clues. Voting opens after the discussion.",
            )}
          </p>
          <ErrorNotice error={vote.error || results.error} />
          {r.participants.map((p) => (
            <article className="participant" key={p.id}>
              <span className={`participant-dot color-${p.id % 5}`}>
                <UserRound size={20} />
              </span>
              <div>
                <strong>
                  {p.display_label}
                  {p.id === r.self_participant_id ? ` (${t("You")})` : ""}
                </strong>
                {r.state === "voting" &&
                  p.id !== r.self_participant_id &&
                  (recordedVotes[p.id] ? (
                    <Badge>
                      <Check size={12} />
                      {t(recordedVotes[p.id])}
                    </Badge>
                  ) : (
                    <div className="vote-buttons">
                      <button
                        disabled={vote.isPending}
                        onClick={() =>
                          vote.mutate({ target: p.id, guess: "human" })
                        }
                      >
                        <UserRound size={14} />
                        {t("Human")}
                      </button>
                      <button
                        disabled={vote.isPending}
                        onClick={() =>
                          vote.mutate({ target: p.id, guess: "bot" })
                        }
                      >
                        <Bot size={14} />
                        {t("Bot")}
                      </button>
                    </div>
                  ))}
              </div>
            </article>
          ))}
          {results.data && (
            <div className="results">
              <Trophy size={28} />
              <h3>{t("The reveal")}</h3>
              {results.data.participants.map((p) => (
                <div className="result-line" key={p.participant_id}>
                  <strong>{p.display_label}</strong>
                  <Badge>{t(p.is_bot ? "Bot" : "Human")}</Badge>
                  <span>
                    {p.is_bot
                      ? `${Math.round((p.deception_rate || 0) * 100)}%`
                      : p.score}{" "}
                    {t(p.is_bot ? "fooled" : "points")}
                  </span>
                </div>
              ))}
              <Link className="button primary full" to="/game">
                {t("Play again")}
                <ArrowRight size={16} />
              </Link>
            </div>
          )}
          <Link className="text-link" to="/game/rules">
            {t("How to play")}
            <ArrowUpRight size={15} />
          </Link>
        </aside>
      </div>
    </>
  );
}
export function GameRules() {
  const { t } = useTranslation();
  return (
    <>
      <PageTitle
        eyebrow="TURING DUEL / THE RULES"
        title="A little curiosity goes a long way."
      />
      <article className="panel prose narrow-panel">
        <h2>{t("How to play")}</h2>
        <p>
          {t(
            "Join matchmaking and wait for a room of 2–5 participants. Rooms may include bots. Everyone appears as an anonymous player.",
          )}
        </p>
        <h3>{t("Talk. Listen. Question.")}</h3>
        <p>
          {t(
            "Discussion lasts 120 seconds. Send messages, ask questions, and decide which other participants are human. The server controls each phase.",
          )}
        </p>
        <h3>{t("Make your call.")}</h3>
        <p>
          {t(
            "You have 45 seconds to vote human or bot for the other participants. Each correct guess earns +1, each wrong guess earns −1, and an unanswered guess earns 0. Votes cannot be changed.",
          )}
        </p>
        <h3>{t("The reveal")}</h3>
        <p>
          {t(
            "The highest human score wins. Equal top scores are a draw. Bot deception rate shows how often a bot was mistaken for a human.",
          )}
        </p>
        <p className="notice">
          {t(
            "Stay on the room page until the reveal. If your connection drops, reconnect to resume the conversation.",
          )}
        </p>
        <Link className="button primary" to="/game">
          {t("Let’s play")}
          <ArrowRight size={17} />
        </Link>
      </article>
    </>
  );
}
