import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  WebSocketClient,
  useWsEvent,
  type WsConnectionState,
} from "../../api/ws";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  Spinner,
} from "../../components";
import { useText } from "../../i18n/useText";
import { gameApi } from "./api";
import { GAME_RULES_PATH } from "./rules/paths";
import type {
  GameChatMessage,
  GamePhaseFinishedEventPayload,
  GamePhaseVotingEventPayload,
  GameResultsResponse,
  GameRoom,
  GameSnapshotPayload,
  VoteGuess,
} from "./types";
import "./game.css";

function dedupeMessages(
  existing: GameChatMessage[],
  incoming: GameChatMessage[],
): GameChatMessage[] {
  const seen = new Set<number>();
  const merged: GameChatMessage[] = [];
  for (const msg of [...existing, ...incoming]) {
    if (!seen.has(msg.id)) {
      seen.add(msg.id);
      merged.push(msg);
    }
  }
  return merged.sort((a, b) => a.id - b.id);
}

export const GameRoomPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const roomId = Number(id);
  const { t } = useText();
  const navigate = useNavigate();

  const [room, setRoom] = useState<GameRoom | null>(null);
  const [messages, setMessages] = useState<GameChatMessage[]>([]);
  const [votes, setVotes] = useState<Record<number, VoteGuess>>({});
  const [savingVotes, setSavingVotes] = useState<Record<number, boolean>>({});
  const [voteError, setVoteError] = useState<string | null>(null);
  const [results, setResults] = useState<GameResultsResponse | null>(null);

  const [loading, setLoading] = useState(true);
  const [loadingResults, setLoadingResults] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [newMessage, setNewMessage] = useState("");
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);
  const [wsState, setWsState] = useState<WsConnectionState>("connected");

  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Dedicated room WebSocket client
  const roomWs = useMemo(() => {
    if (!roomId || isNaN(roomId)) return null;
    const protocol =
      typeof window !== "undefined" && window.location.protocol === "https:"
        ? "wss:"
        : "ws:";
    const host =
      typeof window !== "undefined" ? window.location.host : "localhost";
    return new WebSocketClient({
      url: `${protocol}//${host}/ws/game?room_id=${roomId}`,
    });
  }, [roomId]);

  const loadResults = useCallback(
    async (signal?: AbortSignal) => {
      if (!roomId || isNaN(roomId)) return;
      setLoadingResults(true);
      try {
        const res = await gameApi.getResults(roomId, signal);
        setResults(res);
      } catch {
        if (!signal?.aborted) {
          setVoteError(t("game:room.loadResultsError"));
        }
      } finally {
        if (!signal?.aborted) {
          setLoadingResults(false);
        }
      }
    },
    [roomId, t],
  );

  // Load initial room data
  const loadRoom = useCallback(
    async (signal?: AbortSignal) => {
      if (!roomId || isNaN(roomId)) {
        setError(t("game:room.roomNotFound"));
        setLoading(false);
        return;
      }
      try {
        const [data, messagesRes] = await Promise.all([
          gameApi.getRoom(roomId, signal),
          gameApi.getRoomMessages(roomId, { signal }).catch(() => null),
        ]);
        setRoom(data);
        if (messagesRes?.items) {
          setMessages((prev) => dedupeMessages(prev, messagesRes.items));
        }
        if (data.state === "finished") {
          loadResults(signal);
        }
      } catch {
        if (!signal?.aborted) {
          setError(t("game:room.roomNotFound"));
        }
      } finally {
        if (!signal?.aborted) {
          setLoading(false);
        }
      }
    },
    [roomId, t, loadResults],
  );

  // Initial mount: fetch room
  useEffect(() => {
    const ac = new AbortController();
    loadRoom(ac.signal);
    return () => ac.abort();
  }, [loadRoom]);

  // Connect dedicated room socket and attach event listeners
  useEffect(() => {
    if (!roomWs) return;

    const unsubs: Array<() => void> = [];

    unsubs.push(
      roomWs.onStateChange((state) => {
        setWsState(state);
      }),
    );

    unsubs.push(
      roomWs.subscribe<GameSnapshotPayload>("game_snapshot", (payload) => {
        if (payload.room) {
          setRoom(payload.room);
          if (payload.room.state === "finished") {
            loadResults();
          }
        }
        if (payload.messages) {
          setMessages((prev) => dedupeMessages(prev, payload.messages));
        }
        if (payload.my_votes) {
          const next: Record<number, VoteGuess> = {};
          for (const v of payload.my_votes) {
            next[v.target_participant_id] = v.guess;
          }
          setVotes(next);
        }
      }),
    );

    unsubs.push(
      roomWs.subscribe<GameChatMessage>("game_message", (msg) => {
        setMessages((prev) => {
          if (prev.some((m) => m.id === msg.id)) return prev;
          return [...prev, msg];
        });
      }),
    );

    unsubs.push(
      roomWs.subscribe<GamePhaseVotingEventPayload>(
        "game_phase_voting",
        (payload) => {
          setRoom((prev) =>
            prev
              ? {
                  ...prev,
                  state: "voting",
                  phase_ends_at: payload.phase_ends_at,
                }
              : prev,
          );
        },
      ),
    );

    unsubs.push(
      roomWs.subscribe<GamePhaseFinishedEventPayload>(
        "game_phase_finished",
        () => {
          setRoom((prev) =>
            prev
              ? {
                  ...prev,
                  state: "finished",
                  phase_ends_at: null,
                }
              : prev,
          );
          loadResults();
        },
      ),
    );

    roomWs.connect();

    return () => {
      unsubs.forEach((u) => u());
      roomWs.disconnect();
    };
  }, [roomWs, loadResults]);

  // Listen to global /ws events as fallback routing
  useWsEvent<GamePhaseVotingEventPayload>("game_phase_voting", (payload) => {
    if (payload.room_id === roomId) {
      setRoom((prev) =>
        prev
          ? {
              ...prev,
              state: "voting",
              phase_ends_at: payload.phase_ends_at,
            }
          : prev,
      );
    }
  });

  useWsEvent<GamePhaseFinishedEventPayload>(
    "game_phase_finished",
    (payload) => {
      if (payload.room_id === roomId) {
        setRoom((prev) =>
          prev
            ? {
                ...prev,
                state: "finished",
                phase_ends_at: null,
              }
            : prev,
        );
        loadResults();
      }
    },
  );

  // Calculate countdown timer
  useEffect(() => {
    if (!room?.phase_ends_at) {
      setSecondsLeft(null);
      return;
    }

    const calcTime = () => {
      const endsAt = new Date(room.phase_ends_at!).getTime();
      const now = Date.now();
      const remaining = Math.max(0, Math.floor((endsAt - now) / 1000));
      setSecondsLeft(remaining);
    };

    calcTime();
    const interval = setInterval(calcTime, 1000);
    return () => clearInterval(interval);
  }, [room?.phase_ends_at]);

  // Preset default marks to "human" for every other participant during voting
  useEffect(() => {
    if (room && (room.state === "voting" || room.state === "discussion")) {
      setVotes((prev) => {
        let changed = false;
        const next = { ...prev };
        for (const p of room.participants) {
          if (!p.is_you && !next[p.id]) {
            next[p.id] = "human";
            changed = true;
          }
        }
        return changed ? next : prev;
      });
    }
  }, [room]);

  // Scroll to bottom of chat when new message arrives
  useEffect(() => {
    if (room?.state === "discussion") {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, room?.state]);

  const handleSendMessage = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = newMessage.trim();
    if (
      !trimmed ||
      room?.state !== "discussion" ||
      (secondsLeft !== null && secondsLeft <= 0)
    ) {
      return;
    }
    if (roomWs) {
      roomWs.send("chat_message", { text: trimmed });
    }
    setNewMessage("");
  };

  const handleVote = async (targetId: number, guess: VoteGuess) => {
    if (
      room?.state !== "voting" ||
      (secondsLeft !== null && secondsLeft <= 0) ||
      savingVotes[targetId]
    ) {
      return;
    }
    const previousGuess = votes[targetId] ?? "human";
    if (previousGuess === guess) {
      return;
    }

    setVotes((prev) => ({ ...prev, [targetId]: guess }));
    setSavingVotes((prev) => ({ ...prev, [targetId]: true }));
    setVoteError(null);
    try {
      await gameApi.castVote(roomId, targetId, guess);
    } catch {
      setVotes((prev) => ({ ...prev, [targetId]: previousGuess }));
      setVoteError(t("game:room.voteError"));
    } finally {
      setSavingVotes((prev) => ({ ...prev, [targetId]: false }));
    }
  };

  const formatTimer = (totalSeconds: number): string => {
    const mins = Math.floor(totalSeconds / 60);
    const secs = totalSeconds % 60;
    return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  };

  if (loading) {
    return (
      <div className="game-room-page">
        <EmptyState
          title={t("game:room.loadingRoom")}
          icon={<Spinner size="lg" label={t("game:room.loadingRoom")} />}
        />
      </div>
    );
  }

  if (error || !room) {
    return (
      <div className="game-room-page">
        <Card className="game-card-surface">
          <h2>{error || t("game:room.roomNotFound")}</h2>
          <Button onClick={() => navigate("/game")}>
            {t("game:room.backToLobby")}
          </Button>
        </Card>
      </div>
    );
  }

  // Waiting room redirect if game has not started
  if (room.state === "waiting") {
    return (
      <div className="game-room-page">
        <Card className="game-card-surface">
          <h2>{t("game:waitingTitle")}</h2>
          <p>{t("game:waitingNoChat")}</p>
          <Button onClick={() => navigate("/game")}>
            {t("game:room.backToLobby")}
          </Button>
        </Card>
      </div>
    );
  }

  const isDiscussion = room.state === "discussion";
  const isVoting = room.state === "voting";
  const isFinished = room.state === "finished";

  const isDiscussionEnded =
    isDiscussion && secondsLeft !== null && secondsLeft <= 0;
  const isVotingEnded = isVoting && secondsLeft !== null && secondsLeft <= 0;

  // Find caller's participant result
  const myResult = results?.participants.find(
    (p) => p.participant_id === results.my_participant_id,
  );

  return (
    <div className="game-room-page">
      {/* Header bar */}
      <header className="game-room-header">
        <div className="game-room-header-left">
          <h1 className="game-room-title">{t("game:room.title")}</h1>
          {isDiscussion && (
            <Badge variant="default">{t("game:room.discussionPhase")}</Badge>
          )}
          {isVoting && (
            <Badge variant="warning">{t("game:room.votingPhase")}</Badge>
          )}
          {isFinished && (
            <Badge variant="success">{t("game:room.resultsPhase")}</Badge>
          )}
        </div>

        <div className="game-room-header-right">
          {/* Synchronized Countdown Timer */}
          {(isDiscussion || isVoting) && secondsLeft !== null && (
            <div
              className="game-timer-pill"
              aria-live="polite"
              aria-label={
                isDiscussion
                  ? t("game:room.discussionTimer")
                  : t("game:room.votingTimer")
              }
            >
              <span>{formatTimer(secondsLeft)}</span>
            </div>
          )}

          {/* Link to public rules page (FE-34) */}
          <Link
            to={GAME_RULES_PATH}
            target="_blank"
            rel="noopener noreferrer"
            className="game-room-rules-link"
          >
            {t("game:room.rules")}
          </Link>
        </div>
      </header>

      {/* Socket Reconnecting Banner */}
      {wsState === "reconnecting" && (
        <div
          className="game-reconnecting-banner"
          role="status"
          aria-live="polite"
        >
          {t("game:room.socketDisconnected")}
        </div>
      )}

      {/* Main Grid */}
      <div className="game-room-grid">
        {/* Left Column: Participants List */}
        <aside className="game-participants-sidebar">
          <Card className="game-card-surface">
            <h2>{t("game:room.participantsHeading")}</h2>
            <ul className="game-seat-list">
              {room.participants.map((participant) => {
                const res = results?.participants.find(
                  (r) => r.participant_id === participant.id,
                );
                return (
                  <li key={participant.id} className="game-seat">
                    <span>{participant.display_label}</span>
                    <div
                      style={{
                        display: "flex",
                        gap: "6px",
                        alignItems: "center",
                      }}
                    >
                      {participant.is_you && (
                        <Badge variant="default">
                          {t("game:room.youBadge")}
                        </Badge>
                      )}
                      {isFinished && res && (
                        <Badge variant={res.is_bot ? "warning" : "success"}>
                          {res.is_bot
                            ? t("game:room.botBadge")
                            : t("game:room.humanBadge")}
                        </Badge>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          </Card>
        </aside>

        {/* Right Column: Dynamic Phase Content */}
        <main className="game-room-main">
          {/* A. DISCUSSION PHASE */}
          {isDiscussion && (
            <Card className="game-card-surface game-chat-container">
              <h2>{t("game:room.chatHeading")}</h2>

              {isDiscussionEnded && (
                <div className="game-notice" style={{ marginBlockEnd: "12px" }}>
                  {t("game:room.discussionEnded")}
                </div>
              )}

              <div className="game-chat-messages" role="log" aria-live="polite">
                {messages.length === 0 ? (
                  <div
                    style={{
                      padding: "24px",
                      textAlign: "center",
                      color: "var(--color-ink-muted)",
                    }}
                  >
                    {t("game:room.chatEmpty")}
                  </div>
                ) : (
                  messages.map((msg) => {
                    const isOwn = msg.participant_id === room.my_participant_id;
                    return (
                      <div
                        key={msg.id}
                        className={`game-chat-bubble ${isOwn ? "is-own" : ""}`}
                      >
                        <span className="game-chat-sender">
                          {msg.display_label}
                          {isOwn ? ` (${t("game:room.youBadge")})` : ""}
                        </span>
                        <span className="game-chat-text">{msg.text}</span>
                      </div>
                    );
                  })
                )}
                <div ref={messagesEndRef} />
              </div>

              <form
                onSubmit={handleSendMessage}
                className="game-chat-input-bar"
              >
                <Input
                  type="text"
                  value={newMessage}
                  onChange={(e) => setNewMessage(e.target.value)}
                  placeholder={
                    isDiscussionEnded
                      ? t("game:room.chatDisabledEnded")
                      : t("game:room.chatPlaceholder")
                  }
                  disabled={isDiscussionEnded}
                  maxLength={500}
                />
                <Button
                  type="submit"
                  disabled={isDiscussionEnded || !newMessage.trim()}
                >
                  {t("game:room.chatSend")}
                </Button>
              </form>
            </Card>
          )}

          {/* B. VOTING PHASE */}
          {isVoting && (
            <Card className="game-card-surface">
              <h2>{t("game:room.votingHeading")}</h2>
              <p
                className="game-waiting-hint"
                style={{ marginBlockEnd: "16px" }}
              >
                {t("game:room.votingInstruction")}
              </p>

              {isVotingEnded && (
                <div className="game-notice" style={{ marginBlockEnd: "16px" }}>
                  {t("game:room.votingEnded")}
                </div>
              )}

              {voteError && (
                <div className="game-error" style={{ marginBlockEnd: "16px" }}>
                  {voteError}
                </div>
              )}

              <div className="game-voting-grid">
                {room.participants
                  .filter((p) => !p.is_you)
                  .map((opponent) => {
                    const currentVote = votes[opponent.id] ?? "human";
                    const isSaving = savingVotes[opponent.id];
                    return (
                      <div key={opponent.id} className="game-voting-card">
                        <span style={{ fontWeight: 600 }}>
                          {opponent.display_label}
                        </span>
                        <div className="game-voting-options">
                          <button
                            type="button"
                            className={`game-btn-toggle ${currentVote === "human" ? "is-active" : ""}`}
                            onClick={() => handleVote(opponent.id, "human")}
                            disabled={isVotingEnded}
                          >
                            {t("game:room.markHuman")}
                          </button>
                          <button
                            type="button"
                            className={`game-btn-toggle ${currentVote === "bot" ? "is-active" : ""}`}
                            onClick={() => handleVote(opponent.id, "bot")}
                            disabled={isVotingEnded}
                          >
                            {t("game:room.markBot")}
                          </button>
                          {isSaving && (
                            <span
                              style={{
                                fontSize: "0.8rem",
                                color: "var(--color-ink-muted)",
                              }}
                            >
                              {t("game:room.savingVote")}
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })}
              </div>
            </Card>
          )}

          {/* C. RESULTS PHASE */}
          {isFinished && (
            <Card className="game-card-surface">
              {loadingResults ? (
                <EmptyState
                  title={t("game:room.loadingRoom")}
                  icon={
                    <Spinner size="lg" label={t("game:room.loadingRoom")} />
                  }
                />
              ) : results ? (
                <div>
                  {/* Hero outcome banner */}
                  <div
                    className={`game-results-banner ${
                      myResult?.outcome === "win"
                        ? "is-win"
                        : myResult?.outcome === "draw"
                          ? "is-draw"
                          : "is-loss"
                    }`}
                  >
                    <h2 style={{ fontSize: "2rem", marginBlockEnd: "8px" }}>
                      {myResult?.outcome === "win"
                        ? t("game:room.youWon")
                        : myResult?.outcome === "draw"
                          ? t("game:room.youTied")
                          : t("game:room.youLost")}
                    </h2>
                    <p style={{ opacity: 0.9 }}>
                      {t("game:room.resultsSummary")}
                    </p>
                  </div>

                  {/* Results breakdown */}
                  <div className="game-results-list">
                    {results.participants.map((p) => {
                      const isWinner = results.winner_participant_ids.includes(
                        p.participant_id,
                      );
                      return (
                        <div
                          key={p.participant_id}
                          className={`game-result-row ${isWinner ? "is-winner" : ""}`}
                        >
                          <div>
                            <span
                              style={{
                                fontWeight: 700,
                                marginInlineEnd: "8px",
                              }}
                            >
                              {p.display_label}
                            </span>
                            {p.participant_id === results.my_participant_id && (
                              <Badge variant="default">
                                {t("game:room.youBadge")}
                              </Badge>
                            )}
                          </div>

                          <div
                            style={{
                              display: "flex",
                              gap: "10px",
                              alignItems: "center",
                            }}
                          >
                            {p.is_bot ? (
                              <>
                                <Badge variant="warning">
                                  {t("game:room.botBadge")}
                                </Badge>
                                <span
                                  style={{
                                    fontSize: "0.9rem",
                                    color: "var(--color-ink-muted)",
                                  }}
                                >
                                  {t("game:room.deceptionRate", {
                                    rate: p.deception_rate ?? 0,
                                  })}
                                </span>
                              </>
                            ) : (
                              <>
                                <Badge variant="success">
                                  {t("game:room.humanBadge")}
                                </Badge>
                                <span style={{ fontWeight: 700 }}>
                                  {(p.score ?? 0) > 0
                                    ? t("game:room.scorePointsPositive", {
                                        score: p.score,
                                      })
                                    : t("game:room.scorePoints", {
                                        score: p.score ?? 0,
                                      })}
                                </span>
                                {p.outcome === "win" && (
                                  <Badge variant="success">
                                    {t("game:room.winnerBadge")}
                                  </Badge>
                                )}
                                {p.outcome === "draw" && (
                                  <Badge variant="outline">
                                    {t("game:room.drawBadge")}
                                  </Badge>
                                )}
                                {p.outcome === "loss" && (
                                  <Badge variant="danger">
                                    {t("game:room.lossBadge")}
                                  </Badge>
                                )}
                              </>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  <div
                    style={{ marginBlockStart: "24px", textAlign: "center" }}
                  >
                    <Button onClick={() => navigate("/game")}>
                      {t("game:room.playAgain")}
                    </Button>
                  </div>
                </div>
              ) : (
                <div style={{ textAlign: "center", padding: "24px" }}>
                  <p>{t("game:room.loadResultsError")}</p>
                  <Button onClick={() => navigate("/game")}>
                    {t("game:room.backToLobby")}
                  </Button>
                </div>
              )}
            </Card>
          )}
        </main>
      </div>
    </div>
  );
};
