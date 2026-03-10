"use client";

import { useState } from "react";
import { Tabs } from "@/components/ui";
import { ProjectHeroBanner } from "@/components/po/project-hero-banner";
import { ProjectOverviewPanel } from "@/components/po/project-overview-panel";
import { ProjectPlanGantt } from "@/components/po/project-plan-gantt";

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
