"use client";

import { useState, useEffect, useCallback } from "react";
import { Timer, Loader2 } from "lucide-react";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { StatCard } from "@/components/dashboard/stat-card";
import { Badge, Progress } from "@/components/ui";
import type { HealthSeverity } from "@/lib/types/models";
import { useAutoRefresh } from "@/lib/ws/context";
import { cachedFetch } from "@/lib/fetch-cache";

interface SummaryData {
  storyPoints: { total: number; completed: number; remaining: number };
  completionPct: number;
  activeSprints: number;
}

interface SprintData {
  name: string;
  state: string;
  startDate: string | null;
  endDate: string | null;
  totalStoryPoints: number;
  completedStoryPoints: number;
  completionPct: number;
}

export function MySprintOverviewBar() {
  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [sprint, setSprint] = useState<SprintData | null>(null);
  const [loading, setLoading] = useState(true);
  const refreshKey = useAutoRefresh(["sync_complete", "writeback_success", "writeback_undo"]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [sRes, spRes] = await Promise.all([
        cachedFetch<SummaryData>("/api/dashboard/summary"),
        cachedFetch<{ sprints?: SprintData[] }>("/api/dashboard/sprints"),
      ]);
      if (sRes.ok && sRes.data) setSummary(sRes.data);
      if (spRes.ok && spRes.data) {
        const active = (spRes.data.sprints ?? []).find((s: SprintData) => s.state === "active");
        setSprint(active ?? spRes.data.sprints?.[0] ?? null);
      }
    } catch { /* keep null */ }
    setLoading(false);
  }, []);

  useEffect(() => { fetchData(); }, [fetchData, refreshKey]);

  const sprintName = sprint?.name ?? "No Active Sprint";
  const assignedSP = sprint?.totalStoryPoints ?? summary?.storyPoints?.total ?? 0;
  const completedSP = sprint?.completedStoryPoints ?? summary?.storyPoints?.completed ?? 0;
  const remainingSP = assignedSP - completedSP;
  const completionPct = assignedSP > 0 ? Math.round((completedSP / assignedSP) * 100) : 0;

  let daysLeft = 0;
  if (sprint?.endDate) {
    const end = new Date(sprint.endDate);
    daysLeft = Math.max(0, Math.ceil((end.getTime() - Date.now()) / 86400000));
  }

  const hasReal = summary !== null;
  const capacityPct = hasReal ? Math.min(completionPct + 15, 100) : 0;
  const pacing: HealthSeverity = completionPct >= 80 ? "GREEN" : completionPct >= 50 ? "AMBER" : "RED";

  if (loading) {
    return (
      <DashboardPanel title="My Sprint" icon={Timer}>
        <div className="flex items-center justify-center py-8">
          <Loader2 size={20} className="animate-spin text-[var(--color-brand-secondary)]" />
        </div>
      </DashboardPanel>
    );
  }

  return (
    <DashboardPanel
      title={sprintName}
      icon={Timer}
      actions={<Badge variant="brand">{daysLeft} days remaining</Badge>}
    >
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatCard label="Assigned SP" value={assignedSP} />
          <StatCard label="Completed SP" value={completedSP} severity="GREEN" />
          <StatCard label="Remaining SP" value={remainingSP} />
          <StatCard label="Capacity" value={`${capacityPct}%`} severity={pacing} />
        </div>

        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[var(--text-secondary)]">Sprint Completion</span>
            <span className="text-xs font-semibold text-[var(--text-primary)] tabular-nums">{completionPct}%</span>
          </div>
          <Progress value={completionPct} severity={pacing} size="md" />
        </div>
      </div>
    </DashboardPanel>
  );
}
