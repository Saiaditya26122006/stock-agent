"""SMTP email sender for morning and EOD briefings."""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv


logger = logging.getLogger(__name__)


def _load_env() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)


def _build_html_message(subject: str, html_content: str, sender: str, recipient: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(html_content, "html", "utf-8"))
    return msg


def _send_html_email(html_content: str, subject: str) -> bool:
    _load_env()
    sender = (os.getenv("GMAIL_SENDER") or "").strip()
    app_password = (os.getenv("GMAIL_APP_PASSWORD") or "").strip()
    if not sender or not app_password:
        logger.error("Email send failed: missing GMAIL_SENDER or GMAIL_APP_PASSWORD.")
        return False

    try:
        msg = _build_html_message(subject=subject, html_content=html_content, sender=sender, recipient=sender)
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as server:
            server.starttls()
            server.login(sender, app_password)
            server.sendmail(sender, [sender], msg.as_string())
        return True
    except smtplib.SMTPAuthenticationError as exc:
        logger.error("Email authentication failed (check Gmail app password): %s", exc)
        return False
    except Exception as exc:
        logger.error("Email send failed for subject '%s': %s", subject, exc)
        return False


def send_morning_briefing(html_content: str, subject: str) -> bool:
    """Send morning briefing HTML email to configured sender mailbox."""
    return _send_html_email(html_content=html_content, subject=subject)


def send_eod_report(html_content: str) -> bool:
    """Send EOD report HTML email with fixed subject."""
    return _send_html_email(html_content=html_content, subject="NSE/BSE AI Agent — End of Day Report")


def test_email_connection() -> bool:
    """Verify SMTP login credentials without sending a full report."""
    _load_env()
    sender = (os.getenv("GMAIL_SENDER") or "").strip()
    app_password = (os.getenv("GMAIL_APP_PASSWORD") or "").strip()
    if not sender or not app_password:
        logger.error("Email test failed: missing GMAIL_SENDER or GMAIL_APP_PASSWORD.")
        return False

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as server:
            server.starttls()
            server.login(sender, app_password)
        logger.info("Email SMTP connection test passed.")
        return True
    except smtplib.SMTPAuthenticationError as exc:
        logger.error("Email SMTP authentication failed: %s", exc)
        return False
    except Exception as exc:
        logger.error("Email SMTP connection test failed: %s", exc)
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ok = test_email_connection()
    print("Email connection:", "OK" if ok else "FAILED")
