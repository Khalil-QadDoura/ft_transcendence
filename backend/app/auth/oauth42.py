"""Talking to 42 intra (BE-11): the address of its login page, swapping a code for a 42
token, and reading the user's 42 profile. No database, no rules."""

import asyncio
import http.client
import json
import urllib.parse
import urllib.request

from app.auth.constants import FT_REQUEST_TIMEOUT_SEC, OAUTH_CALLBACK_PATH, OAUTH_SCOPE
from app.core.config import Settings


class FtError(Exception):
    """42 did not give us what we asked for: it refused, was too slow, could not be reached,
    or answered something that is not what its API documents."""


def is_configured(settings: Settings) -> bool:
    """True when both keys of the 42 app are set; without them 42 refuses every login."""
    return bool(settings.ft_client_id and settings.ft_client_secret)


def redirect_uri(settings: Settings) -> str:
    """Our callback address. 42 sends the browser back to it, and only to it: the 42 intra app
    settings must list exactly this, e.g. https://localhost/api/auth/oauth/42/callback."""
    return settings.frontend_base_url.rstrip("/") + OAUTH_CALLBACK_PATH


def authorize_url(settings: Settings, state: str) -> str:
    """The address of 42's login page, with what 42 needs to send the browser back to us."""
    query = urllib.parse.urlencode(
        {
            "client_id": settings.ft_client_id,
            "redirect_uri": redirect_uri(settings),
            "response_type": "code",  # "send back a code", the authorization code flow
            "scope": OAUTH_SCOPE,
            "state": state,  # 42 sends it back unchanged with the code
        }
    )
    return f"{settings.ft_authorize_url}?{query}"


async def exchange_code(settings: Settings, code: str) -> str:
    """Swap the code from the callback for a 42 access token. This goes from our server to
    42, never through the browser, because it carries our client secret."""
    form = {
        "grant_type": "authorization_code",
        "client_id": settings.ft_client_id,
        "client_secret": settings.ft_client_secret,
        "code": code,
        # The same address as on the login page: 42 checks that they match.
        "redirect_uri": redirect_uri(settings),
    }
    request = urllib.request.Request(
        settings.ft_token_url, data=urllib.parse.urlencode(form).encode(), method="POST"
    )
    answer = await _send(request)
    access_token = answer.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise FtError("42's token answer has no access_token")
    return access_token


async def fetch_me(settings: Settings, access_token: str) -> dict:
    """The user's 42 profile (GET /v2/me): email, login, first_name, last_name, ..."""
    request = urllib.request.Request(
        settings.ft_me_url, headers={"Authorization": f"Bearer {access_token}"}
    )
    return await _send(request)


async def _send(request: urllib.request.Request) -> dict:
    # urllib waits for the answer and blocks while it waits, so it runs in a worker thread:
    # meanwhile the server keeps answering other requests (as for Argon2 in the service).
    return await asyncio.to_thread(_send_and_read_json, request)


def _send_and_read_json(request: urllib.request.Request) -> dict:
    request.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=FT_REQUEST_TIMEOUT_SEC) as response:
            answer = json.load(response)
    # OSError: refused (an error status such as 401 or 500), unreachable, or too slow.
    # HTTPException: a broken HTTP answer. ValueError: an answer that is not JSON.
    except (OSError, http.client.HTTPException, ValueError) as error:
        raise FtError(f"{type(error).__name__}: {error}") from error
    if not isinstance(answer, dict):
        raise FtError("42's answer is not a JSON object")
    return answer
