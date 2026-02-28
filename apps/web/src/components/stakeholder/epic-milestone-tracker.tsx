"use client";

import { useState, useEffect, useCallback } from "react";
import { Milestone, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { RagIndicator } from "@/components/dashboard/rag-indicator";
import { Progress } from "@/components/ui";
import type { HealthSeverity } from "@/lib/types/models";
import { useAutoRefresh } from "@/lib/ws/context";
import { cachedFetch } from "@/lib/fetch-cache";

interface EpicData {
  id: string;
  name: string;
  owningTeam: string;
  completedTickets: number;
  totalTickets: number;
  riskFlag: HealthSeverity;
  projectedCompletion: string;
}

interface MilestoneData {
  id: string;
  name: string;
  date: string;
  status: HealthSeverity;
}

const dotColors: Record<HealthSeverity, string> = {
  GREEN: "bg-[var(--color-rag-green)]",
  AMBER: "bg-[var(--color-rag-amber)]",
  RED: "bg-[var(--color-rag-red)]",
};

const lineColors: Record<HealthSeverity, string> = {
  GREEN: "border-[var(--color-rag-green)]",
  AMBER: "border-[var(--color-rag-amber)]",
  RED: "border-[var(--color-rag-red)]",
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export function EpicMilestoneTracker() {
  const [epics, setEpics] = useState<EpicData[]>([]);
  const [milestones, setMilestones] = useState<MilestoneData[]>([]);
  const [loading, setLoading] = useState(true);
  const refreshKey = useAutoRefresh(["sync_complete"]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      // Derive epics from work items by grouping on type=Epic or Feature
      const wiRes = await cachedFetch("/api/dashboard/work-items?limit=200");
      if (wiRes.ok) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const data = wiRes.data as any;
        const workItems = data.workItems ?? [];

        // Group work items by type to create epic-like summaries
        const typeGroups: Record<string, { total: number; done: number; labels: string[] }> = {};
        for (const wi of workItems) {
          const type = wi.type ?? "Other";
          if (!typeGroups[type]) typeGroups[type] = { total: 0, done: 0, labels: [] };
          typeGroups[type].total++;
          if (wi.status === "DONE") typeGroups[type].done++;
        }

        const epicList: EpicData[] = Object.entries(typeGroups).map(([type, g], idx) => {
          const pct = g.total > 0 ? Math.round((g.done / g.total) * 100) : 0;
          const risk: HealthSeverity = pct >= 70 ? "GREEN" : pct >= 40 ? "AMBER" : "RED";
          // Project completion based on current rate
          const daysPerItem = g.done > 0 ? 14 / g.done : 14;
          const remaining = g.total - g.done;
          const projectedDays = Math.ceil(remaining * daysPerItem);
          const projected = new Date(Date.now() + projectedDays * 86400000).toISOString();
          return {
            id: `epic-${idx}`,
            name: `${type} Items`,
            owningTeam: "Team",
            completedTickets: g.done,
            totalTickets: g.total,
            riskFlag: risk,
            projectedCompletion: projected,
          };
        });
        setEpics(epicList);
      } else {
        setEpics([]);
      }

      // Derive milestones from sprints
      const spRes = await cachedFetch("/api/dashboard/sprints");
      if (spRes.ok) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const data = spRes.data as any;
        const sprints = data.sprints ?? [];
        const ms: MilestoneData[] = sprints.map((s: { id: string; name: string; endDate: string; completionPct: number }) => ({
          id: s.id,
          name: `${s.name} End`,
          date: s.endDate ?? new Date().toISOString(),
          status: (s.completionPct >= 70 ? "GREEN" : s.completionPct >= 40 ? "AMBER" : "RED") as HealthSeverity,
        }));
        setMilestones(ms);
      } else {
        setMilestones([]);
      }
    } catch {
      setEpics([]);
      setMilestones([]);
    }
    setLoading(false);
  }, []);

  useEffect(() => { fetchData(); }, [fetchData, refreshKey]);

  if (loading) {
    return (
      <DashboardPanel title="Epics & Milestones" icon={Milestone}>
        <div className="flex items-center justify-center py-8">
          <Loader2 size={20} className="animate-spin text-[var(--color-brand-secondary)]" />
        </div>
      </DashboardPanel>
    );
  }

  if (epics.length === 0 && milestones.length === 0) {
    return (
      <DashboardPanel title="Epics & Milestones" icon={Milestone}>
        <div className="flex flex-col items-center justify-center py-8 gap-2">
          <Milestone size={24} className="text-[var(--text-tertiary)]" />
          <p className="text-sm text-[var(--text-secondary)]">No epic or milestone data available</p>
          <p className="text-xs text-[var(--text-tertiary)]">
            Sync project data to track epics and milestones.
          </p>
        </div>
      </DashboardPanel>
    );
  }

  return (
    <DashboardPanel title="Epics & Milestones" icon={Milestone}>
      {/* Epics Table */}
      {epics.length > 0 && (
        <div className="mb-8">
          <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
            Epic Progress
          </h4>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border-subtle)]">
                  <th className="pb-2 pr-4 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">Epic</th>
                  <th className="pb-2 pr-4 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">Team</th>
                  <th className="pb-2 pr-4 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] min-w-[140px]">Progress</th>
                  <th className="pb-2 pr-4 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">Projected</th>
                  <th className="pb-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">Risk</th>
                </tr>
              </thead>
              <tbody>
                {epics.map((epic) => {
                  const pct = epic.totalTickets > 0 ? Math.round((epic.completedTickets / epic.totalTickets) * 100) : 0;
                  return (
                    <tr key={epic.id} className="border-b border-[var(--border-subtle)] last:border-b-0">
                      <td className="py-3 pr-4"><span className="font-medium text-[var(--text-primary)]">{epic.name}</span></td>
                      <td className="py-3 pr-4 text-[var(--text-secondary)]">{epic.owningTeam}</td>
                      <td className="py-3 pr-4">
                        <div className="flex items-center gap-2">
                          <Progress value={epic.completedTickets} max={epic.totalTickets} severity={epic.riskFlag} size="sm" className="flex-1" />
                          <span className="text-xs font-medium text-[var(--text-secondary)] tabular-nums whitespace-nowrap">
                            {epic.completedTickets}/{epic.totalTickets} ({pct}%)
                          </span>
                        </div>
                      </td>
                      <td className="py-3 pr-4 text-[var(--text-secondary)] whitespace-nowrap">{formatDate(epic.projectedCompletion)}</td>
                      <td className="py-3"><RagIndicator severity={epic.riskFlag} size="sm" /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Milestones Timeline */}
      {milestones.length > 0 && (
        <div>
          <h4 className="mb-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
            Upcoming Milestones
          </h4>
          <div className="relative space-y-0">
            {milestones.map((ms, idx) => (
              <div key={ms.id} className="relative flex gap-4 pb-6 last:pb-0">
                {idx < milestones.length - 1 && (
                  <div className={cn("absolute left-[9px] top-5 bottom-0 w-px border-l-2 border-dashed", lineColors[ms.status])} />
                )}
                <div className={cn("relative mt-1 h-[18px] w-[18px] shrink-0 rounded-full border-2 border-[var(--bg-surface-raised)]", dotColors[ms.status], ms.status === "RED" && "animate-pulse")} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-semibold text-[var(--text-primary)]">{ms.name}</span>
                    <RagIndicator severity={ms.status} size="sm" />
                  </div>
                  <span className="text-xs text-[var(--text-secondary)]">{formatDate(ms.date)}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </DashboardPanel>
  );
}
