"use client";

import { useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui";
import { Lock, AlertCircle, CheckCircle2, Eye, EyeOff, Loader2 } from "lucide-react";

// ──────────────────────────────────────────────────────────────────────
//  ResetPasswordForm
// ──────────────────────────────────────────────────────────────────────
//
// Owns the full recovery flow on the user's side:
//
//   1. The user clicked the "Reset password" link in the email. Supabase
//      already verified the one-time token on its end and bounced them
//      here with ``?code=XXX`` appended to the URL.
//   2. On mount we read ``code`` from the URL and exchange it for a
//      session. After this, Supabase considers the user authenticated
//      with a "recovery" session (lasts ~5 min; auth API allows
//      ``updateUser({password})`` against it).
//   3. We show the new-password form.
//   4. On submit, ``updateUser({password})`` writes the new password.
//      We then explicitly sign the user out (so the recovery session
//      doesn't linger) and redirect to /login with a success banner.
//
// The previous version of this file skipped step 2 - it assumed the
// /auth/callback route had already exchanged the code. It hadn't, in
// the cases where the ``type=recovery`` query param got lost in the
// Supabase /auth/v1/verify redirect chain. Without the exchange, the
// user landed here with NO recovery session and Supabase silently
// rejected the ``updateUser`` call... or in the broken flow that you
// reported, the callback's default redirect sent them past this page
// entirely. Doing the exchange here removes that whole class of bug.
//
// States this component handles:
//   - "exchanging" - running exchangeCodeForSession on mount
//   - "form"       - showing the new-password form (after exchange OK,
//                    OR when the user navigated here without ?code while
//                    already signed in - e.g. clicking "Change password"
//                    from settings)
//   - "exchange_failed" - the code is invalid / expired / already used;
//                    show a clear message and a link back to /forgot-password
//   - "success"    - password updated; auto-redirect to /login

type Phase = "exchanging" | "form" | "exchange_failed" | "success";

export function ResetPasswordForm() {
  const supabase = createClient();
  const router = useRouter();
  const searchParams = useSearchParams();

  const [phase, setPhase] = useState<Phase>("exchanging");
  const [exchangeError, setExchangeError] = useState<string | null>(null);

  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // ── Step 2: exchange the recovery code for a session on mount ──
  useEffect(() => {
    const code = searchParams.get("code");

    // Case A: the user clicked an email link, so ``code`` is present.
    //         Exchange it before showing the form.
    if (code) {
      (async () => {
        const { error: ex } = await supabase.auth.exchangeCodeForSession(code);
        if (ex) {
          // The most common cause of failure is "code already used" -
          // the user clicked the email link from a previewer (Outlook,
          // some corporate spam scanners pre-fetch links to scan them),
          // burning the one-time code before the human got to it. Show
          // a clear path forward instead of a cryptic Supabase error.
          setExchangeError(
            (ex.message || "").toLowerCase().includes("code")
              ? "This reset link has expired or already been used. Request a new one and try again."
              : ex.message || "We couldn't verify this reset link. Please request a new one."
          );
          setPhase("exchange_failed");
          return;
        }
        setPhase("form");
      })();
      return;
    }

    // Case B: no ``code`` query param. Either the user navigated here
    //         directly while already signed in (legitimate change-
    //         password flow), or someone bookmarked the page. Probe
    //         the session - if signed in, show the form; otherwise
    //         redirect to /forgot-password so they can start over.
    (async () => {
      const { data } = await supabase.auth.getSession();
      if (data.session) {
        setPhase("form");
      } else {
        router.replace("/forgot-password");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (password.length < 6) {
      setError("Password must be at least 6 characters");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }

    setLoading(true);

    // Write the new password against the (recovery) session we
    // just established.
    const { error: updateError } = await supabase.auth.updateUser({ password });
    if (updateError) {
      setError(updateError.message);
      setLoading(false);
      return;
    }

    // Sign the user out so the recovery session doesn't linger as a
    // valid auth session (would let them stay signed in without ever
    // typing the new password back in - confusing UX, plus it makes
    // session-revocation-on-password-change weaker). They re-log with
    // the password they just chose, fresh JWT, clean state.
    await supabase.auth.signOut();

    setPhase("success");
    setLoading(false);

    setTimeout(() => {
      router.push("/login?password_reset=success");
    }, 1600);
  };

  // ── Render phases ──

  if (phase === "exchanging") {
    return (
      <div className="text-center">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-[var(--color-brand-secondary)]/10">
          <Loader2 className="h-6 w-6 text-[var(--color-brand-secondary)] animate-spin" />
        </div>
        <h1 className="text-2xl font-bold text-[var(--text-primary)]">
          Verifying your reset link…
        </h1>
        <p className="mt-2 text-sm text-[var(--text-secondary)]">
          One moment.
        </p>
      </div>
    );
  }

  if (phase === "exchange_failed") {
    return (
      <div className="text-center">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-[var(--color-rag-red)]/10">
          <AlertCircle className="h-6 w-6 text-[var(--color-rag-red)]" />
        </div>
        <h1 className="text-2xl font-bold text-[var(--text-primary)]">
          Reset link unavailable
        </h1>
        <p className="mt-2 text-sm text-[var(--text-secondary)] max-w-sm mx-auto">
          {exchangeError}
        </p>
        <Button
          className="mt-6 w-full"
          onClick={() => router.push("/forgot-password")}
        >
          Request a new reset link
        </Button>
      </div>
    );
  }

  if (phase === "success") {
    return (
      <div className="text-center">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-[var(--color-rag-green)]/10">
          <CheckCircle2 className="h-6 w-6 text-[var(--color-rag-green)]" />
        </div>
        <h1 className="text-2xl font-bold text-[var(--text-primary)]">
          Password updated
        </h1>
        <p className="mt-2 text-sm text-[var(--text-secondary)]">
          Your password has been reset successfully. Redirecting to sign in…
        </p>
      </div>
    );
  }

  // phase === "form"
  return (
    <div>
      <div className="mb-6 text-center">
        <h1 className="text-2xl font-bold text-[var(--text-primary)]">
          Set new password
        </h1>
        <p className="mt-2 text-sm text-[var(--text-secondary)]">
          Enter your new password below
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        {error && (
          <div className="flex items-center gap-2 rounded-lg border border-[var(--color-rag-red)]/30 bg-[var(--color-rag-red)]/10 px-4 py-3 text-sm text-[var(--color-rag-red)]">
            <AlertCircle className="h-4 w-4 shrink-0" />
            {error}
          </div>
        )}

        <div>
          <label
            htmlFor="password"
            className="block text-sm font-medium text-[var(--text-primary)] mb-1.5"
          >
            New Password
          </label>
          <div className="relative">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--text-secondary)]" />
            <input
              id="password"
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter new password"
              required
              minLength={6}
              autoFocus
              className="w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] pl-10 pr-10 py-2.5 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-secondary)]/50 focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)] focus:border-transparent transition-all"
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            >
              {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        </div>

        <div>
          <label
            htmlFor="confirm"
            className="block text-sm font-medium text-[var(--text-primary)] mb-1.5"
          >
            Confirm Password
          </label>
          <div className="relative">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--text-secondary)]" />
            <input
              id="confirm"
              type={showConfirm ? "text" : "password"}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="Confirm new password"
              required
              minLength={6}
              className="w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] pl-10 pr-10 py-2.5 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-secondary)]/50 focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)] focus:border-transparent transition-all"
            />
            <button
              type="button"
              onClick={() => setShowConfirm(!showConfirm)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            >
              {showConfirm ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        </div>

        <Button type="submit" className="w-full" disabled={loading}>
          {loading ? "Updating…" : "Update password"}
        </Button>
      </form>
    </div>
  );
}
