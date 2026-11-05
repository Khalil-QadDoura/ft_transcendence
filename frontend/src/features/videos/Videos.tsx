import { useEffect, useRef, useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight,
  Camera,
  Check,
  Film,
  Mic,
  Play,
  Square,
  Upload,
  Video,
} from "lucide-react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api, post, query, uploadFile, type Schema } from "../../api/client";
import {
  Badge,
  Button,
  Confirm,
  Empty,
  ErrorNotice,
  PageTitle,
  Success,
  useAction,
} from "../../components/ui";

export async function videoDuration(file: File): Promise<number> {
  return new Promise((resolve, reject) => {
    const video = document.createElement("video");
    const url = URL.createObjectURL(file);
    const timer = setTimeout(
      () =>
        finish(new Error("Could not read this video. Try a different MP4.")),
      10000,
    );
    const finish = (result: number | Error) => {
      clearTimeout(timer);
      URL.revokeObjectURL(url);
      video.removeAttribute("src");
      if (result instanceof Error) reject(result);
      else resolve(result);
    };
    video.preload = "metadata";
    video.onloadedmetadata = () =>
      Number.isFinite(video.duration)
        ? finish(video.duration)
        : finish(new Error("This file has no readable duration."));
    video.onerror = () =>
      finish(new Error("Could not read this video. Try a different MP4."));
    video.src = url;
  });
}
export function Videos() {
  const { t } = useTranslation();
  const [tab, setTab] = useState("mine");
  const [file, setFile] = useState<File | null>(null);
  const [duration, setDuration] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [progress, setProgress] = useState(0);
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const preview = useRef<HTMLVideoElement>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const limitTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mounted = useRef(true);
  const [localURL, setLocalURL] = useState("");
  useEffect(() => {
    if (!file) {
      setLocalURL("");
      return;
    }
    const url = URL.createObjectURL(file);
    setLocalURL(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (recorder.current?.state === "recording") recorder.current.stop();
      stream.current?.getTracks().forEach((track) => track.stop());
      if (timer.current) clearInterval(timer.current);
      if (limitTimer.current) clearTimeout(limitTimer.current);
    };
  }, []);
  const mine = useQuery({
    queryKey: ["videos"],
    queryFn: () =>
      api<Schema["MineResponse"]>("/media/intro-video/mine?expires_sec=300"),
    refetchInterval: (q) =>
      q.state.data?.items.some((v) => v.moderation_status === "pending")
        ? 5000
        : 120000,
  });
  const feed = useInfiniteQuery({
    queryKey: ["video-feed"],
    initialPageParam: undefined as number | undefined,
    queryFn: ({ pageParam }) =>
      api<Schema["FeedResponse"]>(
        `/media/feed?${query({ limit: 12, cursor: pageParam, expires_sec: 300 })}`,
      ),
    getNextPageParam: (p) => p.next_cursor ?? undefined,
    enabled: tab === "feed",
    staleTime: 120000,
    refetchInterval: tab === "feed" ? 120000 : false,
  });
  const selectFile = async (next: File) => {
    setError(null);
    setFile(null);
    setDuration(null);
    try {
      if (next.type !== "video/mp4" || next.size > 50 * 1024 * 1024)
        throw new Error(t("Choose an MP4 video under 50 MB."));
      const seconds = await videoDuration(next);
      if (seconds < 1 || seconds > 30)
        throw new Error(
          t("Your introduction must be between 1 and 30 seconds."),
        );
      setDuration(seconds);
      setFile(next);
    } catch (err) {
      setError(err);
    }
  };
  const upload = useAction(async () => {
    if (!file || duration == null) return;
    setProgress(0);
    const signed = await post<
      Schema["app__media__handlers__handlers_upload__UploadUrlResponse"]
    >("/media/intro-video/upload-url", {
      content_type: "video/mp4",
      ext: "mp4",
      expires_sec: 900,
    });
    if (file.size > signed.max_bytes)
      throw new Error(t("This file exceeds the server upload limit."));
    await uploadFile(signed.put_url, file, setProgress);
    await post("/media/intro-video/confirm", {
      object_key: signed.object_key,
      duration_sec: Math.ceil(duration),
      size_bytes: file.size,
      content_type: "video/mp4",
    });
    setFile(null);
    setDuration(null);
  }, ["videos"]);
  const publish = useAction(
    ({ id, action }: { id: number; action: string }) =>
      post(`/media/intro-video/${id}/${action}`),
    ["videos", "video-feed"],
  );
  async function startRecording() {
    setError(null);
    try {
      if (!navigator.mediaDevices || typeof MediaRecorder === "undefined")
        throw new Error(
          t("Recording is unavailable in this browser. Upload an MP4 instead."),
        );
      const mime = ["video/mp4;codecs=avc1.42E01E,mp4a.40.2", "video/mp4"].find(
        (type) => MediaRecorder.isTypeSupported(type),
      );
      if (!mime)
        throw new Error(
          t("This browser cannot record MP4. Upload an MP4 instead."),
        );
      stream.current = await navigator.mediaDevices.getUserMedia({
        video: { width: 1280, height: 720 },
        audio: true,
      });
      if (preview.current) {
        preview.current.srcObject = stream.current;
        await preview.current.play();
      }
      const chunks: BlobPart[] = [];
      const r = new MediaRecorder(stream.current, { mimeType: mime });
      recorder.current = r;
      r.ondataavailable = (e) => {
        if (e.data.size) chunks.push(e.data);
      };
      r.onstop = () => {
        stream.current?.getTracks().forEach((track) => track.stop());
        if (preview.current) preview.current.srcObject = null;
        if (timer.current) clearInterval(timer.current);
        if (limitTimer.current) clearTimeout(limitTimer.current);
        if (mounted.current) {
          setRecording(false);
          void selectFile(
            new File(chunks, "my-introduction.mp4", { type: "video/mp4" }),
          );
        }
      };
      r.start();
      setElapsed(0);
      setRecording(true);
      timer.current = setInterval(() => setElapsed((value) => value + 1), 1000);
      limitTimer.current = setTimeout(() => {
        if (r.state === "recording") r.stop();
      }, 29000);
    } catch (err) {
      stream.current?.getTracks().forEach((track) => track.stop());
      setError(err);
    }
  }
  return (
    <>
      <PageTitle
        eyebrow="LESS PAPER. MORE PERSONALITY."
        title="Let them meet the real you."
        description="Thirty seconds. Your voice. A whole new possibility."
      />
      <div className="tabs studio-tabs">
        <button
          className={tab === "mine" ? "selected" : ""}
          onClick={() => setTab("mine")}
        >
          <Video size={17} />
          {t("My studio")}
        </button>
        <button
          className={tab === "feed" ? "selected" : ""}
          onClick={() => setTab("feed")}
        >
          <Play size={17} />
          {t("Meet the community")}
        </button>
      </div>
      {tab === "mine" ? (
        <>
          <div className="studio-grid">
            <section className="studio-record">
              <div
                className={`recording-stage ${recording ? "is-recording" : ""}`}
              >
                <video
                  ref={preview}
                  muted
                  playsInline
                  className={recording ? "" : "hidden"}
                />
                {localURL && !recording ? (
                  <video controls src={localURL} />
                ) : (
                  !recording && (
                    <div className="record-placeholder">
                      <div className="camera-illustration">
                        <Camera size={48} />
                        <span>✦</span>
                      </div>
                      <h2>{t("Your story. Your spotlight.")}</h2>
                      <p>{t("Find good light. Take a breath. Just be you.")}</p>
                      <span className="record-specs">
                        MP4 · 1–30 {t("seconds")} · 50 MB
                      </span>
                    </div>
                  )
                )}
                {recording && (
                  <span className="recording-timer">
                    <i />
                    {elapsed}s / 30s
                  </span>
                )}
              </div>
              <div className="studio-controls">
                {recording ? (
                  <Button
                    variant="danger"
                    onClick={() => recorder.current?.stop()}
                  >
                    <Square size={15} />
                    {t("Finish recording")}
                  </Button>
                ) : (
                  <>
                    <Button
                      onClick={() => void startRecording()}
                      disabled={upload.isPending}
                    >
                      <Camera size={17} />
                      {t("Record my intro")}
                    </Button>
                    <label className="button secondary upload-label">
                      <Upload size={17} />
                      {t("Upload a video")}
                      <input
                        type="file"
                        accept="video/mp4"
                        disabled={upload.isPending}
                        onChange={(e) => {
                          const f = e.target.files?.[0];
                          if (f) void selectFile(f);
                          e.target.value = "";
                        }}
                      />
                    </label>
                  </>
                )}
              </div>
              {file && (
                <div className="selected-file">
                  <Film size={20} />
                  <div>
                    <strong>{file.name}</strong>
                    <span>
                      {duration?.toFixed(1)}s ·{" "}
                      {(file.size / 1024 / 1024).toFixed(1)} MB
                    </span>
                  </div>
                  <Button
                    busy={upload.isPending}
                    onClick={() => upload.mutate()}
                  >
                    {t("Upload introduction")}
                    <ArrowUpRight size={16} />
                  </Button>
                </div>
              )}
              {upload.isPending && (
                <div className="upload-progress">
                  <progress value={progress} max={100} />
                  <span>{progress}%</span>
                </div>
              )}
              <ErrorNotice error={error || upload.error} />
              {upload.isSuccess && (
                <Success>
                  {t(
                    "Uploaded. Your video will appear below while moderation runs.",
                  )}
                </Success>
              )}
            </section>
            <aside className="panel studio-tips">
              <span className="eyebrow">{t("A LITTLE NUDGE")}</span>
              <h2>
                {t("Make 30 seconds count.")}
                <span>✳</span>
              </h2>
              {[
                {
                  icon: Mic,
                  title: "Start with you.",
                  body: "Your name, what you do, and what makes you light up.",
                },
                {
                  icon: Film,
                  title: "Show your spark.",
                  body: "One skill, one story, or one thing you’re proud of.",
                },
                {
                  icon: ArrowUpRight,
                  title: "Look ahead.",
                  body: "Tell your next team what you’d love to do together.",
                },
              ].map(({ icon: Icon, title, body }, i) => (
                <div className="tip" key={title}>
                  <span>0{i + 1}</span>
                  <div>
                    <Icon size={18} />
                    <h3>{t(title)}</h3>
                    <p>{t(body)}</p>
                  </div>
                </div>
              ))}
            </aside>
          </div>
          <section className="my-videos">
            <div className="section-heading">
              <h2>{t("Your introductions")}</h2>
              <Badge tone="neutral">{mine.data?.items.length || 0} / 3</Badge>
            </div>
            <ErrorNotice error={mine.error || publish.error} />
            <div className="video-grid">
              {mine.data?.items.map((v) => (
                <article className="panel video-card" key={v.id}>
                  <video controls preload="metadata" src={v.signed_url} />
                  <div className="video-info">
                    <h3>
                      {t("Introduction")} #{v.id}
                    </h3>
                    <div className="job-tags">
                      <Badge
                        tone={
                          v.moderation_status === "rejected" ? "orange" : ""
                        }
                      >
                        {t(v.moderation_status)}
                      </Badge>
                      <Badge tone="neutral">{t(v.lifecycle_status)}</Badge>
                    </div>
                    <p>
                      {v.duration_sec}s ·{" "}
                      {(v.size_bytes / 1024 / 1024).toFixed(1)} MB
                    </p>
                    <div className="actions">
                      {v.moderation_status === "approved" && (
                        <Button
                          busy={publish.isPending}
                          onClick={() =>
                            publish.mutate({
                              id: v.id,
                              action:
                                v.lifecycle_status === "posted"
                                  ? "unpost"
                                  : "post",
                            })
                          }
                        >
                          <Check size={15} />
                          {t(
                            v.lifecycle_status === "posted"
                              ? "Unpublish"
                              : "Publish",
                          )}
                        </Button>
                      )}
                      <Confirm
                        title="Delete this video?"
                        description="This introduction will be removed from your video library."
                        danger
                        onConfirm={() =>
                          publish.mutateAsync({ id: v.id, action: "delete" })
                        }
                      >
                        {t("Delete")}
                      </Confirm>
                    </div>
                  </div>
                </article>
              ))}
            </div>
            {!mine.isPending && !mine.data?.items.length && (
              <Empty title="Your first hello belongs here">
                {t(
                  "Record or upload your introduction. After approval, publish it to apply for jobs.",
                )}
              </Empty>
            )}
          </section>
        </>
      ) : (
        <>
          <ErrorNotice error={feed.error} />
          <div className="video-grid">
            {feed.data?.pages
              .flatMap((p) => p.items)
              .map((v) => (
                <article className="panel video-card" key={v.id}>
                  <video src={v.signed_url} controls preload="metadata" />
                  <div className="video-info">
                    <h3>{v.author_name || t("WOZU member")}</h3>
                    <p>{v.author_position}</p>
                    <Link className="text-link" to={`/users/${v.user_id}`}>
                      {t("Meet this person")}
                      <ArrowUpRight size={16} />
                    </Link>
                  </div>
                </article>
              ))}
          </div>
          {!feed.isPending && !feed.data?.pages[0].items.length && (
            <Empty title="Be the first to say hello">
              {t(
                "Published introductions from the community will appear here.",
              )}
            </Empty>
          )}
          {feed.hasNextPage && (
            <Button
              busy={feed.isFetchingNextPage}
              onClick={() => void feed.fetchNextPage()}
            >
              {t("Load more")}
            </Button>
          )}
        </>
      )}
    </>
  );
}
