"use client";

/**
 * Shared browser-side Supabase singleton (Hotfix 88).
 *
 * Before this module, three separate files each constructed their own
 * module-level singleton:
 *
 *   - lib/auth/context.tsx          → _supabaseClient
 *   - components/auth/login-form.tsx → _supabase
 *   - components/auth/social-auth-buttons.tsx → _supabase
 *
 * They all shared cookies (so PKCE worked most of the time) but each
 * instance ran its own gotrue auth listener, navigator.locks lock, and
 * in-memory state. On browsers with stricter cookie isolation (Brave's
 * default config; Chrome with strict third-party cookie blocking) the
 * race between `signInWithOAuth` setting the verifier on one instance
 * and the page hydrating with another instance manifested as
 * "have to login twice — first attempt bounces back to /login
 * silently".
 *
 * Single shared instance closes that race. Every call site imports
 * `getSupabase()` from this file.
 */

import { createClient } from "./client";

let _client: ReturnType<typeof createClient> | null = null;

export function getSupabase() {
  if (!_client) _client = createClient();
  return _client;
}
