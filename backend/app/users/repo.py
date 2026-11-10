"""Database queries of /api/users. None so far: the file exists because every domain package
has the same five files.

/users/me only ever works on the logged-in user's own row, which CurrentUser has already
loaded (auth/repo.py, get_user_by_id). The service changes that object and commits, and
SQLAlchemy writes the UPDATE itself, with only the columns that changed.
"""
