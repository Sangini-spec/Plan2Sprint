"use client";

import { ProjectHeroBanner } from "@/components/po/project-hero-banner";
import { ProjectOverviewPanel } from "@/components/po/project-overview-panel";
import { MyStandupCompact } from "@/components/dev/my-standup-compact";
import { EmptyDashboard } from "@/components/dashboard/empty-dashboard";
import { ProjectAccessDeniedBanner } from "@/components/project/project-access-denied-banner";
import { useSelectedProject } from "@/lib/project/context";

export default function DevDashboardPage() {
  const { selectedProject, projects } = useSelectedProject();

  // No projects at all — show welcome/connect card
  if (projects !== undefined && projects.length === 0 && !selectedProject) {
    return <EmptyDashboard />;
  }

  return (
    // Hotfix 91 — banner replaces the dashboard with a friendly
    // "ask your PO to assign you" message when the currently
    // selected project is one the dev can't actually see. Most
    // common path: stale localStorage preference for a project they
    // got removed from. Renders children unchanged when access is
    // granted.
    <ProjectAccessDeniedBanner>
      <div className="space-y-4">
        {/* Project Hero Banner — dark banner with KPIs + timeline */}
        <ProjectHeroBanner />

        {/* Project Overview — Module Status feature cards */}
        <ProjectOverviewPanel hideKpiRow hideRisks />

        {/* Standup summary */}
        <MyStandupCompact />
      </div>
    </ProjectAccessDeniedBanner>
  );
}
