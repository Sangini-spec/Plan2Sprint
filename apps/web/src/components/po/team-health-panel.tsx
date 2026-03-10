"use client";

import { useState, useEffect, useCallback } from "react";
import {
  HeartPulse,
  AlertTriangle,
  Activity,
  Moon,
  Clock,
  Zap,
  Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Badge, Progress } from "@/components/ui";
import { useSelectedProject } from "@/lib/project/context";
import type { HealthSeverity, HealthSignalType } from "@/lib/types/models";
import { useAutoRefresh } from "@/lib/ws/context";
import { cachedFetch } from "@/lib/fetch-cache";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface HealthSignalData {
  id: string;
  type: string;
  severity: string;
  member: string;
  memberId: string;
  message: string;
  metadata: Record<string, unknown>;
  createdAt: string;
}

interface BacklogHealthData {
  overall: number;
  percentEstimated: number;
  percentWithAcceptanceCriteria: number;
  percentStale: number;
  percentWithUnresolvedDeps: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const severityDot: Record<HealthSeverity, string> = {
  GREEN: "bg-[var(--color-rag-green)]",
  AMBER: "bg-[var(--color-rag-amber)]",
  RED: "bg-[var(--color-rag-red)]",
};

const severityText: Record<HealthSeverity, string> = {
  GREEN: "text-[var(--color-rag-green)]",
  AMBER: "text-[var(--color-rag-amber)]",
  RED: "text-[var(--color-rag-red)]",
};

const signalTypeLabels: Record<HealthSignalType, string> = {
  BURNOUT_RISK: "Burnout Risk",
  VELOCITY_VARIANCE: "Velocity",
  STALLED_TICKET: "Stalled",
  REVIEW_LAG: "Review Lag",
  CI_FAILURE: "CI Failure",
  AFTER_HOURS: "After Hours",
  INACTIVITY: "Inactive",
  CAPACITY_OVERLOAD: "Overload",
};

const signalTypeIcons: Record<HealthSignalType, typeof Activity> = {
  BURNOUT_RISK: AlertTriangle,
  VELOCITY_VARIANCE: Activity,
  STALLED_TICKET: Clock,
  REVIEW_LAG: Clock,
  CI_FAILURE: Zap,
  AFTER_HOURS: Moon,
  INACTIVITY: Clock,
  CAPACITY_OVERLOAD: AlertTriangle,
};

function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const hours = Math.floor(diff / (1000 * 60 * 60));
  if (hours < 1) return "just now";
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function mapSeverity(raw: string): HealthSeverity {
  const upper = raw.toUpperCase();
  if (upper === "HIGH" || upper === "RED" || upper === "CRITICAL") return "RED";
  if (upper === "MEDIUM" || upper === "AMBER" || upper === "WARNING") return "AMBER";
  return "GREEN";
}

function mapSignalType(raw: string): HealthSignalType {
  const map: Record<string, HealthSignalType> = {
    high_workload: "CAPACITY_OVERLOAD",
    capacity_overload: "CAPACITY_OVERLOAD",
    burnout_risk: "BURNOUT_RISK",
    velocity_variance: "VELOCITY_VARIANCE",
    stalled_ticket: "STALLED_TICKET",
    review_lag: "REVIEW_LAG",
    ci_failure: "CI_FAILURE",
    after_hours: "AFTER_HOURS",
    inactivity: "INACTIVITY",
  };
  return map[raw.toLowerCase()] ?? "VELOCITY_VARIANCE";
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface HealthBarProps {
  label: string;
  value: number;
  invertColor?: boolean;
}

function HealthBar({ label, value, invertColor = false }: HealthBarProps) {
  let severity: HealthSeverity = "GREEN";
  if (invertColor) {
    if (value > 20) severity = "RED";
    else if (value > 10) severity = "AMBER";
  } else {
    if (value < 50) severity = "RED";
    else if (value < 75) severity = "AMBER";
  }

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-xs text-[var(--text-secondary)]">{label}</span>
        <span
          className={cn(
            "text-xs font-semibold tabular-nums",
            severityText[severity]
          )}
        >
          {value}%
        </span>
      </div>
      <Progress value={value} severity={severity} size="sm" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TeamHealthPanel() {
  const { selectedProject } = useSelectedProject();
  const [signals, setSignals] = useState<HealthSignalData[]>([]);
  const [backlogHealth, setBacklogHealth] = useState<BacklogHealthData | null>(null);
  const [loading, setLoading] = useState(true);
  const refreshKey = useAutoRefresh(["sync_complete", "health_evaluated", "github_activity"]);

  const projectId = selectedProject?.internalId;

  const fetchData = useCallback(async () => {
    setLoading(true);
    const q = projectId ? `?projectId=${projectId}` : "";
    try {
      const [healthRes, analyticsRes] = await Promise.all([
        cachedFetch<{ signals?: HealthSignalData[] }>("/api/team-health"),
        cachedFetch<{ backlogHealth?: BacklogHealthData }>(`/api/analytics${q}`),
      ]);

      if (healthRes.ok) {
        setSignals(healthRes.data?.signals ?? []);
      } else {
        setSignals([]);
      }

      if (analyticsRes.ok && analyticsRes.data?.backlogHealth) {
        setBacklogHealth(analyticsRes.data.backlogHealth);
      }
    } catch {
      setSignals([]);
    }
    setLoading(false);
  }, [projectId]);

  useEffect(() => { fetchData(); }, [fetchData, refreshKey]);

  if (loading) {
    return (
      <DashboardPanel title="Team Health" icon={HeartPulse}>
        <div className="flex items-center justify-center py-8">
          <Loader2 size={20} className="animate-spin text-[var(--color-brand-secondary)]" />
        </div>
      </DashboardPanel>
    );
  }

  const overall = backlogHealth?.overall ?? 0;
  const scoreColor: HealthSeverity =
    overall >= 75 ? "GREEN" : overall >= 50 ? "AMBER" : "RED";

  // Categorize signals
  const burnoutSignals = signals.filter((s) =>
    s.type.toLowerCase().includes("burnout") || s.type.toLowerCase().includes("high_workload")
  );
  const otherSignals = signals.filter((s) =>
    !s.type.toLowerCase().includes("burnout") && !s.type.toLowerCase().includes("high_workload")
  );

  return (
    <DashboardPanel
      title="Team Health"
      icon={HeartPulse}
      collapsible
      actions={
        backlogHealth ? (
          <span
            className={cn(
              "text-sm font-bold tabular-nums",
              severityText[scoreColor]
            )}
          >
            {overall}/100
          </span>
        ) : (
          <span className="text-xs text-[var(--text-tertiary)]">No data</span>
        )
      }
    >
      <div className="space-y-6">
        {/* Backlog Health Score */}
        {backlogHealth && (
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] mb-3">
              Backlog Health
            </h3>
            <div className="space-y-3">
              <HealthBar label="Estimated" value={backlogHealth.percentEstimated} />
              <HealthBar label="Acceptance Criteria" value={backlogHealth.percentWithAcceptanceCriteria} />
              <HealthBar label="Stale Items" value={backlogHealth.percentStale} invertColor />
              <HealthBar label="Unresolved Dependencies" value={backlogHealth.percentWithUnresolvedDeps} invertColor />
            </div>
          </div>
        )}

        {/* Active Health Signals */}
        {otherSignals.length > 0 && (
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] mb-3">
              Active Health Signals
            </h3>
            <div className="space-y-2">
              {otherSignals.map((signal) => {
                const severity = mapSeverity(signal.severity);
                const signalType = mapSignalType(signal.type);
                const SignalIcon = signalTypeIcons[signalType] ?? Activity;

                return (
                  <div
                    key={signal.id}
                    className="flex items-start gap-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/40 p-3"
                  >
                    <span
                      className={cn(
                        "mt-1 h-2 w-2 rounded-full shrink-0",
                        severityDot[severity],
                        severity === "RED" && "animate-pulse"
                      )}
                    />
                    <div className="flex-1 min-w-0 space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge
                          variant={
                            severity === "RED" ? "rag-red" : severity === "AMBER" ? "rag-amber" : "rag-green"
                          }
                          className="text-[10px] gap-1"
                        >
                          <SignalIcon className="h-3 w-3" />
                          {signalTypeLabels[signalType] ?? signal.type}
                        </Badge>
                        {signal.member && (
                          <span className="text-xs font-medium text-[var(--text-primary)]">
                            {signal.member}
                          </span>
                        )}
                        <span className="text-[11px] text-[var(--text-secondary)] ml-auto shrink-0">
                          {formatRelativeTime(signal.createdAt)}
                        </span>
                      </div>
                      <p className="text-sm text-[var(--text-secondary)] leading-snug">
                        {signal.message}
                      </p>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Burnout Alerts */}
        {burnoutSignals.length > 0 && (
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-rag-amber)] mb-3 flex items-center gap-1.5">
              <AlertTriangle className="h-3.5 w-3.5" />
              Burnout / Workload Alerts
            </h3>
            <div className="space-y-2">
              {burnoutSignals.map((alert) => {
                const severity = mapSeverity(alert.severity);
                const borderColor =
                  severity === "RED"
                    ? "border-[var(--color-rag-red)]/30 bg-[var(--color-rag-red)]/5"
                    : "border-[var(--color-rag-amber)]/30 bg-[var(--color-rag-amber)]/5";

                return (
                  <div
                    key={alert.id}
                    className={cn("rounded-lg border p-3 space-y-1", borderColor)}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium text-[var(--text-primary)]">
                        {alert.member || "Unknown"}
                      </span>
                      <Badge variant={severity === "RED" ? "rag-red" : "rag-amber"} className="text-[10px]">
                        {severity}
                      </Badge>
                    </div>
                    <p className="text-xs text-[var(--text-secondary)]">{alert.message}</p>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Empty state when no data at all */}
        {signals.length === 0 && !backlogHealth && (
          <div className="flex flex-col items-center justify-center py-6 gap-2">
            <HeartPulse size={24} className="text-[var(--text-tertiary)]" />
            <p className="text-sm text-[var(--text-secondary)]">No health data available</p>
            <p className="text-xs text-[var(--text-tertiary)]">
              Health signals will appear after syncing project data.
            </p>
          </div>
        )}
      </div>
    </DashboardPanel>
  );
}
