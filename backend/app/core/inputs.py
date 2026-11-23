"""One input rule for every route under /api: no NUL character in the query or the JSON body.

PostgreSQL cannot keep the NUL character (code 0: "\\u0000" in JSON, "%00" in an address) in a
text column. It refuses the whole statement, so before this check the user got a 500. Any text
field of any schema can carry one, so instead of a rule on each field, one dependency on the
/api router (main.py) looks at the whole query and the whole JSON body before the route runs,
like limit_writes. A route added later is covered without a word. The answer is our standard
422.
"""

from typing import Any

from fastapi import HTTPException, Request

NUL = "\x00"
NUL_REFUSED = "Text cannot contain the NUL character (\\u0000)"


def is_json(content_type: str | None) -> bool:
    """Whether FastAPI reads a body with this Content-Type as JSON: no type at all, or
    application/json, or a type such as application/problem+json."""
    if not content_type:
        return True
    media_type = content_type.split(";")[0].strip().lower()
    return media_type == "application/json" or (
        media_type.startswith("application/") and media_type.endswith("+json")
    )


def find_nul(value: Any, where: tuple = ()) -> tuple | None:
    """Where the first NUL character is in a JSON value: the keys and list positions down to
    it, e.g. ("bio",) or ("items", 0). None when there is none."""
    if isinstance(value, str):
        return where if NUL in value else None
    if isinstance(value, dict):
        children = value.items()
    elif isinstance(value, list):
        children = enumerate(value)
    else:  # a number, true, false or null
        return None
    for key, child in children:
        if isinstance(key, str) and NUL in key:  # in a field's name
            return (*where, key)
        found = find_nul(child, (*where, key))
        if found is not None:
            return found
    return None


def refused(where: tuple) -> HTTPException:
    # Written like a validation error of the route: "body → bio: ..." (core/errors.py).
    place = " → ".join(str(part).replace(NUL, "\\u0000") for part in where)
    return HTTPException(status_code=422, detail=f"{place}: {NUL_REFUSED}")


async def refuse_nul(request: Request) -> None:
    """422 when the query or the JSON body holds a NUL character, in a value or in a name."""
    for name, value in request.query_params.multi_items():
        if NUL in name or NUL in value:
            raise refused(("query", name))
    if not is_json(request.headers.get("content-type")) or not await request.body():
        return
    try:
        body = await request.json()  # FastAPI has already read it: this is its own copy
    except ValueError:  # not JSON at all: FastAPI answers that with its own 422
        return
    where = find_nul(body)
    if where is not None:
        raise refused(("body", *where))
