"use client";

import { useState, useEffect, useCallback } from "react";
import { Timer, CheckCircle2, Gauge, Hash, TrendingUp, HeartPulse, Loader2 } from "lucide-react";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { StatCard } from "@/components/dashboard/stat-card";
import { RagIndicator } from "@/components/dashboard/rag-indicator";
import { Badge, Progress } from "@/components/ui";
import type { HealthSeverity } from "@/lib/types/models";
import { useAutoRefresh } from "@/lib/ws/context";
import { useSelectedProject } from "@/lib/project/context";
import { cachedFetch } from "@/lib/fetch-cache";

interface SummaryData {
  totalItems: number;
  storyPoints: { total: number; completed: number; remaining: number };
  teamSize: number;
  healthSignals: number;
  completionPct: number;
}

interface SprintData {
  name: string;
  state: string;
  startDate: string | null;
  endDate: string | null;
  totalItems: number;
  completedItems: number;
  totalStoryPoints: number;
  completedStoryPoints: number;
  completionPct: number;
}

export function SprintOverviewBar() {
  const { selectedProject } = useSelectedProject();
  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [sprint, setSprint] = useState<SprintData | null>(null);
  const [successProbability, setSuccessProbability] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const refreshKey = useAutoRefresh(["sync_complete", "writeback_success", "writeback_undo", "sprint_completed", "github_activity"]);

  const projectId = selectedProject?.internalId;

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const q = projectId ? `?projectId=${projectId}` : "";
      const [sRes, spRes, planRes] = await Promise.all([
        cachedFetch(`/api/dashboard/summary${q}`),
        cachedFetch(`/api/dashboard/sprints${q}`),
        cachedFetch(`/api/sprints${q}`),
      ]);
      if (sRes.ok) setSummary(sRes.data as SummaryData);
      if (spRes.ok) {
        const d = spRes.data as { sprints?: SprintData[] };
        const active = (d.sprints ?? []).find((s: SprintData) => s.state === "active");
        setSprint(active ?? d.sprints?.[0] ?? null);
      }
      if (planRes.ok) {
        const planData = planRes.data as { plan?: { successProbability?: number } };
        const sp = planData?.plan?.successProbability;
        setSuccessProbability(typeof sp === "number" ? sp : null);
      }
    } catch { /* fallback to mock */ }
    setLoading(false);
  }, [projectId]);

  useEffect(() => { fetchData(); }, [fetchData, refreshKey]);

  const hasReal = summary !== null;
  const name = sprint?.name ?? "No Active Sprint";
  const pct = sprint?.completionPct ?? 0;
  const totalSP = sprint?.totalStoryPoints ?? summary?.storyPoints?.total ?? 0;
  const doneSP = sprint?.completedStoryPoints ?? summary?.storyPoints?.completed ?? 0;

  let daysLeft = 0;
  let startStr = "-";
  let endStr = "-";
  if (sprint?.startDate && sprint?.endDate) {
    const end = new Date(sprint.endDate);
    daysLeft = Math.max(0, Math.ceil((end.getTime() - Date.now()) / 86400000));
    startStr = new Date(sprint.startDate).toLocaleDateString("en-US", { month: "short", day: "numeric" });
    endStr = end.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  }

  const pacingPct = sprint ? (sprint.totalItems > 0 ? Math.round((sprint.completedItems / sprint.totalItems) * 100) : 0) : 0;
  const health: HealthSeverity = summary
    ? (summary.healthSignals > 2 ? "RED" : summary.healthSignals > 0 ? "AMBER" : "GREEN")
    : "GREEN";

  if (loading) {
    return (
      <DashboardPanel title="Sprint Overview" icon={Timer}>
        <div className="flex items-center justify-center py-8">
          <Loader2 size={20} className="animate-spin text-[var(--color-brand-secondary)]" />
        </div>
      </DashboardPanel>
    );
  }

  return (
    <DashboardPanel
      title={name}
      icon={Timer}
      actions={
        <div className="flex items-center gap-3">
          <RagIndicator severity={health} size="sm" />
          <Badge variant={daysLeft <= 2 ? "rag-red" : "brand"}>{daysLeft} days left</Badge>
        </div>
      }
    >
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <span className="text-sm text-[var(--text-secondary)]">{startStr} &ndash; {endStr}</span>
          {hasReal && (
            <span className="text-sm text-[var(--text-secondary)] border-l border-[var(--border-subtle)] pl-4">
              {summary.teamSize} team members &bull; {summary.totalItems} work items
            </span>
          )}
        </div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatCard label="Completion" value={`${pct}%`} severity="GREEN" icon={CheckCircle2} />
          <StatCard label="Pacing" value={`${pacingPct}%`} icon={Gauge} />
          <StatCard label="Total SP" value={totalSP} icon={Hash} />
          <StatCard label="Completed SP" value={doneSP} icon={TrendingUp} />
        </div>

        {/* Sprint Health - derived from success probability + pacing */}
        {successProbability !== null && (() => {
          const healthScore = Math.round(
            successProbability * 0.6 + pacingPct * 0.4
          );
          const healthSeverity: HealthSeverity =
            healthScore >= 75 ? "GREEN" : healthScore >= 50 ? "AMBER" : "RED";
          const healthLabel =
            healthScore >= 75 ? "On Track" : healthScore >= 50 ? "At Risk" : "Critical";
          return (
            <div className="flex items-center gap-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/40 p-3">
              <HeartPulse size={18} className="shrink-0 text-[var(--text-secondary)]" />
              <span className="text-sm font-medium text-[var(--text-secondary)] whitespace-nowrap">
                Sprint Health
              </span>
              <div className="flex-1 min-w-0">
                <Progress value={healthScore} severity={healthSeverity} size="sm" />
              </div>
              <span className="text-sm font-bold tabular-nums text-[var(--text-primary)]">
                {healthScore}%
              </span>
              <RagIndicator severity={healthSeverity} label={healthLabel} size="sm" />
            </div>
          );
        })()}
      </div>
    </DashboardPanel>
  );
}
