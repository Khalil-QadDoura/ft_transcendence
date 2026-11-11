"""The email sender: over SMTP to a real mail server running inside the test, or to Brevo.
The test mail server (the smtp_server fixture) is in conftest.py."""

import contextlib
import json

from conftest import free_port

from app.core import mailer as mailer_module
from app.core.config import Settings
from app.core.mailer import BREVO_URL, Mailer


def settings(**values) -> Settings:
    """Settings for one test; _env_file=None ignores a developer's own backend/.env."""
    return Settings(_env_file=None, **values)


def test_sends_the_email_over_smtp(smtp_server):
    port, inbox = smtp_server
    mailer = Mailer(
        settings(smtp_host="127.0.0.1", smtp_port=port, mail_from="no-reply@wozu.local")
    )
    mailer.send(
        "ana@example.com", "Verify your account", "https://localhost/verify-email?token=abc"
    )

    [email] = inbox.emails
    assert email["From"] == "no-reply@wozu.local"
    assert email["To"] == "ana@example.com"
    assert email["Subject"] == "Verify your account"
    assert "https://localhost/verify-email?token=abc" in email.get_content()


def test_uses_brevo_when_its_key_is_set(monkeypatch):
    sent = []

    def fake_urlopen(request, timeout):
        sent.append(request)
        return contextlib.nullcontext()  # stands in for Brevo's "201 Created" answer

    monkeypatch.setattr(mailer_module.urllib.request, "urlopen", fake_urlopen)
    mailer = Mailer(settings(brevo_api_key="made-up-brevo-key", mail_from="hello@wozu.example"))
    mailer.send("ana@example.com", "Verify your account", "the link")

    [request] = sent
    assert request.full_url == BREVO_URL
    assert request.get_header("Api-key") == "made-up-brevo-key"
    assert json.loads(request.data) == {
        "sender": {"email": "hello@wozu.example"},
        "to": [{"email": "ana@example.com"}],
        "subject": "Verify your account",
        "textContent": "the link",
    }


def test_a_failed_send_is_logged_not_raised(caplog):
    # Nothing listens on this port: like Mailpit being down.
    mailer = Mailer(settings(smtp_host="127.0.0.1", smtp_port=free_port()))
    mailer.send("ana@example.com", "Verify your account", "the link")  # does not raise
    [record] = [r for r in caplog.records if r.name == "app.core.mailer"]
    assert record.levelname == "ERROR"
    assert record.msg["event"] == "email not sent"
