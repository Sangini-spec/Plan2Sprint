"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import {
  Eye,
  EyeOff,
  AlertCircle,
  CheckCircle2,
} from "lucide-react";
// Role is assigned post-signup by org admin; signup always creates as product_owner

const isDemoMode =
  !process.env.NEXT_PUBLIC_SUPABASE_URL ||
  process.env.NEXT_PUBLIC_SUPABASE_URL === "https://your-project.supabase.co";

// Hotfix 65C — accept ``?next=/invite/<token>`` from the chain
// (invite → login → signup) and propagate it through Supabase email
// confirmation back to /auth/callback. Same-origin path guard prevents
// open-redirects.
function safeNextPath(raw: string | null): string | null {
  if (!raw) return null;
  if (!raw.startsWith("/")) return null;
  if (raw.startsWith("//")) return null;
  return raw;
}

export function SignupForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextPath = safeNextPath(searchParams.get("next"));
  const [organizationName, setOrganizationName] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [agreedToTerms, setAgreedToTerms] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);

  const fullName = `${firstName} ${lastName}`.trim();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!agreedToTerms) {
      setError("You must agree to the Terms and Conditions");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }

    setLoading(true);

    if (isDemoMode) {
      localStorage.setItem(
        "plan2sprint_demo_user",
        JSON.stringify({
          id: "demo-user-1",
          email,
          full_name: fullName,
          username,
          organization_name: organizationName,
          role: "product_owner",
          onboarding_completed: false,
          created_at: new Date().toISOString(),
        })
      );
      const dashboardRoute = "/po";
      router.push(dashboardRoute);
      return;
    }

    try {
      const supabase = createClient();
      const timeout = new Promise<{ error: { message: string } }>((resolve) =>
        setTimeout(() => resolve({ error: { message: "timeout" } }), 8000)
      );
      const result = await Promise.race([
        supabase.auth.signUp({
          email,
          password,
          options: {
            data: {
              full_name: fullName,
              first_name: firstName,
              last_name: lastName,
              username,
              organization_name: organizationName,
              role: "product_owner",
            },
            // Hotfix 65C — carry ?next=/invite/<token> through the
            // confirmation email so the post-confirm callback puts the
            // user back on the invite page (where Hotfix 65A's
            // server-side auto-accept already moved them into the
            // inviter's org).
            emailRedirectTo: nextPath
              ? `${window.location.origin}/auth/callback?next=${encodeURIComponent(nextPath)}`
              : `${window.location.origin}/auth/callback`,
          },
        }),
        timeout,
      ]);

      if (result.error) {
        const msg = result.error.message?.toLowerCase() ?? "";
        if (msg.includes("failed to fetch") || msg.includes("network") || msg.includes("ssl") || msg.includes("timeout")) {
          console.warn("Supabase unreachable, falling back to demo signup");
          localStorage.setItem(
            "plan2sprint_demo_user",
            JSON.stringify({
              id: `user-${Date.now()}`,
              email,
              full_name: fullName,
              username,
              organization_name: organizationName,
              role: "product_owner",
              onboarding_completed: false,
              created_at: new Date().toISOString(),
            })
          );
          const dashboardRoute = "/po";
          router.push(dashboardRoute);
          return;
        }
        setError(result.error.message);
        setLoading(false);
        return;
      }

      setSuccess(true);
    } catch {
      console.warn("Supabase auth unreachable, falling back to demo signup");
      localStorage.setItem(
        "plan2sprint_demo_user",
        JSON.stringify({
          id: `user-${Date.now()}`,
          email,
          full_name: fullName,
          username,
          organization_name: organizationName,
          role: "product_owner",
          onboarding_completed: false,
          created_at: new Date().toISOString(),
        })
      );
      const dashboardRoute = "/po";
      router.push(dashboardRoute);
    }

    setLoading(false);
  };

  if (success) {
    return (
      <div className="text-center py-8">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-[var(--color-rag-green)]/10">
          <CheckCircle2 className="h-6 w-6 text-[var(--color-rag-green)]" />
        </div>
        <h1 className="text-2xl font-bold text-[var(--text-primary)]">Check your email</h1>
        <p className="mt-2 text-sm text-[var(--text-secondary)]">
          We&apos;ve sent a confirmation link to{" "}
          <span className="font-medium text-[var(--text-primary)]">{email}</span>.
          Click the link to activate your account.
        </p>
        <Link
          href="/login"
          className="mt-6 inline-block text-sm font-medium text-[var(--color-brand-secondary)] hover:underline"
        >
          Back to sign in
        </Link>
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="mb-4">
        <h1 className="text-2xl font-bold text-[var(--text-primary)]">Create an account</h1>
        <p className="mt-1 text-sm text-[var(--text-secondary)]">Welcome! Create an account to get started.</p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-3">
        {error && (
          <div className="flex items-center gap-2 rounded-lg border border-[var(--color-rag-red)]/30 bg-[var(--color-rag-red)]/10 px-4 py-3 text-sm text-[var(--color-rag-red)]">
            <AlertCircle className="h-4 w-4 shrink-0" />
            {error}
          </div>
        )}

        {/* Organization Name */}
        <div>
          <label htmlFor="orgName" className="block text-sm font-medium text-[var(--text-primary)] mb-1">
            Organization Name
          </label>
          <input
            id="orgName"
            type="text"
            value={organizationName}
            onChange={(e) => setOrganizationName(e.target.value)}
            placeholder="e.g., Acme Corp"
            required
            className="w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] px-4 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-secondary)]/50 focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)] focus:border-transparent transition-all"
          />
        </div>

        {/* First name / Last name */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="firstName" className="block text-sm font-medium text-[var(--text-primary)] mb-1">
              First name
            </label>
            <input
              id="firstName"
              type="text"
              value={firstName}
              onChange={(e) => setFirstName(e.target.value)}
              required
              className="w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] px-4 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-secondary)]/50 focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)] focus:border-transparent transition-all"
            />
          </div>
          <div>
            <label htmlFor="lastName" className="block text-sm font-medium text-[var(--text-primary)] mb-1">
              Last name
            </label>
            <input
              id="lastName"
              type="text"
              value={lastName}
              onChange={(e) => setLastName(e.target.value)}
              required
              className="w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] px-4 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-secondary)]/50 focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)] focus:border-transparent transition-all"
            />
          </div>
        </div>

        {/* Username */}
        <div>
          <label htmlFor="username" className="block text-sm font-medium text-[var(--text-primary)] mb-1">
            Username
          </label>
          <input
            id="username"
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            className="w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] px-4 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-secondary)]/50 focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)] focus:border-transparent transition-all"
          />
        </div>

        {/* Email */}
        <div>
          <label htmlFor="email" className="block text-sm font-medium text-[var(--text-primary)] mb-1">
            Email address
          </label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            className="w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] px-4 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-secondary)]/50 focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)] focus:border-transparent transition-all"
          />
        </div>

        {/* Password */}
        <div>
          <label htmlFor="password" className="block text-sm font-medium text-[var(--text-primary)] mb-1">
            Password
          </label>
          <div className="relative">
            <input
              id="password"
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              className="w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] px-4 pr-10 py-3 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-secondary)]/50 focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)] focus:border-transparent transition-all"
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

        {/* Terms checkbox */}
        <div className="flex items-start gap-2">
          <input
            id="terms"
            type="checkbox"
            checked={agreedToTerms}
            onChange={(e) => setAgreedToTerms(e.target.checked)}
            className="mt-1 h-4 w-4 rounded border-[var(--border-subtle)] text-[var(--color-brand-secondary)] focus:ring-[var(--color-brand-secondary)] cursor-pointer"
          />
          <label htmlFor="terms" className="text-sm text-[var(--text-secondary)] cursor-pointer">
            I agree to the{" "}
            <Link href="#" className="text-[var(--color-brand-secondary)] hover:underline">Terms</Link>
            {" "}and{" "}
            <Link href="#" className="text-[var(--color-brand-secondary)] hover:underline">Conditions</Link>
          </label>
        </div>

        {/* Submit */}
        <button
          type="submit"
          disabled={loading}
          className="w-full rounded-lg bg-gradient-to-r from-[var(--color-brand-primary)] to-[var(--color-brand-secondary)] px-4 py-2.5 text-sm font-semibold text-white transition-all hover:opacity-90 disabled:opacity-50 cursor-pointer"
        >
          {loading ? "Creating account..." : "Create free account"}
        </button>
      </form>

      {/* Sign in link */}
      <p className="mt-4 text-center text-sm text-[var(--text-secondary)]">
        Already have an account?{" "}
        <Link href="/login" className="font-medium text-[var(--color-brand-secondary)] hover:underline">
          Sign in
        </Link>
      </p>
    </div>
  );
}
