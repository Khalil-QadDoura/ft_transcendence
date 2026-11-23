"""Constants for the applications domain: transitions, pagination, view dedup, WS events."""

# Deduplication window for counting unique job page views in Redis (24 hours).
JOB_VIEW_DEDUP_TTL_SEC = 86_400

# Upper bound for PostgreSQL BIGINT primary keys / cursors (reject overflows as 422).
MAX_ID = 2**63 - 1

# Cursor pagination bounds for application listings.
DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100

# Text length limits matching the database columns and API contract.
COVER_NOTE_MAX_LENGTH = 1000
STATUS_NOTE_MAX_LENGTH = 500

# Allowed state transitions by role. Any move not listed here returns 409 Conflict.
EMPLOYER_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "submitted": ("viewed", "shortlisted", "rejected"),
    "viewed": ("shortlisted", "rejected"),
    "shortlisted": ("contacted", "hired", "rejected"),
    "contacted": ("hired", "rejected"),
}

APPLICANT_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "submitted": ("withdrawn",),
    "viewed": ("withdrawn",),
    "shortlisted": ("withdrawn",),
    "contacted": ("withdrawn",),
}

# Real-time WebSocket event names pushed over the BE-06 layer.
EVENT_APPLICATION_CREATED = "application_created"
EVENT_APPLICATION_UPDATED = "application_updated"
