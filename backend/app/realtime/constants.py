"""The fixed numbers of the WebSocket layer, in one place."""

# A ticket opens one WebSocket, once, and only within this many seconds of being made.
TICKET_LIFETIME_SECONDS = 30

# A socket counts as online for this many seconds after it opened or last sent "ping". The
# client pings every 25-30 s (api-contract.md), so an open socket never runs out of time; one
# left behind by a crashed API process stops counting after at most this long.
PRESENCE_TTL_SECONDS = 60
