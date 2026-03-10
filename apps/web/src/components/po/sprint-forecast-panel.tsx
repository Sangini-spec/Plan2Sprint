"use client";

import { useState, useEffect, useCallback } from "react";
import {
  TrendingUp,
  AlertTriangle,
  RefreshCw,
  Loader2,
  ShieldAlert,
  User,
  XCircle,
  CheckCircle2,
  Clock,
  GitPullRequest,
  ArrowRight,
  Activity,
  Target,
  Zap,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
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
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  return `${hours}h ago`;
}

type Severity = "GREEN" | "AMBER" | "RED";

function getSeverity(prob: number): Severity {
  return prob >= 75 ? "GREEN" : prob >= 50 ? "AMBER" : "RED";
}

function getVerdict(prob: number): string {
  if (prob >= 80) return "On Track";
  if (prob >= 60) return "At Risk";
  if (prob >= 40) return "Likely to Slip";
  return "Will Fail";
}

function getVerdictIcon(prob: number) {
  if (prob >= 80) return CheckCircle2;
  if (prob >= 60) return Clock;
  if (prob >= 40) return AlertTriangle;
  return XCircle;
}

const severityColor: Record<Severity, string> = {
  GREEN: "var(--color-rag-green)",
  AMBER: "var(--color-rag-amber)",
  RED: "var(--color-rag-red)",
};

const severityBg: Record<Severity, string> = {
  GREEN: "bg-[var(--color-rag-green)]",
  AMBER: "bg-[var(--color-rag-amber)]",
  RED: "bg-[var(--color-rag-red)]",
};

const severityBgLight: Record<Severity, string> = {
  GREEN: "bg-[var(--color-rag-green)]/10",
  AMBER: "bg-[var(--color-rag-amber)]/10",
  RED: "bg-[var(--color-rag-red)]/10",
};

const severityText: Record<Severity, string> = {
  GREEN: "text-[var(--color-rag-green)]",
  AMBER: "text-[var(--color-rag-amber)]",
  RED: "text-[var(--color-rag-red)]",
};

const severityBorder: Record<Severity, string> = {
  GREEN: "border-[var(--color-rag-green)]/30",
  AMBER: "border-[var(--color-rag-amber)]/30",
  RED: "border-[var(--color-rag-red)]/30",
};

const riskOrder: Record<string, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

const riskSeverity: Record<string, Severity> = {
  critical: "RED",
  high: "RED",
  medium: "AMBER",
  low: "GREEN",
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Radial gauge SVG for the main probability score */
function RadialGauge({
  value,
  severity,
  size = 160,
}: {
  value: number;
  severity: Severity;
  size?: number;
}) {
  const strokeWidth = 10;
  const radius = (size - strokeWidth) / 2;
  const circumference = Math.PI * radius; // semi-circle
  const offset = circumference - (value / 100) * circumference;

  return (
    <div className="relative" style={{ width: size, height: size / 2 + 24 }}>
      <svg
        width={size}
        height={size / 2 + strokeWidth}
        viewBox={`0 0 ${size} ${size / 2 + strokeWidth}`}
        className="overflow-visible"
      >
        {/* Track */}
        <path
          d={`M ${strokeWidth / 2} ${size / 2} A ${radius} ${radius} 0 0 1 ${size - strokeWidth / 2} ${size / 2}`}
          fill="none"
          stroke="var(--bg-surface-raised)"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
        />
        {/* Value arc */}
        <motion.path
          d={`M ${strokeWidth / 2} ${size / 2} A ${radius} ${radius} 0 0 1 ${size - strokeWidth / 2} ${size / 2}`}
          fill="none"
          stroke={severityColor[severity]}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: offset }}
          transition={{ duration: 1.2, ease: "easeOut" }}
        />
      </svg>
      {/* Center label */}
      <div className="absolute inset-x-0 bottom-0 flex flex-col items-center">
        <motion.span
          className="text-3xl font-bold tabular-nums text-[var(--text-primary)]"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.6 }}
        >
          {value}%
        </motion.span>
      </div>
    </div>
  );
}

/** Compact signal bar for a single metric */
function SignalMetric({
  icon: Icon,
  label,
  value,
  severity,
  subtext,
}: {
  icon: React.ComponentType<{ className?: string; size?: number }>;
  label: string;
  value: string | number;
  severity: Severity;
  subtext?: string;
}) {
  return (
    <div className="flex items-center gap-3 min-w-0">
      <div
        className={cn(
          "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
          severityBgLight[severity]
        )}
      >
        <Icon size={16} className={severityText[severity]} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-[var(--text-secondary)] truncate">
            {label}
          </span>
          <span
            className={cn(
              "text-sm font-bold tabular-nums shrink-0",
              severityText[severity]
            )}
          >
            {value}
          </span>
        </div>
        {subtext && (
          <span className="text-[10px] text-[var(--text-tertiary)] truncate block">
            {subtext}
          </span>
        )}
      </div>
    </div>
  );
}

