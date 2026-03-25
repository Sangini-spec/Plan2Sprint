"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import {
  Eye,
  EyeOff,
  AlertCircle,
  ArrowRight,
} from "lucide-react";
import { ROLE_DASHBOARD_ROUTES, type UserRole } from "@/lib/types/auth";

const isDemoMode =
  !process.env.NEXT_PUBLIC_SUPABASE_URL ||
  process.env.NEXT_PUBLIC_SUPABASE_URL === "https://your-project.supabase.co";

// Singleton Supabase client
let _supabase: ReturnType<typeof createClient> | null = null;
function getSupabase() {
  if (!_supabase) _supabase = createClient();
  return _supabase;
}

export function LoginForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const demoFallback = (userEmail: string) => {
    localStorage.setItem(
      "plan2sprint_demo_user",
      JSON.stringify({
        id: `user-${Date.now()}`,
        email: userEmail || "demo@plan2sprint.app",
        full_name: userEmail ? userEmail.split("@")[0] : "Demo User",
        organization_name: "Organization",
        role: "product_owner",
        onboarding_completed: true,
        created_at: new Date().toISOString(),
      })
    );
    router.push("/po");
  };

  const handleGoogleLogin = async () => {
    if (isDemoMode) { demoFallback(""); return; }
    try {
      const supabase = getSupabase();
      await supabase.auth.signInWithOAuth({
        provider: "google",
        options: { redirectTo: `${window.location.origin}/auth/callback` },
      });
    } catch {
      console.warn("Google OAuth failed, falling back to demo");
      demoFallback("");
    }
  };

  const handleMicrosoftLogin = async () => {
    if (isDemoMode) { demoFallback(""); return; }
    try {
      const supabase = getSupabase();
      await supabase.auth.signInWithOAuth({
        provider: "azure",
        options: {
          scopes: "email profile openid",
          redirectTo: `${window.location.origin}/auth/callback`,
        },
      });
    } catch {
      console.warn("Microsoft OAuth failed, falling back to demo");
      demoFallback("");
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    if (isDemoMode) {
      demoFallback(email);
      return;
    }

    try {
      const supabase = getSupabase();
      const timeout = new Promise<{ data: null; error: { message: string } }>((resolve) =>
        setTimeout(() => resolve({ data: null, error: { message: "timeout" } }), 5000)
      );
      const { data, error: authError } = await Promise.race([
        supabase.auth.signInWithPassword({ email, password }),
        timeout,
      ]);

      if (authError) {
        const msg = authError.message?.toLowerCase() ?? "";
        if (msg.includes("failed to fetch") || msg.includes("network") || msg.includes("ssl") || msg.includes("timeout")) {
          console.warn("Supabase unreachable, falling back to demo login:", authError.message);
          demoFallback(email);
          return;
        }
        setError(authError.message);
        setLoading(false);
        return;
      }

      const userRole = data?.user?.user_metadata?.role as UserRole | undefined;
      const dashboardRoute = userRole ? (ROLE_DASHBOARD_ROUTES[userRole] ?? "/po") : "/po";
      router.push(dashboardRoute);
      router.refresh();
    } catch {
      console.warn("Supabase auth unreachable, falling back to demo login");
      demoFallback(email);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      {/* Header */}
      <div className="mb-5">
        <h1 className="text-2xl font-bold text-[var(--text-primary)]">Welcome back</h1>
        <p className="mt-1 text-sm text-[var(--text-secondary)]">Sign in to your account</p>
      </div>

      {/* OAuth buttons */}
      <div className="space-y-2.5 mb-5">
        <button
          type="button"
          onClick={handleGoogleLogin}
          className="flex items-center justify-center gap-3 w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] px-4 py-2.5 text-sm font-medium text-[var(--text-primary)] transition-all hover:bg-[var(--bg-surface)] hover:border-[var(--text-secondary)]/40 cursor-pointer"
        >
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
            <path d="M17.64 9.205c0-.639-.057-1.252-.164-1.841H9v3.481h4.844a4.14 4.14 0 01-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.615z" fill="#4285F4" />
            <path d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 009 18z" fill="#34A853" />
            <path d="M3.964 10.71A5.41 5.41 0 013.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.997 8.997 0 000 9c0 1.452.348 2.827.957 4.042l3.007-2.332z" fill="#FBBC05" />
            <path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 00.957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335" />
          </svg>
          Login with Google
        </button>

        <button
          type="button"
          onClick={handleMicrosoftLogin}
          className="flex items-center justify-center gap-3 w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] px-4 py-2.5 text-sm font-medium text-[var(--text-primary)] transition-all hover:bg-[var(--bg-surface)] hover:border-[var(--text-secondary)]/40 cursor-pointer"
        >
          <svg width="18" height="18" viewBox="0 0 21 21" fill="none">
            <rect x="1" y="1" width="9" height="9" fill="#F25022" />
            <rect x="11" y="1" width="9" height="9" fill="#7FBA00" />
            <rect x="1" y="11" width="9" height="9" fill="#00A4EF" />
            <rect x="11" y="11" width="9" height="9" fill="#FFB900" />
          </svg>
          Login with Microsoft
        </button>
      </div>

      {/* Divider */}
      <div className="relative mb-5">
        <div className="absolute inset-0 flex items-center">
          <div className="w-full border-t border-[var(--border-subtle)]" />
        </div>
        <div className="relative flex justify-center text-sm">
          <span className="bg-[var(--bg-base)] px-4 text-[var(--text-secondary)]">or</span>
        </div>
      </div>

      {/* Email/Password form */}
      <form onSubmit={handleSubmit} className="space-y-3">
        {error && (
          <div className="flex items-center gap-2 rounded-lg border border-[var(--color-rag-red)]/30 bg-[var(--color-rag-red)]/10 px-4 py-3 text-sm text-[var(--color-rag-red)]">
            <AlertCircle className="h-4 w-4 shrink-0" />
            {error}
          </div>
        )}

        <div>
          <label htmlFor="email" className="block text-sm font-medium text-[var(--text-primary)] mb-1.5">
            Email <span className="text-[var(--color-rag-red)]">*</span>
          </label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Enter your email address"
            required
            className="w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] px-4 py-2.5 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-secondary)]/50 focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)] focus:border-transparent transition-all"
          />
        </div>

        <div>
          <label htmlFor="password" className="block text-sm font-medium text-[var(--text-primary)] mb-1">
            Password <span className="text-[var(--color-rag-red)]">*</span>
          </label>
          <div className="relative">
            <input
              id="password"
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter your password"
              required
              className="w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] px-4 pr-10 py-2.5 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-secondary)]/50 focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)] focus:border-transparent transition-all"
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
            >
              {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        </div>

        <button
          type="submit"
          disabled={loading}
          className="w-full flex items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-[var(--color-brand-primary)] to-[var(--color-brand-secondary)] px-4 py-2.5 text-sm font-semibold text-white transition-all hover:opacity-90 disabled:opacity-50 cursor-pointer"
        >
          {loading ? "Signing in..." : "Sign in"}
          {!loading && <ArrowRight className="h-4 w-4" />}
        </button>
      </form>

      {/* Forgot password */}
      <div className="mt-4 text-center">
        <Link
          href="/forgot-password"
          className="text-sm text-[var(--color-brand-secondary)] hover:underline"
        >
          Forgot password?
        </Link>
      </div>

      {/* Sign up link */}
      <p className="mt-6 text-center text-sm text-[var(--text-secondary)]">
        Don&apos;t have an account?{" "}
        <Link href="/signup" className="font-medium text-[var(--color-brand-secondary)] hover:underline">
          Create free account
        </Link>
      </p>
    </div>
  );
}
