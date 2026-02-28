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
  AlertCircle,
  LayoutDashboard,
  Code2,
  PieChart,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { ROLE_DASHBOARD_ROUTES, type UserRole } from "@/lib/types/auth";

const isDemoMode =
  !process.env.NEXT_PUBLIC_SUPABASE_URL ||
  process.env.NEXT_PUBLIC_SUPABASE_URL === "https://your-project.supabase.co";

const QUICK_ROLES: { value: UserRole; label: string; icon: React.ReactNode }[] = [
  { value: "product_owner", label: "Product Owner", icon: <LayoutDashboard className="h-4 w-4" /> },
  { value: "developer", label: "Developer", icon: <Code2 className="h-4 w-4" /> },
  { value: "stakeholder", label: "Stakeholder", icon: <PieChart className="h-4 w-4" /> },
];

export function LoginForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleDemoLogin = (role: UserRole) => {
    localStorage.setItem(
      "plan2sprint_demo_user",
      JSON.stringify({
        id: "demo-user-1",
        email: "demo@plan2sprint.app",
        full_name: "Demo User",
        organization_name: "Demo Organization",
        role,
        onboarding_completed: true,
        created_at: new Date().toISOString(),
      })
    );
    const dashboardRoute = ROLE_DASHBOARD_ROUTES[role] ?? "/po";
    router.push(dashboardRoute);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    if (isDemoMode) {
      // In demo mode, login also works — default to product_owner
      localStorage.setItem(
        "plan2sprint_demo_user",
        JSON.stringify({
          id: "demo-user-1",
          email,
          full_name: email.split("@")[0] ?? "Demo User",
          organization_name: "Demo Organization",
          role: "product_owner",
          onboarding_completed: true,
          created_at: new Date().toISOString(),
        })
      );
      router.push("/po");
      return;
    }

    try {
      const supabase = createClient();
      const { data, error: authError } = await supabase.auth.signInWithPassword({
        email,
        password,
      });

      if (authError) {
        // If Supabase is unreachable (paused/SSL error), fall back to demo mode
        const msg = authError.message?.toLowerCase() ?? "";
        if (msg.includes("failed to fetch") || msg.includes("network") || msg.includes("ssl")) {
          console.warn("Supabase unreachable, falling back to demo login:", authError.message);
          localStorage.setItem(
            "plan2sprint_demo_user",
            JSON.stringify({
              id: `user-${Date.now()}`,
              email,
              full_name: email.split("@")[0] ?? "User",
              organization_name: "Organization",
              role: "product_owner",
              onboarding_completed: true,
              created_at: new Date().toISOString(),
            })
          );
          router.push("/po");
          return;
        }
        setError(authError.message);
        setLoading(false);
        return;
      }

      // Get role from user metadata to route correctly
      const userRole = data?.user?.user_metadata?.role as UserRole | undefined;
      const dashboardRoute = userRole ? (ROLE_DASHBOARD_ROUTES[userRole] ?? "/po") : "/po";
      router.push(dashboardRoute);
      router.refresh();
    } catch {
      // Network failure — fall back to demo mode
      console.warn("Supabase auth unreachable, falling back to demo login");
      localStorage.setItem(
        "plan2sprint_demo_user",
        JSON.stringify({
          id: `user-${Date.now()}`,
          email,
          full_name: email.split("@")[0] ?? "User",
          organization_name: "Organization",
          role: "product_owner",
          onboarding_completed: true,
          created_at: new Date().toISOString(),
        })
      );
      router.push("/po");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div className="mb-6 text-center">
        <h1 className="text-2xl font-bold text-[var(--text-primary)]">
          Welcome back
        </h1>
        <p className="mt-2 text-sm text-[var(--text-secondary)]">
          Sign in to your Plan2Sprint account
        </p>
      </div>

      {/* Demo mode: quick role-based login */}
      {isDemoMode && (
        <div className="mb-6">
          <p className="text-xs font-medium text-[var(--text-secondary)] mb-2 text-center">
            Quick demo login — choose a role
          </p>
          <div className="grid grid-cols-3 gap-2">
            {QUICK_ROLES.map((r) => (
              <button
                key={r.value}
                type="button"
                onClick={() => handleDemoLogin(r.value)}
                className={cn(
                  "flex flex-col items-center gap-1.5 rounded-xl border px-3 py-3",
                  "border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]",
                  "text-[var(--text-secondary)] hover:text-[var(--color-brand-secondary)]",
                  "hover:border-[var(--color-brand-secondary)] hover:bg-[var(--color-brand-secondary)]/10",
                  "transition-all cursor-pointer"
                )}
              >
                {r.icon}
                <span className="text-xs font-semibold">{r.label}</span>
              </button>
            ))}
          </div>
          <div className="relative my-5">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-[var(--border-subtle)]" />
            </div>
            <div className="relative flex justify-center text-xs">
              <span className="bg-[var(--bg-surface)] px-3 text-[var(--text-secondary)]">
                or sign in with email
              </span>
            </div>
          </div>
        </div>
      )}

      {!isDemoMode && <SocialAuthButtons className="mb-6" />}

      {!isDemoMode && (
        <div className="relative mb-6">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-[var(--border-subtle)]" />
          </div>
          <div className="relative flex justify-center text-xs">
            <span className="bg-[var(--bg-surface)] px-3 text-[var(--text-secondary)]">
              or continue with email
            </span>
          </div>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        {error && (
          <div className="flex items-center gap-2 rounded-lg border border-[var(--color-rag-red)]/30 bg-[var(--color-rag-red)]/10 px-4 py-3 text-sm text-[var(--color-rag-red)]">
            <AlertCircle className="h-4 w-4 shrink-0" />
            {error}
          </div>
        )}

        <div>
          <label
            htmlFor="email"
            className="block text-sm font-medium text-[var(--text-primary)] mb-1.5"
          >
            Email
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
          <div className="flex items-center justify-between mb-1.5">
            <label
              htmlFor="password"
              className="block text-sm font-medium text-[var(--text-primary)]"
            >
              Password
            </label>
            <Link
              href="/forgot-password"
              className="text-xs text-[var(--color-brand-secondary)] hover:underline"
            >
              Forgot password?
            </Link>
          </div>
          <div className="relative">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--text-secondary)]" />
            <input
              id="password"
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter your password"
              required
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

        <Button
          type="submit"
          className="w-full"
          disabled={loading}
        >
          {loading ? "Signing in..." : "Sign in"}
        </Button>
      </form>

      <p className="mt-6 text-center text-sm text-[var(--text-secondary)]">
        Don&apos;t have an account?{" "}
        <Link
          href="/signup"
          className="font-medium text-[var(--color-brand-secondary)] hover:underline"
        >
          Get started free
        </Link>
      </p>
    </div>
  );
}
