"""
Branded HTML email templates for Plan2Sprint.
"""


def invite_email_html(
    invitee_email: str,
    invite_url: str,
    org_name: str,
    role: str,
    invited_by: str,
) -> str:
    role_display = role.replace("_", " ").title()
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>You're invited to {org_name}</title>
</head>
<body style="margin:0;padding:0;background-color:#f4f6f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f6f9;padding:40px 0;">
<tr><td align="center">

<!-- Main card -->
<table role="presentation" width="560" cellpadding="0" cellspacing="0" style="background-color:#ffffff;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,0.06);overflow:hidden;max-width:560px;width:100%;">

  <!-- Header -->
  <tr>
    <td style="background:linear-gradient(135deg,#0f172a 0%,#1e3a5f 100%);padding:32px 40px;text-align:center;">
      <table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 auto;">
        <tr>
          <td style="padding-right:10px;vertical-align:middle;">
            <div style="width:36px;height:36px;background:#3b82f6;border-radius:8px;display:inline-block;text-align:center;line-height:36px;">
              <span style="color:#fff;font-size:18px;font-weight:700;">P</span>
            </div>
          </td>
          <td style="vertical-align:middle;">
            <span style="color:#ffffff;font-size:22px;font-weight:700;letter-spacing:-0.5px;">Plan2Sprint</span>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- Body -->
  <tr>
    <td style="padding:36px 40px 20px;">
      <h1 style="margin:0 0 8px;font-size:22px;font-weight:700;color:#0f172a;">You've been invited!</h1>
      <p style="margin:0 0 24px;font-size:15px;color:#64748b;line-height:1.5;">
        <strong style="color:#334155;">{invited_by}</strong> has invited you to join
        <strong style="color:#334155;">{org_name}</strong> on Plan2Sprint.
      </p>

      <!-- Role badge -->
      <table role="presentation" cellpadding="0" cellspacing="0" style="margin-bottom:28px;">
        <tr>
          <td style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:14px 20px;">
            <span style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;">Your Role</span><br />
            <span style="font-size:16px;font-weight:600;color:#1e40af;">{role_display}</span>
          </td>
        </tr>
      </table>

      <!-- CTA button -->
      <table role="presentation" cellpadding="0" cellspacing="0" width="100%">
        <tr>
          <td align="center" style="padding:4px 0 28px;">
            <a href="{invite_url}"
               style="display:inline-block;background:#3b82f6;color:#ffffff;font-size:15px;font-weight:600;text-decoration:none;padding:14px 40px;border-radius:8px;letter-spacing:0.2px;">
              Accept Invitation
            </a>
          </td>
        </tr>
      </table>

      <!-- Fallback link -->
      <p style="margin:0 0 8px;font-size:13px;color:#94a3b8;line-height:1.5;">
        If the button doesn't work, copy and paste this link into your browser:
      </p>
      <p style="margin:0 0 24px;font-size:13px;color:#3b82f6;word-break:break-all;line-height:1.5;">
        {invite_url}
      </p>

      <hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0;" />

      <p style="margin:0;font-size:13px;color:#94a3b8;line-height:1.5;">
        This invitation will expire in 7 days. If you didn't expect this email, you can safely ignore it.
      </p>
    </td>
  </tr>

  <!-- Footer -->
  <tr>
    <td style="background:#f8fafc;padding:20px 40px;border-top:1px solid #f1f5f9;text-align:center;">
      <p style="margin:0;font-size:12px;color:#94a3b8;line-height:1.6;">
        Powered by <strong style="color:#64748b;">Plan2Sprint</strong> &mdash; Agile project management, reimagined.<br />
        &copy; 2026 Plan2Sprint. All rights reserved.
      </p>
    </td>
  </tr>

</table>
<!-- /Main card -->

</td></tr>
</table>
</body>
</html>"""


def invite_email_text(
    invitee_email: str,
    invite_url: str,
    org_name: str,
    role: str,
    invited_by: str,
) -> str:
    role_display = role.replace("_", " ").title()
    return f"""\
You've been invited to join {org_name} on Plan2Sprint!

{invited_by} has invited you to join as {role_display}.

Accept your invitation here:
{invite_url}

This invitation will expire in 7 days.

If you didn't expect this email, you can safely ignore it.

---
Powered by Plan2Sprint - Agile project management, reimagined.
"""
