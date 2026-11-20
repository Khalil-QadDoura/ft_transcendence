"""Unit and real Postgres+Redis+uvicorn tests for Turing Duel matchmaking & rooms (BE-27)."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
import redis
from conftest import (
    DATABASE_SKIP_REASON,
    REDIS_SKIP_REASON,
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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from websockets.sync.client import ClientConnection, connect

from app.auth import security
from app.core.config import Settings
from app.game import repo as game_repo
from app.game import service as game_service
from app.game.constants import MAX_ID, MAX_PARTICIPANTS, PLAYER_LABELS, label_number
from app.game.models import GameParticipant, GameRoom
from app.game.schemas import (
    GameMessageEventOut,
    GameParticipantEventOut,
    ParticipantOut,
    RoomParticipantOut,
)

PASSWORD = "correct horse battery"
PASSWORD_HASH = security.hash_password(PASSWORD)
WAIT_SEC = 5


# Helpers ----------------------------------------------------------------------------------


def delete_game_and_ws_keys(client: redis.Redis) -> None:
    """Remove only game and ws keys created by tests."""
    for prefix in ("game:*", "ws:*"):
        for key in client.scan_iter(prefix):
            client.delete(key)


def new_game_app(**overrides: object):
    defaults = {
        "database_url": TEST_DATABASE_URL,
        "redis_url": TEST_REDIS_URL,
        "game_scheduler_enabled": True,  # these tests rely on the server's ticks
        "game_bot_probability": 0.0,
        "game_bot_min_delay_sec": 0.05,
        "game_bot_max_delay_sec": 0.12,
        "game_wait_timeout_sec": 30.0,
        "game_discussion_sec": 30.0,
        "game_voting_sec": 10.0,
        "game_tick_interval_sec": 0.04,
        "game_bot_chat_min_delay_sec": 0.05,
        "game_bot_chat_max_delay_sec": 0.12,
    }
    defaults.update(overrides)
    return build_app(**defaults)


def create_user_and_login(server: str, email: str) -> tuple[int, str]:
    [(user_id,)] = sql(
        "INSERT INTO users (email, password_hash, is_email_verified)"
        " VALUES (:email, :password_hash, true) RETURNING id",
        email=email,
        password_hash=PASSWORD_HASH,
    )
    resp = httpx2.post(
        f"http://{server}/api/auth/login",
        json={"email": email, "password": PASSWORD},
        headers={"X-Real-IP": f"10.0.{(user_id // 250) % 250}.{(user_id % 250) + 1}"},
    )
    assert resp.status_code == 200, resp.text
    return user_id, resp.json()["access_token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def open_user_ws(server: str, token: str) -> ClientConnection:
    resp = httpx2.post(f"http://{server}/api/ws/ticket", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    ticket = resp.json()["ticket"]
    return connect(f"ws://{server}/ws?ticket={ticket}", open_timeout=WAIT_SEC)


def collect_events_until(
    ws: ClientConnection,
    predicate,
    *,
    timeout: float = 4.0,
) -> list[dict]:
    """Read JSON events from WS until `predicate(events)` is true or timeout expires."""
    events: list[dict] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = max(0.05, deadline - time.monotonic())
        try:
            raw = ws.recv(timeout=min(remaining, 0.25))
        except TimeoutError:
            if predicate(events):
                return events
            continue
        frame = json.loads(raw)
        events.append(frame)
        if predicate(events):
            return events
    assert predicate(events), f"Timed out waiting for event; received: {events}"
    return events


def assert_no_bot_leak_in_room_payload(data: dict) -> None:
    forbidden = {"is_bot", "bot_plan", "bot_count", "user_id"}
    assert forbidden.isdisjoint(data.keys()), f"Bot leak in room keys: {data.keys()}"
    assert 1 <= data["my_participant_id"] <= MAX_PARTICIPANTS
    for participant in data["participants"]:
        assert set(participant.keys()) == {"id", "display_label", "is_you"}
        assert isinstance(participant["id"], int)
        assert participant["display_label"] in PLAYER_LABELS
        assert 1 <= participant["id"] <= MAX_PARTICIPANTS
        assert participant["id"] == int(participant["display_label"].rsplit(" ", 1)[-1])
        assert isinstance(participant["is_you"], bool)


def assert_no_bot_leak_in_ws_event(frame: dict) -> None:
    payload = frame.get("payload") or {}
    if isinstance(payload, dict):
        assert "is_bot" not in payload
        assert "bot_plan" not in payload
        assert "bot_count" not in payload
        participant = payload.get("participant")
        if isinstance(participant, dict):
            assert set(participant.keys()) == {"id", "display_label"}
            assert 1 <= participant["id"] <= MAX_PARTICIPANTS
            assert participant["id"] == int(participant["display_label"].rsplit(" ", 1)[-1])
        if "participant_id" in payload:
            assert 1 <= payload["participant_id"] <= MAX_PARTICIPANTS
            if "display_label" in payload:
                assert payload["participant_id"] == int(payload["display_label"].rsplit(" ", 1)[-1])


# Unit & validation tests (no DB or Redis required) --------------------------------------


def test_game_routes_require_auth(client: TestClient) -> None:
    assert client.post("/api/game/queue/join").status_code == 401
    assert client.delete("/api/game/queue/leave").status_code == 401
    assert client.get("/api/game/rooms/1").status_code == 401
    assert client.post("/api/game/rooms/1/start").status_code == 401


def test_room_id_path_validation() -> None:
    user = type("U", (), {"id": 1, "status": "active", "token_version": 1})()
    app = build_app()
    from app.auth.deps import get_current_user

    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as authed:
        for bad_id in (0, -5, MAX_ID + 1):
            r1 = authed.get(f"/api/game/rooms/{bad_id}")
            r2 = authed.post(f"/api/game/rooms/{bad_id}/start")
            assert r1.status_code == 422
            assert r2.status_code == 422
            assert "path → room_id" in r1.json()["error"]["detail"]
            assert "path → room_id" in r2.json()["error"]["detail"]


def test_bot_plan_respects_probability_and_serializer_has_no_leak() -> None:
    now = datetime.now(UTC)
    s_no = Settings(
        database_url="postgresql+asyncpg://test:test@localhost:5432/test",
        jwt_secret="0" * 32,
        game_bot_probability=0.0,
    )
    assert game_service._build_initial_bot_plan(now, s_no) == {"joins": [], "chats": []}

    s_yes = Settings(
        database_url="postgresql+asyncpg://test:test@localhost:5432/test",
        jwt_secret="0" * 32,
        game_bot_probability=1.0,
        game_bot_min_delay_sec=10.0,
        game_bot_max_delay_sec=30.0,
    )
    plan = game_service._build_initial_bot_plan(now, s_yes)
    assert 1 <= len(plan["joins"]) <= 4
    assert plan["joins"] == sorted(plan["joins"])
    for ts in plan["joins"]:
        assert 9.99 <= ts - now.timestamp() <= 30.01

    room = GameRoom(
        id=9,
        target_size=5,
        state="waiting",
        room_expires_at=now + timedelta(seconds=180),
        bot_plan=plan,
    )
    human = GameParticipant(id=11, room_id=9, user_id=7, display_label="Player 2")
    bot = GameParticipant(id=12, room_id=9, user_id=None, display_label="Player 4")
    out = game_service._serialize_room(room, [human, bot], human, s_yes).model_dump()
    assert_no_bot_leak_in_room_payload(out)
    assert out["my_participant_id"] == 2
    assert out["participant_count"] == 2
    assert out["participants"][0]["id"] == 2
    assert out["participants"][0]["is_you"] is True
    assert out["participants"][1]["id"] == 4
    assert out["participants"][1]["is_you"] is False


def test_label_numbers_hide_database_participant_ids() -> None:
    """BE-35: clients see participants only by 1-based label number (1–5), never DB PK."""
    # 1. label_number helper
    assert label_number("Player 1") == 1
    assert label_number("Player 3") == 3
    assert label_number("Player 5") == 5
    assert label_number("Unknown") == 0
    assert label_number("") == 0

    # 2. ParticipantOut hides DB PK in favor of label number
    p_human = GameParticipant(id=999, room_id=1, user_id=42, display_label="Player 3")
    out_p = ParticipantOut.model_validate(p_human)
    assert out_p.id == 3
    assert out_p.display_label == "Player 3"
    assert out_p.model_dump() == {"id": 3, "display_label": "Player 3"}

    # 3. RoomParticipantOut hides DB PK in favor of label number
    out_rp = RoomParticipantOut.model_validate(
        {"id": 888, "display_label": "Player 1", "is_you": True}
    )
    assert out_rp.id == 1
    assert out_rp.display_label == "Player 1"
    assert out_rp.is_you is True
    assert out_rp.model_dump() == {"id": 1, "display_label": "Player 1", "is_you": True}

    # 4. GameMessageEventOut hides DB PK in favor of label number
    out_msg = GameMessageEventOut.model_validate(
        {"id": 42, "participant_id": 777, "display_label": "Player 5", "text": "hello"}
    )
    assert out_msg.participant_id == 5
    assert out_msg.id == 42
    assert out_msg.display_label == "Player 5"
    assert out_msg.text == "hello"

    # 5. GameParticipantEventOut validates participant with label number
    out_event = GameParticipantEventOut(
        room_id=1,
        participant=ParticipantOut.model_validate(p_human),
        participant_count=2,
        room_expires_at=None,
    )
    assert out_event.participant.id == 3
    assert out_event.participant.display_label == "Player 3"

    # 6. _serialize_room with 5 participants having DB PKs != label numbers
    now = datetime.now(UTC)
    settings = Settings(
        database_url="postgresql+asyncpg://test:test@localhost:5432/test",
        jwt_secret="0" * 32,
    )
    room = GameRoom(
        id=1,
        target_size=5,
        state="discussion",
        discussion_started_at=now,
    )
    participants = [
        GameParticipant(id=101, room_id=1, user_id=1, display_label="Player 3"),
        GameParticipant(id=102, room_id=1, user_id=2, display_label="Player 1"),
        GameParticipant(id=103, room_id=1, user_id=None, display_label="Player 5"),
        GameParticipant(id=104, room_id=1, user_id=4, display_label="Player 2"),
        GameParticipant(id=105, room_id=1, user_id=None, display_label="Player 4"),
    ]
    me = participants[0]  # Player 3 (DB id 101)
    room_out = game_service._serialize_room(room, participants, me, settings).model_dump()
    assert_no_bot_leak_in_room_payload(room_out)
    assert room_out["my_participant_id"] == 3
    assert room_out["participants"][0]["id"] == 3
    assert room_out["participants"][0]["is_you"] is True
    assert room_out["participants"][1]["id"] == 1
    assert room_out["participants"][1]["is_you"] is False
    assert room_out["participants"][2]["id"] == 5
    assert room_out["participants"][3]["id"] == 2
    assert room_out["participants"][4]["id"] == 4
    for p in room_out["participants"]:
        assert p["id"] not in {101, 102, 103, 104, 105}


# Integration tests (real Postgres + Redis + uvicorn) -------------------------------------


@pytest.fixture(scope="module")
def game_schema_at_head():
    if DATABASE_SKIP_REASON is not None:
        pytest.skip(DATABASE_SKIP_REASON)
    alembic("upgrade", "head")


@pytest.fixture
def clean_db_and_redis(game_schema_at_head) -> Iterator[redis.Redis]:
    if REDIS_SKIP_REASON is not None:
        pytest.skip(REDIS_SKIP_REASON)
    client = redis.Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    delete_game_and_ws_keys(client)
    sql(
        "TRUNCATE game_votes, game_messages, game_participants, game_rooms RESTART IDENTITY CASCADE"
    )
    sql("TRUNCATE users RESTART IDENTITY CASCADE")
    yield client
    delete_game_and_ws_keys(client)
    client.close()


@needs_database
@needs_redis
def test_room_no_bots_start_now_and_autostart_at_five(clean_db_and_redis) -> None:
    app = new_game_app(game_bot_probability=0.0, game_wait_timeout_sec=60.0)
    with running_server(app) as srv:
        tokens = [create_user_and_login(srv, f"h{i}@example.com")[1] for i in range(6)]
        with open_user_ws(srv, tokens[0]) as ws0, open_user_ws(srv, tokens[1]) as ws1:
            # First human creates room 1; Start now rejected with 409 at 1 participant.
            j0 = httpx2.post(f"http://{srv}/api/game/queue/join", headers=auth_headers(tokens[0]))
            assert j0.status_code == 202
            room_a = j0.json()["room_id"]
            assert j0.json()["message"] == "queued"

            too_early = httpx2.post(
                f"http://{srv}/api/game/rooms/{room_a}/start",
                headers=auth_headers(tokens[0]),
            )
            assert too_early.status_code == 409

            # Second human joins oldest waiting room (room_a).
            j1 = httpx2.post(f"http://{srv}/api/game/queue/join", headers=auth_headers(tokens[1]))
            assert j1.status_code == 202
            assert j1.json()["room_id"] == room_a

            # Non-participant rejected with 403; unknown room 404.
            assert (
                httpx2.get(
                    f"http://{srv}/api/game/rooms/{room_a}",
                    headers=auth_headers(tokens[2]),
                ).status_code
                == 403
            )
            assert (
                httpx2.get(
                    f"http://{srv}/api/game/rooms/999999",
                    headers=auth_headers(tokens[0]),
                ).status_code
                == 404
            )

            # Start now succeeds at 2 participants -> both receive game_started.
            started = httpx2.post(
                f"http://{srv}/api/game/rooms/{room_a}/start",
                headers=auth_headers(tokens[0]),
            )
            assert started.status_code == 200
            room_a_data = started.json()
            assert room_a_data["state"] == "discussion"
            assert room_a_data["phase_ends_at"] is not None
            assert_no_bot_leak_in_room_payload(room_a_data)

            ev0 = collect_events_until(
                ws0, lambda evs: any(e["type"] == "game_started" for e in evs)
            )
            ev1 = collect_events_until(
                ws1, lambda evs: any(e["type"] == "game_started" for e in evs)
            )
            assert any(e["type"] == "game_room_formed" for e in ev0)
            assert any(e["type"] == "game_participant_joined" for e in ev0)
            assert any(e["type"] == "game_started" for e in ev1)

        # Room B fills with 5 new humans (fresh accounts) -> auto-starts on 5th join.
        room_b_tokens = [create_user_and_login(srv, f"b{i}@example.com")[1] for i in range(6)]
        room_b_id = None
        for idx in range(4):
            r = httpx2.post(
                f"http://{srv}/api/game/queue/join", headers=auth_headers(room_b_tokens[idx])
            )
            assert r.status_code == 202
            if room_b_id is None:
                room_b_id = r.json()["room_id"]
            else:
                assert r.json()["room_id"] == room_b_id
            state_resp = httpx2.get(
                f"http://{srv}/api/game/rooms/{room_b_id}",
                headers=auth_headers(room_b_tokens[0]),
            )
            assert state_resp.json()["state"] == "waiting"

        # 5th human triggers immediate auto-start.
        r5 = httpx2.post(
            f"http://{srv}/api/game/queue/join", headers=auth_headers(room_b_tokens[4])
        )
        assert r5.status_code == 202
        assert r5.json()["room_id"] == room_b_id
        after_5 = httpx2.get(
            f"http://{srv}/api/game/rooms/{room_b_id}",
            headers=auth_headers(room_b_tokens[0]),
        ).json()
        assert after_5["state"] == "discussion"
        assert after_5["participant_count"] == 5

        # 6th human opens a new room rather than overflowing Room B.
        r6 = httpx2.post(
            f"http://{srv}/api/game/queue/join", headers=auth_headers(room_b_tokens[5])
        )
        assert r6.status_code == 202
        assert r6.json()["room_id"] != room_b_id


@needs_database
@needs_redis
def test_room_with_four_bots_autostarts_and_extra_bots_dropped(
    clean_db_and_redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(game_service.random, "randint", lambda a, b: 4)
    app = new_game_app(
        game_bot_probability=1.0,
        game_bot_min_delay_sec=0.06,
        game_bot_max_delay_sec=0.18,
        game_wait_timeout_sec=30.0,
        game_tick_interval_sec=0.03,
    )
    with running_server(app) as srv:
        _, tok0 = create_user_and_login(srv, "solo_bot@example.com")
        with open_user_ws(srv, tok0) as ws0:
            res = httpx2.post(f"http://{srv}/api/game/queue/join", headers=auth_headers(tok0))
            assert res.status_code == 202
            room1 = res.json()["room_id"]

            events = collect_events_until(
                ws0,
                lambda evs: any(e["type"] == "game_started" for e in evs),
                timeout=4.0,
            )
            joined_counts = [
                e["payload"]["participant_count"]
                for e in events
                if e["type"] == "game_participant_joined"
            ]
            assert joined_counts == [1, 2, 3, 4, 5]
            for ev in events:
                assert_no_bot_leak_in_ws_event(ev)

            room_data = httpx2.get(
                f"http://{srv}/api/game/rooms/{room1}", headers=auth_headers(tok0)
            ).json()
            assert room_data["state"] == "discussion"
            assert room_data["participant_count"] == 5
            assert_no_bot_leak_in_room_payload(room_data)
            labels = [p["display_label"] for p in room_data["participants"]]
            assert len(set(labels)) == 5

    # Second room: 4 bots scheduled later while 3 humans join early -> extra 2 bots dropped at 5.
    app2 = new_game_app(
        game_bot_probability=1.0,
        game_bot_min_delay_sec=0.25,
        game_bot_max_delay_sec=0.40,
        game_wait_timeout_sec=30.0,
        game_tick_interval_sec=0.04,
    )
    with running_server(app2) as srv2:
        tokens = [create_user_and_login(srv2, f"mix{i}@example.com")[1] for i in range(3)]
        room2 = None
        for t in tokens:
            resp = httpx2.post(f"http://{srv2}/api/game/queue/join", headers=auth_headers(t))
            assert resp.status_code == 202
            room2 = resp.json()["room_id"]

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            data = httpx2.get(
                f"http://{srv2}/api/game/rooms/{room2}", headers=auth_headers(tokens[0])
            ).json()
            if data["state"] == "discussion":
                break
            time.sleep(0.05)

        time.sleep(0.5)  # Past original max bot delay: no extra bots joined after start.
        final_data = httpx2.get(
            f"http://{srv2}/api/game/rooms/{room2}", headers=auth_headers(tokens[0])
        ).json()
        assert final_data["state"] == "discussion"
        assert final_data["participant_count"] == 5
        [(db_count,)] = sql(
            "SELECT COUNT(*) FROM game_participants WHERE room_id = :rid", rid=room2
        )
        assert db_count == 5
        [(bot_plan,)] = sql("SELECT bot_plan FROM game_rooms WHERE id = :rid", rid=room2)
        assert (bot_plan or {}).get("joins", []) == []


@needs_database
@needs_redis
def test_start_now_race_exactly_one_game_start(clean_db_and_redis) -> None:
    app = new_game_app(game_bot_probability=0.0, game_wait_timeout_sec=30.0)
    with running_server(app) as srv:
        _, tok1 = create_user_and_login(srv, "race1@example.com")
        _, tok2 = create_user_and_login(srv, "race2@example.com")
        with open_user_ws(srv, tok1) as ws1, open_user_ws(srv, tok2) as ws2:
            r1 = httpx2.post(f"http://{srv}/api/game/queue/join", headers=auth_headers(tok1))
            r2 = httpx2.post(f"http://{srv}/api/game/queue/join", headers=auth_headers(tok2))
            room_id = r1.json()["room_id"]
            assert r2.json()["room_id"] == room_id

            barrier = threading.Barrier(2)

            def press_start(token: str) -> httpx2.Response:
                barrier.wait(timeout=3.0)
                return httpx2.post(
                    f"http://{srv}/api/game/rooms/{room_id}/start",
                    headers=auth_headers(token),
                )

            with ThreadPoolExecutor(max_workers=2) as pool:
                res1, res2 = list(pool.map(press_start, [tok1, tok2]))

            assert res1.status_code == 200
            assert res2.status_code == 200
            assert res1.json()["state"] == "discussion"
            assert res2.json()["state"] == "discussion"

            ev1 = collect_events_until(
                ws1, lambda evs: any(e["type"] == "game_started" for e in evs)
            )
            ev2 = collect_events_until(
                ws2, lambda evs: any(e["type"] == "game_started" for e in evs)
            )
            time.sleep(0.15)
            for ws, evs in ((ws1, ev1), (ws2, ev2)):
                while True:
                    try:
                        evs.append(json.loads(ws.recv(timeout=0.05)))
                    except TimeoutError:
                        break
                started_events = [e for e in evs if e["type"] == "game_started"]
                assert len(started_events) == 1


@needs_database
@needs_redis
def test_timer_expiry_starts_game_with_two_participants(clean_db_and_redis) -> None:
    app = new_game_app(
        game_bot_probability=0.0,
        game_wait_timeout_sec=0.4,
        game_tick_interval_sec=0.04,
    )
    with running_server(app) as srv:
        _, tok1 = create_user_and_login(srv, "exp2_1@example.com")
        _, tok2 = create_user_and_login(srv, "exp2_2@example.com")
        with open_user_ws(srv, tok1) as ws1, open_user_ws(srv, tok2) as ws2:
            j1 = httpx2.post(f"http://{srv}/api/game/queue/join", headers=auth_headers(tok1))
            j2 = httpx2.post(f"http://{srv}/api/game/queue/join", headers=auth_headers(tok2))
            room_id = j1.json()["room_id"]
            assert j2.json()["room_id"] == room_id

            collect_events_until(
                ws1, lambda evs: any(e["type"] == "game_started" for e in evs), timeout=3.0
            )
            collect_events_until(
                ws2, lambda evs: any(e["type"] == "game_started" for e in evs), timeout=3.0
            )
            room = httpx2.get(
                f"http://{srv}/api/game/rooms/{room_id}", headers=auth_headers(tok1)
            ).json()
            assert room["state"] == "discussion"
            assert room["participant_count"] == 2


@needs_database
@needs_redis
def test_timer_expiry_closes_one_participant_room(clean_db_and_redis) -> None:
    app = new_game_app(
        game_bot_probability=0.0,
        game_wait_timeout_sec=0.35,
        game_tick_interval_sec=0.04,
    )
    with running_server(app) as srv:
        _, tok = create_user_and_login(srv, "solo_exp@example.com")
        with open_user_ws(srv, tok) as ws:
            j1 = httpx2.post(f"http://{srv}/api/game/queue/join", headers=auth_headers(tok))
            room_id = j1.json()["room_id"]

            events = collect_events_until(
                ws,
                lambda evs: any(e["type"] == "game_room_closed" for e in evs),
                timeout=3.0,
            )
            closed_ev = next(e for e in events if e["type"] == "game_room_closed")
            assert closed_ev["payload"] == {"room_id": room_id}

            room = httpx2.get(
                f"http://{srv}/api/game/rooms/{room_id}", headers=auth_headers(tok)
            ).json()
            assert room["state"] == "closed"

            # Human returns to lobby and can queue into a new room.
            j2 = httpx2.post(f"http://{srv}/api/game/queue/join", headers=auth_headers(tok))
            assert j2.status_code == 202
            assert j2.json()["room_id"] != room_id


@needs_database
@needs_redis
def test_two_workers_never_create_duplicate_rooms_on_concurrent_join(clean_db_and_redis) -> None:
    app1 = new_game_app(game_bot_probability=0.0, game_wait_timeout_sec=30.0)
    app2 = new_game_app(game_bot_probability=0.0, game_wait_timeout_sec=30.0)
    with running_server(app1) as srv1, running_server(app2) as srv2:
        _, tok1 = create_user_and_login(srv1, "w1@example.com")
        _, tok2 = create_user_and_login(srv2, "w2@example.com")
        barrier = threading.Barrier(2)

        def join_on(target: tuple[str, str]) -> httpx2.Response:
            srv, token = target
            barrier.wait(timeout=3.0)
            return httpx2.post(f"http://{srv}/api/game/queue/join", headers=auth_headers(token))

        with ThreadPoolExecutor(max_workers=2) as pool:
            r1, r2 = list(pool.map(join_on, [(srv1, tok1), (srv2, tok2)]))

        assert r1.status_code == 202
        assert r2.status_code == 202
        assert r1.json()["room_id"] == r2.json()["room_id"]
        [(room_count,)] = sql("SELECT COUNT(*) FROM game_rooms")
        assert room_count == 1


@needs_database
@needs_redis
def test_scheduled_bot_joins_survive_api_restart(
    clean_db_and_redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(game_service.random, "randint", lambda a, b: 2)
    app1 = new_game_app(
        game_bot_probability=1.0,
        game_bot_min_delay_sec=0.35,
        game_bot_max_delay_sec=0.45,
        game_wait_timeout_sec=30.0,
        game_tick_interval_sec=0.04,
    )
    with running_server(app1) as srv1:
        _, tok = create_user_and_login(srv1, "restart@example.com")
        room_id = httpx2.post(
            f"http://{srv1}/api/game/queue/join", headers=auth_headers(tok)
        ).json()["room_id"]
        # Room currently only has the 1 human before srv1 shuts down.
        pre = httpx2.get(
            f"http://{srv1}/api/game/rooms/{room_id}", headers=auth_headers(tok)
        ).json()
        assert pre["participant_count"] == 1

    # Start a brand new API process pointing at the same DB & Redis.
    app2 = new_game_app(
        game_bot_probability=1.0,
        game_bot_min_delay_sec=0.35,
        game_bot_max_delay_sec=0.45,
        game_wait_timeout_sec=30.0,
        game_tick_interval_sec=0.04,
    )
    with running_server(app2) as srv2:
        deadline = time.monotonic() + 3.0
        post = None
        while time.monotonic() < deadline:
            post = httpx2.get(
                f"http://{srv2}/api/game/rooms/{room_id}", headers=auth_headers(tok)
            ).json()
            if post["participant_count"] == 3:
                break
            time.sleep(0.05)
        assert post is not None and post["participant_count"] == 3


@needs_database
@needs_redis
def test_leave_waiting_room_frees_label_and_last_human_closes_room(clean_db_and_redis) -> None:
    app = new_game_app(game_bot_probability=0.0, game_wait_timeout_sec=30.0)
    with running_server(app) as srv:
        _, tok1 = create_user_and_login(srv, "lv1@example.com")
        _, tok2 = create_user_and_login(srv, "lv2@example.com")
        with open_user_ws(srv, tok1) as ws1:
            r1 = httpx2.post(f"http://{srv}/api/game/queue/join", headers=auth_headers(tok1))
            r2 = httpx2.post(f"http://{srv}/api/game/queue/join", headers=auth_headers(tok2))
            room_id = r1.json()["room_id"]
            assert r2.json()["room_id"] == room_id

            before = httpx2.get(
                f"http://{srv}/api/game/rooms/{room_id}", headers=auth_headers(tok1)
            ).json()
            assert before["participant_count"] == 2
            orig_expiry = before["room_expires_at"]

            lv2 = httpx2.delete(f"http://{srv}/api/game/queue/leave", headers=auth_headers(tok2))
            assert lv2.status_code == 204

            events = collect_events_until(
                ws1, lambda evs: any(e["type"] == "game_participant_left" for e in evs)
            )
            left_ev = next(e for e in events if e["type"] == "game_participant_left")
            assert left_ev["payload"]["participant_count"] == 1
            assert left_ev["payload"]["room_id"] == room_id

            after = httpx2.get(
                f"http://{srv}/api/game/rooms/{room_id}", headers=auth_headers(tok1)
            ).json()
            assert after["participant_count"] == 1
            assert after["room_expires_at"] == orig_expiry

            # Last human leaves -> room closes.
            lv1 = httpx2.delete(f"http://{srv}/api/game/queue/leave", headers=auth_headers(tok1))
            assert lv1.status_code == 204
            [(state, plan)] = sql(
                "SELECT state, bot_plan FROM game_rooms WHERE id = :rid", rid=room_id
            )
            assert state == "closed"
            assert plan is None


@needs_database
@needs_redis
def test_discussion_bot_chat_and_server_phase_loop(
    clean_db_and_redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(game_service.random, "randint", lambda a, b: 1)
    app = new_game_app(
        game_bot_probability=1.0,
        game_bot_min_delay_sec=0.05,
        game_bot_max_delay_sec=0.08,
        game_wait_timeout_sec=30.0,
        game_discussion_sec=0.65,
        game_voting_sec=0.35,
        game_tick_interval_sec=0.04,
        game_bot_chat_min_delay_sec=0.05,
        game_bot_chat_max_delay_sec=0.15,
    )
    with running_server(app) as srv:
        _, tok = create_user_and_login(srv, "phases@example.com")
        with open_user_ws(srv, tok) as ws:
            room_id = httpx2.post(
                f"http://{srv}/api/game/queue/join", headers=auth_headers(tok)
            ).json()["room_id"]

            # Wait for the 1 planned bot to join so count == 2.
            collect_events_until(
                ws,
                lambda evs: any(
                    e["type"] == "game_participant_joined"
                    and e["payload"]["participant_count"] == 2
                    for e in evs
                ),
                timeout=3.0,
            )

            started = httpx2.post(
                f"http://{srv}/api/game/rooms/{room_id}/start",
                headers=auth_headers(tok),
            )
            assert started.status_code == 200

            events = collect_events_until(
                ws,
                lambda evs: any(e["type"] == "game_phase_finished" for e in evs),
                timeout=4.0,
            )
            types = [e["type"] for e in events]
            assert "game_started" in types
            assert "game_message" in types
            assert "game_phase_voting" in types
            assert "game_phase_finished" in types

            bot_msg = next(e for e in events if e["type"] == "game_message")
            assert set(bot_msg["payload"].keys()) == {
                "id",
                "participant_id",
                "display_label",
                "text",
            }
            assert 1 <= bot_msg["payload"]["participant_id"] <= MAX_PARTICIPANTS
            assert bot_msg["payload"]["participant_id"] == int(
                bot_msg["payload"]["display_label"].rsplit(" ", 1)[-1]
            )

            room = httpx2.get(
                f"http://{srv}/api/game/rooms/{room_id}", headers=auth_headers(tok)
            ).json()
            assert room["state"] == "finished"


@pytest.mark.anyio
@needs_database
async def test_get_room_for_update_forces_refresh_of_stale_identity_map(
    game_schema_at_head,
) -> None:
    """Preloaded room in session A must refresh when session B commits state change."""
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as session_a, session_maker() as session_b:
        room = GameRoom(target_size=5, state="waiting")
        session_b.add(room)
        await session_b.commit()
        await session_b.refresh(room)
        room_id = room.id

        # Session A preloads the room into identity map
        loaded_a = await session_a.scalar(select(GameRoom).where(GameRoom.id == room_id))
        assert loaded_a is not None
        assert loaded_a.state == "waiting"

        # Session B transitions room to discussion and commits
        loaded_b = await session_b.scalar(select(GameRoom).where(GameRoom.id == room_id))
        assert loaded_b is not None
        loaded_b.state = "discussion"
        await session_b.commit()

        # Session A calls get_room_for_update; with populate_existing=True,
        # it MUST refresh the identity-map instance to 'discussion'
        locked_a = await game_repo.get_room_for_update(session_a, room_id)
        assert locked_a is not None
        assert locked_a.state == "discussion"
        assert loaded_a.state == "discussion"

    await engine.dispose()


@needs_database
@needs_redis
def test_concurrent_start_vs_leave_queue_does_not_remove_participant(
    clean_db_and_redis,
) -> None:
    """A room start must prevent concurrent leave_queue from removing the participant."""
    app = new_game_app(game_bot_probability=0.0, game_wait_timeout_sec=30.0)
    with running_server(app) as srv:
        _, tok1 = create_user_and_login(srv, "cstart1@example.com")
        _, tok2 = create_user_and_login(srv, "cstart2@example.com")
        r1 = httpx2.post(f"http://{srv}/api/game/queue/join", headers=auth_headers(tok1))
        r2 = httpx2.post(f"http://{srv}/api/game/queue/join", headers=auth_headers(tok2))
        room_id = r1.json()["room_id"]
        assert r2.json()["room_id"] == room_id

        # Start the room
        started = httpx2.post(
            f"http://{srv}/api/game/rooms/{room_id}/start",
            headers=auth_headers(tok1),
        )
        assert started.status_code == 200
        assert started.json()["state"] == "discussion"

        # User 2 calls leave_queue while game is in discussion
        leave_resp = httpx2.delete(
            f"http://{srv}/api/game/queue/leave",
            headers=auth_headers(tok2),
        )
        assert leave_resp.status_code == 204

        # Participant is NOT removed from active discussion room
        room = httpx2.get(
            f"http://{srv}/api/game/rooms/{room_id}",
            headers=auth_headers(tok1),
        ).json()
        assert room["state"] == "discussion"
        assert room["participant_count"] == 2
