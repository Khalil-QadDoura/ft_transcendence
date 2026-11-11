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
