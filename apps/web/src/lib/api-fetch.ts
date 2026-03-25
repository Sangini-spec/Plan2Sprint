/**
 * Authenticated fetch wrapper — automatically attaches the Supabase
 * access token as an Authorization header so the FastAPI backend can
 * identify the real logged-in user instead of falling back to DEMO_USER.
 *
 * Uses the Supabase browser client (which reads from cookies via @supabase/ssr).
 */
import { createClient } from "@/lib/supabase/client";

// Singleton client — same pattern as auth context
let _supabase: ReturnType<typeof createClient> | null = null;
function getSupabase() {
  if (!_supabase) _supabase = createClient();
  return _supabase;
}

export async function apiFetch(
  input: RequestInfo | URL,
  init?: RequestInit
): Promise<Response> {
  const headers = new Headers(init?.headers);

  if (typeof window !== "undefined" && !headers.has("Authorization")) {
    try {
      const supabase = getSupabase();
      const { data } = await supabase.auth.getSession();
      const accessToken = data.session?.access_token;
      if (accessToken) {
        headers.set("Authorization", `Bearer ${accessToken}`);
      }
    } catch {
      // fallback — no token
    }
  }

  return fetch(input, { ...init, headers });
}
