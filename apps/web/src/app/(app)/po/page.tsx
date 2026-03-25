"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { Loader2 } from "lucide-react";
import { Tabs } from "@/components/ui";
import { ProjectHeroBanner } from "@/components/po/project-hero-banner";
import { ProjectOverviewPanel } from "@/components/po/project-overview-panel";

const ProjectPlanGantt = dynamic(
  () => import("@/components/po/project-plan-gantt").then((m) => ({ default: m.ProjectPlanGantt })),
  { loading: () => (
    <div className="flex items-center justify-center py-16">
      <Loader2 className="h-5 w-5 animate-spin text-[var(--text-secondary)]" />
    </div>
  )}
);

const TAB_ITEMS = [
  { id: "dashboard", label: "Dashboard" },
  { id: "project-plan", label: "Project Plan" },
];

export default function PODashboardPage() {
  const [activeTab, setActiveTab] = useState("dashboard");

  return (
    <div className="space-y-4">
      {/* Tab bar */}
      <Tabs
        items={TAB_ITEMS}
        activeId={activeTab}
        onChange={setActiveTab}
        className="max-w-xs"
      />

      {/* ── Dashboard Tab ── */}
      {activeTab === "dashboard" && (
        <div className="space-y-4">
          {/* Project Hero Banner — dark banner with KPIs + timeline */}
          <ProjectHeroBanner />

          {/* Project Overview — Module Status feature cards */}
          <ProjectOverviewPanel hideKpiRow />
        </div>
      )}

      {/* ── Project Plan Tab ── */}
      {activeTab === "project-plan" && <ProjectPlanGantt />}
    </div>
  );
}
