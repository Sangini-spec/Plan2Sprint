import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export async function GET(request: Request) {
  const { searchParams, origin: rawOrigin } = new URL(request.url);
  const code = searchParams.get("code");
  const rawNext = searchParams.get("next") ?? "/dashboard";

  // Prevent open redirect: only allow internal paths starting with /
  // Block protocol-relative URLs (//evil.com) and absolute URLs.
  // Hotfix 61 — also allow ``/invite/<token>`` so OAuth-based invitees
  // (Google / Microsoft sign-in) land back on the invite-accept screen
  // after auth completes, matching the password-login path.
  const SAFE_PREFIXES = [
    "/dashboard",
    "/po",
    "/dev",
    "/stakeholder",
    "/settings",
    "/onboarding",
    "/invite/",
  ];
  const next = SAFE_PREFIXES.some((p) => rawNext.startsWith(p)) ? rawNext : "/dashboard";

  // Use X-Forwarded-Host header (set by Azure Container Apps / reverse proxy)
  // to get the real public URL, not the container's internal 0.0.0.0:3000
  const forwardedHost = (request as any).headers?.get?.("x-forwarded-host");
  const forwardedProto = (request as any).headers?.get?.("x-forwarded-proto") || "https";
  const origin = forwardedHost
    ? `${forwardedProto}://${forwardedHost}`
    : rawOrigin;

  if (code) {
    const supabase = await createClient();
    const { data, error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) {
      // Password-recovery flow no longer touches this callback. The
      // forgot-password form's ``redirectTo`` now points STRAIGHT to
      // /reset-password, which exchanges its own code on mount and
      // renders the new-password form. Routing recovery through here
      // was unreliable because Supabase's /auth/v1/verify endpoint
      // doesn't preserve query params on ``redirect_to``, so the
      // ``type=recovery`` hint that drove this branch was getting
      // lost in transit and users were silently bounced to
      // /dashboard with a recovery session — never seeing the
      // password form, never actually changing their password.
      //
      // This callback is now only for the OAuth (Google/Microsoft)
      // sign-in + signup-confirmation flows, both of which want the
      // user to land on their role's default route.
      return NextResponse.redirect(`${origin}${next}`);
    }
    // Hotfix 15 — surface the actual failure reason in the URL so we
    // can diagnose "had to pick twice" race conditions. Common values
    // we've seen: "invalid_grant" (PKCE verifier missing because the
    // user hit back during the redirect), "invalid_request" (code
    // already used), "expired_token". Without this, the user just
    // sees a generic error and we have nothing to debug from.
    console.error("[auth/callback] exchangeCodeForSession failed", {
      message: error.message,
      name: error.name,
      status: (error as { status?: number }).status,
    });
    const reason = encodeURIComponent(error.message || "exchange_failed");
    // Hotfix 88 — best-effort hint about which provider the user picked,
    // so the /login page's auto-retry can re-trigger the right OAuth
    // round-trip without making the user pick again. Supabase tags the
    // referer-style hint inconsistently, so we sniff the error message
    // first, then fall back to the redirect URL params.
    const msg = (error.message || "").toLowerCase();
    const provider = msg.includes("azure") || msg.includes("microsoft")
      ? "azure"
      : "google";
    return NextResponse.redirect(
      `${origin}/login?error=auth_callback_failed&reason=${reason}&provider=${provider}`
    );
  }

  // Return the user to login with an error
  return NextResponse.redirect(`${origin}/login?error=auth_callback_failed&reason=missing_code`);
}
