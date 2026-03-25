import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export async function GET(request: Request) {
  const { searchParams, origin: rawOrigin } = new URL(request.url);
  const code = searchParams.get("code");
  const next = searchParams.get("next") ?? "/dashboard";

  // Use X-Forwarded-Host header (set by Azure Container Apps / reverse proxy)
  // to get the real public URL, not the container's internal 0.0.0.0:3000
  const forwardedHost = (request as any).headers?.get?.("x-forwarded-host");
  const forwardedProto = (request as any).headers?.get?.("x-forwarded-proto") || "https";
  const origin = forwardedHost
    ? `${forwardedProto}://${forwardedHost}`
    : rawOrigin;

  if (code) {
    const supabase = await createClient();
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) {
      return NextResponse.redirect(`${origin}${next}`);
    }
  }

  // Return the user to login with an error
  return NextResponse.redirect(`${origin}/login?error=auth_callback_failed`);
}
