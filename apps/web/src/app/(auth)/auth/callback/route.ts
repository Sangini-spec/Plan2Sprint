import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export async function GET(request: Request) {
  const { searchParams, origin: rawOrigin } = new URL(request.url);
  const code = searchParams.get("code");
  const rawNext = searchParams.get("next") ?? "/dashboard";

  // Prevent open redirect: only allow internal paths starting with /
  // Block protocol-relative URLs (//evil.com) and absolute URLs
  const SAFE_PREFIXES = ["/dashboard", "/po", "/dev", "/stakeholder", "/settings", "/onboarding"];
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
      // Check if this is a password recovery flow
      const type = searchParams.get("type");
      if (type === "recovery") {
        return NextResponse.redirect(`${origin}/reset-password`);
      }
      return NextResponse.redirect(`${origin}${next}`);
    }
  }

  // Return the user to login with an error
  return NextResponse.redirect(`${origin}/login?error=auth_callback_failed`);
}
