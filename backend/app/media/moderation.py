"""Video moderation pipeline: internal MinIO download, ffmpeg/ffprobe, OpenAI, WS push (BE-29)."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import tempfile
from collections.abc import Callable
from typing import Any

import certifi
import structlog
import urllib3
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.core.storage import Storage
from app.media import repo as media_repo
from app.media.constants import (
    DURATION_TOLERANCE_SEC,
    EVENT_VIDEO_MODERATED,
    FFMPEG_TIMEOUT_SEC,
    MAX_DURATION_SEC,
    MIN_AUDIO_BYTES,
    MODERATION_FRAME_TIMESTAMPS,
    OPENAI_MODERATION_MODEL,
    OPENAI_MODERATION_URL,
    OPENAI_TIMEOUT_SEC,
    OPENAI_WHISPER_MODEL,
    OPENAI_WHISPER_URL,
)
from app.media.models import IntroVideo
from app.realtime import service as realtime_service
from app.users.models import User

log = structlog.get_logger(__name__)


def _run_cmd(cmd: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(cmd, check=True, capture_output=True, timeout=FFMPEG_TIMEOUT_SEC)


def probe_duration(video_path: str) -> float:
    """Measure the video's real duration in seconds using ffprobe."""
    res = _run_cmd(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            video_path,
        ]
    )
    raw = res.stdout.decode().strip()
    duration = float(raw)
    if duration <= 0:
        raise ValueError(f"Non-positive video duration: {duration}")
    return duration


def probe_video_stream_duration(video_path: str) -> float | None:
    """Measure duration of the video stream (v:0) specifically using ffprobe."""
    try:
        res = _run_cmd(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                video_path,
            ]
        )
        raw = res.stdout.decode().strip()
        duration = float(raw)
        return duration if duration > 0 else None
    except Exception:
        return None


def extract_frames(video_path: str, out_dir: str, duration: float) -> list[str]:
    """Extract PNG frames at 5s/15s/25s, or at least one frame from the video stream."""
    v_dur = probe_video_stream_duration(video_path) or duration
    timestamps: list[float] = [float(ts) for ts in MODERATION_FRAME_TIMESTAMPS if ts < v_dur]
    if not timestamps:
        timestamps = [0.0 if v_dur <= 0 else round(min(v_dur / 2.0, 1.0), 2)]

    paths: list[str] = []
    for idx, ts in enumerate(timestamps):
        out = os.path.join(out_dir, f"frame_{idx}.png")
        try:
            _run_cmd(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    str(ts),
                    "-i",
                    video_path,
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    out,
                ]
            )
            if os.path.exists(out) and os.path.getsize(out) > 0:
                paths.append(out)
        except Exception:
            pass

    # If no frames could be extracted from chosen timestamps, fallback to 0.0s
    if not paths:
        fallback_out = os.path.join(out_dir, "frame_fallback_0.png")
        try:
            _run_cmd(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    "0",
                    "-i",
                    video_path,
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    fallback_out,
                ]
            )
            if os.path.exists(fallback_out) and os.path.getsize(fallback_out) > 0:
                paths.append(fallback_out)
        except Exception:
            pass

    return paths


def extract_audio(video_path: str, out_dir: str) -> str | None:
    """Extract 16 kHz mono MP3 audio for Whisper; returns None if silent or no audio track."""
    out = os.path.join(out_dir, "audio.mp3")
    try:
        _run_cmd(
            [
                "ffmpeg",
                "-y",
                "-i",
                video_path,
                "-vn",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-b:a",
                "64k",
                out,
            ]
        )
    except subprocess.CalledProcessError:
        return None
    return out if os.path.exists(out) and os.path.getsize(out) >= MIN_AUDIO_BYTES else None


