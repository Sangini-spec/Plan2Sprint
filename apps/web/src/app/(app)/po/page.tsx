"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { Loader2, PlugZap, ArrowRight } from "lucide-react";
import { Tabs, Button } from "@/components/ui";
import { ProjectHeroBanner } from "@/components/po/project-hero-banner";
import { ProjectOverviewPanel } from "@/components/po/project-overview-panel";
import { useSelectedProject } from "@/lib/project/context";
import { useIntegrations } from "@/lib/integrations/context";

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

function EmptyDashboard() {
  const { openModal } = useIntegrations();

  return (
    <div className="flex flex-col items-center justify-center py-20 px-6 text-center">
      <div className="flex h-20 w-20 items-center justify-center rounded-2xl bg-[var(--bg-surface-raised)] mb-6">
        <PlugZap size={40} className="text-[var(--color-brand-secondary)]" />
      </div>

      <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-3">
        Welcome to Plan2Sprint
      </h2>
      <p className="text-sm text-[var(--text-secondary)] max-w-md mb-8">
        Connect your project management tools to get started. Link Jira or Azure DevOps
        to import your projects, work items, and sprint data.
      </p>

      <Button
        variant="brand"
        size="lg"
        onClick={() => openModal?.()}
        className="gap-2"
      >
        Connect Tools
        <ArrowRight size={16} />
      </Button>

      <div className="mt-8 grid grid-cols-1 sm:grid-cols-3 gap-4 max-w-lg w-full">
        {[
          { title: "Import Projects", desc: "Fetch work items, features & sprints" },
          { title: "AI Sprint Plans", desc: "Auto-generate optimized sprint plans" },
          { title: "Track Progress", desc: "Monitor team health & delivery" },
        ].map(({ title, desc }) => (
          <div
            key={title}
            className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]/50 p-4 text-center"
          >
            <p className="text-xs font-semibold text-[var(--text-primary)]">{title}</p>
            <p className="text-[11px] text-[var(--text-secondary)] mt-1">{desc}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function PODashboardPage() {
  const [activeTab, setActiveTab] = useState("dashboard");
  const { selectedProject, projects } = useSelectedProject();

  // No projects at all — show welcome/connect card
  if (projects !== undefined && projects.length === 0 && !selectedProject) {
    return <EmptyDashboard />;
  }

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
