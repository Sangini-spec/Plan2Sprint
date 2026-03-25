"use client";

import { ProjectHeroBanner } from "@/components/po/project-hero-banner";
import { ProjectOverviewPanel } from "@/components/po/project-overview-panel";
import { MyStandupCompact } from "@/components/dev/my-standup-compact";

export default function DevDashboardPage() {
  return (
    <div className="space-y-4">
      {/* Project Hero Banner — dark banner with KPIs + timeline */}
      <ProjectHeroBanner />

      {/* Project Overview — Module Status feature cards */}
      <ProjectOverviewPanel hideKpiRow hideRisks />

      {/* Standup summary */}
      <MyStandupCompact />
    </div>
  );
}
