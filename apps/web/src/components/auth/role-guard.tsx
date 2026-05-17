"use client";

/* ==========================================================================
   RoleGuard - gates role-specific routes (/po, /dev, /stakeholder).

   Without this, a user logged in as PO can navigate to /stakeholder and see
   the stakeholder dashboard (and vice versa). That's a UI/data isolation
   bug, since each role's page renders different content for the same org.

   This component:
     1. Waits for auth to finish loading.
     2. If the user's role isn't in `allow`, redirects to ROLE_DASHBOARD_ROUTES.
     3. Otherwise renders children.
   ========================================================================== */

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { useAuth } from "@/lib/auth/context";
import { ROLE_DASHBOARD_ROUTES, type UserRole } from "@/lib/types/auth";

interface RoleGuardProps {
  allow: UserRole[];
  children: React.ReactNode;
}

export function RoleGuard({ allow, children }: RoleGuardProps) {
  const { appUser, loading } = useAuth();
  const router = useRouter();

  const userRole = appUser?.role;
  const allowed = userRole !== undefined && allow.includes(userRole);

  useEffect(() => {
    if (loading) return;
    if (!appUser) {
      router.replace("/login");
      return;
    }
    if (!allowed) {
      const dest = ROLE_DASHBOARD_ROUTES[appUser.role] ?? "/dashboard";
      router.replace(dest);
    }
  }, [allowed, appUser, loading, router]);

  if (loading || !appUser || !allowed) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-[var(--color-brand-secondary)]" />
      </div>
    );
  }

  return <>{children}</>;
}
