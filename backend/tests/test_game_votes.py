"""Turing Duel votes, scoring and results (BE-10).

The scoring rules (app/game/scoring.py) are tested without a database, on the worked examples
of docs/game/turing-duel-rules.md. The vote and results tests need a real PostgreSQL and Redis,
like the other game tests: the API runs in uvicorn, and each room is written straight into the
database (its state, its labels, who is a bot), so every case is exact. Every user is made up.
"""

from __future__ import annotations

import asyncio
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
from websockets.sync.client import ClientConnection, connect

from app.auth import security
from app.auth.deps import get_current_user
from app.game import repo as game_repo
from app.game import scoring

PASSWORD = "correct horse battery"
PASSWORD_HASH = security.hash_password(PASSWORD)


# Scoring rules, no database -------------------------------------------------------------


def test_worked_example_a_three_humans_two_bots() -> None:
    # Humans are Player 1, 2 and 4; bots are Player 3 and 5 (rules, section 6, example A).
    everyone = [1, 2, 3, 4, 5]
    bots = {3, 5}
    marks = {
        (1, 2): "human",  # sent on purpose; the same as leaving the preset
        (1, 3): "bot",
        (1, 5): "bot",
        (2, 5): "bot",  # Player 2 left Player 1, 3 and 4 at "human"
        (4, 1): "bot",
        (4, 3): "bot",
        (4, 5): "bot",
    }
    scores = {h: scoring.human_score(h, everyone, bots, marks) for h in (1, 2, 4)}
    assert scores == {1: 4, 2: 2, 4: 2}
    assert scoring.outcomes(scores) == {1: "win", 2: "loss", 4: "loss"}
    assert scoring.deception_rate(3, [1, 2, 4], marks) == 33  # fooled Player 2 only: 1 of 3
    assert scoring.deception_rate(5, [1, 2, 4], marks) == 0

    # "If Player 1 had also scored +2, all three humans would share the top score."
    marks[(1, 2)] = "bot"
    scores[1] = scoring.human_score(1, everyone, bots, marks)
    assert scores[1] == 2
    assert scoring.outcomes(scores) == {1: "draw", 2: "draw", 4: "draw"}


@pytest.mark.parametrize(
    ("marks", "score", "outcome", "rate_1", "rate_4"),
    [
        ({(2, 1): "bot", (2, 4): "bot"}, 2, "win", 0, 0),
        ({(2, 1): "bot"}, 0, "draw", 0, 100),  # Player 4 left at the preset "human"
        ({}, -2, "loss", 100, 100),  # nothing sent: both bots count as marked "human"
    ],
)
def test_worked_example_b_one_human_two_bots(marks, score, outcome, rate_1, rate_4) -> None:
    # The human is Player 2; bots are Player 1 and 4 (rules, section 6, example B).
    assert scoring.human_score(2, [1, 2, 4], {1, 4}, marks) == score
    assert scoring.outcomes({2: score}) == {2: outcome}
    assert scoring.deception_rate(1, [2], marks) == rate_1
    assert scoring.deception_rate(4, [2], marks) == rate_4


def test_marking_a_human_human_earns_a_point_and_wrong_marks_cost_one() -> None:
    # Two humans, no bots: each right "human" mark is +1, a wrong "bot" mark is -1.
    assert scoring.human_score(1, [1, 2], set(), {}) == 1
    assert scoring.human_score(1, [1, 2], set(), {(1, 2): "bot"}) == -1


def test_top_score_wins_even_when_it_is_negative() -> None:
    assert scoring.outcomes({1: -1, 2: -3}) == {1: "win", 2: "loss"}
    assert scoring.outcomes({1: 0, 2: 0, 3: -2}) == {1: "draw", 2: "draw", 3: "loss"}


def test_deception_rate_rounds_to_a_whole_percentage() -> None:
    humans = [1, 2, 3]
    assert scoring.deception_rate(9, humans, {(1, 9): "bot"}) == 67  # 2 of 3
    assert scoring.deception_rate(9, [], {}) == 0  # no human left: never a division by zero


