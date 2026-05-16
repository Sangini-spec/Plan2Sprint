#!/usr/bin/env python3
"""
Push the Plan2Sprint-branded email templates to Supabase via the
Management API.

This avoids manual paste-into-the-dashboard. The HTML file lives at
``docs/email-templates/confirm-signup.html`` and is the version-
controlled source of truth; running this script copies its contents
(plus the Subject) up to Supabase Auth's "Confirm signup" template.

USAGE
-----
1. Generate a Supabase Personal Access Token (PAT) at:
       https://supabase.com/dashboard/account/tokens
   Click "Generate new token", name it ``plan2sprint-cli``, copy
   the ``sbp_…`` token. Treat it like a password.

2. Run this script with the token as an env var:
       # bash / git-bash
       SUPABASE_PAT=sbp_xxxxxxxxxxxx python scripts/push_supabase_email_template.py

       # PowerShell
       $env:SUPABASE_PAT="sbp_xxxxxxxxxxxx"; python scripts/push_supabase_email_template.py

3. The script PATCHes the auth config for the Plan2Sprint project
   (ref ``obmbpfoormxbbizudrrp``) with the new subject + HTML and
   exits 0 on success.

WHAT IT TOUCHES
---------------
- ``mailer_subjects_confirmation``     ← "Confirm your Plan2Sprint email"
- ``mailer_templates_confirmation_content`` ← contents of confirm-signup.html

Nothing else. Existing templates (reset password, magic link, invite,
email change) are left as-is. SMTP settings are NOT touched — those
stay on the Gmail config you saved in the dashboard.

RE-RUNNING
----------
Idempotent. If you tweak ``confirm-signup.html`` later, just re-run.
Supabase replaces the stored template with whatever you PATCH.

ROLLBACK
--------
The Supabase dashboard lets you "Reset to default" for any template
under Authentication → Email Templates. That undoes this script's
effect in one click.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx  # standard in the API venv; falls back to a clear error below


PROJECT_REF = "obmbpfoormxbbizudrrp"
SUBJECT = "Confirm your Plan2Sprint email"

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO_ROOT / "docs" / "email-templates" / "confirm-signup.html"


def fail(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def main() -> None:
    pat = os.environ.get("SUPABASE_PAT", "").strip()
    if not pat:
        fail(
            "SUPABASE_PAT env var not set. Generate a token at "
            "https://supabase.com/dashboard/account/tokens then "
            "run:\n  SUPABASE_PAT=sbp_xxxx python "
            "scripts/push_supabase_email_template.py"
        )
    if not pat.startswith("sbp_"):
        fail(
            "SUPABASE_PAT doesn't look like a Personal Access Token "
            "(should start with ``sbp_``). You may have pasted a "
            "service-role JWT or anon key by mistake — those won't "
            "work for the Management API."
        )

    if not TEMPLATE_PATH.exists():
        fail(
            f"Template not found at {TEMPLATE_PATH}\n"
            "Check that you're running from the repo root and that "
            "docs/email-templates/confirm-signup.html hasn't been "
            "deleted."
        )

    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    if "{{ .ConfirmationURL }}" not in html:
        fail(
            "Template HTML is missing the Supabase variable "
            "``{{ .ConfirmationURL }}`` — that's the verification "
            "link. Refusing to push a template that won't work."
        )
    print(f"Loaded template: {len(html):,} chars from "
          f"{TEMPLATE_PATH.relative_to(REPO_ROOT).as_posix()}")
    print(f"Subject:        {SUBJECT!r}")
    print(f"Target project: https://supabase.com/dashboard/project/{PROJECT_REF}")

    url = f"https://api.supabase.com/v1/projects/{PROJECT_REF}/config/auth"
    body = {
        "mailer_subjects_confirmation": SUBJECT,
        "mailer_templates_confirmation_content": html,
    }
    headers = {
        "Authorization": f"Bearer {pat}",
        "Content-Type": "application/json",
        "User-Agent": "plan2sprint-cli/1.0",
    }

    print()
    print(f"PATCH {url} …")
    try:
        resp = httpx.patch(url, headers=headers, json=body, timeout=30.0)
    except httpx.HTTPError as e:
        fail(f"Network/HTTP error talking to Supabase Management API: {e}")
        return  # for type-checker; fail() exits

    if resp.status_code in (200, 204):
        print(f"  OK ({resp.status_code}). Template + subject updated.")
        print()
        print("Next:")
        print("  1. Sign up at the Plan2Sprint app with a fresh email.")
        print("  2. Check inbox — From should be "
              "``Plan2Sprint <sanginitripathi8@gmail.com>`` "
              "with the new branded card.")
        print("  3. Click ``Confirm my email`` — should land you back "
              "in the app, signed in.")
    elif resp.status_code == 401:
        fail(
            "401 Unauthorized — your SUPABASE_PAT was rejected. "
            "Verify the token at "
            "https://supabase.com/dashboard/account/tokens, regenerate "
            "if needed, and re-run."
        )
    elif resp.status_code == 403:
        fail(
            "403 Forbidden — your PAT is valid but doesn't have access "
            "to project ``{}``. Are you signed into Supabase as a "
            "member of ``Sangini-spec's Org``?".format(PROJECT_REF)
        )
    elif resp.status_code == 404:
        fail(
            "404 Not Found — project ``{}`` doesn't exist (or your PAT "
            "doesn't see it). Double-check the project ref in the "
            "browser URL when you're on the dashboard.".format(PROJECT_REF)
        )
    else:
        fail(
            f"PATCH failed: HTTP {resp.status_code}\n"
            f"Response: {resp.text[:800]}"
        )


if __name__ == "__main__":
    main()
