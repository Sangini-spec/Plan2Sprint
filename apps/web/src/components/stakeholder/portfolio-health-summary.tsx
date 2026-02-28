"use client";

import { useState, useEffect, useCallback } from "react";
import { Briefcase, AlertTriangle, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { StatCard } from "@/components/dashboard/stat-card";
import { RagIndicator } from "@/components/dashboard/rag-indicator";
import { Badge, Progress } from "@/components/ui";
import type { HealthSeverity } from "@/lib/types/models";
import { useAutoRefresh } from "@/lib/ws/context";
import { cachedFetch } from "@/lib/fetch-cache";

interface SprintSummary {
  id: string;
  teamName: string;
  sprintName: string;
  health: HealthSeverity;
  completionPct: number;
  atRiskCount: number;
  daysRemaining: number;
}

interface PortfolioStats {
  totalTeams: number;
  sprintsOnTrack: number;
  sprintsAmber: number;
  sprintsRed: number;
}

export function PortfolioHealthSummary() {
  const [sprints, setSprints] = useState<SprintSummary[]>([]);
  const [stats, setStats] = useState<PortfolioStats>({ totalTeams: 0, sprintsOnTrack: 0, sprintsAmber: 0, sprintsRed: 0 });
  const [loading, setLoading] = useState(true);
  const refreshKey = useAutoRefresh(["sync_complete"]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [summaryRes, sprintsRes, healthRes] = await Promise.all([
        cachedFetch("/api/dashboard/summary"),
        cachedFetch("/api/dashboard/sprints"),
        cachedFetch("/api/team-health"),
      ]);

      let teamSize = 0;
      if (summaryRes.ok) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const data = summaryRes.data as any;
        teamSize = data.teamSize ?? 0;
      }

      const sprintList: SprintSummary[] = [];
      if (sprintsRes.ok) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const data = sprintsRes.data as any;
        const rawSprints = data.sprints ?? [];
        let onTrack = 0, amber = 0, red = 0;
        for (const s of rawSprints) {
          const pct = s.completionPct ?? 0;
          const daysLeft = s.endDate
            ? Math.max(0, Math.ceil((new Date(s.endDate).getTime() - Date.now()) / 86400000))
            : 0;
          const health: HealthSeverity = pct >= 70 ? "GREEN" : pct >= 40 ? "AMBER" : "RED";
          if (health === "GREEN") onTrack++;
          else if (health === "AMBER") amber++;
          else red++;

          sprintList.push({
            id: s.id,
            teamName: s.teamName ?? s.sourceTool ?? "Team",
            sprintName: s.name,
            health,
            completionPct: pct,
            atRiskCount: health === "RED" ? s.totalItems - s.completedItems : 0,
            daysRemaining: daysLeft,
          });
        }
        setStats({
          totalTeams: teamSize,
          sprintsOnTrack: onTrack,
          sprintsAmber: amber,
          sprintsRed: red,
        });
      }
      setSprints(sprintList);
    } catch {
      setSprints([]);
    }
    setLoading(false);
  }, []);

  useEffect(() => { fetchData(); }, [fetchData, refreshKey]);

  if (loading) {
    return (
      <DashboardPanel title="Portfolio Health" icon={Briefcase}>
        <div className="flex items-center justify-center py-8">
          <Loader2 size={20} className="animate-spin text-[var(--color-brand-secondary)]" />
        </div>
      </DashboardPanel>
    );
  }

  if (sprints.length === 0) {
    return (
      <DashboardPanel title="Portfolio Health" icon={Briefcase}>
        <div className="flex flex-col items-center justify-center py-8 gap-2">
          <Briefcase size={24} className="text-[var(--text-tertiary)]" />
          <p className="text-sm text-[var(--text-secondary)]">No portfolio data available</p>
          <p className="text-xs text-[var(--text-tertiary)]">
            Sync project data to see portfolio health across teams.
          </p>
        </div>
      </DashboardPanel>
    );
  }

  return (
    <DashboardPanel title="Portfolio Health" icon={Briefcase}>
      {/* Summary stat cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 mb-6">
        <StatCard label="Total Teams" value={stats.totalTeams} />
        <StatCard label="On Track" value={stats.sprintsOnTrack} severity="GREEN" />
        <StatCard label="At Risk" value={stats.sprintsAmber} severity="AMBER" />
        <StatCard label="Critical" value={stats.sprintsRed} severity="RED" />
      </div>

      {/* Sprint health cards grid */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {sprints.map((sprint) => (
          <div
            key={sprint.id}
            className={cn(
              "rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] p-4",
              "transition-shadow duration-200 hover:shadow-md"
            )}
          >
            <div className="flex items-center justify-between mb-3">
              <div>
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">{sprint.teamName}</h3>
                <p className="text-xs text-[var(--text-secondary)]">{sprint.sprintName}</p>
              </div>
              <RagIndicator severity={sprint.health} size="sm" />
            </div>

            <div className="mb-3">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-[var(--text-secondary)]">Completion</span>
                <span className="text-xs font-semibold text-[var(--text-primary)] tabular-nums">{sprint.completionPct}%</span>
              </div>
              <Progress value={sprint.completionPct} severity={sprint.health} size="sm" />
            </div>

            <div className="flex items-center justify-between">
              {sprint.atRiskCount > 0 ? (
                <Badge variant={sprint.health === "RED" ? "rag-red" : sprint.health === "AMBER" ? "rag-amber" : "brand"}>
                  <AlertTriangle className="h-3 w-3 mr-1" />
                  {sprint.atRiskCount} at risk
                </Badge>
              ) : (
                <span className="text-xs text-[var(--text-secondary)]">No risks</span>
              )}
              <span className="text-xs text-[var(--text-secondary)] tabular-nums">{sprint.daysRemaining}d remaining</span>
            </div>
          </div>
        ))}
      </div>
    </DashboardPanel>
  );
}
