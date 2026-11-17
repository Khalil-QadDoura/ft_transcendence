"""The game scheduler (BE-27) never blocks the app's shutdown. No database or Redis needed.

At shutdown the lifespan cancels the scheduler task once. If a library uses up that cancel
(redis-py 8.1.0 does, when the cancel lands while it opens a new connection), the loop must
still stop, and the lifespan must never wait for it forever.
"""

import asyncio
import io
import json
import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from types import SimpleNamespace

import pytest
from conftest import build_app
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.logging import json_handler
from app.game import service as game_service
from app.main import SCHEDULER_STOP_TIMEOUT_SEC


@contextmanager
def captured_logs() -> Iterator[list[dict]]:
    """Collects the JSON log lines written inside the `with` block, as dicts."""
    stream = io.StringIO()
    handler = json_handler(stream)
    logging.getLogger().addHandler(handler)
    lines: list[dict] = []
    try:
        yield lines
    finally:
        logging.getLogger().removeHandler(handler)
        lines.extend(json.loads(line) for line in stream.getvalue().splitlines())


@pytest.mark.anyio
async def test_scheduler_stops_when_a_tick_swallows_the_cancel(monkeypatch):
    swallowed = []

    async def tick_that_swallows_the_cancel(app):
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            if swallowed:  # only the first one, so the cleanup below can still stop the task
                raise
            swallowed.append(True)  # like redis-py while it opens a connection: the cancel is
            return  # used up and the tick returns normally

    monkeypatch.setattr(game_service, "tick_all_active_rooms", tick_that_swallows_the_cancel)
    settings = SimpleNamespace(game_tick_interval_sec=0.01)
    app = SimpleNamespace(state=SimpleNamespace(settings=settings))
    task = asyncio.create_task(game_service.run_scheduler(app))
    try:
        await asyncio.sleep(0.05)  # the scheduler is now inside its first tick
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=2)
        assert done, "run_scheduler went on after its cancel was swallowed inside a tick"
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def test_shutdown_waits_for_a_stuck_scheduler_only_up_to_the_limit(monkeypatch):
    stuck: dict = {}

    async def scheduler_that_loses_the_cancel(app):
        stuck["loop"], stuck["task"] = asyncio.get_running_loop(), asyncio.current_task()
        with suppress(asyncio.CancelledError):
            await asyncio.sleep(3600)  # the lifespan's cancel lands here and is lost
        await asyncio.sleep(3600)  # it goes on, as the real loop did; a later cancel stops it

    monkeypatch.setattr(game_service, "run_scheduler", scheduler_that_loses_the_cancel)
    app = build_app(game_scheduler_enabled=True)

    def start_and_stop():
        with TestClient(app):
            pass

    limit = SCHEDULER_STOP_TIMEOUT_SEC + 2
    with captured_logs() as lines:
        started = time.monotonic()
        thread = threading.Thread(target=start_and_stop, daemon=True)
        thread.start()
        thread.join(timeout=limit)
        elapsed = time.monotonic() - started
        if thread.is_alive():  # the shutdown hangs: free it, so this test fails and ends
            stuck["loop"].call_soon_threadsafe(stuck["task"].cancel)
            thread.join(timeout=5)
    assert elapsed < limit, f"the app took more than {limit} s to shut down"
    assert any(line["event"] == "game scheduler did not stop within 5 s" for line in lines)
    assert any(line["event"] == "shutdown" for line in lines)  # and the rest of it still ran


def test_test_apps_start_the_scheduler_only_when_asked(monkeypatch):
    started = []

    def recording_scheduler(app):  # called when the lifespan creates the task
        started.append(app)
        return asyncio.sleep(0)

    monkeypatch.setattr(game_service, "run_scheduler", recording_scheduler)
    with TestClient(build_app()):
        pass
    assert started == []

    app = build_app(game_scheduler_enabled=True)
    with TestClient(app):
        pass
    assert started == [app]


def test_the_scheduler_is_on_by_default_outside_tests():
    assert Settings.model_fields["game_scheduler_enabled"].default is True
