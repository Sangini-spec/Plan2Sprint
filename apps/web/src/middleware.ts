import { type NextRequest } from "next/server";
import { updateSession } from "@/lib/supabase/middleware";

export async function middleware(request: NextRequest) {
  return await updateSession(request);
}

export const config = {
  matcher: [
    /*
     * Only run middleware on page routes that need auth checks.
     * Skip: static files, images, favicon, API routes (handled by FastAPI),
     * and Next.js internals.
     */
    "/((?!_next/static|_next/image|api/|favicon.ico|logo.png|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
