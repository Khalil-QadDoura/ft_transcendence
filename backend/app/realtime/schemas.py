"""Shapes of the WebSocket layer: the ticket answer and the frames sent on the socket."""

from typing import Any

from pydantic import BaseModel


class TicketOut(BaseModel):
    """POST /api/ws/ticket: open wss://<host>/ws?ticket=<ticket> with it, within 30 seconds."""

    ticket: str


class Event(BaseModel):
    """Every frame the server sends: {"type": "...", "payload": ...}, as JSON text.

    The client looks at `type` to know what happened, and ignores types it does not know.
    `payload` can be a dict, a response model (e.g. a message) or None.
    """

    type: str
    payload: Any = None


class PresenceOut(BaseModel):
    """Payload of a "presence" event, sent to a user's friends when the user's first socket
    opens (is_online true) and when the last one closes (is_online false)."""

    user_id: int
    is_online: bool
