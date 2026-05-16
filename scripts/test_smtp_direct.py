#!/usr/bin/env python3
"""
Direct-from-server SMTP test. Bypasses Supabase entirely and sends a
plain-text email using the exact same SMTP_* credentials in
``apps/api/.env``.

This isolates whether Gmail SMTP is working at all with these
credentials. If this script delivers a mail, Gmail SMTP is fine and
the no-mail problem we just hit is in Supabase's integration (almost
always: a typo in the App Password when it was pasted into the
dashboard's SMTP Settings — spaces, wrong character, copy from the
wrong cell of the App Password page, etc.). If this script ALSO
fails to deliver, the underlying Gmail App Password is bad.

USAGE
-----
    python scripts/test_smtp_direct.py [recipient_email]

If no recipient is provided, defaults to ``EMAIL_FROM_ADDRESS`` (the
SMTP user itself — Gmail is happy to relay to yourself).
"""
from __future__ import annotations

import os
import sys
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

from dotenv import load_dotenv  # type: ignore

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / "apps" / "api" / ".env")


def main() -> int:
    host = os.environ.get("SMTP_HOST", "")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    pw = os.environ.get("SMTP_PASS", "")
    from_addr = os.environ.get("EMAIL_FROM_ADDRESS", "")

    if not all([host, port, user, pw, from_addr]):
        print("ERROR: Missing SMTP_* env vars in apps/api/.env", file=sys.stderr)
        return 1

    recipient = sys.argv[1] if len(sys.argv) > 1 else "sangini@concept2action.ai"

    print(f"SMTP host:        {host}:{port}")
    print(f"SMTP user:        {user}")
    print(f"SMTP password:    {'•' * len(pw)} ({len(pw)} chars)")
    print(f"From address:     {from_addr}")
    print(f"Recipient:        {recipient}")
    print()

    msg = MIMEMultipart("alternative")
    msg["From"] = from_addr
    msg["To"] = recipient
    msg["Subject"] = "[Plan2Sprint] Direct SMTP test"
    msg.attach(MIMEText(
        "This is a direct-from-server SMTP test, sent via Python "
        "smtplib using the same Gmail credentials configured in "
        "apps/api/.env. If you received this, Gmail SMTP is working "
        "fine and the Supabase no-email issue is a configuration "
        "problem inside Supabase (most likely a typo in the App "
        "Password field of the SMTP Settings panel).",
        "plain",
    ))

    try:
        print(f"Connecting to {host}:{port} …")
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.set_debuglevel(0)  # bump to 1 if you want to see the full SMTP convo
            print("  EHLO …")
            server.ehlo()
            print("  STARTTLS …")
            server.starttls()
            server.ehlo()
            print(f"  Login as {user} …")
            server.login(user, pw)
            print(f"  Sending to {recipient} …")
            envelope_from = user  # Gmail rewrites this to the authenticated user anyway
            server.sendmail(envelope_from, recipient, msg.as_string())
        print()
        print(f"  OK. Message accepted by Gmail SMTP.")
        print(f"  → Now check {recipient} (inbox + spam) within ~30 seconds.")
        return 0
    except smtplib.SMTPAuthenticationError as e:
        print()
        print(f"  AUTH FAILED: {e}")
        print(f"  This means SMTP_USER / SMTP_PASS in apps/api/.env are wrong.")
        print(f"  Generate a fresh Gmail App Password at:")
        print(f"     https://myaccount.google.com/apppasswords")
        return 2
    except smtplib.SMTPRecipientsRefused as e:
        print()
        print(f"  RECIPIENT REFUSED: {e}")
        print(f"  Gmail SMTP wouldn't deliver to {recipient}.")
        return 3
    except smtplib.SMTPException as e:
        print()
        print(f"  SMTP error: {e}")
        return 4
    except Exception as e:
        print()
        print(f"  Unexpected error: {type(e).__name__}: {e}")
        return 5


if __name__ == "__main__":
    sys.exit(main())
