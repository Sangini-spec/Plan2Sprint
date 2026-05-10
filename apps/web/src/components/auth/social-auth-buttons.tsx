"use client";

import { getSupabase } from "@/lib/supabase/shared-client";
import { cn } from "@/lib/utils";

interface SocialAuthButtonsProps {
  className?: string;
}

export function SocialAuthButtons({ className }: SocialAuthButtonsProps) {
  const handleGoogleLogin = async () => {
    const supabase = getSupabase();
    // Hotfix 14 — force the Google account picker.
    //
    // Without ``prompt=select_account``, Google's default OAuth flow
    // remembers which account a user previously consented to and
    // silently re-uses it on subsequent ``signInWithOAuth`` calls. This
    // surfaced as: "first device shows account picker, second device
    // skips it after the first login and just signs me back in as the
    // same dev." That meant a user couldn't switch between two
    // Plan2Sprint identities (e.g. PO + Developer accounts) on the same
    // browser without manually clearing Google's session.
    //
    // ``prompt=select_account`` makes Google show the picker every time
    // — the user explicitly chooses which Google account to use, and
    // can cancel out without auto-signing in. Standard OAuth 2.0 spec
    // parameter, supported by every provider that follows OIDC.
    await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: `${window.location.origin}/auth/callback`,
        queryParams: {
          prompt: "select_account",
        },
      },
    });
  };

  const handleMicrosoftLogin = async () => {
    const supabase = getSupabase();
    // Same picker-always behaviour for Microsoft / Azure AD — the
    // ``prompt=select_account`` value is in the OIDC spec so Azure
    // honours it too.
    await supabase.auth.signInWithOAuth({
      provider: "azure",
      options: {
        scopes: "email profile openid",
        redirectTo: `${window.location.origin}/auth/callback`,
        queryParams: {
          prompt: "select_account",
        },
      },
    });
  };

  return (
    <div className={cn("flex flex-col gap-3", className)}>
      <button
        type="button"
        onClick={handleGoogleLogin}
        className="flex items-center justify-center gap-3 w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] px-4 py-2.5 text-sm font-medium text-[var(--text-primary)] transition-all hover:bg-[var(--bg-surface)] hover:border-[var(--color-brand-secondary)]/30 cursor-pointer"
      >
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
          <path
            d="M17.64 9.205c0-.639-.057-1.252-.164-1.841H9v3.481h4.844a4.14 4.14 0 01-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.615z"
            fill="#4285F4"
          />
          <path
            d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 009 18z"
            fill="#34A853"
          />
          <path
            d="M3.964 10.71A5.41 5.41 0 013.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.997 8.997 0 000 9c0 1.452.348 2.827.957 4.042l3.007-2.332z"
            fill="#FBBC05"
          />
          <path
            d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 00.957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z"
            fill="#EA4335"
          />
        </svg>
        Continue with Google
      </button>

      <button
        type="button"
        onClick={handleMicrosoftLogin}
        className="flex items-center justify-center gap-3 w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] px-4 py-2.5 text-sm font-medium text-[var(--text-primary)] transition-all hover:bg-[var(--bg-surface)] hover:border-[var(--color-brand-secondary)]/30 cursor-pointer"
      >
        <svg width="18" height="18" viewBox="0 0 21 21" fill="none">
          <rect x="1" y="1" width="9" height="9" fill="#F25022" />
          <rect x="11" y="1" width="9" height="9" fill="#7FBA00" />
          <rect x="1" y="11" width="9" height="9" fill="#00A4EF" />
          <rect x="11" y="11" width="9" height="9" fill="#FFB900" />
        </svg>
        Continue with Microsoft
      </button>
    </div>
  );
}