/** Visual risk bar for a spillover item */
function RiskBar({ risk }: { risk: string }) {
  const sev = riskSeverity[risk] ?? "GREEN";
  const widthPct =
    risk === "critical" ? 100 : risk === "high" ? 75 : risk === "medium" ? 50 : 25;
  return (
    <div className="flex items-center gap-2 min-w-[80px]">
      <div className="flex-1 h-1.5 rounded-full bg-[var(--bg-surface-raised)] overflow-hidden">
        <motion.div
          className={cn("h-full rounded-full", severityBg[sev])}
          initial={{ width: 0 }}
          animate={{ width: `${widthPct}%` }}
          transition={{ duration: 0.6, ease: "easeOut" }}
        />
      </div>
      <span
        className={cn("text-[10px] font-semibold uppercase", severityText[sev])}
      >
        {risk}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
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
    "sprint_completed",
    "github_activity",
  ]);

  const projectId = selectedProject?.internalId;

  const fetchForecast = useCallback(async () => {
    if (!projectId) return;
    try {
      const params = `?projectId=${projectId}`;
      const res = await cachedFetch<ForecastData>(
        `/api/sprints/forecast${params}`
      );
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

  // Loading
  if (loading) {
    return (
      <DashboardPanel title="Sprint Forecast" icon={Activity}>
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-5 w-5 animate-spin text-[var(--text-secondary)]" />
        </div>
      </DashboardPanel>
    );
  }

  // Empty state
  if (!data || data.successProbability === null) {
    return (
      <DashboardPanel title="Sprint Forecast" icon={Activity}>
        <div className="flex flex-col items-center justify-center py-16 gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-[var(--bg-surface-raised)]">
            <Activity size={22} className="text-[var(--text-tertiary)]" />
          </div>
          <p className="text-sm font-medium text-[var(--text-secondary)]">
            No forecast available
          </p>
          <p className="text-xs text-[var(--text-tertiary)] text-center max-w-xs">
            Generate a sprint plan first to see AI-powered predictions.
          </p>
        </div>
      </DashboardPanel>
    );
  }

  const prob = data.successProbability;
  const severity = getSeverity(prob);
  const verdict = getVerdict(prob);
  const VerdictIcon = getVerdictIcon(prob);

  const spilloverItems = (data.spilloverItems || []).sort(
    (a, b) => (riskOrder[a.spilloverRisk] ?? 4) - (riskOrder[b.spilloverRisk] ?? 4)
  );
  const criticalOrHigh = spilloverItems.filter(
    (i) => i.spilloverRisk === "critical" || i.spilloverRisk === "high"
  ).length;

  // Pacing analysis
  const pacingDelta = data.completionPct - data.elapsedPct;
  const pacingSeverity: Severity =
    pacingDelta >= 0 ? "GREEN" : pacingDelta >= -15 ? "AMBER" : "RED";

  return (
    <div className="space-y-4">
      {/* ─── Primary Forecast Card ─── */}
      <DashboardPanel
        title="Sprint Forecast"
        icon={Activity}
        actions={
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-[var(--text-tertiary)]">
              {timeAgo(data.forecastUpdatedAt)}
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleRefresh}
              disabled={refreshing}
              className="h-7 w-7 p-0"
            >
              <RefreshCw
                className={cn("h-3.5 w-3.5", refreshing && "animate-spin")}
              />
            </Button>
          </div>
        }
      >
        <div className="space-y-5">
          {/* Top section: Gauge + Verdict + Signal metrics */}
          <div className="flex flex-col sm:flex-row items-center gap-6">
            {/* Radial gauge */}
            <div className="flex flex-col items-center shrink-0">
              <RadialGauge value={prob} severity={severity} size={150} />
              <motion.div
                className="flex items-center gap-1.5 mt-1"
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.8 }}
              >
                <VerdictIcon size={14} className={severityText[severity]} />
                <span
                  className={cn(
                    "text-sm font-bold uppercase tracking-wide",
                    severityText[severity]
                  )}
                >
                  {verdict}
                </span>
              </motion.div>
            </div>

            {/* Signal metrics grid */}
            <div className="flex-1 w-full grid grid-cols-1 gap-3">
              <SignalMetric
                icon={Target}
                label="Completion"
                value={`${data.completionPct}%`}
                severity={getSeverity(data.completionPct)}
                subtext={`${data.doneSP} / ${data.totalSP} SP done`}
              />
              <SignalMetric
                icon={Zap}
                label="Pacing"
                value={`${pacingDelta >= 0 ? "+" : ""}${pacingDelta.toFixed(0)}%`}
                severity={pacingSeverity}
                subtext={`${data.elapsedPct}% sprint elapsed`}
              />
              <SignalMetric
                icon={AlertTriangle}
                label="Blockers"
                value={data.activeBlockers}
                severity={
                  data.activeBlockers === 0
                    ? "GREEN"
                    : data.activeBlockers <= 2
                      ? "AMBER"
                      : "RED"
                }
              />
              <SignalMetric
                icon={GitPullRequest}
                label="Stalled PRs"
                value={data.stalledPRs}
                severity={
                  data.stalledPRs === 0
                    ? "GREEN"
                    : data.stalledPRs <= 2
                      ? "AMBER"
                      : "RED"
                }
              />
            </div>
          </div>

          {/* Spillover risk summary strip */}
          {data.totalSpilloverSP > 0 && (
            <div
              className={cn(
                "flex items-center justify-between rounded-lg border px-4 py-2.5",
                severityBorder[
                  criticalOrHigh > 0 ? "RED" : "AMBER"
                ],
                severityBgLight[
                  criticalOrHigh > 0 ? "RED" : "AMBER"
                ]
              )}
            >
              <div className="flex items-center gap-2">
                <AlertTriangle
                  size={14}
                  className={
                    severityText[criticalOrHigh > 0 ? "RED" : "AMBER"]
                  }
                />
                <span className="text-xs font-medium text-[var(--text-primary)]">
                  {data.totalSpilloverSP} SP at spillover risk
                </span>
              </div>
              <div className="flex items-center gap-3">
                {criticalOrHigh > 0 && (
                  <Badge variant="rag-red" className="text-[10px]">
                    {criticalOrHigh} critical/high
                  </Badge>
                )}
                <span className="text-[10px] text-[var(--text-tertiary)]">
                  {spilloverItems.length} item{spilloverItems.length !== 1 ? "s" : ""}
                </span>
              </div>
            </div>
          )}
        </div>
      </DashboardPanel>

      {/* ─── Spillover Detail Table ─── */}
      <AnimatePresence>
        {spilloverItems.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            transition={{ duration: 0.3 }}
          >
            <DashboardPanel
              title="Spillover Risk Items"
              icon={AlertTriangle}
              collapsible
              actions={
                <span className="text-xs tabular-nums text-[var(--text-tertiary)]">
                  {spilloverItems.length} item{spilloverItems.length !== 1 ? "s" : ""}
                </span>
              }
            >
              <div className="space-y-2">
                {spilloverItems.map((item) => (
                  <div
                    key={item.workItemId}
                    className="flex items-center gap-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/40 px-3 py-2.5"
                  >
                    {/* Ticket info */}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs text-[var(--color-brand-secondary)] shrink-0">
                          {item.externalId}
                        </span>
                        <span className="text-xs text-[var(--text-primary)] truncate">
                          {item.title}
                        </span>
                      </div>
                      <div className="flex items-center gap-3 mt-1">
                        <span className="flex items-center gap-1 text-[10px] text-[var(--text-tertiary)]">
                          <User size={10} />
                          {item.assigneeName ?? "Unassigned"}
                        </span>
                        <span className="text-[10px] text-[var(--text-tertiary)]">
                          {item.storyPoints} SP
                        </span>
                      </div>
                    </div>
                    {/* Risk bar */}
                    <div className="shrink-0 w-[110px]">
                      <RiskBar risk={item.spilloverRisk} />
                    </div>
                  </div>
                ))}
              </div>
            </DashboardPanel>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ─── Rebalancing Recommendation ─── */}
      <AnimatePresence>
        {data.rebalancingRecommended && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            transition={{ duration: 0.3, delay: 0.1 }}
          >
            <DashboardPanel
              title="Rebalancing Recommended"
              icon={ShieldAlert}
              collapsible
            >
              <div className="space-y-4">
                {/* Reason chips */}
                <div className="flex flex-wrap gap-2">
                  {data.rebalancingReasons.map((reason, idx) => (
                    <div
                      key={idx}
                      className="flex items-center gap-1.5 rounded-full border border-[var(--color-rag-amber)]/30 bg-[var(--color-rag-amber)]/5 px-3 py-1"
                    >
                      <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-rag-amber)]" />
                      <span className="text-xs text-[var(--text-primary)]">
                        {reason}
                      </span>
                    </div>
                  ))}
                </div>

                {/* Actions */}
                <div className="flex items-center gap-3">
                  <Button
                    variant="primary"
                    size="sm"
                    className="flex-1"
                    onClick={onRebalance}
                  >
                    <ArrowRight className="h-3.5 w-3.5" />
                    View Rebalancing Plan
                  </Button>
                  <Button variant="ghost" size="sm" className="flex-1">
                    <XCircle className="h-3.5 w-3.5" />
                    Dismiss
                  </Button>
                </div>
              </div>
            </DashboardPanel>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
