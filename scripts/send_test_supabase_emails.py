#!/usr/bin/env python3
"""
One-shot test trigger for the two Supabase Auth emails we just
re-templated. Reads Supabase creds from ``apps/api/.env`` and calls
the Auth REST API directly.

Two requests fire:
  1. POST /auth/v1/recover  — sends the "Reset password" email
     (uses the recovery template we just pushed).
  2. POST /auth/v1/admin/generate_link  — type=signup, creates a
     throwaway user at a Gmail+alias address and sends the
     "Confirm signup" email (uses the confirmation template).

The confirm-signup path needs a NEW email (Supabase only sends
confirmation for fresh signups, not for existing confirmed users).
We append a timestamp to the local part of a Gmail address so each
run gets a brand-new throwaway user. Gmail delivers it to the
underlying inbox via the ``+alias`` rule. The throwaway user stays
in Supabase's users table — harmless, but you can clean them up
later in the dashboard under Authentication → Users → filter for
"+confirm_" in the email and bulk-delete.

USAGE
-----
    python scripts/send_test_supabase_emails.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv  # type: ignore


REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / "apps" / "api" / ".env")

# ─── Recipients ───
# Reset-password lands at the user's work account (where they're
# already a confirmed user — recovery just sends a fresh recovery
# link). Confirm-signup needs a NEW user, so we pin it to a
# timestamp-suffixed Gmail alias delivered to the underlying
# sanginitripathi8 inbox.
RECOVERY_TO = "sangini@concept2action.ai"
CONFIRM_BASE = "sanginitripathi8@gmail.com"
TIMESTAMP = int(time.time())
local, _, domain = CONFIRM_BASE.partition("@")
CONFIRM_TO = f"{local}+confirm_{TIMESTAMP}@{domain}"


def fail(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def main() -> None:
    supabase_url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    anon_key = os.environ.get("SUPABASE_ANON_KEY", "")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not supabase_url or not anon_key or not service_key:
        fail(
            "Missing one of SUPABASE_URL / SUPABASE_ANON_KEY / "
            "SUPABASE_SERVICE_ROLE_KEY in apps/api/.env"
        )

    print(f"Project: {supabase_url}")
    print(f"Recovery → {RECOVERY_TO}")
    print(f"Confirm  → {CONFIRM_TO}  (Gmail alias; delivers to {CONFIRM_BASE})")
    print()

    # ── 1) Recovery (reset password) ────────────────────────────────
    print("[1/2] Triggering recovery email …")
    r = httpx.post(
        f"{supabase_url}/auth/v1/recover",
        json={"email": RECOVERY_TO},
        headers={
            "apikey": anon_key,
            "Authorization": f"Bearer {anon_key}",
            "Content-Type": "application/json",
        },
        timeout=20.0,
    )
    if r.status_code in (200, 204):
        print(f"      OK ({r.status_code}). Recovery email queued to {RECOVERY_TO}.")
    else:
        # Supabase returns 422 if the address isn't a registered user;
        # for security it usually returns 200 even then to avoid
        # leaking existence. Anything else is a real failure.
        print(
            f"      Unexpected response: HTTP {r.status_code}\n"
            f"      Body: {r.text[:400]}"
        )

    # ── 2) Confirm signup ───────────────────────────────────────────
    print()
    print("[2/2] Triggering confirm-signup email …")
    # generate_link with type=signup creates the user AND triggers
    # the confirm-signup email via the configured SMTP / template.
    # We pass a random-but-deterministic password the user will never
    # use — the test isn't about logging into this throwaway account,
    # it's about exercising the email template.
    throwaway_password = f"P2S_test_{TIMESTAMP}_x!K9"
    r2 = httpx.post(
        f"{supabase_url}/auth/v1/admin/generate_link",
        json={
            "type": "signup",
            "email": CONFIRM_TO,
            "password": throwaway_password,
        },
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        },
        timeout=20.0,
    )
    if r2.status_code in (200, 204):
        body = r2.json() if r2.text else {}
        link = body.get("action_link") or body.get("properties", {}).get("action_link")
        print(f"      OK ({r2.status_code}). Confirm-signup email queued to {CONFIRM_TO}.")
        if link:
            # The action_link is the same URL the button in the email
            # points to. Printing here so you can side-by-side check
            # the inbox version against this expected target.
            print(f"      action_link (for verification): {link[:120]}…")
    else:
        print(
            f"      Unexpected response: HTTP {r2.status_code}\n"
            f"      Body: {r2.text[:400]}"
        )

    print()
    print("Done. Check both inboxes:")
    print(f"  • {RECOVERY_TO}  — 'Reset your Plan2Sprint password'")
    print(f"  • {CONFIRM_BASE}  — 'Confirm your Plan2Sprint email' (delivered via +alias)")


if __name__ == "__main__":
    main()
