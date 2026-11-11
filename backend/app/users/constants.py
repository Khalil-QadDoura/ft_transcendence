"""The fixed numbers of the profile, in one place."""

# Users must be at least this old (birth_date, checked on PATCH /api/users/me).
MIN_AGE = 18

# Longest text allowed in each profile field: the column sizes in users/models.py.
NAME_MAX_LENGTH = 50  # first_name and last_name
POSITION_MAX_LENGTH = 100
BIO_MAX_LENGTH = 500
