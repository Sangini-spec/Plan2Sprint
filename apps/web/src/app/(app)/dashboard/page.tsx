"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth/context";
import { ROLE_DASHBOARD_ROUTES } from "@/lib/types/auth";

export default function DashboardPage() {
  const { role, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading) {
      const route = ROLE_DASHBOARD_ROUTES[role] ?? "/po";
      router.replace(route);
    }
  }, [role, loading, router]);

  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="flex items-center gap-3">
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-[var(--color-brand-secondary)] border-t-transparent" />
        <span className="text-sm text-[var(--text-secondary)]">
          Loading your dashboard...
        </span>
      </div>
    </div>
  );
}
