"""Guard for /_internal/* routes: only callers that know INTERNAL_API_KEY get in."""

import secrets
from typing import Annotated

from fastapi import Header, HTTPException, Request


def require_internal_key(request: Request, x_internal_key: Annotated[str, Header()] = "") -> None:
    expected = request.app.state.settings.internal_api_key
    # 404, not 403: an outsider cannot even tell that the route exists.
    if not expected or not secrets.compare_digest(x_internal_key, expected):
        raise HTTPException(status_code=404, detail="Not Found")
