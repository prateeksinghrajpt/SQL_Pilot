from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def _send_email(recipient: str, subject: str, body: str) -> None:
    settings = get_settings()
    if not settings.smtp_host or not settings.smtp_from_email:
        logger.warning("Access notification email is not configured")
        return

    message = EmailMessage()
    message["From"] = settings.smtp_from_email
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=8) as server:
            server.starttls(context=ssl.create_default_context())
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password or "")
            server.send_message(message)
    except (OSError, smtplib.SMTPException):
        logger.exception("Could not deliver access notification email")


def notify_admin_access_request(email: str) -> None:
    settings = get_settings()
    if not settings.admin_email:
        logger.warning("Admin email is not configured; access request remains in the admin queue")
        return
    url = settings.app_public_url.rstrip("/")
    _send_email(
        settings.admin_email,
        "SQL Copilot access request",
        f"{email} requested access to SQL Copilot.\n\nReview pending requests here: {url}/?view=access-requests\n",
    )


def notify_user_access_decision(email: str, approved: bool) -> None:
    status = "approved" if approved else "not approved"
    url = get_settings().app_public_url.rstrip("/")
    _send_email(
        email,
        f"Your SQL Copilot access was {status}",
        f"Your request for SQL Copilot access was {status}.\n\nSign in here: {url}\n",
    )