class OpenAIModerator:
    """Calls OpenAI Whisper and Omni-Moderation over HTTPS with urllib3."""

    def __init__(self, api_key: str, *, http: urllib3.PoolManager | None = None):
        self.api_key = api_key
        self._http = http or urllib3.PoolManager(
            cert_reqs="CERT_REQUIRED",
            ca_certs=certifi.where(),
            timeout=urllib3.Timeout(connect=10, read=OPENAI_TIMEOUT_SEC),
            retries=False,
        )

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def transcribe(self, audio_path: str) -> str:
        """Transcribe extracted MP3 audio with Whisper (whisper-1)."""
        with open(audio_path, "rb") as fh:
            audio_bytes = fh.read()
        resp = self._http.request(
            "POST",
            OPENAI_WHISPER_URL,
            headers=self._auth_headers(),
            fields={
                "model": OPENAI_WHISPER_MODEL,
                "response_format": "text",
                "file": ("audio.mp3", audio_bytes, "audio/mpeg"),
            },
        )
        if resp.status >= 400:
            raise RuntimeError(f"Whisper API returned HTTP {resp.status}")
        return resp.data.decode("utf-8", errors="replace").strip()

    def _moderate_payload(self, items: list[dict[str, Any]]) -> list[str]:
        body = json.dumps({"model": OPENAI_MODERATION_MODEL, "input": items}).encode("utf-8")
        resp = self._http.request(
            "POST",
            OPENAI_MODERATION_URL,
            body=body,
            headers={**self._auth_headers(), "Content-Type": "application/json"},
        )
        if resp.status >= 400:
            raise RuntimeError(f"OpenAI moderation API returned HTTP {resp.status}")
        data = json.loads(resp.data.decode("utf-8"))
        flagged: list[str] = []
        for entry in data.get("results", []):
            if entry.get("flagged"):
                categories = entry.get("categories") or {}
                flagged.extend(name for name, active in categories.items() if active)
        return flagged

    def moderate_text(self, transcript: str) -> list[str]:
        return self._moderate_payload([{"type": "text", "text": transcript}])

    def moderate_frame(self, frame_path: str) -> list[str]:
        with open(frame_path, "rb") as fh:
            encoded = base64.standard_b64encode(fh.read()).decode("ascii")
        return self._moderate_payload(
            [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}}]
        )

    async def moderate_all(self, frame_paths: list[str], transcript: str) -> tuple[bool, str]:
        """Run Omni-Moderation on transcript and each extracted frame in parallel."""
        tasks = []
        if transcript:
            tasks.append(asyncio.to_thread(self.moderate_text, transcript))
        for path in frame_paths:
            tasks.append(asyncio.to_thread(self.moderate_frame, path))
        if not tasks:
            return False, "Processing failed"

        results = await asyncio.gather(*tasks)
        all_flagged = sorted({category for batch in results for category in batch})
        if all_flagged:
            return False, ", ".join(all_flagged)
        return True, ""


async def apply_moderation_result(
    session: AsyncSession,
    redis: Redis,
    *,
    video_id: int,
    moderation_status: str,
    rejected_reason: str | None = None,
    real_duration_sec: int | None = None,
) -> IntroVideo | None:
    """Persist moderation outcome (auto-posting on approval) and push video_moderated WS event."""
    video = await session.get(IntroVideo, video_id)
    if video is None or video.lifecycle_status == "deleted":
        return None

    # Serialize against concurrent post/unpost/delete/confirm requests for the same user (BE-07),
    # and never approve/publish a deleted user's waiting video (BE-34 / BE-13 follow-up).
    await media_repo.lock_user(session, video.user_id)
    user_status = await session.scalar(select(User.status).where(User.id == video.user_id))
    if user_status != "active":
        await session.rollback()
        return None
    video = await session.scalar(
        select(IntroVideo)
        .where(IntroVideo.id == video_id)
        .execution_options(populate_existing=True)
    )
    if video is None or video.lifecycle_status == "deleted":
        await session.rollback()
        return None
    if video.moderation_status != "pending":
        await session.rollback()
        return video

    video.moderation_status = moderation_status
    video.rejected_reason = rejected_reason
    if real_duration_sec is not None and real_duration_sec >= 1:
        video.duration_sec = real_duration_sec

    if moderation_status == "approved" and video.lifecycle_status == "loaded":
        await media_repo.unpost_posted_video(session, video.user_id)
        video.lifecycle_status = "posted"

    await session.commit()

    payload = {
        "id": video.id,
        "moderation_status": video.moderation_status,
        "lifecycle_status": video.lifecycle_status,
        "rejected_reason": video.rejected_reason,
    }
    await realtime_service.send_to_user(redis, video.user_id, EVENT_VIDEO_MODERATED, payload)
    return video


