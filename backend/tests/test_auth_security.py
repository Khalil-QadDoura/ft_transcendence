"""Password hashing, tokens and the JWT secret setting. No database needed."""

from datetime import timedelta

import jwt
import pytest
from pydantic import ValidationError

from app.auth import security
from app.core.config import Settings

SECRET = "made-up-secret-for-these-tests-0123456789"
PASSWORD = "correct horse battery"


def test_password_hash_is_argon2id_with_its_own_salt():
    first = security.hash_password(PASSWORD)
    second = security.hash_password(PASSWORD)
    assert first.startswith("$argon2id$")
    assert PASSWORD not in first
    # A new random salt each time: the same password never gives the same hash.
    assert first != second
    assert security.verify_password(PASSWORD, first)
    assert security.verify_password(PASSWORD, second)


def test_wrong_password_or_no_hash_does_not_verify():
    password_hash = security.hash_password(PASSWORD)
    assert not security.verify_password("wrong password", password_hash)
    assert not security.verify_password(PASSWORD, None)  # no such account
    assert not security.verify_password(PASSWORD, "not a hash")


def test_token_carries_user_scope_and_extra_claims():
    token, claims = security.create_token(SECRET, 42, "access", timedelta(minutes=15), ver=3)
    read = security.read_token(SECRET, token, "access")
    assert read["sub"] == "42"
    assert read["scope"] == "access"
    assert read["ver"] == 3
    assert read["jti"] == claims["jti"]
    assert read["exp"] - read["iat"] == 15 * 60


def test_every_token_has_its_own_id():
    _, first = security.create_token(SECRET, 42, "refresh", timedelta(days=30))
    _, second = security.create_token(SECRET, 42, "refresh", timedelta(days=30))
    assert first["jti"] != second["jti"]


def test_expired_token_is_refused():
    token, _ = security.create_token(SECRET, 42, "access", timedelta(seconds=-1))
    with pytest.raises(jwt.ExpiredSignatureError):
        security.read_token(SECRET, token, "access")


def test_token_of_another_kind_is_refused():
    refresh_token, _ = security.create_token(SECRET, 42, "refresh", timedelta(days=30))
    with pytest.raises(jwt.InvalidTokenError, match="wrong scope, expected access"):
        security.read_token(SECRET, refresh_token, "access")


def test_token_signed_with_another_secret_is_refused():
    token, _ = security.create_token(
        "another-secret-that-we-never-use-0000", 42, "access", timedelta(minutes=15)
    )
    with pytest.raises(jwt.InvalidSignatureError):
        security.read_token(SECRET, token, "access")


def test_changed_token_is_refused():
    # A token is three parts: header.claims.signature. Ours is for user 42.
    ours, _ = security.create_token(SECRET, 42, "access", timedelta(minutes=15))
    header, _, signature = ours.split(".")
    # The claims part is only base64 JSON, so anyone can write one that says "user 1"...
    forged, _ = security.create_token(
        "attacker-key-0123456789abcdef0123", 1, "access", timedelta(minutes=15)
    )
    forged_claims = forged.split(".")[1]
    # ...but without our secret they cannot make the signature that matches it.
    with pytest.raises(jwt.InvalidSignatureError):
        security.read_token(SECRET, f"{header}.{forged_claims}.{signature}", "access")


def test_app_refuses_to_start_without_a_jwt_secret(monkeypatch):
    monkeypatch.delenv("JWT_SECRET")
    with pytest.raises(ValidationError, match="jwt_secret"):
        Settings(_env_file=None)


def test_app_refuses_a_short_jwt_secret():
    with pytest.raises(ValidationError, match="at least 32 characters"):
        Settings(_env_file=None, jwt_secret="too-short")
