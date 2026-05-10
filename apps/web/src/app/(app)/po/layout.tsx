"use client";

import { RoleGuard } from "@/components/auth/role-guard";
import { PO_DASHBOARD_ROLES } from "@/lib/types/auth";

export default function POLayout({ children }: { children: React.ReactNode }) {
  return <RoleGuard allow={PO_DASHBOARD_ROLES}>{children}</RoleGuard>;
}
