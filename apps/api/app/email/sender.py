"""
Email delivery via SMTP.
"""

import logging
import smtplib
import ssl
from concurrent.futures import ThreadPoolExecutor
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from ..config import settings
from .templates import invite_email_html, invite_email_text

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2)


async def send_invite_email(
    to_email: str,
    invite_url: str,
    org_name: str,
    role: str,
    invited_by: str,
) -> bool:
    """Send a branded Plan2Sprint invitation email via SMTP. Returns True on success."""
    import asyncio

    if not settings.smtp_host or not settings.smtp_user:
        log.warning("SMTP not configured (host=%r, user=%r)", settings.smtp_host, settings.smtp_user)
        return False

    html = invite_email_html(to_email, invite_url, org_name, role, invited_by)
    text = invite_email_text(to_email, invite_url, org_name, role, invited_by)

    msg = MIMEMultipart("alternative")
    msg["From"] = settings.email_from_address
    msg["To"] = to_email
    msg["Subject"] = f"You've been invited to join {org_name} on Plan2Sprint"
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _smtp_send, msg, to_email)


async def send_report_email(
    to_email: str,
    subject: str,
    html_body: str,
    pdf_bytes: bytes,
    pdf_filename: str = "weekly-report.pdf",
) -> bool:
    """Send an HTML email with a PDF attachment. Used by the Friday stakeholder report."""
    import asyncio

    if not settings.smtp_host or not settings.smtp_user:
        log.warning("SMTP not configured — cannot send report to %s", to_email)
        return False

    msg = MIMEMultipart("mixed")
    msg["From"] = settings.email_from_address
    msg["To"] = to_email
    msg["Subject"] = subject

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(_html_to_plain(html_body), "plain"))
    alt.attach(MIMEText(html_body, "html"))
    msg.attach(alt)

    attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
    attachment.add_header("Content-Disposition", "attachment", filename=pdf_filename)
    msg.attach(attachment)

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _smtp_send, msg, to_email)


def _html_to_plain(html: str) -> str:
    """Very rough HTML → text fallback for the multipart alt body."""
    import re
    s = re.sub(r"<[^>]+>", " ", html)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _smtp_send(msg: MIMEMultipart, to_email: str) -> bool:
    try:
        envelope_from = settings.smtp_user

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
            server.login(settings.smtp_user, settings.smtp_pass)
            server.sendmail(envelope_from, to_email, msg.as_string())

        log.info("Invite email sent to %s via SMTP", to_email)
        return True
    except Exception as e:
        log.error("SMTP send failed to %s: %s", to_email, e, exc_info=True)
        return False
