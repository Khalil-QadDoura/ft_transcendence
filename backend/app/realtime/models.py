"""The WebSocket layer owns no tables: its tickets and presence live in Redis, which forgets
them by itself after a few seconds. The file exists because every domain package has the same
five files."""
