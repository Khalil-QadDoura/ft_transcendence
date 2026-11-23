"""The fixed numbers of the profile, in one place."""

# Users must be at least this old (birth_date, checked on PATCH /api/users/me).
MIN_AGE = 18

# Longest text allowed in each profile field: the column sizes in users/models.py.
NAME_MAX_LENGTH = 50  # first_name and last_name
POSITION_MAX_LENGTH = 100
BIO_MAX_LENGTH = 500

# The second stage of an account deletion (Privacy Policy section 6, BE-34): the daily job of
# the worker anonymises an account this many days after DELETE /api/users/me.
ANONYMISE_AFTER_DAYS = 30
# The hour (UTC) of that daily job: 00:00 UTC is 04:00 in the UAE.
ANONYMISE_HOUR_UTC = 0
# What the API shows instead of the name of a deleted account (chat, applications).
DELETED_USER_NAME = "Deleted user"
