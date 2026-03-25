"use client";

import dynamic from "next/dynamic";
import { Loader2 } from "lucide-react";

function PageLoader() {
  return (
    <div className="flex items-center justify-center py-16">
      <Loader2 className="h-5 w-5 animate-spin text-[var(--text-secondary)]" />
    </div>
  );
}

const TeamHealthOverview = dynamic(
  () =>
    import("@/components/stakeholder/team-health-overview").then((m) => ({
      default: m.TeamHealthOverview,
    })),
  { loading: () => <PageLoader /> }
);

export default function StakeholderHealthPage() {
  return (
    <div className="space-y-6">
      <TeamHealthOverview />
    </div>
  );
}
