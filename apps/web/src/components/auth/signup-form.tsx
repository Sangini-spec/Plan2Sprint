"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui";
import { SocialAuthButtons } from "./social-auth-buttons";
import {
  Mail,
  Lock,
  Eye,
  EyeOff,
  User,
  Building2,
  AlertCircle,
  CheckCircle2,
  LayoutDashboard,
  Code2,
  PieChart,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { ROLE_DASHBOARD_ROUTES, type UserRole } from "@/lib/types/auth";

const SELECTABLE_ROLES: { value: UserRole; label: string; description: string; icon: React.ReactNode }[] = [
  {
    value: "product_owner",
    label: "Product Owner",
    description: "Plan sprints, manage team, review AI plans",
    icon: <LayoutDashboard className="h-5 w-5" />,
  },
  {
    value: "developer",
    label: "Developer",
    description: "View your sprint, standups, and AI rationale",
    icon: <Code2 className="h-5 w-5" />,
  },
  {
    value: "stakeholder",
    label: "Stakeholder",
    description: "Portfolio health, delivery metrics, read-only",
    icon: <PieChart className="h-5 w-5" />,
  },
];

const isDemoMode =
  !process.env.NEXT_PUBLIC_SUPABASE_URL ||
  process.env.NEXT_PUBLIC_SUPABASE_URL === "https://your-project.supabase.co";

export function SignupForm() {
  const router = useRouter();
  const [fullName, setFullName] = useState("");
  const [orgName, setOrgName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<UserRole>("product_owner");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      setLoading(false);
      return;
    }

    // Demo mode: skip Supabase, store role in localStorage, redirect to dashboard
    if (isDemoMode) {
      localStorage.setItem(
        "plan2sprint_demo_user",
        JSON.stringify({
          id: "demo-user-1",
          email,
          full_name: fullName,
          organization_name: orgName,
          role,
          onboarding_completed: false,
          created_at: new Date().toISOString(),
        })
      );
      const dashboardRoute = ROLE_DASHBOARD_ROUTES[role] ?? "/po";
      router.push(dashboardRoute);
      return;
    }

    // Real Supabase auth — with fallback to demo mode if Supabase is unreachable
    try {
      const supabase = createClient();
      const { error: authError } = await supabase.auth.signUp({
        email,
        password,
        options: {
          data: {
            full_name: fullName,
            organization_name: orgName,
            role,
          },
          emailRedirectTo: `${window.location.origin}/auth/callback`,
        },
      });

      if (authError) {
        // If Supabase is unreachable (paused/SSL error), fall back to demo mode
        const msg = authError.message?.toLowerCase() ?? "";
        if (msg.includes("failed to fetch") || msg.includes("network") || msg.includes("ssl")) {
          console.warn("Supabase unreachable, falling back to demo signup:", authError.message);
          localStorage.setItem(
            "plan2sprint_demo_user",
            JSON.stringify({
              id: `user-${Date.now()}`,
              email,
              full_name: fullName,
              organization_name: orgName,
              role,
              onboarding_completed: false,
              created_at: new Date().toISOString(),
            })
          );
          const dashboardRoute = ROLE_DASHBOARD_ROUTES[role] ?? "/po";
          router.push(dashboardRoute);
          return;
        }
        setError(authError.message);
        setLoading(false);
        return;
      }

      setSuccess(true);
    } catch {
      // Network failure — fall back to demo mode
      console.warn("Supabase auth unreachable, falling back to demo signup");
      localStorage.setItem(
        "plan2sprint_demo_user",
        JSON.stringify({
          id: `user-${Date.now()}`,
          email,
          full_name: fullName,
          organization_name: orgName,
          role,
          onboarding_completed: false,
          created_at: new Date().toISOString(),
        })
      );
      const dashboardRoute = ROLE_DASHBOARD_ROUTES[role] ?? "/po";
      router.push(dashboardRoute);
      return;
    }

    setLoading(false);
  };

  if (success) {
    return (
      <div className="text-center">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-[var(--color-rag-green)]/10">
          <CheckCircle2 className="h-6 w-6 text-[var(--color-rag-green)]" />
        </div>
        <h1 className="text-2xl font-bold text-[var(--text-primary)]">
          Check your email
        </h1>
        <p className="mt-2 text-sm text-[var(--text-secondary)]">
          We&apos;ve sent a confirmation link to{" "}
          <span className="font-medium text-[var(--text-primary)]">
            {email}
          </span>
          . Click the link to activate your account.
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
      <div className="mb-6 text-center">
        <h1 className="text-2xl font-bold text-[var(--text-primary)]">
          Create your account
        </h1>
        <p className="mt-2 text-sm text-[var(--text-secondary)]">
          Start planning smarter sprints in minutes
        </p>
      </div>

      {!isDemoMode && <SocialAuthButtons className="mb-6" />}

      {!isDemoMode && (
        <div className="relative mb-6">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-[var(--border-subtle)]" />
          </div>
          <div className="relative flex justify-center text-xs">
            <span className="bg-[var(--bg-surface)] px-3 text-[var(--text-secondary)]">
              or sign up with email
            </span>
          </div>
        </div>
      )}

      {isDemoMode && (
        <div className="mb-5 flex items-center gap-2 rounded-lg border border-[var(--color-brand-secondary)]/30 bg-[var(--color-brand-secondary)]/5 px-4 py-3 text-xs text-[var(--color-brand-secondary)]">
          <LayoutDashboard className="h-4 w-4 shrink-0" />
          Demo mode — enter any details to explore the dashboards
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        {error && (
          <div className="flex items-center gap-2 rounded-lg border border-[var(--color-rag-red)]/30 bg-[var(--color-rag-red)]/10 px-4 py-3 text-sm text-[var(--color-rag-red)]">
            <AlertCircle className="h-4 w-4 shrink-0" />
            {error}
          </div>
        )}

        {/* Role Selection */}
        <div>
          <label className="block text-sm font-medium text-[var(--text-primary)] mb-2">
            I am a...
          </label>
          <div className="grid grid-cols-3 gap-2">
            {SELECTABLE_ROLES.map((r) => (
              <button
                key={r.value}
                type="button"
                onClick={() => setRole(r.value)}
                className={cn(
                  "flex flex-col items-center gap-1.5 rounded-xl border px-3 py-3 transition-all cursor-pointer",
                  role === r.value
                    ? "border-[var(--color-brand-secondary)] bg-[var(--color-brand-secondary)]/10 text-[var(--color-brand-secondary)]"
                    : "border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] text-[var(--text-secondary)] hover:border-[var(--color-brand-secondary)]/30 hover:text-[var(--text-primary)]"
                )}
              >
                {r.icon}
                <span className="text-xs font-semibold">{r.label}</span>
              </button>
            ))}
          </div>
          <p className="mt-1.5 text-xs text-[var(--text-secondary)]">
            {SELECTABLE_ROLES.find((r) => r.value === role)?.description}
          </p>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label
              htmlFor="fullName"
              className="block text-sm font-medium text-[var(--text-primary)] mb-1.5"
            >
              Full name
            </label>
            <div className="relative">
              <User className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--text-secondary)]" />
              <input
                id="fullName"
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder="Jane Doe"
                required
                className="w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] pl-10 pr-4 py-2.5 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-secondary)]/50 focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)] focus:border-transparent transition-all"
              />
            </div>
          </div>
          <div>
            <label
              htmlFor="orgName"
              className="block text-sm font-medium text-[var(--text-primary)] mb-1.5"
            >
              Organization
            </label>
            <div className="relative">
              <Building2 className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--text-secondary)]" />
              <input
                id="orgName"
                type="text"
                value={orgName}
                onChange={(e) => setOrgName(e.target.value)}
                placeholder="Acme Inc"
                required
                className="w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] pl-10 pr-4 py-2.5 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-secondary)]/50 focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)] focus:border-transparent transition-all"
              />
            </div>
          </div>
        </div>

        <div>
          <label
            htmlFor="email"
            className="block text-sm font-medium text-[var(--text-primary)] mb-1.5"
          >
            Work email
          </label>
          <div className="relative">
            <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--text-secondary)]" />
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
              required
              className="w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] pl-10 pr-4 py-2.5 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-secondary)]/50 focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)] focus:border-transparent transition-all"
            />
          </div>
        </div>

        <div>
          <label
            htmlFor="password"
            className="block text-sm font-medium text-[var(--text-primary)] mb-1.5"
          >
            Password
          </label>
          <div className="relative">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--text-secondary)]" />
            <input
              id="password"
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="8+ characters"
              required
              minLength={8}
              className="w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] pl-10 pr-10 py-2.5 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-secondary)]/50 focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)] focus:border-transparent transition-all"
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
            >
              {showPassword ? (
                <EyeOff className="h-4 w-4" />
              ) : (
                <Eye className="h-4 w-4" />
              )}
            </button>
          </div>
        </div>

        <Button type="submit" className="w-full" disabled={loading}>
          {loading ? "Creating account..." : "Create account"}
        </Button>

        <p className="text-xs text-center text-[var(--text-secondary)]">
          By signing up, you agree to our{" "}
          <Link
            href="#"
            className="text-[var(--color-brand-secondary)] hover:underline"
          >
            Terms of Service
          </Link>{" "}
          and{" "}
          <Link
            href="#"
            className="text-[var(--color-brand-secondary)] hover:underline"
          >
            Privacy Policy
          </Link>
        </p>
      </form>

      <p className="mt-6 text-center text-sm text-[var(--text-secondary)]">
        Already have an account?{" "}
        <Link
          href="/login"
          className="font-medium text-[var(--color-brand-secondary)] hover:underline"
        >
          Sign in
        </Link>
      </p>
    </div>
  );
}
