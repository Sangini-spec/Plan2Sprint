"use client";

import { useState, useEffect, useCallback } from "react";
import {
  TrendingUp,
  AlertTriangle,
  RefreshCw,
  Loader2,
  ShieldAlert,
  Clock,
  User,
  XCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Badge, Button, Progress } from "@/components/ui";
import { useSelectedProject } from "@/lib/project/context";
import { useAutoRefresh } from "@/lib/ws/context";
import { cachedFetch } from "@/lib/fetch-cache";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SpilloverItem {
  workItemId: string;
  externalId: string;
  title: string;
  status: string;
  storyPoints: number;
  assigneeId: string | null;
  assigneeName: string | null;
  spilloverRisk: "low" | "medium" | "high" | "critical";
  spilloverReason: string;
}

interface ForecastData {
  successProbability: number | null;
  pacingScore: number;
  totalSP: number;
  doneSP: number;
  activeBlockers: number;
  stalledPRs: number;
  completionPct: number;
  elapsedPct: number;
  spilloverItems: SpilloverItem[];
  totalSpilloverSP: number;
  forecastUpdatedAt: string | null;
  rebalancingRecommended: boolean;
  rebalancingReasons: string[];
}

interface SprintForecastPanelProps {
  onRebalance?: () => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function timeAgo(iso: string | null): string {
  if (!iso) return "Never";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins} min${mins > 1 ? "s" : ""} ago`;
  const hours = Math.floor(mins / 60);
  return `${hours} hour${hours > 1 ? "s" : ""} ago`;
}

const riskBadge: Record<string, { label: string; variant: "rag-red" | "rag-amber" | "brand" }> = {
  critical: { label: "Critical", variant: "rag-red" },
  high: { label: "High", variant: "rag-red" },
  medium: { label: "Medium", variant: "rag-amber" },
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function SprintForecastPanel({ onRebalance }: SprintForecastPanelProps) {
  const { selectedProject } = useSelectedProject();
  const [data, setData] = useState<ForecastData | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const refreshKey = useAutoRefresh([
    "sync_complete",
    "sprint_plan_generated",
    "sprint_plan_updated",
  ]);

  const projectId = selectedProject?.internalId;

  const fetchForecast = useCallback(async () => {
    if (!projectId) return;
    try {
      const params = `?projectId=${projectId}`;
      const res = await cachedFetch<ForecastData>(`/api/sprints/forecast${params}`);
      if (res.ok && res.data) {
        setData(res.data);
      }
    } catch {
      // API unavailable
    }
  }, [projectId]);

  useEffect(() => {
    setLoading(true);
    fetchForecast().finally(() => setLoading(false));
  }, [fetchForecast, refreshKey]);

  const handleRefresh = async () => {
    if (!selectedProject) return;
    setRefreshing(true);
    try {
      const res = await fetch("/api/sprints/forecast/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ projectId: selectedProject.internalId }),
      });
      if (res.ok) {
        setData(await res.json());
      }
    } catch {
      // swallow
    }
    setRefreshing(false);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-5 w-5 animate-spin text-[var(--text-secondary)]" />
      </div>
    );
  }

  if (!data || data.successProbability === null) {
    return (
      <div className="flex flex-col items-center justify-center py-12 gap-2">
        <TrendingUp size={24} className="text-[var(--text-tertiary)]" />
        <p className="text-sm text-[var(--text-secondary)]">
          No forecast data available
        </p>
        <p className="text-xs text-[var(--text-tertiary)]">
          Generate a sprint plan first, then forecast data will appear here.
        </p>
      </div>
    );
  }

  const prob = data.successProbability;
  const probSeverity =
    prob >= 75 ? "GREEN" : prob >= 50 ? "AMBER" : "RED";
  const probLabel =
    prob >= 75 ? "On Track" : prob >= 50 ? "At Risk" : "Critical";

  const spilloverItems = data.spilloverItems || [];
  const criticalCount = spilloverItems.filter(
    (i) => i.spilloverRisk === "critical"
  ).length;
  const highCount = spilloverItems.filter(
    (i) => i.spilloverRisk === "high"
  ).length;

  return (
    <div className="space-y-6">
      {/* ── Card 1: Success Probability ── */}
      <DashboardPanel
        title="Sprint Success Probability"
        icon={TrendingUp}
        actions={
          <div className="flex items-center gap-2">
            <span className="text-xs text-[var(--text-tertiary)]">
              Updated {timeAgo(data.forecastUpdatedAt)}
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleRefresh}
              disabled={refreshing}
              className="h-7 w-7 p-0"
            >
              <RefreshCw
                className={cn(
                  "h-3.5 w-3.5",
                  refreshing && "animate-spin"
                )}
              />
            </Button>
          </div>
        }
      >
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-[var(--text-secondary)]">
              Sprint Success Probability
            </span>
            <div className="flex items-center gap-2">
              <span className="text-2xl font-bold tabular-nums text-[var(--text-primary)]">
                {prob}%
              </span>
              <Badge
                variant={
                  probSeverity === "GREEN"
                    ? "rag-green"
                    : probSeverity === "AMBER"
                      ? "rag-amber"
                      : "rag-red"
                }
              >
                {probLabel}
              </Badge>
            </div>
          </div>

          <Progress
            value={prob}
            severity={probSeverity as "GREEN" | "AMBER" | "RED"}
            size="md"
          />

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/40 p-3 text-center">
              <p className="text-xs text-[var(--text-secondary)] mb-1">
                Spillover Risk
              </p>
              <p className="text-lg font-bold tabular-nums text-[var(--text-primary)]">
                {data.totalSpilloverSP} SP
              </p>
            </div>
            <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/40 p-3 text-center">
              <p className="text-xs text-[var(--text-secondary)] mb-1">
                Active Blockers
              </p>
              <p className="text-lg font-bold tabular-nums text-[var(--text-primary)]">
                {data.activeBlockers}
              </p>
            </div>
            <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/40 p-3 text-center">
              <p className="text-xs text-[var(--text-secondary)] mb-1">
                Stalled PRs
              </p>
              <p className="text-lg font-bold tabular-nums text-[var(--text-primary)]">
                {data.stalledPRs}
              </p>
            </div>
            <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/40 p-3 text-center">
              <p className="text-xs text-[var(--text-secondary)] mb-1">
                Completion
              </p>
              <p className="text-lg font-bold tabular-nums text-[var(--text-primary)]">
                {data.completionPct}%
              </p>
            </div>
          </div>
        </div>
      </DashboardPanel>

      {/* ── Card 2: Per-Ticket Spillover Prediction ── */}
      {spilloverItems.length > 0 && (
        <DashboardPanel
          title="Spillover Prediction"
          icon={AlertTriangle}
          actions={
            <div className="flex items-center gap-2">
              {criticalCount > 0 && (
                <Badge variant="rag-red">{criticalCount} Critical</Badge>
              )}
              {highCount > 0 && (
                <Badge variant="rag-red">{highCount} High</Badge>
              )}
            </div>
          }
        >
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border-subtle)]">
                  <th className="text-left py-2 px-3 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
                    Ticket
                  </th>
                  <th className="text-left py-2 px-3 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
                    Assignee
                  </th>
                  <th className="text-left py-2 px-3 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
                    Risk
                  </th>
                  <th className="text-left py-2 px-3 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
                    Reason
                  </th>
                </tr>
              </thead>
              <tbody>
                {spilloverItems.map((item) => {
                  const badge = riskBadge[item.spilloverRisk];
                  return (
                    <tr
                      key={item.workItemId}
                      className="border-b border-[var(--border-subtle)] last:border-b-0"
                    >
                      <td className="py-2.5 px-3">
                        <div className="flex flex-col">
                          <span className="font-mono text-xs text-[var(--color-brand-secondary)]">
                            {item.externalId}
                          </span>
                          <span className="text-xs text-[var(--text-secondary)] truncate max-w-[200px]">
                            {item.title}
                          </span>
                        </div>
                      </td>
                      <td className="py-2.5 px-3">
                        <span className="flex items-center gap-1.5 text-xs text-[var(--text-primary)]">
                          <User className="h-3 w-3 text-[var(--text-tertiary)]" />
                          {item.assigneeName ?? "Unassigned"}
                        </span>
                      </td>
                      <td className="py-2.5 px-3">
                        {badge && (
                          <Badge variant={badge.variant} className="text-[10px]">
                            {badge.label}
                          </Badge>
                        )}
                      </td>
                      <td className="py-2.5 px-3">
                        <span className="text-xs text-[var(--text-secondary)]">
                          {item.spilloverReason}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </DashboardPanel>
      )}

      {/* ── Card 3: Rebalancing Recommendation (conditional) ── */}
      {data.rebalancingRecommended && (
        <DashboardPanel
          title="Rebalancing Recommended"
          icon={ShieldAlert}
          collapsible
        >
          <div className="space-y-4">
            <div className="rounded-lg border border-[var(--color-rag-amber)]/30 bg-[var(--color-rag-amber)]/5 p-4">
              <div className="flex items-start gap-3">
                <AlertTriangle className="h-5 w-5 shrink-0 text-[var(--color-rag-amber)] mt-0.5" />
                <div className="space-y-2">
                  <p className="text-sm font-medium text-[var(--text-primary)]">
                    AI has identified {spilloverItems.length} ticket
                    {spilloverItems.length !== 1 ? "s" : ""} at spillover risk.
                  </p>
                  <ul className="space-y-1">
                    {data.rebalancingReasons.map((reason, idx) => (
                      <li
                        key={idx}
                        className="text-xs text-[var(--text-secondary)] flex items-center gap-1.5"
                      >
                        <span className="h-1 w-1 rounded-full bg-[var(--color-rag-amber)] shrink-0" />
                        {reason}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <Button
                variant="primary"
                size="sm"
                className="flex-1"
                onClick={onRebalance}
              >
                <RefreshCw className="h-3.5 w-3.5" />
                View Rebalancing Plan
              </Button>
              <Button variant="ghost" size="sm" className="flex-1">
                <XCircle className="h-3.5 w-3.5" />
                Dismiss for this sprint
              </Button>
            </div>
          </div>
        </DashboardPanel>
      )}
    </div>
  );
}
