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

   By default this pushes BOTH ``confirmation`` (signup) and
   ``recovery`` (password reset) templates in a single atomic PATCH.
   To push just one, add ``--only confirmation`` or ``--only recovery``.

3. The script PATCHes the auth config for the Plan2Sprint project
   (ref ``obmbpfoormxbbizudrrp``) with the new subjects + HTML and
   exits 0 on success.

WHAT IT TOUCHES
---------------
- ``mailer_subjects_confirmation``       ← "Confirm your Plan2Sprint email"
- ``mailer_templates_confirmation_content`` ← contents of confirm-signup.html
- ``mailer_subjects_recovery``           ← "Reset your Plan2Sprint password"
- ``mailer_templates_recovery_content``  ← contents of reset-password.html

Nothing else. Other templates (magic link, invite, email change) are
left as-is. SMTP settings are NOT touched — those stay on the Gmail
config you saved in the dashboard.

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
REPO_ROOT = Path(__file__).resolve().parent.parent

# Each entry maps a logical "template kind" to:
#   - The local HTML file in docs/email-templates/ that is the source of truth.
#   - The Supabase Auth config field for the SUBJECT.
#   - The Supabase Auth config field for the HTML body.
#   - The default subject we set on Supabase.
TEMPLATES = {
    "confirmation": {
        "file": "confirm-signup.html",
        "subject_field": "mailer_subjects_confirmation",
        "body_field": "mailer_templates_confirmation_content",
        "subject": "Confirm your Plan2Sprint email",
    },
    "recovery": {
        "file": "reset-password.html",
        "subject_field": "mailer_subjects_recovery",
        "body_field": "mailer_templates_recovery_content",
        "subject": "Reset your Plan2Sprint password",
    },
}


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
            "scripts/push_supabase_email_template.py [--only confirmation|recovery]"
        )
    if not pat.startswith("sbp_"):
        fail(
            "SUPABASE_PAT doesn't look like a Personal Access Token "
            "(should start with ``sbp_``). You may have pasted a "
            "service-role JWT or anon key by mistake — those won't "
            "work for the Management API."
        )

    # CLI: ``--only <kind>`` pushes just one template (handy when
    # iterating on a single template's design). Default = push all.
    only = None
    for i, arg in enumerate(sys.argv):
        if arg == "--only" and i + 1 < len(sys.argv):
            only = sys.argv[i + 1]
            if only not in TEMPLATES:
                fail(
                    f"--only {only} not recognised. Valid values: "
                    f"{', '.join(TEMPLATES.keys())}."
                )

    # Collect template contents up front so we either push EVERY
    # configured template atomically or bail with a clear error before
    # we touch Supabase. PATCH-ing two fields in one call is
    # transactionally cleaner than two separate PATCHes.
    body: dict[str, str] = {}
    pushed: list[str] = []
    for kind, spec in TEMPLATES.items():
        if only and kind != only:
            continue
        path = REPO_ROOT / "docs" / "email-templates" / spec["file"]
        if not path.exists():
            fail(
                f"Template not found at {path}\n"
                f"docs/email-templates/{spec['file']} is missing — has "
                "it been deleted or moved?"
            )
        html = path.read_text(encoding="utf-8")
        if "{{ .ConfirmationURL }}" not in html:
            fail(
                f"{spec['file']} is missing the Supabase variable "
                "``{{ .ConfirmationURL }}`` — that's the verification "
                "link. Refusing to push a template that won't work."
            )
        body[spec["subject_field"]] = spec["subject"]
        body[spec["body_field"]] = html
        pushed.append(kind)
        print(f"Loaded {kind:13s} ← {path.relative_to(REPO_ROOT).as_posix()} "
              f"({len(html):,} chars, subject={spec['subject']!r})")

    if not pushed:
        fail("Nothing to push. Check --only argument.")

    print(f"Target project: https://supabase.com/dashboard/project/{PROJECT_REF}")

    url = f"https://api.supabase.com/v1/projects/{PROJECT_REF}/config/auth"
    headers = {
        "Authorization": f"Bearer {pat}",
        "Content-Type": "application/json",
        "User-Agent": "plan2sprint-cli/1.1",
    }

    print()
    print(f"PATCH {url} …")
    try:
        resp = httpx.patch(url, headers=headers, json=body, timeout=30.0)
    except httpx.HTTPError as e:
        fail(f"Network/HTTP error talking to Supabase Management API: {e}")
        return  # for type-checker; fail() exits

    if resp.status_code in (200, 204):
        print(f"  OK ({resp.status_code}). Updated: {', '.join(pushed)}.")
        print()
        print("Next:")
        if "confirmation" in pushed:
            print("  • Sign up at Plan2Sprint with a fresh email.")
            print("    Inbox should show the branded confirm-signup card.")
        if "recovery" in pushed:
            print("  • Hit /forgot-password, enter your email.")
            print("    Inbox should show the branded reset-password card.")
            print("    Click the button → /reset-password should render a "
                  "new-password form (not auto-log you in).")
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
