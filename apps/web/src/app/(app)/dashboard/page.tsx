"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth/context";
import { ROLE_DASHBOARD_ROUTES } from "@/lib/types/auth";

export default function DashboardPage() {
  const { appUser, loading } = useAuth();
  const router = useRouter();

  // Hotfix 15 — wait for ``appUser`` to actually populate before
  // routing. Previously this read the ``role`` from useAuth which
  // returns a default ("developer" then "product_owner" since this
  // hotfix) when appUser is still null. There was a brief window
  // where ``loading=false`` but ``appUser=null`` (e.g. between
  // ``setLoading(false)`` and ``setAppUser`` in the auth provider),
  // during which the dashboard would route to whatever the fallback
  // was, locking the user out of their actual role's pages.
  //
  // Now we wait for ``appUser`` to be set (or for ``loading`` to be
  // explicitly false AND appUser still null, which means there's no
  // session — bounce to login rather than guess a role).
  useEffect(() => {
    if (loading) return;
    if (!appUser) {
      router.replace("/login");
      return;
    }
    const route = ROLE_DASHBOARD_ROUTES[appUser.role] ?? "/po";
    router.replace(route);
  }, [appUser, loading, router]);

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
