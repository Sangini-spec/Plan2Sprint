"""Email to the org founder when a new join request comes in (Hotfix 86).

Mirrors the SMTP path used by overdue_alert.py — fails silently if
SMTP isn't configured, so the join request still gets created and
shows up via WS / the in-app Invitations page.
"""

from __future__ import annotations

import asyncio
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from ..config import settings

logger = logging.getLogger(__name__)


async def send_join_request_email(
    *,
    founder_email: str,
    founder_name: str,
    requester_email: str,
    requester_name: str,
    target_org_name: str,
) -> bool:
    if not settings.smtp_host or not settings.smtp_user:
        logger.warning("SMTP not configured — join-request email NOT sent")
        return False

    from ..email.sender import _smtp_send, _executor, _html_to_plain

    base = "https://plan2sprint-web.purplebeach-150945ee.westus3.azurecontainerapps.io"
    html = f"""\
<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#f5f5f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
    <div style="max-width:560px;margin:24px auto;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #e2e8f0;">
      <div style="background:linear-gradient(135deg,#0f172a 0%,#334155 100%);color:white;padding:22px 26px;">
        <div style="font-size:11px;letter-spacing:0.18em;text-transform:uppercase;opacity:0.85;">Join Request</div>
        <h1 style="margin:6px 0 0;font-size:20px;line-height:1.3;">Approval needed for {target_org_name}</h1>
      </div>
      <div style="padding:22px 26px;color:#0f172a;font-size:14px;line-height:1.55;">
        <p>Hi {founder_name},</p>
        <p><b>{requester_name}</b> ({requester_email}) is requesting to
        join your Plan2Sprint organisation <b>{target_org_name}</b>.</p>
        <p>They submitted this by renaming their own organisation to
        match yours. Plan2Sprint won't move them in until you approve
        the request.</p>
        <div style="margin-top:20px;padding:14px;background:#f1f5f9;border-radius:8px;">
          <p style="margin:0 0 10px;color:#334155;">Review the request and decide:</p>
          <a href="{base}/po/invitations"
             style="display:inline-block;padding:9px 16px;background:#0f172a;color:white;text-decoration:none;border-radius:6px;font-weight:600;font-size:13px;">
            Open Plan2Sprint &rarr; Invitations
          </a>
        </div>
        <p style="margin-top:18px;color:#475569;font-size:12px;">
          If you don't recognise this person, click <b>Reject</b>. They will
          stay in their own organisation; nothing in {target_org_name}
          changes.
        </p>
      </div>
      <div style="padding:12px 26px;background:#f8fafc;color:#94a3b8;font-size:11px;text-align:center;border-top:1px solid #e2e8f0;">
        Sent because {requester_email} requested to join {target_org_name}.
      </div>
    </div>
  </body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg["From"] = settings.email_from_address
    msg["To"] = founder_email
    msg["Subject"] = (
        f"Plan2Sprint: {requester_email} wants to join '{target_org_name}'"
    )
    msg.attach(MIMEText(_html_to_plain(html), "plain"))
    msg.attach(MIMEText(html, "html"))

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _smtp_send, msg, founder_email)
