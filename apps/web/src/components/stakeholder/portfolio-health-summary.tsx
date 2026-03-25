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
import { useSelectedProject } from "@/lib/project/context";

interface SprintSummary {
  id: string;
  teamName: string;
  sprintName: string;
  health: HealthSeverity;
  completionPct: number;
  atRiskCount: number;
  daysRemaining: number;
  totalItems: number;
  completedItems: number;
  totalStoryPoints: number;
  completedStoryPoints: number;
  plannedPct: number;
  progressDelta: number;
  source: string;
}

interface PortfolioStats {
  totalTeams: number;
  sprintsOnTrack: number;
  sprintsAmber: number;
  sprintsRed: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function computePlannedPct(startDate: string | null, endDate: string | null): number {
  if (!startDate || !endDate) return 0;
  const start = new Date(startDate).getTime();
  const end = new Date(endDate).getTime();
  const now = Date.now();
  if (now <= start) return 0;
  if (now >= end) return 100;
  return Math.round(((now - start) / (end - start)) * 100);
}

function deltaToSeverity(delta: number): HealthSeverity {
  if (delta >= 0) return "GREEN";
  if (delta >= -15) return "AMBER";
  return "RED";
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function PortfolioHealthSummary() {
  const [sprints, setSprints] = useState<SprintSummary[]>([]);
  const [stats, setStats] = useState<PortfolioStats>({ totalTeams: 0, sprintsOnTrack: 0, sprintsAmber: 0, sprintsRed: 0 });
  const [blockerCount, setBlockerCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const refreshKey = useAutoRefresh(["sync_complete"]);
  const { selectedProject } = useSelectedProject();
  const projectId = selectedProject?.internalId;

  const fetchData = useCallback(async () => {
    setLoading(true);
    const q = projectId ? `?projectId=${projectId}` : "";
    try {
      const [summaryRes, sprintsRes, healthRes, standupsRes] = await Promise.all([
        cachedFetch(`/api/dashboard/summary${q}`),
        cachedFetch(`/api/dashboard/sprints${q}`),
        cachedFetch(`/api/team-health${q}`),
        cachedFetch(`/api/standups${q}`),
      ]);

      let teamSize = 0;
      if (summaryRes.ok) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const data = summaryRes.data as any;
        teamSize = data.teamSize ?? 0;
      }

      // Extract blocker count from standups
      if (standupsRes.ok) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const data = standupsRes.data as any;
        const standups = data.standups ?? data.entries ?? [];
        let blockers = 0;
        for (const s of standups) {
          const blockerList = s.blockers ?? s.blockerItems ?? [];
          if (Array.isArray(blockerList)) {
            blockers += blockerList.length;
          } else if (typeof blockerList === "string" && blockerList.trim()) {
            blockers += 1;
          }
        }
        setBlockerCount(blockers);
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
          const totalItems = s.totalItems ?? 0;
          const completedItems = s.completedItems ?? 0;
          const totalSP = s.totalStoryPoints ?? 0;
          const completedSP = s.completedStoryPoints ?? 0;
          const plannedPct = computePlannedPct(s.startDate ?? null, s.endDate ?? null);
          const progressDelta = pct - plannedPct;
          const health = deltaToSeverity(progressDelta);

          if (health === "GREEN") onTrack++;
          else if (health === "AMBER") amber++;
          else red++;

          sprintList.push({
            id: s.id,
            teamName: s.teamName ?? s.sourceTool ?? "Team",
            sprintName: s.name,
            health,
            completionPct: pct,
            atRiskCount: health === "RED" ? totalItems - completedItems : 0,
            daysRemaining: daysLeft,
            totalItems,
            completedItems,
            totalStoryPoints: totalSP,
            completedStoryPoints: completedSP,
            plannedPct,
            progressDelta,
            source: (s.sourceTool ?? "").toUpperCase(),
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
  }, [projectId]);

  useEffect(() => { fetchData(); }, [fetchData, refreshKey]);

  if (loading) {
    return (
      <DashboardPanel title="Project Overview" icon={Briefcase}>
        <div className="flex items-center justify-center py-8">
          <Loader2 size={20} className="animate-spin text-[var(--color-brand-secondary)]" />
        </div>
      </DashboardPanel>
    );
  }

  if (sprints.length === 0) {
    return (
      <DashboardPanel title="Project Overview" icon={Briefcase}>
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
            {/* Header: team name + source badge + RAG */}
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2 min-w-0">
                <div className="min-w-0">
                  <h3 className="text-sm font-semibold text-[var(--text-primary)] truncate">{sprint.teamName}</h3>
                  <p className="text-xs text-[var(--text-secondary)]">{sprint.sprintName}</p>
                </div>
                {sprint.source && (
                  <Badge variant="brand" className="text-[10px] shrink-0">
                    {sprint.source}
                  </Badge>
                )}
              </div>
              <RagIndicator severity={sprint.health} size="sm" />
            </div>

            {/* Dual progress: Actual vs Expected */}
            <div className="mb-3 space-y-2">
              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs text-[var(--text-secondary)]">Actual</span>
                  <span className="text-xs font-semibold text-[var(--text-primary)] tabular-nums">{sprint.completionPct}%</span>
                </div>
                <div title={`Actual completion: ${sprint.completionPct}%`}>
                  <Progress
                    value={sprint.completionPct}
                    severity={sprint.health}
                    size="sm"
                  />
                </div>
              </div>
              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs text-[var(--text-secondary)]">Expected</span>
                  <span className="text-xs font-semibold text-[var(--text-primary)] tabular-nums">{sprint.plannedPct}%</span>
                </div>
                <div title={`Expected progress: ${sprint.plannedPct}%`}>
                  <Progress
                    value={sprint.plannedPct}
                    severity="GREEN"
                    size="sm"
                  />
                </div>
              </div>
            </div>

            {/* Delta badge + SP info + blockers */}
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div className="flex items-center gap-2">
                {/* Delta badge */}
                <Badge
                  variant={sprint.progressDelta >= 0 ? "rag-green" : sprint.progressDelta >= -15 ? "rag-amber" : "rag-red"}
                  title={`Progress delta: ${sprint.progressDelta >= 0 ? "+" : ""}${sprint.progressDelta}%`}
                >
                  {sprint.progressDelta >= 0 ? `+${sprint.progressDelta}% ahead` : `${sprint.progressDelta}% behind`}
                </Badge>

                {/* Blocker badge (only if atRiskCount > 0) */}
                {sprint.atRiskCount > 0 && (
                  <Badge
                    variant="rag-red"
                    title={`${sprint.atRiskCount} items at risk`}
                  >
                    <AlertTriangle className="h-3 w-3 mr-1" />
                    {sprint.atRiskCount}
                  </Badge>
                )}
              </div>

              <div className="flex items-center gap-3">
                {/* SP info */}
                {sprint.totalStoryPoints > 0 && (
                  <span className="text-xs text-[var(--text-secondary)] tabular-nums">
                    {sprint.completedStoryPoints}/{sprint.totalStoryPoints} SP
                  </span>
                )}
                <span className="text-xs text-[var(--text-secondary)] tabular-nums">{sprint.daysRemaining}d remaining</span>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Global blocker count */}
      {blockerCount > 0 && (
        <div className="mt-4 flex items-center gap-2 rounded-lg border border-[var(--color-rag-red)]/30 bg-[var(--color-rag-red)]/5 px-4 py-2">
          <AlertTriangle className="h-4 w-4 text-[var(--color-rag-red)]" />
          <span className="text-sm text-[var(--text-primary)]">
            <strong>{blockerCount}</strong> active blocker{blockerCount !== 1 ? "s" : ""} across teams
          </span>
        </div>
      )}
    </DashboardPanel>
  );
}
