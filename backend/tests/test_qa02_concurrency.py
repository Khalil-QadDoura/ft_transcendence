"""Multi-user, two-worker concurrency suite: chat, friends, games, applications, jobs (QA-02)."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack

import httpx2
import pytest
import redis
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
from websockets.sync.client import ClientConnection, connect

from app.auth import security

pytestmark = [needs_database, needs_redis]

PASSWORD = "correct horse battery"
PASSWORD_HASH = security.hash_password(PASSWORD)
WAIT = 6


@pytest.fixture(scope="module", autouse=True)
def schema_at_head() -> None:
    alembic("upgrade", "head")


def _clear_redis(client: redis.Redis) -> None:
    for pattern in ("ws:*", "game:*", "presence:*", "job:view:*", "LIMITER*"):
        for key in client.scan_iter(pattern):
            client.delete(key)


@pytest.fixture
def clean_env() -> Iterator[redis.Redis]:
    """Reset PostgreSQL app tables and Redis transient keys around each concurrency test."""
    client = redis.Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    _clear_redis(client)
    sql(
        "TRUNCATE game_votes, game_messages, game_participants, game_rooms, messages,"
        " conversation_participants, conversations, application_events, applications,"
        " job_views, jobs, companies, intro_videos, friendships, users RESTART IDENTITY CASCADE"
    )
    sql("ALTER SEQUENCE game_participants_id_seq RESTART WITH 1001")
    yield client
    _clear_redis(client)
    client.close()


def _app(**overrides: object):
    settings: dict[str, object] = {
        "database_url": TEST_DATABASE_URL,
        "redis_url": TEST_REDIS_URL,
        "game_scheduler_enabled": False,
        "game_bot_probability": 0.0,
    }
    settings.update(overrides)
    return build_app(**settings)


def _create_verified_user(
    srv: str,
    email: str,
    *,
    first_name: str = "User",
    last_name: str = "Demo",
    position: str = "Engineer",
) -> tuple[int, dict[str, str]]:
    [(uid,)] = sql(
        "INSERT INTO users"
        " (email, password_hash, is_email_verified, first_name, last_name, position)"
        " VALUES (:email, :pw, true, :fn, :ln, :pos) RETURNING id",
        email=email,
        pw=PASSWORD_HASH,
        fn=first_name,
        ln=last_name,
        pos=position,
    )
    res = httpx2.post(
        f"http://{srv}/api/auth/login",
        json={"email": email, "password": PASSWORD},
        headers={"X-Real-IP": f"10.88.0.{uid % 250 + 1}"},
    )
    assert res.status_code == 200, res.text
    hdrs = {
        "Authorization": f"Bearer {res.json()['access_token']}",
        "X-Real-IP": f"10.88.0.{uid % 250 + 1}",
    }
    return uid, hdrs


def _issue_ticket(srv: str, headers: dict[str, str]) -> str:
    res = httpx2.post(f"http://{srv}/api/ws/ticket", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()["ticket"]


def _recv_until(ws: ClientConnection, expected: set[str], count: int) -> list[dict]:
    collected: list[dict] = []
    deadline = time.monotonic() + WAIT
    while len(collected) < count and time.monotonic() < deadline:
        remaining = max(0.05, deadline - time.monotonic())
        frame = json.loads(ws.recv(timeout=remaining))
        if frame.get("type") in expected:
            collected.append(frame)
    return collected


# Tests ---------------------------------------------------------------------------------------


def test_chat_parallel_send_idempotency_and_edit_delete_across_two_workers(clean_env) -> None:
    """Two users send messages at the exact same moment across two API workers; identical
    idempotency keys produce one row; concurrent edit + delete + reader GET remain consistent.
    """
    with running_server(_app()) as srv1, running_server(_app()) as srv2:
        alice_id, alice_h = _create_verified_user(srv1, "alice@example.com", first_name="Alice")
        bob_id, bob_h = _create_verified_user(srv2, "bob@example.com", first_name="Bob")

        conv_res = httpx2.post(
            f"http://{srv1}/api/conversations",
            json={"type": "direct", "peer_user_id": bob_id},
            headers=alice_h,
        )
        assert conv_res.status_code == 201, conv_res.text
        conv_id = conv_res.json()["id"]

        t1 = _issue_ticket(srv1, alice_h)
        t2 = _issue_ticket(srv2, bob_h)
        with (
            connect(f"ws://{srv1}/ws?ticket={t1}") as alice_ws,
            connect(f"ws://{srv2}/ws?ticket={t2}") as bob_ws,
        ):
            # 1. Both users send messages simultaneously across srv1 & srv2.
            barrier = threading.Barrier(2, timeout=WAIT)

            def _send(args: tuple[str, dict[str, str], str, str]) -> tuple[int, int]:
                srv, hdrs, content, idem = args
                barrier.wait()
                resp = httpx2.post(
                    f"http://{srv}/api/conversations/{conv_id}/messages",
                    json={"content": content, "idempotency_key": idem},
                    headers=hdrs,
                )
                return resp.status_code, resp.json()["items"][0]["id"]

            with ThreadPoolExecutor(max_workers=2) as pool:
                res_parallel = list(
                    pool.map(
                        _send,
                        [
                            (srv1, alice_h, "Hello from Alice", "qa02-alice-1"),
                            (srv2, bob_h, "Hello from Bob", "qa02-bob-1"),
                        ],
                    )
                )
            assert all(code == 200 for code, _ in res_parallel)
            alice_msg_id = res_parallel[0][1]
            bob_msg_id = res_parallel[1][1]
            assert alice_msg_id != bob_msg_id

            # Redis pub/sub delivers messages across both workers.
            bob_frames = _recv_until(bob_ws, {"message"}, 2)
            alice_frames = _recv_until(alice_ws, {"message"}, 2)
            assert {f["payload"]["content"] for f in bob_frames} == {
                "Hello from Alice",
                "Hello from Bob",
            }
            assert {f["payload"]["content"] for f in alice_frames} == {
                "Hello from Alice",
                "Hello from Bob",
            }

            # 2. Same idempotency_key racing across srv1 and srv2 -> exactly 1 DB message.
            with ThreadPoolExecutor(max_workers=2) as pool:
                idem_res = list(
                    pool.map(
                        _send,
                        [
                            (srv1, alice_h, "Deduped message", "qa02-dup-key"),
                            (srv2, alice_h, "Deduped message", "qa02-dup-key"),
                        ],
                    )
                )
            assert [c for c, _ in idem_res] == [200, 200]
            assert idem_res[0][1] == idem_res[1][1]
            dup_msg_id = idem_res[0][1]
            msg_count = sql(
                "SELECT COUNT(*) FROM messages WHERE conversation_id = :cid",
                cid=conv_id,
            )
            assert msg_count == [(3,)]

            # 3. Edit + delete + reader GET racing across both workers -> zero errors, live events.
            b3 = threading.Barrier(3, timeout=WAIT)

            def _edit() -> int:
                b3.wait()
                return httpx2.patch(
                    f"http://{srv1}/api/conversations/{conv_id}/messages/{alice_msg_id}",
                    json={"content": "Hello from Alice (edited)"},
                    headers=alice_h,
                ).status_code

            def _delete() -> int:
                b3.wait()
                return httpx2.delete(
                    f"http://{srv2}/api/conversations/{conv_id}/messages/{dup_msg_id}",
                    headers=alice_h,
                ).status_code

            def _read() -> int:
                b3.wait()
                return httpx2.get(
                    f"http://{srv2}/api/conversations/{conv_id}/messages",
                    headers=bob_h,
                ).status_code

            with ThreadPoolExecutor(max_workers=3) as pool:
                f_e = pool.submit(_edit)
                f_d = pool.submit(_delete)
                f_r = pool.submit(_read)
                assert f_e.result() == 200
                assert f_d.result() == 204
                assert f_r.result() == 200

            updates = _recv_until(bob_ws, {"message_updated", "message_deleted"}, 2)
            assert {f["type"] for f in updates} == {"message_updated", "message_deleted"}

            final_list = httpx2.get(
                f"http://{srv1}/api/conversations/{conv_id}/messages",
                headers=bob_h,
            ).json()["items"]
            contents_by_id = {m["id"]: m["content"] for m in final_list}
            assert contents_by_id[alice_msg_id] == "Hello from Alice (edited)"
            assert bob_msg_id in contents_by_id
            assert alice_id != bob_id


def test_friends_concurrent_requests_across_two_workers(clean_env) -> None:
    """Three users concurrently send opposing and parallel friend requests across 2 API workers
    without violating the unordered pair unique constraint or duplicating friendships.
    """
    with running_server(_app()) as srv1, running_server(_app()) as srv2:
        alice_id, alice_h = _create_verified_user(srv1, "alice@example.com")
        bob_id, bob_h = _create_verified_user(srv2, "bob@example.com")
        carol_id, carol_h = _create_verified_user(srv1, "carol@example.com")

        barrier = threading.Barrier(3, timeout=WAIT)

        def _req(args: tuple[str, dict[str, str], int]) -> int:
            srv, hdrs, target_id = args
            barrier.wait()
            return httpx2.post(
                f"http://{srv}/api/friends/requests",
                json={"addressee_id": target_id},
                headers=hdrs,
            ).status_code

        # Alice->Bob on srv1, Bob->Alice on srv2, Carol->Alice on srv1 simultaneously.
        with ThreadPoolExecutor(max_workers=3) as pool:
            statuses = list(
                pool.map(
                    _req,
                    [
                        (srv1, alice_h, bob_id),
                        (srv2, bob_h, alice_id),
                        (srv1, carol_h, alice_id),
                    ],
                )
            )
        # Opposing Alice<->Bob race produces one 201 and one 409 (or 200); Carol->Alice is 201.
        pair_statuses = sorted(statuses[:2])
        assert pair_statuses == [201, 409] or all(s in (200, 201) for s in pair_statuses)
        assert statuses[2] == 201
        assert sql("SELECT COUNT(*) FROM friendships") == [(2,)]
        assert carol_id > 0


def test_game_4_players_two_workers_join_disconnect_and_simultaneous_votes(clean_env) -> None:
    """Four humans join matchmaking at the same moment across 2 API workers: zero duplicate rooms,
    all share one room_id, one player drops/reconnects during discussion while others chat, and
    all 4 cast concurrent votes across both workers cleanly.
    """
    with (
        running_server(_app(game_scheduler_enabled=False)) as srv1,
        running_server(_app(game_scheduler_enabled=False)) as srv2,
    ):
        players = [
            _create_verified_user(srv1 if i % 2 == 0 else srv2, f"g{i}@example.com")
            for i in range(4)
        ]
        barrier = threading.Barrier(4, timeout=WAIT)

        def _join(idx: int) -> tuple[int, int]:
            srv = srv1 if idx % 2 == 0 else srv2
            barrier.wait()
            res = httpx2.post(f"http://{srv}/api/game/queue/join", headers=players[idx][1])
            return res.status_code, res.json()["room_id"]

        with ThreadPoolExecutor(max_workers=4) as pool:
            joined = list(pool.map(_join, range(4)))

        assert all(code in (200, 202) for code, _ in joined)
        room_ids = {rid for _, rid in joined}
        assert len(room_ids) == 1
        room_id = next(iter(room_ids))

        # Race two concurrent start clicks across srv1 and srv2 -> zero 500s.
        b_start = threading.Barrier(2, timeout=WAIT)

        def _start(idx: int) -> int:
            srv = srv1 if idx == 0 else srv2
            b_start.wait()
            return httpx2.post(
                f"http://{srv}/api/game/rooms/{room_id}/start",
                headers=players[idx][1],
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            start_codes = list(pool.map(_start, [0, 1]))
        assert 200 in start_codes
        assert all(c in (200, 409) for c in start_codes)

        # Open 4 game sockets split across both workers.
        with ExitStack() as stack:
            sockets: list[ClientConnection] = []
            for idx in range(4):
                srv = srv1 if idx % 2 == 0 else srv2
                ticket = _issue_ticket(srv, players[idx][1])
                ws = stack.enter_context(
                    connect(f"ws://{srv}/ws/game?ticket={ticket}&room_id={room_id}")
                )
                snap = json.loads(ws.recv(timeout=WAIT))
                assert snap["type"] == "game_snapshot"
                sockets.append(ws)

            # Player 2 disconnects while Player 0 and Player 1 chat concurrently across srv1/srv2.
            sockets[2].close()
            sockets[0].send(json.dumps({"type": "chat_message", "payload": {"text": "msg from 0"}}))
            sockets[1].send(json.dumps({"type": "chat_message", "payload": {"text": "msg from 1"}}))

            # Player 2 reconnects via srv2 and sees discussion restored without errors.
            rejoin_ticket = _issue_ticket(srv2, players[2][1])
            ws2_rejoined = stack.enter_context(
                connect(f"ws://{srv2}/ws/game?ticket={rejoin_ticket}&room_id={room_id}")
            )
            sockets[2] = ws2_rejoined
            re_snap = json.loads(ws2_rejoined.recv(timeout=WAIT))
            assert re_snap["type"] == "game_snapshot"
            p0_frames = _recv_until(sockets[0], {"game_message"}, 2)
            assert len(p0_frames) == 2

            # Advance room to voting and have all 4 humans vote simultaneously across srv1 & srv2.
            sql(
                "UPDATE game_rooms SET state = CAST('voting' AS game_room_state),"
                " voting_started_at = now() WHERE id = :rid",
                rid=room_id,
            )
            snap_after = httpx2.get(
                f"http://{srv1}/api/game/rooms/{room_id}", headers=players[0][1]
            ).json()
            all_nums = [p["id"] for p in snap_after["participants"]]
            assert len(all_nums) == 4

            b_vote = threading.Barrier(4, timeout=WAIT)

            def _cast_votes(idx: int) -> list[int]:
                srv = srv1 if idx % 2 == 0 else srv2
                me = httpx2.get(
                    f"http://{srv}/api/game/rooms/{room_id}", headers=players[idx][1]
                ).json()["my_participant_id"]
                targets = [n for n in all_nums if n != me]
                b_vote.wait()
                codes = []
                for t in targets:
                    r = httpx2.post(
                        f"http://{srv}/api/game/rooms/{room_id}/votes",
                        json={"target_participant_id": t, "guess": "human"},
                        headers=players[idx][1],
                    )
                    codes.append(r.status_code)
                return codes

            with ThreadPoolExecutor(max_workers=4) as pool:
                vote_results = list(pool.map(_cast_votes, range(4)))
            assert all(codes == [200, 200, 200] for codes in vote_results)
            vote_count = sql("SELECT COUNT(*) FROM game_votes WHERE room_id = :rid", rid=room_id)
            assert vote_count == [(12,)]


def test_application_employer_transition_vs_candidate_withdraw_race(clean_env) -> None:
    """Employer updates application status on srv1 at the exact moment candidate withdraws on
    srv2: exactly one succeeds and the loser receives 409 Conflict with consistent DB state.
    """
    with running_server(_app()) as srv1, running_server(_app()) as srv2:
        emp_id, emp_h = _create_verified_user(srv1, "emp@example.com", position="Hiring Lead")
        cand_id, cand_h = _create_verified_user(srv2, "cand@example.com", position="Developer")

        sql(
            "INSERT INTO intro_videos"
            " (user_id, object_key, duration_sec, size_bytes, content_type,"
            "  moderation_status, lifecycle_status, video_rating)"
            " VALUES (:uid, 'videos/race/1.mp4', 10, 1024, 'video/mp4', 'approved', 'posted', 'A')",
            uid=cand_id,
        )
        assert (
            httpx2.post(
                f"http://{srv1}/api/companies",
                json={"name": "Race Co", "country": "UAE", "city": "Abu Dhabi"},
                headers=emp_h,
            ).status_code
            == 201
        )
        job_id = httpx2.post(
            f"http://{srv1}/api/jobs",
            json={
                "title": "Race Engineer",
                "description": "Concurrency verification",
                "latitude": 24.4539,
                "longitude": 54.3773,
                "location": "Abu Dhabi",
                "status": "open",
            },
            headers=emp_h,
        ).json()["id"]
        app_id = httpx2.post(
            f"http://{srv2}/api/jobs/{job_id}/apply",
            json={"cover_note": "Testing concurrency"},
            headers=cand_h,
        ).json()["id"]
        assert emp_id != cand_id

        barrier = threading.Barrier(2, timeout=WAIT)

        def _employer_reject() -> int:
            barrier.wait()
            return httpx2.patch(
                f"http://{srv1}/api/applications/{app_id}/status",
                json={"status": "rejected", "note": "Role closed"},
                headers=emp_h,
            ).status_code

        def _candidate_withdraw() -> int:
            barrier.wait()
            return httpx2.delete(
                f"http://{srv2}/api/applications/{app_id}",
                headers=cand_h,
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            f_emp = pool.submit(_employer_reject)
            f_cand = pool.submit(_candidate_withdraw)
            emp_code = f_emp.result()
            cand_code = f_cand.result()

        assert sorted([emp_code, cand_code]) in ([200, 409], [204, 409])
        [(final_status,)] = sql("SELECT status::text FROM applications WHERE id = :id", id=app_id)
        events = sql(
            "SELECT to_status::text FROM application_events WHERE application_id = :id ORDER BY id",
            id=app_id,
        )
        expected_final = "rejected" if emp_code == 200 else "withdrawn"
        assert final_status == expected_final
        assert [e[0] for e in events] == ["submitted", expected_final]


def test_jobs_parallel_edits_and_view_dedup_across_two_workers(clean_env) -> None:
    """Two employers concurrently update their jobs while duplicate + distinct viewers hit
    POST /jobs/{id}/view across 2 API workers; edits persist cleanly and view counts never inflate.
    """
    with running_server(_app()) as srv1, running_server(_app()) as srv2:
        _, emp1_h = _create_verified_user(srv1, "e1@example.com")
        _, emp2_h = _create_verified_user(srv2, "e2@example.com")
        viewers = [_create_verified_user(srv1, f"v{i}@example.com")[1] for i in range(4)]

        assert (
            httpx2.post(
                f"http://{srv1}/api/companies",
                json={"name": "Co One", "country": "UAE", "city": "Abu Dhabi"},
                headers=emp1_h,
            ).status_code
            == 201
        )
        assert (
            httpx2.post(
                f"http://{srv2}/api/companies",
                json={"name": "Co Two", "country": "Azerbaijan", "city": "Baku"},
                headers=emp2_h,
            ).status_code
            == 201
        )

        job1 = httpx2.post(
            f"http://{srv1}/api/jobs",
            json={
                "title": "Job One",
                "description": "Desc 1",
                "latitude": 24.45,
                "longitude": 54.37,
                "location": "Abu Dhabi",
                "status": "open",
            },
            headers=emp1_h,
        ).json()["id"]
        job2 = httpx2.post(
            f"http://{srv2}/api/jobs",
            json={
                "title": "Job Two",
                "description": "Desc 2",
                "latitude": 40.38,
                "longitude": 49.86,
                "location": "Baku",
                "status": "open",
            },
            headers=emp2_h,
        ).json()["id"]

        # Viewer 0 hammers job1 5x simultaneously across srv1 & srv2 alongside viewers 1, 2, 3
        # and both employers simultaneously patching their own jobs.
        calls: list[tuple[str, str, dict[str, str], dict | None]] = [
            ("PATCH", f"http://{srv1}/api/jobs/{job1}", emp1_h, {"title": "Job One Updated"}),
            ("PATCH", f"http://{srv2}/api/jobs/{job2}", emp2_h, {"title": "Job Two Updated"}),
            *[
                (
                    "POST",
                    f"http://{srv1 if i % 2 == 0 else srv2}/api/jobs/{job1}/view",
                    viewers[0],
                    None,
                )
                for i in range(5)
            ],
            ("POST", f"http://{srv1}/api/jobs/{job1}/view", viewers[1], None),
            ("POST", f"http://{srv2}/api/jobs/{job1}/view", viewers[2], None),
            ("POST", f"http://{srv1}/api/jobs/{job1}/view", viewers[3], None),
        ]
        barrier = threading.Barrier(len(calls), timeout=WAIT)

        def _call(item: tuple[str, str, dict[str, str], dict | None]) -> int:
            method, url, hdrs, payload = item
            barrier.wait()
            if method == "PATCH":
                return httpx2.patch(url, json=payload, headers=hdrs).status_code
            return httpx2.post(url, headers=hdrs).status_code

        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
            codes = list(pool.map(_call, calls))

        assert codes[:2] == [200, 200]
        assert all(c == 204 for c in codes[2:])
        assert sql("SELECT title FROM jobs WHERE id = :id", id=job1) == [("Job One Updated",)]
        assert sql("SELECT title FROM jobs WHERE id = :id", id=job2) == [("Job Two Updated",)]
        assert sql("SELECT COUNT(*) FROM job_views WHERE job_id = :id", id=job1) == [(4,)]
