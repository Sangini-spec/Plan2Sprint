"use client";

import dynamic from "next/dynamic";
import { Loader2 } from "lucide-react";

const TeamHealthDashboard = dynamic(
  () => import("@/components/po/team-health-dashboard").then((m) => ({ default: m.TeamHealthDashboard })),
  { loading: () => <PageLoader /> }
);

function PageLoader() {
  return (
    <div className="flex items-center justify-center py-16">
      <Loader2 className="h-5 w-5 animate-spin text-[var(--text-secondary)]" />
    </div>
  );
}

export default function HealthPage() {
  return (
    <div className="space-y-6">
      <TeamHealthDashboard />
    </div>
  );
}