async def run_moderation(
    video_id: int,
    object_key: str,
    *,
    settings: Settings | None = None,
    storage: Storage | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    redis_client: Redis | None = None,
    moderator: OpenAIModerator | None = None,
    duration_fn: Callable[[str], float] = probe_duration,
    frames_fn: Callable[[str, str, float], list[str]] = extract_frames,
    audio_fn: Callable[[str, str], str | None] = extract_audio,
) -> str:
    """Execute the full moderation pipeline for one intro video and return the final status."""
    cfg = settings or get_settings()
    files = storage or Storage(cfg)

    owned_engine = None
    if session_factory is None:
        owned_engine = create_async_engine(cfg.database_url, poolclass=NullPool)
        session_factory = async_sessionmaker(
            owned_engine, class_=AsyncSession, expire_on_commit=False
        )

    owned_redis = False
    if redis_client is None:
        redis_client = Redis.from_url(cfg.redis_url, decode_responses=True)
        owned_redis = True

    async def _finish(
        status_val: str, reason: str | None = None, duration_sec: int | None = None
    ) -> str:
        async with session_factory() as session:
            await apply_moderation_result(
                session,
                redis_client,
                video_id=video_id,
                moderation_status=status_val,
                rejected_reason=reason,
                real_duration_sec=duration_sec,
            )
        return status_val

    log.info("moderation started", video_id=video_id, object_key=object_key)
    try:
        async with session_factory() as session:
            owner_status = await session.scalar(
                select(User.status)
                .join(IntroVideo, IntroVideo.user_id == User.id)
                .where(IntroVideo.id == video_id)
            )
        if owner_status is not None and owner_status != "active":
            log.info(
                "moderation skipped: account not active",
                video_id=video_id,
                user_status=owner_status,
            )
            return "skipped"

        with tempfile.TemporaryDirectory(prefix="wozu-mod-") as tmp:
            video_path = os.path.join(tmp, "video.mp4")

            # 1. Download directly from internal MinIO (never the external /files URL, issue #25).
            try:
                await asyncio.to_thread(files.download_to_file, object_key, video_path)
            except Exception:
                log.exception("moderation download failed", video_id=video_id)
                return await _finish("moderation_error", "Download failed")

            # 2. Probe real duration (issue #13) and extract frames + audio.
            try:
                duration = await asyncio.to_thread(duration_fn, video_path)
            except Exception:
                log.exception("moderation ffprobe failed", video_id=video_id)
                return await _finish("moderation_error", "Processing failed")

            real_duration_sec = max(1, round(duration))
            if duration > MAX_DURATION_SEC + DURATION_TOLERANCE_SEC:
                reason = f"Video exceeds maximum duration of {MAX_DURATION_SEC} seconds"
                log.info("moderation rejected duration", video_id=video_id, duration=duration)
                return await _finish("rejected", reason, duration_sec=real_duration_sec)

            try:
                frame_paths = await asyncio.to_thread(frames_fn, video_path, tmp, duration)
                audio_path = await asyncio.to_thread(audio_fn, video_path, tmp)
            except Exception:
                log.exception("moderation ffmpeg failed", video_id=video_id)
                return await _finish("moderation_error", "Processing failed")

            if not frame_paths:
                log.error("moderation extracted zero frames", video_id=video_id)
                return await _finish(
                    "moderation_error", "Processing failed", duration_sec=real_duration_sec
                )

            # 3. Dev fallback when OPENAI_API_KEY is unset (respects MODERATION_FAIL_OPEN).
            active_moderator = moderator
            if active_moderator is None:
                if not cfg.openai_api_key.strip():
                    if cfg.moderation_fail_open:
                        log.warning(
                            "OPENAI_API_KEY not set; dev fail-open approving video",
                            video_id=video_id,
                        )
                        return await _finish("approved", None, duration_sec=real_duration_sec)
                    log.error(
                        "OPENAI_API_KEY not set and MODERATION_FAIL_OPEN=false",
                        video_id=video_id,
                    )
                    return await _finish(
                        "moderation_error",
                        "OpenAI API key not configured",
                        duration_sec=real_duration_sec,
                    )
                active_moderator = OpenAIModerator(cfg.openai_api_key)

            # 4. Transcribe audio with Whisper (failure degrades gracefully to frame-only check).
            transcript = ""
            if audio_path:
                try:
                    transcript = await asyncio.to_thread(active_moderator.transcribe, audio_path)
                except Exception:
                    log.warning("moderation whisper failed", video_id=video_id, exc_info=True)
                    if not cfg.moderation_fail_open:
                        return await _finish(
                            "moderation_error",
                            "Transcription API error",
                            duration_sec=real_duration_sec,
                        )

            # 5. Run OpenAI Omni-Moderation on transcript and extracted frames.
            try:
                is_safe, reason = await active_moderator.moderate_all(frame_paths, transcript)
            except Exception:
                log.exception("moderation openai call failed", video_id=video_id)
                if cfg.moderation_fail_open:
                    return await _finish("approved", None, duration_sec=real_duration_sec)
                return await _finish(
                    "moderation_error", "Moderation API error", duration_sec=real_duration_sec
                )

        final_status = "approved" if is_safe else "rejected"
        final_reason = None if is_safe else reason
        log.info(
            "moderation completed",
            video_id=video_id,
            status=final_status,
            rejected_reason=final_reason,
        )
        return await _finish(final_status, final_reason, duration_sec=real_duration_sec)
    finally:
        if owned_redis:
            await redis_client.aclose()
        if owned_engine is not None:
            await owned_engine.dispose()
