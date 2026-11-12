"""Loopback-only integration harness. Use a disposable test DB; never deploy.

Uses the actual team application, migrations and auth. Only outgoing email is
captured so frontend tests can follow the verification link without real delivery.
"""

import html
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from urllib.parse import urlsplit


def main():
    database = os.environ.get("TEST_DATABASE_URL", "")
    parsed = urlsplit(database)
    if (
        parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or "test" not in parsed.path.lower()
        or parsed.scheme != "postgresql+asyncpg"
    ):
        raise SystemExit("Use an explicit loopback TEST_DATABASE_URL with 'test' in the database name.")
    frontend = os.environ.get("TEST_FRONTEND_ORIGIN", "http://127.0.0.1:5178")
    if urlsplit(frontend).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise SystemExit("TEST_FRONTEND_ORIGIN must be loopback.")
    backend = Path(__file__).resolve().parents[2] / "backend"
    os.environ.update(
        DATABASE_URL=database,
        JWT_SECRET=secrets.token_hex(32),
        FRONTEND_BASE_URL=frontend,
        ENV="dev",
        LOG_LEVEL="ERROR",
    )
    sys.path.insert(0, str(backend))
    os.chdir(backend)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)

    from app.core.mailer import get_mailer
    from app.main import app
    from fastapi import HTTPException
    from fastapi.responses import HTMLResponse
    import uvicorn

    messages = []

    class CapturedMail:
        def send(self, to, subject, body):
            messages.append({"to": to, "body": body})

    app.dependency_overrides[get_mailer] = CapturedMail

    def link(message):
        return re.search(re.escape(frontend.rstrip("/")) + r"/verify-email\?token=\S+", message["body"])[0]

    @app.get("/__review/mail", include_in_schema=False)
    def mail(email: str):
        if email.endswith("@example.com"):
            for message in reversed(messages):
                if message["to"] == email:
                    return {"link": link(message)}
        raise HTTPException(404)

    @app.get("/__review/inbox", response_class=HTMLResponse, include_in_schema=False)
    def inbox():
        return "<h1>Local test inbox</h1><p>Captured mail only.</p>" + "".join(
            f'<article><h2>{html.escape(message["to"])}</h2>'
            f'<a href="{html.escape(link(message))}">Verify test account</a></article>'
            for message in reversed(messages)
        )

    uvicorn.run(app, host="127.0.0.1", port=8010, access_log=False)


if __name__ == "__main__":
    main()
