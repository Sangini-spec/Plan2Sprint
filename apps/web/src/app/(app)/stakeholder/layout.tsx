"use client";

import { RoleGuard } from "@/components/auth/role-guard";
import { STAKEHOLDER_DASHBOARD_ROLES } from "@/lib/types/auth";

export default function StakeholderLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <RoleGuard allow={STAKEHOLDER_DASHBOARD_ROLES}>{children}</RoleGuard>
  );
}