# Request checks, no database --------------------------------------------------------------


def test_votes_and_results_need_login(client: TestClient) -> None:
    vote = {"target_participant_id": 2, "guess": "bot"}
    assert client.post("/api/game/rooms/1/votes", json=vote).status_code == 401
    assert client.get("/api/game/rooms/1/results").status_code == 401


def test_bad_vote_bodies_and_room_ids_are_422() -> None:
    user = type("U", (), {"id": 1, "status": "active", "token_version": 1})()
    app = build_app()
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as authed:
        bad_bodies = [
            {"target_participant_id": 0, "guess": "bot"},
            {"target_participant_id": 6, "guess": "bot"},
            {"target_participant_id": "x", "guess": "bot"},
            {"target_participant_id": 2, "guess": "maybe"},
            {"target_participant_id": 2},
            {"guess": "human"},
        ]
        for body in bad_bodies:
            response = authed.post("/api/game/rooms/1/votes", json=body)
            assert response.status_code == 422, body
            assert response.json()["error"]["detail"].startswith("body → ")
        good = {"target_participant_id": 2, "guess": "bot"}
        for bad_id in (0, -5, 2**63):
            assert authed.post(f"/api/game/rooms/{bad_id}/votes", json=good).status_code == 422
            assert authed.get(f"/api/game/rooms/{bad_id}/results").status_code == 422


# With PostgreSQL, Redis and uvicorn ---------------------------------------------------------


@pytest.fixture(scope="module")
def schema_at_head():
    if DATABASE_SKIP_REASON is not None:
        pytest.skip(DATABASE_SKIP_REASON)
    alembic("upgrade", "head")


@pytest.fixture
def clean_game(schema_at_head) -> Iterator[None]:
    """Empty game tables and users, and only the game: and ws: keys in the test Redis."""
    if REDIS_SKIP_REASON is not None:
        pytest.skip(REDIS_SKIP_REASON)
    client = redis.Redis.from_url(TEST_REDIS_URL)

    def delete_keys() -> None:
        for pattern in ("game:*", "ws:*"):
            for key in client.scan_iter(pattern):
                client.delete(key)

    delete_keys()
    sql(
        "TRUNCATE game_votes, game_messages, game_participants, game_rooms RESTART IDENTITY CASCADE"
    )
    sql("TRUNCATE users RESTART IDENTITY CASCADE")
    yield
    delete_keys()
    client.close()


def game_app(**overrides: object):
    """The API on the test database and Redis. The server clock is off unless a test needs it."""
    settings = {
        "database_url": TEST_DATABASE_URL,
        "redis_url": TEST_REDIS_URL,
        "game_scheduler_enabled": False,
        "game_bot_probability": 0.0,
        "game_discussion_sec": 120.0,
        "game_voting_sec": 45.0,
        "game_tick_interval_sec": 0.04,
    }
    settings.update(overrides)
    return build_app(**settings)


def login(server: str, email: str) -> tuple[int, dict[str, str]]:
    """Make a verified user, log in, and return its id and Authorization header."""
    [(user_id,)] = sql(
        "INSERT INTO users (email, password_hash, is_email_verified)"
        " VALUES (:email, :hash, true) RETURNING id",
        email=email,
        hash=PASSWORD_HASH,
    )
    response = httpx2.post(
        f"http://{server}/api/auth/login",
        json={"email": email, "password": PASSWORD},
        headers={"X-Real-IP": f"10.10.0.{user_id}"},  # one IP each: the login limit is per IP
    )
    assert response.status_code == 200, response.text
    return user_id, {"Authorization": f"Bearer {response.json()['access_token']}"}


