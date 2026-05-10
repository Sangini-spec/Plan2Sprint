"use client";

import { RoleGuard } from "@/components/auth/role-guard";
import { DEV_DASHBOARD_ROLES } from "@/lib/types/auth";

export default function DevLayout({ children }: { children: React.ReactNode }) {
  return <RoleGuard allow={DEV_DASHBOARD_ROLES}>{children}</RoleGuard>;
}
