import "../../i18n";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ApiError, getAccessToken, onAuthChange } from "../../api/client";
import { useWsEvent, wsClient } from "../../api/ws";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { gameApi } from "./api";
import { GAME_RULES_PATH } from "./rules/paths";
import type {
  GameParticipantEventPayload,
  GameRoom,
  GameRoomClosedEventPayload,
  GameStartedEventPayload,
} from "./types";
import "./game.css";

function computeRemainingSeconds(expiresAt: string | null): number {
  if (!expiresAt) return 0;
  const targetMs = Date.parse(expiresAt);
  if (Number.isNaN(targetMs)) return 0;
  return Math.max(0, Math.ceil((targetMs - Date.now()) / 1000));
}

function formatCountdown(totalSeconds: number): string {
  const mins = Math.floor(totalSeconds / 60);
  const secs = totalSeconds % 60;
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

export function GameLobbyPage() {
  const { t } = useTranslation("game");
  const navigate = useNavigate();

  const [room, setRoom] = useState<GameRoom | null>(null);
  const [joining, setJoining] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [startPressed, setStartPressed] = useState(false);
  const [error, setError] = useState("");
  const [closedNotice, setClosedNotice] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState(0);

  // Track whether we are still in a waiting room so unmounting leaves cleanly,
  // while transitioning into an active game room does NOT leave the room.
  const waitingRoomIdRef = useRef<number | null>(null);
  const gameStartedRef = useRef(false);
  const lastAccessTokenRef = useRef<string | null>(getAccessToken());

  const syncWaitingRef = useCallback((next: GameRoom | null) => {
    waitingRoomIdRef.current =
      next && next.state === "waiting" ? next.id : null;
  }, []);

  const enterActiveRoom = useCallback(
    (roomId: number) => {
      gameStartedRef.current = true;
      waitingRoomIdRef.current = null;
      setRoom(null);
      navigate(`/game/rooms/${roomId}`);
    },
    [navigate],
  );

  // Room countdown from room_expires_at (single 3-minute timer, never restarted).
  useEffect(() => {
    const expiresAt = room?.room_expires_at ?? null;
    if (!expiresAt) {
      setSecondsLeft(0);
      return;
    }
    setSecondsLeft(computeRemainingSeconds(expiresAt));
    const timer = setInterval(() => {
      setSecondsLeft(computeRemainingSeconds(expiresAt));
    }, 1000);
    return () => clearInterval(timer);
  }, [room?.room_expires_at]);

  // Leave waiting room on unmount (navigating away from /game) or browser unload/hide.
  // Also clear room state on back/forward cache restore (pageshow with persisted).
  useEffect(() => {
    const leaveIfWaiting = () => {
      if (waitingRoomIdRef.current !== null && !gameStartedRef.current) {
        waitingRoomIdRef.current = null;
        setRoom(null);
        setStartPressed(false);
        void gameApi.leaveQueue().catch(() => {
          /* Best-effort cleanup on leave. */
        });
      }
    };
    const handlePageShow = (event: PageTransitionEvent) => {
      if (event.persisted && !gameStartedRef.current) {
        waitingRoomIdRef.current = null;
        setRoom(null);
        setStartPressed(false);
      }
    };
    window.addEventListener("pagehide", leaveIfWaiting);
    window.addEventListener("pageshow", handlePageShow);
    return () => {
      window.removeEventListener("pagehide", leaveIfWaiting);
      window.removeEventListener("pageshow", handlePageShow);
      leaveIfWaiting();
    };
  }, []);

  // Leave waiting room cleanly when auth session clears (logout).
  useEffect(() => {
    return onAuthChange((hasToken) => {
      if (hasToken) {
        lastAccessTokenRef.current = getAccessToken();
        return;
      }
      const token = lastAccessTokenRef.current;
      lastAccessTokenRef.current = null;
      if (waitingRoomIdRef.current !== null && !gameStartedRef.current) {
        waitingRoomIdRef.current = null;
        setRoom(null);
        setStartPressed(false);
        void gameApi.leaveQueue(token ?? undefined).catch(() => {
          /* Best-effort leave on logout. */
        });
      }
    });
  }, []);

  // Refresh waiting room state after WebSocket reconnection so missed events sync.
  useEffect(() => {
    let previousState = wsClient.getState();
    return wsClient.onStateChange((nextState) => {
      const reconnected =
        previousState !== "connected" && nextState === "connected";
      previousState = nextState;
      const activeId = waitingRoomIdRef.current;
      if (!reconnected || activeId === null || gameStartedRef.current) return;
      void gameApi
        .getRoom(activeId)
        .then((latest) => {
          if (waitingRoomIdRef.current !== activeId) return;
          if (latest.state === "discussion" || latest.state === "voting") {
            enterActiveRoom(latest.id);
          } else if (latest.state === "closed" || latest.state === "finished") {
            syncWaitingRef(null);
            setRoom(null);
            setStartPressed(false);
            setClosedNotice(true);
          } else {
            setRoom(latest);
          }
        })
        .catch((err: unknown) => {
          // If server answers 403 or 404 (e.g. participant was removed or room was destroyed),
          // cleanly clear waiting state and return to lobby.
          if (
            err instanceof ApiError &&
            (err.status === 403 || err.status === 404)
          ) {
            syncWaitingRef(null);
            setRoom(null);
            setStartPressed(false);
          }
        });
    });
  }, [enterActiveRoom, syncWaitingRef]);

  const handleParticipantJoined = useCallback(
    (payload: GameParticipantEventPayload) => {
      if (!payload || !payload.participant) return;
      setRoom((current) => {
        if (!current || current.id !== payload.room_id) return current;
        const alreadyListed = current.participants.some(
          (item) => item.id === payload.participant.id,
        );
        const participants = (
          alreadyListed
            ? current.participants
            : [
                ...current.participants,
                {
                  id: payload.participant.id,
                  display_label: payload.participant.display_label,
                  is_you: payload.participant.id === current.my_participant_id,
                },
              ]
        )
          .slice()
          .sort((a, b) =>
            a.display_label.localeCompare(b.display_label, undefined, {
              numeric: true,
            }),
          );
        return {
          ...current,
          participants,
          participant_count: payload.participant_count,
          room_expires_at: payload.room_expires_at ?? current.room_expires_at,
        };
      });
    },
    [],
  );

  const handleParticipantLeft = useCallback(
    (payload: GameParticipantEventPayload) => {
      if (!payload || !payload.participant) return;
      setRoom((current) => {
        if (!current || current.id !== payload.room_id) return current;
        const participants = current.participants.filter(
          (item) => item.id !== payload.participant.id,
        );
        return {
          ...current,
          participants,
          participant_count: payload.participant_count,
          room_expires_at: payload.room_expires_at ?? current.room_expires_at,
        };
      });
    },
    [],
  );

  const handleGameStarted = useCallback(
    (payload: GameStartedEventPayload) => {
      if (!payload) return;
      if (waitingRoomIdRef.current === payload.room_id) {
        enterActiveRoom(payload.room_id);
      }
    },
    [enterActiveRoom],
  );

  const handleRoomClosed = useCallback(
    (payload: GameRoomClosedEventPayload) => {
      if (!payload) return;
      if (waitingRoomIdRef.current === payload.room_id) {
        syncWaitingRef(null);
        setRoom(null);
        setStartPressed(false);
        setError("");
        setClosedNotice(true);
      }
    },
    [syncWaitingRef],
  );

  useWsEvent<GameParticipantEventPayload>(
    "game_participant_joined",
    handleParticipantJoined,
  );
  useWsEvent<GameParticipantEventPayload>(
    "game_participant_left",
    handleParticipantLeft,
  );
  useWsEvent<GameStartedEventPayload>("game_started", handleGameStarted);
  useWsEvent<GameRoomClosedEventPayload>("game_room_closed", handleRoomClosed);

  async function handleFindGame() {
    if (joining) return;
    setJoining(true);
    setError("");
    setClosedNotice(false);
    setStartPressed(false);
    gameStartedRef.current = false;
    try {
      const active = await gameApi.getActiveRoom().catch(() => null);
      if (
        active &&
        (active.state === "discussion" || active.state === "voting")
      ) {
        enterActiveRoom(active.id);
        return;
      }
      const joined = await gameApi.joinQueue();
      lastAccessTokenRef.current = getAccessToken();
      try {
        const loaded = await gameApi.getRoom(joined.room_id);
        if (loaded.state === "discussion" || loaded.state === "voting") {
          enterActiveRoom(loaded.id);
          return;
        }
        if (loaded.state === "closed" || loaded.state === "finished") {
          setClosedNotice(true);
          return;
        }
        syncWaitingRef(loaded);
        setRoom(loaded);
      } catch (getErr) {
        void gameApi.leaveQueue().catch(() => {});
        throw getErr;
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        try {
          const active = await gameApi.getActiveRoom();
          if (
            active &&
            (active.state === "discussion" || active.state === "voting")
          ) {
            enterActiveRoom(active.id);
            return;
          }
        } catch {
          // ignore error and show alreadyInRoom
        }
        setError(t("alreadyInRoom"));
      } else {
        setError(t("joinError"));
      }
    } finally {
      setJoining(false);
    }
  }

  async function handleLeaveRoom() {
    if (leaving) return;
    setLeaving(true);
    setError("");
    try {
      await gameApi.leaveQueue();
      syncWaitingRef(null);
      setRoom(null);
      setStartPressed(false);
    } catch {
      setError(t("leaveError"));
    } finally {
      setLeaving(false);
    }
  }

  async function handleStartNow() {
    if (!room || startPressed) return;
    setStartPressed(true);
    setError("");
    try {
      const updated = await gameApi.startRoom(room.id);
      if (updated.state === "discussion" || updated.state === "voting") {
        enterActiveRoom(updated.id);
      }
    } catch (err) {
      // Losing a concurrent Start now race (409 after another player started) is harmless.
      if (err instanceof ApiError && err.status === 409) {
        try {
          const latest = await gameApi.getRoom(room.id);
          if (latest.state === "discussion" || latest.state === "voting") {
            enterActiveRoom(latest.id);
            return;
          }
          setRoom(latest);
          setStartPressed(false);
          return;
        } catch {
          // Wait for game_started / game_room_closed if refresh failed.
          return;
        }
      }
      setStartPressed(false);
      setError(t("startError"));
    }
  }

  const canStartNow =
    room !== null &&
    room.state === "waiting" &&
    room.participant_count >= 2 &&
    room.participant_count <= 4;

  return (
    <section className="game-lobby-page">
      <header className="game-lobby-heading">
        <p className="eyebrow">{t("eyebrow")}</p>
        <h1>{t("title")}</h1>
        <p>{t("intro")}</p>
      </header>

      {room ? (
        <section
          className="game-card-surface"
          aria-labelledby="waiting-room-title"
          data-testid="game-waiting-room"
        >
          <div className="game-waiting-header">
            <div>
              <p className="eyebrow">{t("waitingEyebrow")}</p>
              <h2 id="waiting-room-title">{t("waitingTitle")}</h2>
            </div>
            <div className="game-waiting-stats">
              <Badge variant="info" size="md" data-testid="participant-count">
                <bdi>
                  {t("participantCount", {
                    count: room.participant_count,
                    target: room.target_size,
                  })}
                </bdi>
              </Badge>
              <span
                className="game-timer-pill"
                aria-label={t("timeRemaining", {
                  time: formatCountdown(secondsLeft),
                })}
                data-testid="room-countdown"
              >
                {formatCountdown(secondsLeft)}
              </span>
            </div>
          </div>

          <p className="game-waiting-hint">{t("waitingNoChat")}</p>

          <ul className="game-seat-list" data-testid="participant-list">
            {room.participants.map((participant) => (
              <li
                key={participant.id}
                className="game-seat"
                data-testid={`participant-seat-${participant.id}`}
              >
                <span>{participant.display_label}</span>
                {participant.is_you && (
                  <Badge variant="lime" size="sm">
                    {t("youMarker")}
                  </Badge>
                )}
              </li>
            ))}
          </ul>

          {error && (
            <p role="alert" className="game-error">
              {error}
            </p>
          )}

          <div className="game-waiting-actions">
            {canStartNow && (
              <Button
                type="button"
                variant="lime"
                disabled={startPressed}
                isLoading={startPressed}
                onClick={() => void handleStartNow()}
                data-testid="start-now-btn"
              >
                {t(startPressed ? "startingGame" : "startNow")}
              </Button>
            )}
            <Button
              type="button"
              variant="outline"
              disabled={leaving}
              isLoading={leaving}
              onClick={() => void handleLeaveRoom()}
              data-testid="leave-room-btn"
            >
              {t(leaving ? "leavingRoom" : "leaveRoom")}
            </Button>
          </div>

          <p className="game-waiting-hint">
            {t(canStartNow ? "startHint" : "waitingForSecond")}
          </p>
        </section>
      ) : (
        <div className="game-lobby-grid">
          <section className="game-card-dark" aria-labelledby="rules-summary">
            <h2 id="rules-summary">{t("rulesTitle")}</h2>
            <ul className="game-rules-list">
              <li>{t("ruleAnonymous")}</li>
              <li>{t("ruleWaiting")}</li>
              <li>{t("ruleDiscussion")}</li>
            </ul>
            <Link className="game-rules-link" to={GAME_RULES_PATH}>
              {t("readFullRules")}
            </Link>
          </section>

          <section className="game-card-surface game-cta-panel">
            {closedNotice && (
              <p
                role="status"
                className="game-notice"
                data-testid="room-closed-notice"
              >
                {t("roomClosedNotice")}
              </p>
            )}
            {error && (
              <p role="alert" className="game-error">
                {error}
              </p>
            )}
            <Button
              type="button"
              variant="lime"
              size="lg"
              isLoading={joining}
              disabled={joining}
              onClick={() => void handleFindGame()}
              data-testid="find-game-btn"
            >
              {t(joining ? "findingGame" : "findGame")}
            </Button>
          </section>
        </div>
      )}
    </section>
  );
}
