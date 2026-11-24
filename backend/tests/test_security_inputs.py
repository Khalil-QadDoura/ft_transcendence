"""Hostile input (BE-13): wrong types, huge or negative numbers, huge strings, the NUL character,
unknown fields and broken JSON never give a 500 on any route, and the fixes of BE-13 each have
their own test below.

The big test takes every route under /api from the app's OpenAPI description, with a request
that the route would accept, and replaces one input at a time (a path id, a query parameter, a
body field, or the whole body) with each hostile value. A route added later is covered too: a
new route with a body fails here until it gets a sample body in BODIES. On a real database and a
real Redis; the users are made up.
"""

import json
import re
from datetime import timedelta

import httpx2
import pytest
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
from websockets.sync.client import connect

from app.auth import security
from app.auth.constants import ACCESS_SCOPE, TOKEN_MAX_LENGTH
from app.core import limiter
from app.core.inputs import find_nul

pytestmark = [needs_database, needs_redis]

NUL = "\x00"
BIG = 2**63  # one more than the largest id the database can hold
TEXTS = ["", " ", "x" * 100_000, NUL, f"a{NUL}b", "😀" * 1000, "<script>alert(1)</script>",
         "' OR '1'='1' --", "../../etc/passwd", "\u202e", "%00", "\uff11"]  # fmt: skip
NUMBERS = [-1, 0, 1.5, 2**31, BIG, 2**64, -BIG - 1, 1e308]
OTHERS = [None, True, [], {}, [1, 2], {"$gt": ""}]
FIELD_VALUES = TEXTS + NUMBERS + OTHERS
# A query string is a few kB at most (the proxy refuses a longer address).
QUERY_VALUES = [*TEXTS[:2], "x" * 4000, *TEXTS[3:], "-1", "0", str(BIG), "1e999", "NaN", "abc"]
PATH_VALUES = [
    "0",
    "-1",
    str(BIG),
    "99999999999999999999",
    "abc",
    "1.5",
    "%00",
    "\uff11",
    "1 OR 1=1",
]
WHOLE_BODIES = [[], "text", 1, None, b"{", b'{"a": NaN}', b"\xff\xfe"]

# A body each route accepts, or nearly (the job and the chat are Ana's own, from the fixture).
BODIES = {
    "POST /api/auth/register": {"email": "zoe@example.com", "password": "long enough pw"},
    "POST /api/auth/login": {"email": "ana@example.com", "password": "wrong password"},
    "POST /api/auth/refresh": {"refresh_token": "not.a.token"},
    "POST /api/auth/logout": {"refresh_token": "not.a.token"},
    # A wrong current password, so that no try ever changes it (it would end Ana's token).
    "POST /api/auth/change-password": {"current_password": "wrong", "new_password": "new pw 1234"},
    "POST /api/auth/forgot-password": {"email": "ana@example.com"},
    "POST /api/auth/reset-password": {"token": "x" * 64, "new_password": "new pw 1234"},
    "PATCH /api/users/me": {"first_name": "Ana", "bio": "Hi", "birth_date": "1990-01-01"},
    "POST /api/friends/requests": {"addressee_id": "{ben}"},
    "PATCH /api/companies/me": {"name": "Ana Co", "country": "UAE", "city": "AD"},
    "POST /api/companies": {"name": "Second Co", "description": "x"},
    "POST /api/conversations": {"type": "direct", "peer_user_id": "{ben}"},
    "POST /api/conversations/{conv_id}/participants": {"user_id": "{ben}", "role": "member"},
    "POST /api/conversations/{conv_id}/messages": {"content": "Hi", "idempotency_key": "k"},
    "PATCH /api/conversations/{conv_id}/messages/{mid}": {"content": "Edited"},
    "POST /api/conversations/{conv_id}/read": {"last_message_id": "{mid}"},
    "POST /api/jobs": {
        "title": "Cook",
        "description": "Cook well.",
        "latitude": 24.4,
        "longitude": 54.4,
        "location": "Abu Dhabi",
        "salary_amount": "1000.50",
        "salary_currency": "AED",
    },
    "PATCH /api/jobs/{job_id}": {"title": "Head cook", "urgency": "hot"},
    "POST /api/jobs/{job_id}/apply": {"cover_note": "Hello"},
    "PATCH /api/applications/{app_id}/status": {"status": "viewed", "note": "ok"},
    "POST /api/game/rooms/{room_id}/votes": {"target_participant_id": 2, "guess": "bot"},
    "POST /api/media/intro-video/upload-url": {"content_type": "video/mp4", "ext": "mp4"},
    # Keys that are refused before any file is looked up: these tests need no MinIO (the media
    # tests check the files themselves).
    "POST /api/media/intro-video/confirm": {
        "object_key": "users/{ana}/intro/not-a-uuid.mp4",
        "duration_sec": 10,
        "size_bytes": 1000,
        "content_type": "video/mp4",
    },
    "POST /api/media/avatar/confirm": {"object_key": "staging/avatars/{ana}/x.png"},
    "POST /api/media/company-logo/confirm": {"object_key": "staging/logos/1/x.png"},
}

