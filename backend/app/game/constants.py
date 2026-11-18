"""Turing Duel constants: room capacities, label pool, lock timings, and template lines."""

MAX_PARTICIPANTS = 5
MIN_HUMAN_PARTICIPANTS = 1
START_NOW_MIN_PARTICIPANTS = 2
START_NOW_MAX_PARTICIPANTS = 4
MIN_EXPIRY_START_PARTICIPANTS = 2

# Largest positive BIGINT accepted in path/query parameters.
MAX_ID = 9_223_372_036_854_775_807

# Anonymous seats drawn randomly from this pool on join (DOC-08).
PLAYER_LABELS = tuple(f"Player {n}" for n in range(1, MAX_PARTICIPANTS + 1))


def label_number(display_label: str) -> int:
    """The number of a label: 3 for "Player 3". Before the results, players know each other
    only by this number, never by the database id (rules, section 9)."""
    return PLAYER_LABELS.index(display_label) + 1


# Redis lock timeouts for queue assignment and per-room transitions.
MATCHMAKING_LOCK_KEY = "game:lock:matchmaking"
ROOM_LOCK_KEY_PREFIX = "game:lock:room:"
LOCK_TTL_SECONDS = 10
LOCK_BLOCKING_TIMEOUT_SECONDS = 5

# Template discussion lines used by bots with simulated typing delays until TC-01.
BOT_CHAT_TEMPLATES = (
    "hey everyone, good luck figuring this out",
    "so who here is actually human lol",
    "anyone else feel like the chat starts way too fast?",
    "honestly half of us sound like bots right now",
    "wait what kind of jobs are people looking for here?",
    "that sounded weirdly polite, suspicious tbh",
    "i'm definitely human, just typing slowly on my laptop",
    "interesting... nobody wants to go first?",
)
