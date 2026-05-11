"use client";

import { PortfolioHealthSummary } from "@/components/stakeholder/portfolio-health-summary";
import { EmptyDashboard } from "@/components/dashboard/empty-dashboard";
import { useSelectedProject } from "@/lib/project/context";

export default function StakeholderDashboardPage() {
  const { selectedProject, projects } = useSelectedProject();

  // No projects at all — show welcome/connect card
  if (projects !== undefined && projects.length === 0 && !selectedProject) {
    return <EmptyDashboard />;
  }

  return (
    <div className="space-y-4" data-onboarding="portfolio-health">
      <PortfolioHealthSummary />
    </div>
  );
}