# Routes that answer 503 by design: the health check when a component is down, and login with
# 42 on a server without the 42 keys (as in the tests).
MAY_BE_503 = {"GET /api/health", "GET /api/auth/oauth/42/start"}


@pytest.fixture(scope="module", autouse=True)
def schema_at_head():
    alembic("upgrade", "head")


@pytest.fixture
def no_limits(monkeypatch):
    """Thousands of requests from one user and one IP: lift the rate limits for this test."""
    monkeypatch.setattr(limiter, "WRITE_RATE_LIMIT", "1000000/minute")
    monkeypatch.setattr(limiter, "ROUTE_RATE_LIMITS", {})
    monkeypatch.setattr(limiter.limiter, "enabled", False)


def new_user(email: str) -> int:
    [(user_id,)] = sql(
        "INSERT INTO users (email, password_hash, is_email_verified)"
        " VALUES (:email, :hash, true) RETURNING id",
        email=email,
        hash=security.hash_password("correct horse battery"),
    )
    return user_id


def bearer(app, user_id: int) -> dict:
    token, _ = security.create_token(
        app.state.settings.jwt_secret, user_id, ACCESS_SCOPE, timedelta(minutes=15), ver=1
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def ana(no_limits):
    """A test client logged in as Ana, who has a company, an open job and a chat with Ben."""
    sql("TRUNCATE users, game_rooms RESTART IDENTITY CASCADE")
    app = build_app(database_url=TEST_DATABASE_URL, redis_url=TEST_REDIS_URL)
    ids = {"ana": new_user("ana@example.com"), "ben": new_user("ben@example.com")}
    with TestClient(app, raise_server_exceptions=False) as client:
        client.headers.update(bearer(app, ids["ana"]))
        assert client.post("/api/companies", json={"name": "Ana Co"}).status_code == 201
        job = client.post("/api/jobs", json={**BODIES["POST /api/jobs"], "status": "open"})
        ids["job_id"] = job.json()["id"]
        ids["conv_id"] = client.post(
            "/api/conversations", json={"peer_user_id": ids["ben"]}
        ).json()["id"]
        sent = client.post(f"/api/conversations/{ids['conv_id']}/messages", json={"content": "Hi"})
        ids["mid"] = sent.json()["items"][0]["id"]
        client.ids = ids
        yield client


def fill(value, ids: dict):
    """The value with each "{name}" replaced by its id (a whole "{name}" becomes the number)."""
    if isinstance(value, dict):
        return {key: fill(item, ids) for key, item in value.items()}
    if isinstance(value, str) and re.fullmatch(r"\{\w+\}", value):
        return ids[value[1:-1]]
    return value.format(**ids) if isinstance(value, str) else value


def path_ids(client) -> dict:
    """A real id for each path parameter (Ana's own where she has one)."""
    ids = client.ids
    return {
        "conv_id": ids["conv_id"],
        "mid": ids["mid"],
        "uid": ids["ben"],
        "job_id": ids["job_id"],
        "user_id": ids["ben"],
        "app_id": 1,
        "room_id": 1,
        "video_id": 1,
        "friendship_id": 1,
    }


def send(client, method: str, path: str, body=..., query=None):
    if isinstance(body, bytes):
        headers = {"Content-Type": "application/json"}
        return client.request(method, path, content=body, params=query, headers=headers)
    if body is ...:
        return client.request(method, path, params=query)
    return client.request(method, path, json=body, params=query)


def hostile_requests(spec: dict, operation: dict, template: str, ids: dict, base):
    """Each hostile request for one route, as (what was changed, path, body, query): one path
    id, one query parameter or one body field at a time, then unknown fields and broken bodies.
    `base` is the route's sample body (... when it has none)."""
    params = operation.get("parameters", [])
    names = {p["name"] for p in params if p["in"] == "path"}
    path = template.format(**{name: ids[name] for name in names})
    for name in names:
        for value in PATH_VALUES:
            bad = template.format(**{n: (value if n == name else ids[n]) for n in names})
            yield f"path {name}={value!r}", bad, base, None
    for param in (p["name"] for p in params if p["in"] == "query"):
        for value in QUERY_VALUES:
            yield f"query {param}={value[:20]!r}", path, base, {param: value}
    yield "an unknown query parameter with NUL", path, base, {"unknown": NUL}
    if base is ...:
        return
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    for field in sorted(set(base) | set(resolve(spec, schema).get("properties", {}))):
        for value in FIELD_VALUES:
            yield f"body {field}={str(value)[:20]!r}", path, {**base, field: value}, None
    extra = {"id": 1, "owner_user_id": 2, "status": "deleted", "is_admin": True}
    yield "unknown fields", path, {**base, **extra}, None
    for whole in WHOLE_BODIES:
        yield f"the whole body {whole!r}", path, whole, None


def test_no_hostile_input_gives_a_500_on_any_route(ana):
    spec = ana.app.openapi()
    ids = path_ids(ana)
    with_body, failures, tries = set(), [], 0
    for template, methods in spec["paths"].items():
        for method, operation in methods.items():
            route = f"{method.upper()} {template}"
            names = {p["name"] for p in operation.get("parameters", []) if p["in"] == "path"}
            assert names <= set(ids), f"{route}: add a real id for its path parameters"
            base = ...
            if "requestBody" in operation:
                with_body.add(route)
                assert route in BODIES, f"{route}: add a sample body to BODIES"
                base = fill(BODIES[route], {**ids, **ana.ids})
            for what, path, body, query in hostile_requests(spec, operation, template, ids, base):
                status = (response := send(ana, method.upper(), path, body, query)).status_code
                tries += 1
                if status >= 500 and not (status == 503 and route in MAY_BE_503):
                    failures.append(f"{route} with {what}: {status} {response.text[:100]}")
    assert with_body == set(BODIES), "BODIES names a route that has no body any more"
    assert tries > 3000
    assert failures == []


def resolve(spec: dict, schema: dict) -> dict:
    """The schema itself, behind a $ref or the "or null" of an optional body."""
    for option in schema.get("anyOf", []):
        if option.get("type") != "null":
            schema = option
    if "$ref" in schema:
        schema = spec["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
    return schema


# ── The NUL character (any text field, any query parameter) ──────────────────────────────────

NUL_DETAIL = "Text cannot contain the NUL character (\\u0000)"


def test_a_nul_in_a_text_field_is_422_and_saves_nothing(ana):
    response = ana.patch("/api/users/me", json={"bio": f"Coffee{NUL}first"})
    assert response.status_code == 422
    assert response.json()["error"]["detail"] == f"body → bio: {NUL_DETAIL}"
    assert sql("SELECT bio FROM users WHERE email = 'ana@example.com'") == [(None,)]


def test_a_nul_in_a_query_parameter_is_422(ana):
    response = ana.get("/api/jobs/open", params={"keyword": f"cook{NUL}"})
    assert response.status_code == 422
    assert response.json()["error"]["detail"] == f"query → keyword: {NUL_DETAIL}"


def test_a_nul_is_refused_before_the_login_check_too(ana):
    response = ana.post("/api/auth/login", json={"email": "ana@example.com", "password": NUL})
    assert (response.status_code, response.json()["error"]["detail"]) == (
        422,
        f"body → password: {NUL_DETAIL}",
    )


def test_find_nul_names_the_place_of_the_first_nul():
    assert find_nul({"a": 1, "b": [None, {"c": f"x{NUL}"}]}) == ("b", 1, "c")
    assert find_nul({f"na{NUL}me": "x"}) == (f"na{NUL}me",)
    assert find_nul(f"top{NUL}") == ()
    assert find_nul({"a": ["fine", 3, True, None], "b": "😀 \\u0000 written out"}) is None


def test_broken_json_is_still_answered_by_fastapi(ana):
    response = ana.patch(
        "/api/users/me", content=b'{"bio": ', headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert "JSON decode error" in response.json()["error"]["detail"]


# ── Conversations: ids above BIGINT, an unknown partner, a deleted last message ──────────────


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/conversations/{big}", None),
        ("GET", "/api/conversations/{conv_id}/messages?before_id={big}", None),
        ("POST", "/api/conversations", {"peer_user_id": BIG}),
        ("POST", "/api/conversations/{conv_id}/messages", {"content": "x", "reply_to_id": BIG}),
        ("POST", "/api/conversations/{conv_id}/read", {"last_message_id": BIG}),
        ("PATCH", "/api/conversations/{conv_id}/messages/{big}", {"content": "x"}),
        ("DELETE", "/api/conversations/{conv_id}/participants/{big}", None),
    ],
)
def test_conversation_ids_above_bigint_are_422(ana, method, path, body):
    url = path.format(big=BIG, conv_id=ana.ids["conv_id"])
    response = ana.request(method, url, json=body)
    assert response.status_code == 422
    assert "less than or equal to 9223372036854775807" in response.json()["error"]["detail"]


def test_a_chat_with_an_unknown_or_deleted_user_is_404(ana):
    [(gone,)] = sql(
        "INSERT INTO users (email, status) VALUES ('gone@example.com', 'deleted') RETURNING id"
    )
    for peer in (gone, 999_999):
        response = ana.post("/api/conversations", json={"peer_user_id": peer})
        assert (response.status_code, response.json()["error"]["detail"]) == (404, "User not found")
    assert sql("SELECT count(*) FROM conversations") == [(1,)]  # only the fixture's chat


def test_a_deleted_message_leaves_the_conversation_preview(ana):
    ids = ana.ids
    ben = bearer(ana.app, ids["ben"])
    sent = ana.post(f"/api/conversations/{ids['conv_id']}/messages", json={"content": "Oops"})
    oops = sent.json()["items"][0]["id"]
    assert ana.get("/api/conversations", headers=ben).json()[0]["last_message_content"] == "Oops"
    assert ana.delete(f"/api/conversations/{ids['conv_id']}/messages/{oops}").status_code == 204
    for path in ("/api/conversations", f"/api/conversations/{ids['conv_id']}"):
        answer = ana.get(path, headers=ben).json()
        chat = answer[0] if isinstance(answer, list) else answer
        assert chat["last_message_content"] is None
        assert chat["last_message_author_id"] is None


# ── Text limits ──────────────────────────────────────────────────────────────────────────────


def test_a_job_description_has_at_most_5000_characters(ana):
    body = {**BODIES["POST /api/jobs"], "description": "x" * 5000}
    assert ana.post("/api/jobs", json=body).status_code == 201
    response = ana.post("/api/jobs", json={**body, "description": "x" * 5001})
    assert response.status_code == 422
    path = f"/api/jobs/{ana.ids['job_id']}"
    assert ana.patch(path, json={"description": "x" * 5001}).status_code == 422


def test_a_company_description_has_at_most_2000_characters(ana):
    assert ana.delete("/api/companies").status_code == 204
    response = ana.post("/api/companies", json={"name": "Long", "description": "x" * 2001})
    assert response.status_code == 422
    response = ana.post("/api/companies", json={"name": "Long", "description": "x" * 2000})
    assert response.status_code == 201


def test_a_token_longer_than_any_of_ours_is_422(ana):
    too_long = "x" * (TOKEN_MAX_LENGTH + 1)
    assert ana.post("/api/auth/refresh", json={"refresh_token": too_long}).status_code == 422
    body = {"token": too_long, "new_password": "new pw 1234"}
    assert ana.post("/api/auth/reset-password", json=body).status_code == 422
    assert ana.get("/api/auth/verify", params={"token": too_long}).status_code == 422
    # Logout still answers 204 for any token, as the contract says.
    assert ana.post("/api/auth/logout", json={"refresh_token": too_long}).status_code == 204


# ── WebSocket frames ─────────────────────────────────────────────────────────────────────────

HOSTILE_FRAMES = [
    "not json",
    "[1, 2]",
    '"text"',
    json.dumps({"type": None}),
    json.dumps({"type": "x" * 100_000}),
    json.dumps({"type": f"ping{NUL}"}),
    json.dumps({"type": "delivered", "message_id": BIG}),
    json.dumps({"type": "delivered", "message_id": -1}),
    json.dumps({"type": "delivered", "payload": {"message_id": "1"}}),
    json.dumps({"type": "read", "conversation_id": BIG, "last_message_id": BIG}),
    json.dumps({"type": "read", "conversation_id": 1, "last_message_id": 2**64}),
    json.dumps({"type": "read", "payload": [1]}),
    json.dumps({"type": "chat_message", "text": f"hi{NUL}"}),
    json.dumps({"type": "chat_message", "text": BIG}),
    json.dumps({"type": "chat_message", "payload": {"text": "x" * 100_000}}),
]


def test_hostile_frames_never_break_a_socket(ana):
    """Each socket ignores (or answers with game_error) every hostile frame and still answers
    the next ping: a frame can never crash the socket it came on."""
    ids = ana.ids
    [(room,)] = sql(
        "INSERT INTO game_rooms (target_size, state, discussion_started_at)"
        " VALUES (5, 'discussion', now()) RETURNING id"
    )
    sql(
        "INSERT INTO game_participants (room_id, user_id, display_label)"
        " VALUES (:room, :ana, 'Player 1')",
        room=room,
        ana=ids["ana"],
    )
    # Its own app: the test client's app runs on another event loop.
    server_app = build_app(database_url=TEST_DATABASE_URL, redis_url=TEST_REDIS_URL)
    with running_server(server_app) as server:
        for path, query in (("/ws", ""), ("/ws/game", f"&room_id={room}")):
            answer = httpx2.post(f"http://{server}/api/ws/ticket", headers=ana.headers)
            ticket = answer.json()["ticket"]
            with connect(f"ws://{server}{path}?ticket={ticket}{query}", open_timeout=5) as ws:
                if path == "/ws/game":
                    assert json.loads(ws.recv(timeout=5))["type"] == "game_snapshot"
                for frame in [*HOSTILE_FRAMES, b"\x00\xff binary"]:
                    ws.send(frame)
                    ws.send(json.dumps({"type": "ping"}))
                    while (answer := json.loads(ws.recv(timeout=5)))["type"] != "pong":
                        assert answer["type"] == "game_error", (path, frame[:50], answer)
    assert sql("SELECT count(*) FROM game_messages") == [(0,)]
    assert sql("SELECT status FROM messages") == [("sent",)]
