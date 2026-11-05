import { useEffect, useRef, useState } from "react";
import {
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowDown,
  ArrowUpRight,
  CheckCheck,
  MessageCircle,
  Pencil,
  Plus,
  Send,
  Trash2,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  api,
  patch,
  post,
  remove,
  type Conversation,
  type Schema,
} from "../../api/client";
import { useAuth } from "../../app/state";
import {
  Avatar,
  Badge,
  Button,
  Confirm,
  Empty,
  ErrorNotice,
  Field,
  Loading,
  PageTitle,
  useAction,
} from "../../components/ui";

export function Chat() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { t } = useTranslation();
  const client = useQueryClient();
  const bottom = useRef<HTMLDivElement>(null);
  const [text, setText] = useState("");
  const [peer, setPeer] = useState("");
  const [newChat, setNewChat] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const [editText, setEditText] = useState("");
  const conversations = useQuery({
    queryKey: ["conversations"],
    queryFn: () => api<Conversation[]>("/conversations?limit=100"),
    refetchInterval: 30000,
  });
  const conversation = useQuery({
    queryKey: ["conversation", id],
    queryFn: () => api<Conversation>(`/conversations/${id}`),
    enabled: !!id,
  });
  const messages = useInfiniteQuery({
    queryKey: ["messages", id],
    initialPageParam: undefined as number | undefined,
    queryFn: ({ pageParam }) =>
      api<Schema["app__conversations__schemas__MessagesPage"]>(
        `/conversations/${id}/messages?limit=30${pageParam ? `&before_id=${pageParam}` : ""}`,
      ),
    getNextPageParam: (p) => p.prev_before_id ?? undefined,
    enabled: !!id,
  });
  const items =
    messages.data?.pages
      .slice()
      .reverse()
      .flatMap((p) => p.items) || [];
  const lastId = items.at(-1)?.id;
  const sentKey = useRef<string | null>(null);
  const send = useAction(async () => {
    if (!text.trim()) return;
    sentKey.current ??= crypto.randomUUID();
    await post(`/conversations/${id}/messages`, {
      content: text.trim(),
      idempotency_key: sentKey.current,
    });
    sentKey.current = null;
    setText("");
  }, ["messages", "conversations"]);
  const start = useAction(async () => {
    const c = await post<Conversation>("/conversations", {
      type: "direct",
      peer_user_id: Number(peer),
    });
    setNewChat(false);
    setPeer("");
    navigate(`/chat/${c.id}`);
  }, ["conversations"]);
  const edit = useAction(async () => {
    await patch(`/conversations/${id}/messages/${editing}`, {
      content: editText,
    });
    setEditing(null);
  }, ["messages"]);
  useEffect(() => {
    setText("");
    setEditing(null);
    sentKey.current = null;
  }, [id]);
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    if (id && lastId)
      void post(`/conversations/${id}/read`, { last_message_id: lastId })
        .then(() => client.invalidateQueries({ queryKey: ["unread"] }))
        .catch(() => {});
  }, [id, lastId, client]);
  return (
    <>
      <PageTitle
        eyebrow="A CONVERSATION CAN CHANGE EVERYTHING"
        title="Good things start with hello."
      />
      <div className={`chat-workspace ${id ? "has-conversation" : ""}`}>
        <aside className="chat-list">
          <div className="chat-list-title">
            <h2>{t("Messages")}</h2>
            <button
              className="icon-button"
              aria-label={t("New conversation")}
              onClick={() => setNewChat(!newChat)}
            >
              <Plus size={21} />
            </button>
          </div>
          {newChat && (
            <form
              className="new-chat"
              onSubmit={(e) => {
                e.preventDefault();
                start.mutate();
              }}
            >
              <Field label="User ID">
                <input
                  type="number"
                  min="1"
                  required
                  value={peer}
                  onChange={(e) => setPeer(e.target.value)}
                />
              </Field>
              <Button type="submit" busy={start.isPending}>
                {t("Say hello")}
                <ArrowUpRight size={15} />
              </Button>
              <ErrorNotice error={start.error} />
            </form>
          )}
          <ErrorNotice error={conversations.error} />
          {conversations.isPending && <Loading />}
          {conversations.data?.map((c) => (
            <Link
              to={`/chat/${c.id}`}
              key={c.id}
              className={`conversation ${String(c.id) === id ? "selected" : ""}`}
            >
              <Avatar name={c.title || c.job_title || "Conversation"} />
              <div>
                <strong>
                  {c.title || c.job_title || `${t("Conversation")} ${c.id}`}
                </strong>
                <p>{c.last_message_content || t("Start a conversation")}</p>
              </div>
              {c.unread_count > 0 && (
                <span className="nav-count">{c.unread_count}</span>
              )}
            </Link>
          ))}
          {!conversations.isPending && !conversations.data?.length && (
            <Empty title="A space for your conversations">
              {t("Use + to connect with someone by their user ID.")}
            </Empty>
          )}
        </aside>
        <section className="chat-thread">
          {!id ? (
            <div className="chat-welcome">
              <div className="chat-illustration">
                <MessageCircle size={70} />
                <span>hello.</span>
                <i>✦</i>
              </div>
              <h2>{t("Your next connection starts here.")}</h2>
              <p>{t("Choose a conversation or say hello to someone new.")}</p>
              <Button onClick={() => setNewChat(true)}>
                {t("Start a conversation")}
                <Plus size={17} />
              </Button>
            </div>
          ) : (
            <>
              <header className="thread-header">
                <Link
                  className="mobile-only"
                  to="/chat"
                  aria-label={t("Back to messages")}
                >
                  ←
                </Link>
                <Avatar name={conversation.data?.title || "Conversation"} />
                <div>
                  <h3>
                    {conversation.data?.title ||
                      conversation.data?.job_title ||
                      `${t("Conversation")} ${id}`}
                  </h3>
                  <span className="small-text muted">
                    {t("A little more human. A little more connected.")}
                  </span>
                </div>
              </header>
              <ErrorNotice error={messages.error || conversation.error} />
              <div
                className="message-scroll"
                aria-label={t("Conversation messages")}
              >
                {messages.hasNextPage && (
                  <Button
                    variant="ghost"
                    busy={messages.isFetchingNextPage}
                    onClick={() => void messages.fetchNextPage()}
                  >
                    {t("Earlier messages")}
                    <ArrowDown size={15} />
                  </Button>
                )}
                {messages.isPending && <Loading />}
                {items.map((m) => (
                  <div
                    key={m.id}
                    className={`message-row ${m.author_id === user?.id ? "own" : ""}`}
                  >
                    <div className="message-bubble">
                      {editing === m.id ? (
                        <form
                          onSubmit={(e) => {
                            e.preventDefault();
                            edit.mutate();
                          }}
                        >
                          <textarea
                            aria-label={t("Edit message")}
                            maxLength={4000}
                            value={editText}
                            onChange={(e) => setEditText(e.target.value)}
                          />
                          <Button
                            busy={edit.isPending}
                            disabled={!editText.trim()}
                            type="submit"
                          >
                            {t("Save")}
                          </Button>
                          <button
                            type="button"
                            className="icon-button"
                            aria-label={t("Cancel")}
                            onClick={() => setEditing(null)}
                          >
                            <X size={16} />
                          </button>
                          <ErrorNotice error={edit.error} />
                        </form>
                      ) : (
                        <p dir="auto">
                          {m.deleted_at ? t("Message deleted") : m.content}
                        </p>
                      )}
                      <div className="message-meta">
                        <time>
                          {new Intl.DateTimeFormat(undefined, {
                            hour: "2-digit",
                            minute: "2-digit",
                          }).format(new Date(m.created_at))}
                        </time>
                        {m.edited_at && <span>{t("edited")}</span>}
                        {m.author_id === user?.id && (
                          <CheckCheck size={13} aria-label={m.status} />
                        )}
                      </div>
                    </div>
                    {m.author_id === user?.id && !m.deleted_at && (
                      <div className="message-tools">
                        {Date.now() - new Date(m.created_at).getTime() <
                          15 * 60 * 1000 && (
                          <button
                            className="icon-button"
                            aria-label={t("Edit message")}
                            onClick={() => {
                              setEditing(m.id);
                              setEditText(m.content);
                            }}
                          >
                            <Pencil size={13} />
                          </button>
                        )}
                        <Confirm
                          title="Delete this message?"
                          description="The message will be removed for everyone in this conversation."
                          onConfirm={async () => {
                            await remove(
                              `/conversations/${id}/messages/${m.id}`,
                            );
                            await client.invalidateQueries({
                              queryKey: ["messages"],
                            });
                          }}
                          danger
                        >
                          <Trash2 size={13} />
                        </Confirm>
                      </div>
                    )}
                  </div>
                ))}
                {!messages.isPending && !items.length && (
                  <Empty title="Break the ice">
                    {t("A simple hello is a great place to start.")}
                  </Empty>
                )}
                <div ref={bottom} />
              </div>
              <ErrorNotice error={send.error} />
              <form
                className="message-composer"
                onSubmit={(e) => {
                  e.preventDefault();
                  send.mutate();
                }}
              >
                <textarea
                  aria-label={t("Message")}
                  placeholder={t("Say something good…")}
                  maxLength={4000}
                  rows={1}
                  value={text}
                  onChange={(e) => {
                    setText(e.target.value);
                    sentKey.current = null;
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      if (text.trim() && !send.isPending) send.mutate();
                    }
                  }}
                />
                <Badge tone="neutral">{text.length}/4000</Badge>
                <Button
                  type="submit"
                  busy={send.isPending}
                  disabled={!text.trim()}
                  aria-label={t("Send message")}
                >
                  <Send size={18} />
                </Button>
              </form>
            </>
          )}
        </section>
      </div>
    </>
  );
}
