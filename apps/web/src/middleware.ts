import { type NextRequest, NextResponse } from "next/server";
import { createServerClient } from "@supabase/ssr";
import { updateSession } from "@/lib/supabase/middleware";

// ── Security headers applied to all responses ──
function _addSecurityHeaders(response: NextResponse): NextResponse {
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("X-Frame-Options", "DENY");
  response.headers.set("X-XSS-Protection", "1; mode=block");
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  response.headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  // HSTS — only in production (not localhost)
  if (process.env.NODE_ENV === "production") {
    response.headers.set(
      "Strict-Transport-Security",
      "max-age=31536000; includeSubDomains"
    );
  }
  return response;
}

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // For API routes: inject Supabase auth token as Authorization header
  // so the backend (via Next.js rewrite proxy) receives the Bearer token.
  if (pathname.startsWith("/api/")) {
    // Skip if Authorization header already present
    if (request.headers.get("authorization")) {
      return _addSecurityHeaders(NextResponse.next());
    }

    const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
    const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
    if (!supabaseUrl || !supabaseKey) {
      return _addSecurityHeaders(NextResponse.next());
    }

    // Read Supabase session from cookies
    const supabase = createServerClient(supabaseUrl, supabaseKey, {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll() {
          // No-op for read-only middleware
        },
      },
    });

    const { data: { session } } = await supabase.auth.getSession();

    if (session?.access_token) {
      // Clone request headers and add Authorization
      const requestHeaders = new Headers(request.headers);
      requestHeaders.set("Authorization", `Bearer ${session.access_token}`);
      return _addSecurityHeaders(
        NextResponse.next({ request: { headers: requestHeaders } })
      );
    }

    return _addSecurityHeaders(NextResponse.next());
  }

  // For page routes: run the existing session check + security headers
  const response = await updateSession(request);
  return _addSecurityHeaders(response);
}

export const config = {
  matcher: [
    /*
     * Run middleware on:
     * 1. API routes — to inject auth token for proxy
     * 2. Page routes — for auth checks
     * Skip: static files, images, favicon, Next.js internals
     */
    "/((?!_next/static|_next/image|favicon.ico|logo.png|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
