"""Every rate limit of the API, in one place (BE-12). Listed in api-contract.md ("Rate limit").

A limit is "<number>/<second|minute|hour>". A count starts again at the end of each window.
"""

# Login and sign-up: per client IP, with @limiter.limit(...) on the route (BE-03, BE-11).
REGISTER_RATE_LIMIT = "5/minute"
LOGIN_RATE_LIMIT = "10/minute"
REFRESH_RATE_LIMIT = "20/minute"
CHANGE_PASSWORD_RATE_LIMIT = "5/minute"
FORGOT_PASSWORD_RATE_LIMIT = "3/minute"
RESET_PASSWORD_RATE_LIMIT = "5/minute"
OAUTH_START_RATE_LIMIT = "10/minute"  # the same as login: it is a login too

# Every write (POST, PUT, PATCH, DELETE) under /api, counted per route: a logged-in user has
# a count of their own, anyone else shares the count of their IP. One write a second, for a
# minute, on the same route is far more than a person clicks.
WRITE_RATE_LIMIT = "60/minute"

# Stricter numbers for the writes that cost the most or annoy other people.
UPLOAD_URL_RATE_LIMIT = "10/minute"  # each signed upload link lets the browser store a file
MESSAGE_SEND_RATE_LIMIT = "30/minute"
FRIEND_REQUEST_RATE_LIMIT = "10/minute"
GAME_QUEUE_JOIN_RATE_LIMIT = "10/minute"

# The routes that do not use WRITE_RATE_LIMIT, each with its own limit. The path is written
# as its router writes it, without /api (as in api-contract.md). One line here gives a route
# its own number.
ROUTE_RATE_LIMITS = {
    "POST /media/intro-video/upload-url": UPLOAD_URL_RATE_LIMIT,
    "POST /media/avatar/upload-url": UPLOAD_URL_RATE_LIMIT,
    "POST /media/company-logo/upload-url": UPLOAD_URL_RATE_LIMIT,
    "POST /conversations/{conv_id}/messages": MESSAGE_SEND_RATE_LIMIT,
    "POST /friends/requests": FRIEND_REQUEST_RATE_LIMIT,
    "POST /game/queue/join": GAME_QUEUE_JOIN_RATE_LIMIT,
}

# Chat lines a player sends over /ws/game, per user, in all rooms and tabs together. The
# discussion lasts 120 s: a line every 2 s is still allowed.
GAME_CHAT_RATE_LIMIT = "30/minute"