def make_room(
    state: str,
    humans: dict[int, int],
    bots: tuple[int, ...] = (),
    *,
    marks: dict[tuple[int, int], str] | None = None,
    discussion_started_at: datetime | None = None,
    voting_started_at: datetime | None = None,
) -> tuple[int, dict[int, int]]:
    """Write a room in the given state. `humans` maps label numbers to user ids, `bots` lists
    the label numbers of bots, `marks` maps (voter number, target number) to a guess.
    Returns the room id and {label number: participant id}.

    The room is written as "closed" first, which the server clock ignores, and switched to its
    state at the end, so the clock never sees a half-built room."""
    now = datetime.now(UTC)
    if state == "voting" and voting_started_at is None:
        voting_started_at = now
    [(room_id,)] = sql(
        "INSERT INTO game_rooms (target_size, state, room_expires_at,"
        " discussion_started_at, voting_started_at)"
        " VALUES (5, 'closed', :expires, :discussion, :voting) RETURNING id",
        expires=now + timedelta(seconds=180),
        discussion=discussion_started_at,
        voting=voting_started_at,
    )
    seats = [*humans.items(), *((number, None) for number in bots)]
    ids = {}
    for number, user_id in seats:
        [(participant_id,)] = sql(
            "INSERT INTO game_participants (room_id, user_id, display_label)"
            " VALUES (:room, :user, :label) RETURNING id",
            room=room_id,
            user=user_id,
            label=f"Player {number}",
        )
        ids[number] = participant_id
    for (voter, target), guess in (marks or {}).items():
        sql(
            "INSERT INTO game_votes (room_id, voter_participant_id, target_participant_id, guess)"
            " VALUES (:room, :voter, :target, CAST(:guess AS game_vote_guess))",
            room=room_id,
            voter=ids[voter],
            target=ids[target],
            guess=guess,
        )
    sql(
        "UPDATE game_rooms SET state = CAST(:state AS game_room_state) WHERE id = :room",
        state=state,
        room=room_id,
    )
    return room_id, ids


def vote(server: str, headers: dict, room_id: int, target: int, guess: str) -> httpx2.Response:
    return httpx2.post(
        f"http://{server}/api/game/rooms/{room_id}/votes",
        json={"target_participant_id": target, "guess": guess},
        headers=headers,
    )


def human_row(number: int, score: int, outcome: str) -> dict:
    return {
        "participant_id": number,
        "display_label": f"Player {number}",
        "is_bot": False,
        "score": score,
        "outcome": outcome,
        "deception_rate": None,
    }


def bot_row(number: int, deception_rate: int) -> dict:
    return {
        "participant_id": number,
        "display_label": f"Player {number}",
        "is_bot": True,
        "score": None,
        "outcome": None,
        "deception_rate": deception_rate,
    }


def stored_marks(room_id: int) -> dict[tuple[int, int], str]:
    rows = sql(
        "SELECT voter_participant_id, target_participant_id, guess FROM game_votes"
        " WHERE room_id = :room",
        room=room_id,
    )
    return {(voter, target): guess for voter, target, guess in rows}


def open_socket(server: str, headers: dict) -> ClientConnection:
    ticket = httpx2.post(f"http://{server}/api/ws/ticket", headers=headers).json()["ticket"]
    return connect(f"ws://{server}/ws?ticket={ticket}", open_timeout=5)


