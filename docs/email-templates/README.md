# Supabase email templates — Plan2Sprint

Templates uploaded into Supabase Auth → Email Templates. Custom SMTP
plus a branded HTML template = Plan2Sprint-branded inbox experience,
no more Supabase strings showing up in the user's mail client.

---

## One-time SMTP setup (Supabase Dashboard)

Supabase falls back to its own mail relay (`noreply@mail.app.supabase.io`)
unless you configure custom SMTP. Once configured, ALL auth emails go
through your relay and ship with your from-name.

1. Go to **Supabase Dashboard → Project → Authentication → Emails →
   SMTP Settings**.
2. Toggle **Enable Custom SMTP** ON.
3. Paste the values that already live in `apps/api/.env`:

   | Field             | Value (from `apps/api/.env`)                       |
   | ----------------- | -------------------------------------------------- |
   | Sender email      | `sanginitripathi8@gmail.com`                       |
   | Sender name       | `Plan2Sprint`                                      |
   | Host              | `smtp.gmail.com`                                   |
   | Port              | `587`                                              |
   | Username          | `sanginitripathi8@gmail.com`                       |
   | Password          | The Gmail **App Password** (NOT the account password). It's the same value in `SMTP_PASS=`. |
   | Minimum interval  | `60` (default — Supabase's anti-abuse throttle).   |

4. Click **Save**.
5. Click **Send test email** and put your own address in. Confirm it
   arrives from `Plan2Sprint <sanginitripathi8@gmail.com>`, NOT from
   `noreply@mail.app.supabase.io`.

### Gmail SMTP gotchas (call out, then move on)

- The password must be a **Gmail App Password**, not the regular
  account password. Generate one at <https://myaccount.google.com/apppasswords>
  (requires 2FA enabled on the Gmail account).
- Free Gmail caps at ~**500 outbound emails per 24h**. Workspace tiers
  raise this to 2000/day. If Plan2Sprint scales past hundreds of
  signups per day, migrate to **Resend** or **Postmark** — change the
  five SMTP settings above and you're done; the template stays the
  same.
- Some recipient providers (corporate Exchange, in particular) flag
  Gmail-relayed mail with looser DKIM as "external" — fine for an MVP,
  worth re-evaluating before enterprise pilots.

---

## Upload the "Confirm signup" template

1. Go to **Supabase Dashboard → Project → Authentication → Emails →
   Email Templates → Confirm signup**.
2. **Subject:** replace the default with:

   ```
   Confirm your Plan2Sprint email
   ```

3. **Message (HTML)** field: open `confirm-signup.html` (this folder),
   select-all, copy, paste over the existing content. Save.
4. (Optional) Open the **Magic Link**, **Change Email Address**,
   **Reset Password**, and **Invite User** template tabs and replace
   them with copies of `confirm-signup.html` adapted for each context
   — we can do those later in the same shape as this one.

### Supabase template variables

The HTML uses two Supabase Auth variables:

- `{{ .ConfirmationURL }}` — the verification link Supabase generates
  per user. Embedded twice (button + manual-link fallback).
- `{{ .Email }}` — the recipient's email, used in the body line
  "we just need to verify {{ .Email }} belongs to you."

Supabase auto-substitutes these server-side before sending. Do NOT
hard-code an email or URL in their place.

---

## Verifying it works

1. Open the Plan2Sprint app in an incognito window.
2. Sign up with a fresh email.
3. Check the inbox — within ~10s, you should see:
   - From: `Plan2Sprint <sanginitripathi8@gmail.com>`
   - Subject: `Confirm your Plan2Sprint email`
   - Body: the branded card with a blue "Confirm my email" button.
4. Click the button → lands back in Plan2Sprint with the account
   confirmed.

If the email still arrives from `noreply@mail.app.supabase.io`, the
SMTP toggle in step 1 above wasn't saved or Supabase rejected the
credentials (test-send in the SMTP screen will surface the error).

---

## Files in this folder

- `confirm-signup.html` — branded template. Paste into Supabase Auth
  → Email Templates → Confirm signup → Message (HTML).
- `README.md` — this file.

No other transactional emails are templated yet. Order to do them in,
when ready:

1. Confirm signup ← **done** with this commit
2. Reset password (next-most-touched)
3. Magic Link (only if passwordless flow is exposed in the app)
4. Invite User (PO-invites-team-member flow, if used)
5. Change Email Address (low-volume, low priority)
