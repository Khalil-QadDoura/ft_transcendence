"""Unit, PostgreSQL, Redis, and WebSocket tests for the video moderation worker (BE-29)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx2
import pytest
import redis
import structlog
from conftest import (
    TEST_DATABASE_URL,
    TEST_REDIS_URL,
    alembic,
    build_app,
    needs_database,
    needs_redis,
    running_server,
    sql,
)
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from websockets.sync.client import connect as ws_connect

from app.auth import security
from app.core.config import Settings
from app.core.queue import MODERATION_TASK
from app.media.constants import EVENT_VIDEO_MODERATED, WORKER_HEARTBEAT_KEY
from app.media.models import IntroVideo
from app.media.moderation import (
    OpenAIModerator,
    apply_moderation_result,
    extract_audio,
    extract_frames,
    probe_duration,
    run_moderation,
)
from app.worker.celery_app import _on_setup_logging, celery_app
from app.worker.tasks.moderation import requeue_stuck_videos, write_worker_heartbeat

PASSWORD = "correct horse battery"
PASSWORD_HASH = security.hash_password(PASSWORD)


class FakeModerator:
    """Deterministic OpenAI replacement for unit and integration tests."""

    def __init__(
        self,
        *,
        transcript: str = "Hello, I am a backend developer.",
        flagged: list[str] | None = None,
        whisper_error: Exception | None = None,
        moderation_error: Exception | None = None,
    ):
        self.transcript = transcript
        self.flagged = flagged or []
        self.whisper_error = whisper_error
        self.moderation_error = moderation_error
        self.transcribed_paths: list[str] = []
        self.moderated_calls: list[tuple[list[str], str]] = []

    def transcribe(self, audio_path: str) -> str:
        self.transcribed_paths.append(audio_path)
        if self.whisper_error is not None:
            raise self.whisper_error
        return self.transcript

    async def moderate_all(self, frame_paths: list[str], transcript: str) -> tuple[bool, str]:
        self.moderated_calls.append((list(frame_paths), transcript))
        if self.moderation_error is not None:
            raise self.moderation_error
        if self.flagged:
            return False, ", ".join(sorted(set(self.flagged)))
        return True, ""


class FakeStorage:
    """In-memory stand-in verifying only internal download_to_file is ever called."""

    def __init__(self, *, fail_download: bool = False):
        self.fail_download = fail_download
        self.downloaded: list[str] = []

    def download_to_file(self, key: str, dest_path: str) -> None:
        self.downloaded.append(key)
        if self.fail_download:
            raise RuntimeError("MinIO internal download failed")
        with open(dest_path, "wb") as fh:
            fh.write(b"\x00\x00\x00\x18ftypmp42")

    def download_url(self, *args, **kwargs) -> str:
        raise AssertionError("Worker must never use external presigned URLs (issue #25)")


def _fake_frames(video_path: str, out_dir: str, duration: float) -> list[str]:
    path = os.path.join(out_dir, "frame_0.png")
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\nfakedata")
    return [path]


def _fake_audio(video_path: str, out_dir: str) -> str | None:
    path = os.path.join(out_dir, "audio.mp3")
    with open(path, "wb") as fh:
        fh.write(b"ID3" + b"\x00" * 2048)
    return path


def _test_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "database_url": TEST_DATABASE_URL,
        "redis_url": TEST_REDIS_URL,
        "jwt_secret": "test-only-jwt-secret-0123456789abcdef",
        "openai_api_key": "sk-test-only",
        "moderation_fail_open": False,
    }
    defaults.update(overrides)
    return Settings(**defaults)


# ── Fast Unit Tests (No DB / Redis required) ───────────────────────────────────


def test_celery_app_configuration_and_beat_schedule():
    """Celery configures late acks, /tmp beat schedule file, and all BE-29 tasks."""
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True
    assert celery_app.conf.beat_schedule_filename == "/tmp/celerybeat-schedule"
    assert MODERATION_TASK in celery_app.tasks
    assert "app.worker.tasks.moderation.requeue_stuck" in celery_app.tasks
    assert "app.worker.tasks.moderation.heartbeat" in celery_app.tasks
    assert "requeue-stuck-moderation" in celery_app.conf.beat_schedule
    assert "worker-heartbeat" in celery_app.conf.beat_schedule


def test_probe_duration_and_extraction_helpers(tmp_path):
    """ffprobe/ffmpeg helpers parse duration, handle short videos, and ignore silent audio."""
    video_file = str(tmp_path / "clip.mp4")
    with open(video_file, "wb") as fh:
        fh.write(b"fake")

    with patch("app.media.moderation._run_cmd") as mock_cmd:
        mock_cmd.return_value = SimpleNamespace(stdout=b"18.4\n")
        assert probe_duration(video_file) == pytest.approx(18.4)

        mock_cmd.return_value = SimpleNamespace(stdout=b"0\n")
        with pytest.raises(ValueError, match="Non-positive"):
            probe_duration(video_file)

    # Short video (< 5s) still extracts one midpoint frame
    def _write_out(cmd: list[str]):
        with open(cmd[-1], "wb") as fh:
            fh.write(b"png-bytes")
        return SimpleNamespace(stdout=b"")

    with patch("app.media.moderation._run_cmd", side_effect=_write_out) as mock_cmd:
        frames = extract_frames(video_file, str(tmp_path), duration=2.4)
        assert len(frames) == 1
        assert "-ss" in mock_cmd.call_args.args[0]

    # 30s video extracts frames at 5, 15, 25 seconds
    with patch("app.media.moderation._run_cmd", side_effect=_write_out) as mock_cmd:
        frames = extract_frames(video_file, str(tmp_path), duration=30.0)
        assert len(frames) == 3

    # Missing audio track -> returns None instead of raising
    with patch(
        "app.media.moderation._run_cmd",
        side_effect=subprocess.CalledProcessError(1, ["ffmpeg"]),
    ):
        assert extract_audio(video_file, str(tmp_path)) is None


def test_openai_moderator_rest_requests_and_aggregation(tmp_path):
    """OpenAIModerator calls Whisper + Omni-Moderation via urllib3 and merges categories."""
    audio_file = tmp_path / "audio.mp3"
    audio_file.write_bytes(b"mp3-bytes")
    frame_file = tmp_path / "frame.png"
    frame_file.write_bytes(b"png-bytes")

    http = MagicMock()

    def _fake_request(method, url, **kwargs):
        assert kwargs["headers"]["Authorization"] == "Bearer sk-unit"
        if url.endswith("/audio/transcriptions"):
            return SimpleNamespace(status=200, data=b"Hello world\n")
        payload = json.loads(kwargs["body"].decode("utf-8"))
        item_type = payload["input"][0]["type"]
        if item_type == "text":
            res = {
                "results": [
                    {"flagged": True, "categories": {"harassment": True, "hate": False}},
                ]
            }
        else:
            res = {"results": [{"flagged": True, "categories": {"violence": True}}]}
        return SimpleNamespace(status=200, data=json.dumps(res).encode("utf-8"))

    http.request.side_effect = _fake_request
    mod = OpenAIModerator("sk-unit", http=http)

    assert mod.transcribe(str(audio_file)) == "Hello world"
    is_safe, reason = asyncio.run(mod.moderate_all([str(frame_file)], "Hello world"))
    assert is_safe is False
    assert reason == "harassment, violence"

    # Non-2xx response raises RuntimeError
    http.request.side_effect = None
    http.request.return_value = SimpleNamespace(status=503, data=b"error")
    with pytest.raises(RuntimeError, match="HTTP 503"):
        mod.moderate_text("hello")


# ── Real PostgreSQL + Redis + WebSocket Integration Tests ──────────────────────


def _seed_user(email: str) -> int:
    sql(
        "INSERT INTO users (email, password_hash, is_email_verified, status, token_version,"
        " first_name, last_name, position)"
        " VALUES (:email, :pw, true, 'active', 1, 'Mod', 'Tester', 'Engineer')",
        email=email,
        pw=PASSWORD_HASH,
    )
    return int(sql("SELECT id FROM users WHERE email = :email", email=email)[0][0])


def _seed_video(
    user_id: int,
    *,
    object_key: str,
    moderation_status: str = "pending",
    lifecycle_status: str = "loaded",
    duration_sec: int = 10,
) -> int:
    sql(
        "INSERT INTO intro_videos (user_id, object_key, duration_sec, size_bytes, content_type,"
        " moderation_status, lifecycle_status)"
        " VALUES (:uid, :key, :dur, 2048, 'video/mp4', :mod, :life)",
        uid=user_id,
        key=object_key,
        dur=duration_sec,
        mod=moderation_status,
        life=lifecycle_status,
    )
    return int(sql("SELECT id FROM intro_videos WHERE object_key = :key", key=object_key)[0][0])


def _fetch_video_row(video_id: int) -> tuple[str, str, str | None, int]:
    row = sql(
        "SELECT moderation_status::text, lifecycle_status::text, rejected_reason, duration_sec"
        " FROM intro_videos WHERE id = :vid",
        vid=video_id,
    )[0]
    return row[0], row[1], row[2], int(row[3])


@contextmanager
def _open_ws(base_http: str, auth_headers: dict[str, str]):
    ticket = httpx2.post(f"{base_http}/api/ws/ticket", headers=auth_headers).json()["ticket"]
    ws_url = base_http.replace("http://", "ws://") + f"/ws?ticket={ticket}"
    with ws_connect(ws_url, open_timeout=5) as ws:
        yield ws


def _wait_event(ws, expected_type: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        assert remaining > 0, f"timed out waiting for WS event {expected_type!r}"
        frame = json.loads(ws.recv(timeout=remaining))
        if frame.get("type") == expected_type:
            return frame["payload"]


@needs_database
@needs_redis
def test_moderation_pipeline_all_outcomes_and_live_ws_events():
    """Approve (+auto-post), reject (AI & >30s), moderation_error, fail-open, and live WS push."""
    alembic("upgrade", "head")
    sql("TRUNCATE users, intro_videos RESTART IDENTITY CASCADE")
    user_id = _seed_user("moderator@example.com")

    # Existing posted video should automatically become unposted when a new video is approved.
    old_posted_id = _seed_video(
        user_id,
        object_key=f"users/{user_id}/intro/old.mp4",
        moderation_status="approved",
        lifecycle_status="posted",
    )
    vid_ok = _seed_video(user_id, object_key=f"users/{user_id}/intro/ok.mp4")
    vid_rej = _seed_video(user_id, object_key=f"users/{user_id}/intro/rej.mp4")
    vid_long = _seed_video(user_id, object_key=f"users/{user_id}/intro/long.mp4")
    vid_dl_err = _seed_video(user_id, object_key=f"users/{user_id}/intro/dl.mp4")
    vid_api_err = _seed_video(user_id, object_key=f"users/{user_id}/intro/api.mp4")
    vid_fail_open = _seed_video(user_id, object_key=f"users/{user_id}/intro/open.mp4")
    vid_no_key_strict = _seed_video(user_id, object_key=f"users/{user_id}/intro/nokey_strict.mp4")
    vid_no_key_dev = _seed_video(user_id, object_key=f"users/{user_id}/intro/nokey_dev.mp4")
    vid_whisper_fail_strict = _seed_video(
        user_id, object_key=f"users/{user_id}/intro/whisper_strict.mp4"
    )
    vid_whisper_fail_open = _seed_video(
        user_id, object_key=f"users/{user_id}/intro/whisper_open.mp4"
    )
    vid_no_frames = _seed_video(user_id, object_key=f"users/{user_id}/intro/no_frames.mp4")
    vid_deleted = _seed_video(
        user_id,
        object_key=f"users/{user_id}/intro/deleted.mp4",
        lifecycle_status="deleted",
    )

    app = build_app(database_url=TEST_DATABASE_URL, redis_url=TEST_REDIS_URL)
    with running_server(app) as addr:
        base = f"http://{addr}"
        tok = httpx2.post(
            f"{base}/api/auth/login",
            json={"email": "moderator@example.com", "password": PASSWORD},
        ).json()["access_token"]
        headers = {"Authorization": f"Bearer {tok}"}

        with _open_ws(base, headers) as ws:
            # 1. Approved video (internal download, clean moderation, frame check passes)
            storage_ok = FakeStorage()
            mod_ok = FakeModerator()
            res = asyncio.run(
                run_moderation(
                    vid_ok,
                    f"users/{user_id}/intro/ok.mp4",
                    settings=_test_settings(),
                    storage=storage_ok,
                    moderator=mod_ok,
                    duration_fn=lambda _: 14.6,
                    frames_fn=_fake_frames,
                    audio_fn=_fake_audio,
                )
            )
            assert res == "approved"
            assert storage_ok.downloaded == [f"users/{user_id}/intro/ok.mp4"]
            assert _fetch_video_row(vid_ok) == ("approved", "posted", None, 15)
            assert _fetch_video_row(old_posted_id)[1] == "unposted"
            evt_ok = _wait_event(ws, EVENT_VIDEO_MODERATED)
            assert evt_ok == {
                "id": vid_ok,
                "moderation_status": "approved",
                "lifecycle_status": "posted",
                "rejected_reason": None,
            }

            # 2. Rejected by AI moderation with categories + exposed in /intro-video/mine
            mod_rej = FakeModerator(flagged=["violence", "harassment"])
            res = asyncio.run(
                run_moderation(
                    vid_rej,
                    f"users/{user_id}/intro/rej.mp4",
                    settings=_test_settings(),
                    storage=FakeStorage(),
                    moderator=mod_rej,
                    duration_fn=lambda _: 12.0,
                    frames_fn=_fake_frames,
                    audio_fn=_fake_audio,
                )
            )
            assert res == "rejected"
            assert _fetch_video_row(vid_rej) == ("rejected", "loaded", "harassment, violence", 12)
            evt_rej = _wait_event(ws, EVENT_VIDEO_MODERATED)
            assert evt_rej["id"] == vid_rej
            assert evt_rej["moderation_status"] == "rejected"
            assert evt_rej["rejected_reason"] == "harassment, violence"

            mine = httpx2.get(f"{base}/api/media/intro-video/mine", headers=headers).json()["items"]
            mine_by_id = {item["id"]: item for item in mine}
            assert mine_by_id[vid_rej]["rejected_reason"] == "harassment, violence"

            # 3. Rejected by real ffprobe duration > 30 s (issue #13) without calling OpenAI
            mod_unused = FakeModerator()
            res = asyncio.run(
                run_moderation(
                    vid_long,
                    f"users/{user_id}/intro/long.mp4",
                    settings=_test_settings(),
                    storage=FakeStorage(),
                    moderator=mod_unused,
                    duration_fn=lambda _: 34.2,
                    frames_fn=_fake_frames,
                    audio_fn=_fake_audio,
                )
            )
            assert res == "rejected"
            assert mod_unused.moderated_calls == []
            assert "30 seconds" in (_fetch_video_row(vid_long)[2] or "")
            assert _wait_event(ws, EVENT_VIDEO_MODERATED)["id"] == vid_long

            # 4. Internal download failure -> moderation_error (issue #2) + WS event
            res = asyncio.run(
                run_moderation(
                    vid_dl_err,
                    f"users/{user_id}/intro/dl.mp4",
                    settings=_test_settings(),
                    storage=FakeStorage(fail_download=True),
                    moderator=FakeModerator(),
                )
            )
            assert res == "moderation_error"
            assert _fetch_video_row(vid_dl_err)[:3] == (
                "moderation_error",
                "loaded",
                "Download failed",
            )
            evt_err = _wait_event(ws, EVENT_VIDEO_MODERATED)
            assert evt_err["id"] == vid_dl_err
            assert evt_err["moderation_status"] == "moderation_error"

            # 5. OpenAI API failure with MODERATION_FAIL_OPEN=False -> moderation_error
            res = asyncio.run(
                run_moderation(
                    vid_api_err,
                    f"users/{user_id}/intro/api.mp4",
                    settings=_test_settings(moderation_fail_open=False),
                    storage=FakeStorage(),
                    moderator=FakeModerator(moderation_error=RuntimeError("503")),
                    duration_fn=lambda _: 10.0,
                    frames_fn=_fake_frames,
                    audio_fn=_fake_audio,
                )
            )
            assert res == "moderation_error"
            assert _fetch_video_row(vid_api_err)[2] == "Moderation API error"
            assert _wait_event(ws, EVENT_VIDEO_MODERATED)["id"] == vid_api_err

            # 6. OpenAI API failure with MODERATION_FAIL_OPEN=True -> approved
            res = asyncio.run(
                run_moderation(
                    vid_fail_open,
                    f"users/{user_id}/intro/open.mp4",
                    settings=_test_settings(moderation_fail_open=True),
                    storage=FakeStorage(),
                    moderator=FakeModerator(moderation_error=RuntimeError("503")),
                    duration_fn=lambda _: 10.0,
                    frames_fn=_fake_frames,
                    audio_fn=_fake_audio,
                )
            )
            assert res == "approved"
            assert _fetch_video_row(vid_fail_open)[:2] == ("approved", "posted")
            assert _wait_event(ws, EVENT_VIDEO_MODERATED)["id"] == vid_fail_open

            # 7. Missing OPENAI_API_KEY: strict defense mode -> moderation_error; dev mode -> ok
            res = asyncio.run(
                run_moderation(
                    vid_no_key_strict,
                    f"users/{user_id}/intro/nokey_strict.mp4",
                    settings=_test_settings(openai_api_key="", moderation_fail_open=False),
                    storage=FakeStorage(),
                    duration_fn=lambda _: 10.0,
                    frames_fn=_fake_frames,
                    audio_fn=_fake_audio,
                )
            )
            assert res == "moderation_error"
            assert _fetch_video_row(vid_no_key_strict)[2] == "OpenAI API key not configured"
            assert _wait_event(ws, EVENT_VIDEO_MODERATED)["id"] == vid_no_key_strict

            res = asyncio.run(
                run_moderation(
                    vid_no_key_dev,
                    f"users/{user_id}/intro/nokey_dev.mp4",
                    settings=_test_settings(openai_api_key="", moderation_fail_open=True),
                    storage=FakeStorage(),
                    duration_fn=lambda _: 10.0,
                    frames_fn=_fake_frames,
                    audio_fn=_fake_audio,
                )
            )
            assert res == "approved"
            assert _fetch_video_row(vid_no_key_dev)[:2] == ("approved", "posted")
            assert _wait_event(ws, EVENT_VIDEO_MODERATED)["id"] == vid_no_key_dev

            # 8. Deleted video mid-moderation is left untouched and does not unpost active video
            res = asyncio.run(
                run_moderation(
                    vid_deleted,
                    f"users/{user_id}/intro/deleted.mp4",
                    settings=_test_settings(),
                    storage=FakeStorage(),
                    moderator=FakeModerator(),
                    duration_fn=lambda _: 10.0,
                    frames_fn=_fake_frames,
                    audio_fn=_fake_audio,
                )
            )
            assert res == "approved"
            assert _fetch_video_row(vid_deleted)[:2] == ("pending", "deleted")
            assert _fetch_video_row(vid_no_key_dev)[1] == "posted"

            # 9. Whisper error with fail_open=False -> moderation_error "Transcription API error"
            res = asyncio.run(
                run_moderation(
                    vid_whisper_fail_strict,
                    f"users/{user_id}/intro/whisper_strict.mp4",
                    settings=_test_settings(moderation_fail_open=False),
                    storage=FakeStorage(),
                    moderator=FakeModerator(whisper_error=RuntimeError("Whisper unreachable")),
                    duration_fn=lambda _: 10.0,
                    frames_fn=_fake_frames,
                    audio_fn=_fake_audio,
                )
            )
            assert res == "moderation_error"
            assert _fetch_video_row(vid_whisper_fail_strict)[2] == "Transcription API error"
            assert _wait_event(ws, EVENT_VIDEO_MODERATED)["id"] == vid_whisper_fail_strict

            # 10. Whisper error with fail_open=True -> approved (falls back to frame-only check)
            res = asyncio.run(
                run_moderation(
                    vid_whisper_fail_open,
                    f"users/{user_id}/intro/whisper_open.mp4",
                    settings=_test_settings(moderation_fail_open=True),
                    storage=FakeStorage(),
                    moderator=FakeModerator(whisper_error=RuntimeError("Whisper unreachable")),
                    duration_fn=lambda _: 10.0,
                    frames_fn=_fake_frames,
                    audio_fn=_fake_audio,
                )
            )
            assert res == "approved"
            assert _fetch_video_row(vid_whisper_fail_open)[:2] == ("approved", "posted")
            assert _wait_event(ws, EVENT_VIDEO_MODERATED)["id"] == vid_whisper_fail_open

            # 11. Empty frames extracted -> moderation_error "Processing failed"
            res = asyncio.run(
                run_moderation(
                    vid_no_frames,
                    f"users/{user_id}/intro/no_frames.mp4",
                    settings=_test_settings(),
                    storage=FakeStorage(),
                    moderator=FakeModerator(),
                    duration_fn=lambda _: 10.0,
                    frames_fn=lambda _v, _t, _d: [],
                    audio_fn=_fake_audio,
                )
            )
            assert res == "moderation_error"
            assert _fetch_video_row(vid_no_frames)[2] == "Processing failed"
            assert _wait_event(ws, EVENT_VIDEO_MODERATED)["id"] == vid_no_frames

            # 12. Duplicate moderation task / beat redelivery ignores non-pending videos
            res = asyncio.run(
                run_moderation(
                    vid_ok,
                    f"users/{user_id}/intro/ok.mp4",
                    settings=_test_settings(),
                    storage=FakeStorage(),
                    moderator=FakeModerator(flagged=["violence"]),
                    duration_fn=lambda _: 14.6,
                    frames_fn=_fake_frames,
                    audio_fn=_fake_audio,
                )
            )
            # vid_ok was already approved, so it stays approved (and unposted)
            assert _fetch_video_row(vid_ok)[:2] == ("approved", "unposted")


@needs_database
def test_requeue_stuck_videos_enqueues_only_old_non_deleted_pending():
    """Beat requeues pending videos older than threshold once and ignores fresh/deleted rows."""
    alembic("upgrade", "head")
    sql("TRUNCATE users, intro_videos RESTART IDENTITY CASCADE")
    user_id = _seed_user("stuck@example.com")

    old_pending = _seed_video(user_id, object_key=f"users/{user_id}/intro/old_p.mp4")
    fresh_pending = _seed_video(user_id, object_key=f"users/{user_id}/intro/fresh_p.mp4")
    old_deleted = _seed_video(
        user_id, object_key=f"users/{user_id}/intro/old_d.mp4", lifecycle_status="deleted"
    )
    old_done = _seed_video(
        user_id, object_key=f"users/{user_id}/intro/old_done.mp4", moderation_status="approved"
    )

    async def _run() -> tuple[list[int], list[int], list[tuple[int, str]]]:
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        enqueued: list[tuple[int, str]] = []
        try:
            async with maker() as session:
                stale = datetime.now(UTC) - timedelta(minutes=15)
                await session.execute(
                    update(IntroVideo)
                    .where(IntroVideo.id.in_([old_pending, old_deleted, old_done]))
                    .values(created_at=stale, updated_at=stale)
                )
                await session.commit()

                first = await requeue_stuck_videos(
                    session,
                    enqueue_fn=lambda vid, key: enqueued.append((vid, key)),
                    stuck_minutes=10,
                )
                # Second immediate run sees refreshed updated_at and does not duplicate-enqueue.
                second = await requeue_stuck_videos(
                    session,
                    enqueue_fn=lambda vid, key: enqueued.append((vid, key)),
                    stuck_minutes=10,
                )
                return first, second, enqueued
        finally:
            await engine.dispose()

    first, second, enqueued = asyncio.run(_run())
    assert first == [old_pending]
    assert second == []
    assert enqueued == [(old_pending, f"users/{user_id}/intro/old_p.mp4")]
    assert fresh_pending != old_pending


@needs_database
@needs_redis
def test_worker_heartbeat_marks_health_worker_component_ok():
    """write_worker_heartbeat sets worker:heartbeat in Redis so /api/health reports worker=ok."""
    with redis.Redis.from_url(TEST_REDIS_URL, decode_responses=True) as r:
        r.delete(WORKER_HEARTBEAT_KEY)

    write_worker_heartbeat(TEST_REDIS_URL, ttl_sec=30)

    with redis.Redis.from_url(TEST_REDIS_URL, decode_responses=True) as r:
        assert r.get(WORKER_HEARTBEAT_KEY) == "1"
        assert 0 < r.ttl(WORKER_HEARTBEAT_KEY) <= 30

    app = build_app(database_url=TEST_DATABASE_URL, redis_url=TEST_REDIS_URL)
    with TestClient(app) as test_client:
        res = test_client.get("/api/health")
        assert res.status_code == 200
        assert res.json()["components"]["worker"] == "ok"


@needs_database
@needs_redis
def test_deleted_account_pending_videos_are_skipped_by_worker_and_beat():
    """Waiting videos owned by deleted accounts are never moderated, approved or re-queued."""
    alembic("upgrade", "head")
    sql("TRUNCATE users, intro_videos RESTART IDENTITY CASCADE")
    deleted_uid = _seed_user("gone@example.com")
    vid_id = _seed_video(deleted_uid, object_key=f"users/{deleted_uid}/intro/gone.mp4")
    sql("UPDATE users SET status = 'deleted', deleted_at = now() WHERE id = :id", id=deleted_uid)

    storage = FakeStorage()
    res = asyncio.run(
        run_moderation(
            vid_id,
            f"users/{deleted_uid}/intro/gone.mp4",
            settings=_test_settings(),
            storage=storage,
            moderator=FakeModerator(),
            duration_fn=lambda _: 10.0,
            frames_fn=_fake_frames,
            audio_fn=_fake_audio,
        )
    )
    assert res == "skipped"
    assert storage.downloaded == []
    assert _fetch_video_row(vid_id)[:2] == ("pending", "loaded")

    # Even if account deletion happened mid-flight before apply_moderation_result, stay pending.
    async def _direct_apply() -> IntroVideo | None:
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        rclient = redis.asyncio.Redis.from_url(TEST_REDIS_URL, decode_responses=True)
        try:
            async with maker() as session:
                return await apply_moderation_result(
                    session,
                    rclient,
                    video_id=vid_id,
                    moderation_status="approved",
                    real_duration_sec=10,
                )
        finally:
            await rclient.aclose()
            await engine.dispose()

    assert asyncio.run(_direct_apply()) is None
    assert _fetch_video_row(vid_id)[:2] == ("pending", "loaded")

    # Beat recovery must skip stuck pending videos of deleted accounts.
    async def _beat_deleted() -> list[int]:
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        stale = datetime.now(UTC) - timedelta(minutes=15)
        try:
            async with maker() as session:
                await session.execute(
                    update(IntroVideo)
                    .where(IntroVideo.id == vid_id)
                    .values(created_at=stale, updated_at=stale)
                )
                await session.commit()
                return await requeue_stuck_videos(
                    session,
                    enqueue_fn=lambda _vid, _key: None,
                    stuck_minutes=10,
                )
        finally:
            await engine.dispose()

    assert asyncio.run(_beat_deleted()) == []


def test_celery_setup_logging_configures_json_handler():
    """Celery worker configures our JSON log formatter without leaking root plain text."""
    assert celery_app.conf.worker_hijack_root_logger is False
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    saved_config = structlog.get_config()
    try:
        _on_setup_logging()
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, structlog.stdlib.ProcessorFormatter)
    finally:
        root.handlers = saved_handlers
        root.setLevel(saved_level)
        structlog.configure(**saved_config)
