"""Room chat and resync (BE-09): the /ws/game socket, chat messages and their history, and the
snapshot a player gets each time the socket opens.

The socket listens on its user's Redis channel, like /ws (BE-06), so every game event the rest
of the game sends with send_to_user() reaches it as well. What /ws/game adds: the snapshot
first, then the `chat_message` frame.

Before the results, players know each other only by label number (1-5: "Player 3" is 3), never
by database id (rules, section 9). Every payload in this file follows that.
"""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.game import repo
from app.game.constants import label_number
from app.game.models import GameMessage, GameParticipant
from app.game.schemas import GameMessageEventOut, GameMessagesPage
from app.users.models import User

NOT_A_PARTICIPANT = "Not a participant of this room"


def message_out(message: GameMessage, author: GameParticipant) -> GameMessageEventOut:
    """A chat message as players see it: the author by label number, never by database id."""
    return GameMessageEventOut(
        id=message.id,
        participant_id=label_number(author.display_label),
        display_label=author.display_label,
        text=message.text,
    )


async def list_messages(
    session: AsyncSession, user: User, room_id: int, before_id: int | None, limit: int
) -> GameMessagesPage:
    """GET /api/game/rooms/{id}/messages: one page of the room's chat, for its participants."""
    if await repo.get_room(session, room_id) is None:
        raise HTTPException(status_code=404, detail="Room not found")
    if await repo.get_participant_for_user(session, room_id, user.id) is None:
        raise HTTPException(status_code=403, detail=NOT_A_PARTICIPANT)
    rows, prev_before_id = await repo.list_room_messages(session, room_id, before_id, limit)
    return GameMessagesPage(
        items=[message_out(message, author) for message, author in rows],
        prev_before_id=prev_before_id,
    )