def wait_for_event(ws: ClientConnection, event_type: str, timeout: float = 6.0) -> dict:
    """Read frames until one of this type arrives; returns its payload."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            frame = json.loads(ws.recv(timeout=max(0.05, deadline - time.monotonic())))
        except TimeoutError:
            break
        if frame["type"] == event_type:
            return frame["payload"]
    raise AssertionError(f"no {event_type} event within {timeout} s")


def wait_until_finished(server: str, headers: dict, room_id: int, timeout: float = 6.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        room = httpx2.get(f"http://{server}/api/game/rooms/{room_id}", headers=headers).json()
        if room["state"] == "finished":
            return
        time.sleep(0.05)
    raise AssertionError("the room did not finish")


@needs_database
@needs_redis
def test_a_vote_is_saved_and_a_new_mark_replaces_it(clean_game) -> None:
    with running_server(game_app()) as srv:
        u1, h1 = login(srv, "ana@example.com")
        u2, h2 = login(srv, "ben@example.com")
        room_id, ids = make_room("voting", {1: u1, 3: u2}, bots=(2,))

        on_bot = vote(srv, h1, room_id, 2, "bot")
        assert on_bot.status_code == 200
        assert on_bot.json() == {"target_participant_id": 2, "guess": "bot"}
        assert stored_marks(room_id) == {(ids[1], ids[2]): "bot"}

        # Changing the mark replaces it: still one row, now "human". No "already voted" error.
        again = vote(srv, h1, room_id, 2, "human")
        assert again.status_code == 200
        assert stored_marks(room_id) == {(ids[1], ids[2]): "human"}

        # A mark on a human answers exactly like a mark on a bot: nothing tells them apart.
        on_human = vote(srv, h1, room_id, 3, "bot")
        assert on_human.status_code == 200
        assert on_human.json().keys() == on_bot.json().keys()
        assert on_human.headers["content-type"] == on_bot.headers["content-type"]

        assert vote(srv, h2, room_id, 1, "bot").status_code == 200
        assert stored_marks(room_id) == {
            (ids[1], ids[2]): "human",
            (ids[1], ids[3]): "bot",
            (ids[3], ids[1]): "bot",
        }


@needs_database
@needs_redis
def test_vote_refusals_are_never_500(clean_game) -> None:
    with running_server(game_app()) as srv:
        u1, h1 = login(srv, "ana@example.com")
        u2, _ = login(srv, "ben@example.com")
        u3, h3 = login(srv, "cy@example.com")
        u4, _ = login(srv, "dee@example.com")
        room_a, _ = make_room("voting", {1: u1, 3: u2}, bots=(2,))
        room_b, _ = make_room("voting", {1: u3, 4: u4})

        def refused(headers: dict, room_id: int, target: int) -> int:
            response = vote(srv, headers, room_id, target, "bot")
            assert response.json()["error"]["code"] == str(response.status_code)
            return response.status_code

        # Cross-room: a player of room B cannot vote in room A, and the other way round, even
        # for a label number that exists in the other room.
        assert refused(h3, room_a, 3) == 403
        assert refused(h1, room_b, 4) == 403
        assert refused(h1, 999_999, 3) == 404
        assert refused(h1, room_a, 1) == 400  # self
        assert refused(h1, room_a, 4) == 422  # nobody is "Player 4" in room A
        assert refused(h1, room_a, 5) == 422

        # Outside the voting phase.
        for state in ("waiting", "discussion", "finished", "closed"):
            other_room, _ = make_room(state, {1: u1}, bots=(2,))
            assert refused(h1, other_room, 2) == 409, state
        # Still "voting" in the database, but its 45 seconds are over: the clock has not
        # ticked yet, and a late mark must not count.
        late_room, _ = make_room(
            "voting", {1: u1}, bots=(2,), voting_started_at=datetime.now(UTC) - timedelta(hours=1)
        )
        assert refused(h1, late_room, 2) == 409

        assert sql("SELECT COUNT(*) FROM game_votes") == [(0,)]


@needs_database
@needs_redis
def test_results_refusals(clean_game) -> None:
    with running_server(game_app()) as srv:
        u1, h1 = login(srv, "ana@example.com")
        _, h2 = login(srv, "ben@example.com")
        for state in ("waiting", "discussion", "voting", "closed"):
            room_id, _ = make_room(state, {1: u1}, bots=(2,))
            response = httpx2.get(f"http://{srv}/api/game/rooms/{room_id}/results", headers=h1)
            assert response.status_code == 409, state
            assert "is_bot" not in response.text
        finished, _ = make_room("finished", {1: u1}, bots=(2,))
        assert httpx2.get(f"http://{srv}/api/game/rooms/{finished}/results", headers=h1).is_success
        assert (
            httpx2.get(f"http://{srv}/api/game/rooms/{finished}/results", headers=h2).status_code
            == 403
        )
        assert (
            httpx2.get(f"http://{srv}/api/game/rooms/999999/results", headers=h1).status_code == 404
        )


@needs_database
@needs_redis
def test_worked_example_a_played_over_the_api(clean_game) -> None:
    """Three humans and two bots vote as in the rules' example A; the server clock ends voting,
    scores the humans and announces it; everyone then reads the same results."""
    with running_server(game_app(game_scheduler_enabled=True, game_voting_sec=3.0)) as srv:
        u1, h1 = login(srv, "ana@example.com")
        u2, h2 = login(srv, "ben@example.com")
        u4, h4 = login(srv, "cy@example.com")
        with open_socket(srv, h1) as ws1, open_socket(srv, h2) as ws2, open_socket(srv, h4) as ws4:
            room_id, ids = make_room("voting", {1: u1, 2: u2, 4: u4}, bots=(3, 5))
            sent = [
                (h1, 2, "human"),
                (h1, 3, "bot"),
                (h1, 4, "bot"),  # changed below
                (h1, 5, "bot"),
                (h1, 4, "human"),
                (h2, 5, "bot"),  # Player 2 leaves the others at "human"
                (h4, 1, "bot"),
                (h4, 3, "bot"),
                (h4, 5, "bot"),
            ]
            for headers, target, guess in sent:
                assert vote(srv, headers, room_id, target, guess).status_code == 200

            for ws in (ws1, ws2, ws4):
                payload = wait_for_event(ws, "game_phase_finished")
                assert payload == {"room_id": room_id, "state": "finished", "phase_ends_at": None}

        assert vote(srv, h1, room_id, 2, "bot").status_code == 409  # too late now
        scores = sql(
            "SELECT display_label, score FROM game_participants WHERE room_id = :r", r=room_id
        )
        assert dict(scores) == {
            "Player 1": 4,
            "Player 2": 2,
            "Player 3": 0,
            "Player 4": 2,
            "Player 5": 0,
        }

        results = {}
        for headers in (h1, h2, h4):
            response = httpx2.get(f"http://{srv}/api/game/rooms/{room_id}/results", headers=headers)
            assert response.status_code == 200
            results[response.json()["my_participant_id"]] = response.json()
        assert sorted(results) == [1, 2, 4]
        body = results[1]
        assert body["room_id"] == room_id
        assert body["state"] == "finished"
        assert body["winner_participant_ids"] == [1]
        assert body["is_draw"] is False
        assert body["participants"] == [
            human_row(1, 4, "win"),
            human_row(2, 2, "loss"),
            bot_row(3, 33),
            human_row(4, 2, "loss"),
            bot_row(5, 0),
        ]
        # Every player sees the same results; only "my_participant_id" differs.
        for number in (2, 4):
            assert {**results[number], "my_participant_id": 1} == body
        assert set(ids) == {1, 2, 3, 4, 5}


@needs_database
@needs_redis
@pytest.mark.parametrize(
    ("humans", "bots", "marks", "winners", "is_draw", "outcomes", "rates"),
    [
        # One human, two bots (example B, middle row): 0 points is a draw.
        ([2], (1, 4), {(2, 1): "bot"}, [], True, {2: "draw"}, {1: 0, 4: 100}),
        # One human, one bot, a wrong mark: below 0 is a loss, and nobody wins.
        ([1], (2,), {}, [], False, {1: "loss"}, {2: 100}),
        # Two humans; Player 3 never sent a mark (disconnected): the presets count, they still
        # get a score and an outcome, and they count for the bot's deception rate (1 of 2).
        ([1, 3], (2,), {(1, 2): "bot"}, [1], False, {1: "win", 3: "loss"}, {2: 50}),
        # Two humans with the same top score draw.
        ([1, 2], (3,), {}, [], True, {1: "draw", 2: "draw"}, {3: 100}),
    ],
)
def test_outcome_cases_scored_by_the_server_clock(
    clean_game, humans, bots, marks, winners, is_draw, outcomes, rates
) -> None:
    with running_server(game_app(game_scheduler_enabled=True, game_voting_sec=0.5)) as srv:
        users = {number: login(srv, f"p{number}@example.com") for number in humans}
        room_id, _ = make_room(
            "voting",
            {number: user_id for number, (user_id, _) in users.items()},
            bots,
            marks=marks,
            voting_started_at=datetime.now(UTC) - timedelta(seconds=10),  # ends on the next tick
        )
        headers = users[humans[0]][1]
        wait_until_finished(srv, headers, room_id)
        body = httpx2.get(f"http://{srv}/api/game/rooms/{room_id}/results", headers=headers).json()
        assert body["winner_participant_ids"] == winners
        assert body["is_draw"] is is_draw
        by_number = {p["participant_id"]: p for p in body["participants"]}
        assert {n: by_number[n]["outcome"] for n in humans} == outcomes
        assert {n: by_number[n]["deception_rate"] for n in bots} == rates


@needs_database
@needs_redis
def test_two_players_voting_at_once_through_two_api_workers(clean_game) -> None:
    with running_server(game_app()) as srv1, running_server(game_app()) as srv2:
        u1, h1 = login(srv1, "ana@example.com")
        u2, h2 = login(srv1, "ben@example.com")
        room_id, ids = make_room("voting", {1: u1, 4: u2}, bots=(2, 5))
        start = threading.Barrier(2)

        def mark_all(job: tuple[str, dict, list[int]]) -> list[int]:
            server, headers, targets = job
            start.wait(timeout=5)
            return [vote(server, headers, room_id, t, "bot").status_code for t in targets]

        jobs = [(srv1, h1, [2, 4, 5]), (srv2, h2, [1, 2, 5])]
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(mark_all, jobs))
        assert statuses == [[200, 200, 200], [200, 200, 200]]
        assert stored_marks(room_id) == {
            (ids[a], ids[b]): "bot" for a, b in [(1, 2), (1, 4), (1, 5), (4, 1), (4, 2), (4, 5)]
        }

        # One player sends two different marks for the same target at the same moment, from
        # two tabs on two workers: both are accepted, and one row is left, with one of them.
        def send(job: tuple[str, str]) -> int:
            server, guess = job
            start.wait(timeout=5)
            return vote(server, h1, room_id, 2, guess).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(send, [(srv1, "human"), (srv2, "bot")])) == [200, 200]
        [(count, guess)] = sql(
            "SELECT COUNT(*), MIN(guess::text) FROM game_votes"
            " WHERE voter_participant_id = :v AND target_participant_id = :t",
            v=ids[1],
            t=ids[2],
        )
        assert count == 1 and guess in ("bot", "human")


@needs_database
@needs_redis
def test_votes_racing_the_end_of_voting_are_counted_or_refused(clean_game) -> None:
    """Two players keep flipping their marks while the server clock ends voting. Every vote is
    either accepted and counted in the stored score, or refused with 409, never lost."""
    app = game_app(game_scheduler_enabled=True, game_voting_sec=0.8, game_tick_interval_sec=0.01)
    with running_server(app) as srv:
        u1, h1 = login(srv, "ana@example.com")
        u2, h2 = login(srv, "ben@example.com")
        room_id, ids = make_room("voting", {1: u1, 2: u2}, bots=(3,))
        start = threading.Barrier(2)

        def flip_until_refused(job: tuple[dict, int]) -> tuple[dict, set[int]]:
            headers, me = job
            accepted: dict[int, str] = {}
            statuses = set()
            start.wait(timeout=5)
            for n in range(10_000):
                target = (2, 3)[n % 2] if me == 1 else (1, 3)[n % 2]
                guess = ("bot", "human")[(n // 2) % 2]
                response = vote(srv, headers, room_id, target, guess)
                statuses.add(response.status_code)
                if response.status_code != 200:
                    break
                accepted[target] = guess
            return accepted, statuses

        with ThreadPoolExecutor(max_workers=2) as pool:
            (acc1, st1), (acc2, st2) = pool.map(flip_until_refused, [(h1, 1), (h2, 2)])
        assert st1 == {200, 409} and st2 == {200, 409}
        wait_until_finished(srv, h1, room_id)

        marks = stored_marks(room_id)
        # The marks in the database are exactly the last accepted ones...
        assert marks == {
            **{(ids[1], ids[t]): g for t, g in acc1.items()},
            **{(ids[2], ids[t]): g for t, g in acc2.items()},
        }
        # ...and the stored scores were computed from exactly those marks.
        everyone = list(ids.values())
        for number in (1, 2):
            expected = scoring.human_score(ids[number], everyone, {ids[3]}, marks)
            [(score,)] = sql("SELECT score FROM game_participants WHERE id = :p", p=ids[number])
            assert score == expected


@needs_database
@needs_redis
def test_a_vote_still_being_saved_when_voting_ends_is_counted(
    clean_game, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The vote passes its checks just before the end, but its save is slowed down past the
    end. The server clock must wait for it before it scores, or the accepted mark is lost."""
    real_save_mark = game_repo.save_mark

    async def slow_save_mark(*args, **kwargs) -> None:
        await asyncio.sleep(0.8)
        await real_save_mark(*args, **kwargs)

    monkeypatch.setattr(game_repo, "save_mark", slow_save_mark)
    app = game_app(game_scheduler_enabled=True, game_voting_sec=0.5, game_tick_interval_sec=0.01)
    with running_server(app) as srv:
        u1, h1 = login(srv, "ana@example.com")
        room_id, ids = make_room("voting", {1: u1}, bots=(2,))
        assert vote(srv, h1, room_id, 2, "bot").status_code == 200  # saved about 0.8 s later
        wait_until_finished(srv, h1, room_id)
        assert stored_marks(room_id) == {(ids[1], ids[2]): "bot"}
        [(score,)] = sql("SELECT score FROM game_participants WHERE id = :p", p=ids[1])
        assert score == 1  # the bot was caught; without the mark it would be -1


