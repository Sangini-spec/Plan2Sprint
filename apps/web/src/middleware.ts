import { type NextRequest, NextResponse } from "next/server";
import { createServerClient } from "@supabase/ssr";
import { updateSession } from "@/lib/supabase/middleware";

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // For API routes: inject Supabase auth token as Authorization header
  // so the backend (via Next.js rewrite proxy) receives the Bearer token.
  if (pathname.startsWith("/api/")) {
    // Skip if Authorization header already present
    if (request.headers.get("authorization")) {
      return NextResponse.next();
    }

    const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
    const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
    if (!supabaseUrl || !supabaseKey) {
      return NextResponse.next();
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
      return NextResponse.next({
        request: { headers: requestHeaders },
      });
    }

    return NextResponse.next();
  }

  // For page routes: run the existing session check
  return await updateSession(request);
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
