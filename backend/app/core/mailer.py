"""Outgoing email: over SMTP (Mailpit by default), or Brevo's API when BREVO_API_KEY is set."""

import json
import smtplib
import urllib.request
from email.message import EmailMessage

import structlog
from fastapi import Request

from app.core.config import Settings

BREVO_URL = "https://api.brevo.com/v3/smtp/email"
TIMEOUT_SEC = 10
log = structlog.get_logger(__name__)


class Mailer:
    """Sends plain-text emails with the settings of one app."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def send(self, to: str, subject: str, body: str) -> None:
        """Send one email. Routes run it as a background task, after the answer has gone out,
        so a failure cannot reach the user any more: it is written to the log instead."""
        try:
            if self.settings.brevo_api_key:
                self._send_with_brevo(to, subject, body)
            else:
                self._send_with_smtp(to, subject, body)
        except Exception:  # mail server down, wrong key...: log it with the traceback
            log.exception("email not sent", subject=subject)

    def _send_with_smtp(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self.settings.mail_from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        with smtplib.SMTP(
            self.settings.smtp_host, self.settings.smtp_port, timeout=TIMEOUT_SEC
        ) as smtp:
            smtp.send_message(message)

    def _send_with_brevo(self, to: str, subject: str, body: str) -> None:
        # Brevo only sends from an address verified in the Brevo account: set MAIL_FROM to it.
        payload = {
            "sender": {"email": self.settings.mail_from},
            "to": [{"email": to}],
            "subject": subject,
            "textContent": body,
        }
        request = urllib.request.Request(
            BREVO_URL,
            data=json.dumps(payload).encode(),
            headers={"api-key": self.settings.brevo_api_key, "content-type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT_SEC):
            pass  # an error answer (4xx, 5xx) raises an exception instead


def get_mailer(request: Request) -> Mailer:
    """FastAPI dependency: a mailer with this app's settings. Tests replace it with a fake."""
    return Mailer(request.app.state.settings)