@needs_database
@needs_redis
def test_phase_ends_at_in_room_payload_and_phase_events(clean_game) -> None:
    app = game_app(game_scheduler_enabled=True, game_discussion_sec=1.5, game_voting_sec=1.0)
    with running_server(app) as srv:
        u1, h1 = login(srv, "ana@example.com")
        u2, h2 = login(srv, "ben@example.com")
        with open_socket(srv, h1) as ws1, open_socket(srv, h2) as ws2:
            started = datetime.now(UTC)
            room_id, _ = make_room("discussion", {2: u1, 5: u2}, discussion_started_at=started)
            url = f"http://{srv}/api/game/rooms/{room_id}"

            room = httpx2.get(url, headers=h1).json()
            assert room["state"] == "discussion"
            discussion_end = datetime.fromisoformat(room["phase_ends_at"])
            assert discussion_end == started + timedelta(seconds=1.5)

            voting = wait_for_event(ws1, "game_phase_voting")
            assert wait_for_event(ws2, "game_phase_voting") == voting
            assert voting["room_id"] == room_id and voting["state"] == "voting"
            room = httpx2.get(url, headers=h2).json()
            assert room["state"] == "voting"
            assert datetime.fromisoformat(room["phase_ends_at"]) == datetime.fromisoformat(
                voting["phase_ends_at"]
            )
            voting_end = datetime.fromisoformat(voting["phase_ends_at"])
            assert discussion_end <= voting_end - timedelta(seconds=1.0)

            for ws in (ws1, ws2):
                finished = wait_for_event(ws, "game_phase_finished")
                assert finished == {"room_id": room_id, "state": "finished", "phase_ends_at": None}
            room = httpx2.get(url, headers=h1).json()
            assert room["state"] == "finished"
            assert room["phase_ends_at"] is None
