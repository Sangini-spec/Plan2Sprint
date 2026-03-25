"use client";

import { useState, useEffect, useCallback } from "react";
import {
  HeartPulse,
  AlertTriangle,
  Clock,
  TrendingUp,
  Users,
  Zap,
  Shield,
  Loader2,
  ChevronDown,
  ChevronUp,
  ArrowUpRight,
  ArrowDownRight,
  Minus,
  Brain,
  RefreshCw,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { StatCard } from "@/components/dashboard/stat-card";
import { RagIndicator } from "@/components/dashboard/rag-indicator";
import { Badge, Progress, Avatar, Tooltip } from "@/components/ui";
import {
  ChartWrapper,
  chartColors,
} from "@/components/dashboard/chart-wrapper";
import { useSelectedProject } from "@/lib/project/context";
import { useAutoRefresh } from "@/lib/ws/context";
import { cachedFetch } from "@/lib/fetch-cache";
import type { HealthSeverity } from "@/lib/types/models";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip as RechartsTooltip,
  CartesianGrid,
  ResponsiveContainer,
  Cell,
} from "recharts";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type DashboardSeverity = HealthSeverity | "GREY";

interface BurnoutDeveloper {
  name: string;
  score: number;
  severity: string;
  breakdown: Record<string, number>;
}

interface VelocityPoint {
  sprint: string;
  planned: number;
  completed: number;
}

interface BusFactorFeature {
  name: string;
  busFactor: number;
  severity: string;
  contributors: string[];
}

interface FlowDeveloper {
  name: string;
  flowScore: number;
  avgWip: number;
  blockedHours: number;
  itemsPerDay: number;
}

interface WorkloadEntry {
  name: string;
  assignedSp: number;
  pctOfTotal: number;
}

interface WorkHoursDeveloper {
  name: string;
  id: string;
  thisWeek: number;
  lastWeek: number;
  trend: "up" | "down" | "stable";
  severity: string;
  weeklyHistory: number[];
  afterHoursRatio: number;
}

interface Recommendation {
  severity: string;
  target: string;
  message: string;
  action: string;
}

interface HealthDashboardData {
  overallScore: number;
  overallSeverity: DashboardSeverity;
  pillars: {
    burnoutRisk: {
      score: number;
      severity: string;
      developers: BurnoutDeveloper[];
    };
    sprintSustainability: {
      score: number;
      severity: string;
      metrics: {
        velocityTrend: VelocityPoint[];
        carryOverTrend: number[];
        scopeCreepPct: number;
      };
    };
    busFactor: {
      score: number;
      severity: string;
      features: BusFactorFeature[];
      matrix: Record<string, Record<string, number>>;
    };
    flowHealth: {
      score: number;
      severity: string;
      developers: FlowDeveloper[];
    };
    teamResilience: {
      score: number;
      severity: string;
      metrics: {
        giniCoefficient: number;
        crossTrainingIndex: number;
        attritionRiskCount: number;
        workloadDistribution: WorkloadEntry[];
      };
    };
  };
  workHours: {
    developers: WorkHoursDeveloper[];
  };
  recommendations: Recommendation[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mapSeverity(raw: string): HealthSeverity {
  const upper = raw.toUpperCase();
  if (upper === "RED" || upper === "CRITICAL" || upper === "HIGH") return "RED";
  if (upper === "AMBER" || upper === "WARNING" || upper === "MEDIUM")
    return "AMBER";
  return "GREEN";
}

const severityColor: Record<DashboardSeverity, string> = {
  GREEN: "var(--color-rag-green)",
  AMBER: "var(--color-rag-amber)",
  RED: "var(--color-rag-red)",
  GREY: "var(--text-tertiary)",
};

// ---------------------------------------------------------------------------
// ScoreCircle
// ---------------------------------------------------------------------------

function ScoreCircle({
  score,
  severity,
}: {
  score: number;
  severity: DashboardSeverity;
}) {
  const circumference = 2 * Math.PI * 54;
  const offset = circumference - (score / 100) * circumference;
  const color = severityColor[severity] || severityColor.GREY;

  return (
    <div className="relative w-32 h-32">
      <svg className="w-full h-full -rotate-90" viewBox="0 0 120 120">
        <circle
          cx="60"
          cy="60"
          r="54"
          fill="none"
          stroke="var(--border-subtle)"
          strokeWidth="8"
        />
        <circle
          cx="60"
          cy="60"
          r="54"
          fill="none"
          stroke={color}
          strokeWidth="8"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          className="transition-all duration-1000 ease-out"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span
          className="text-3xl font-bold tabular-nums"
          style={{ color }}
        >
          {score}
        </span>
        <span className="text-[10px] text-[var(--text-tertiary)] uppercase tracking-wider">
          / 100
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// PillarCard
// ---------------------------------------------------------------------------

interface PillarCardProps {
  icon: React.ElementType;
  title: string;
  score: number;
  severity: DashboardSeverity;
  metric: string;
}

function PillarCard({
  icon: Icon,
  title,
  score,
  severity,
  metric,
}: PillarCardProps) {
  const colors: Record<
    DashboardSeverity,
    { bg: string; text: string; border: string }
  > = {
    GREEN: {
      bg: "bg-[var(--color-rag-green)]/5",
      text: "text-[var(--color-rag-green)]",
      border: "border-[var(--color-rag-green)]/20",
    },
    AMBER: {
      bg: "bg-[var(--color-rag-amber)]/5",
      text: "text-[var(--color-rag-amber)]",
      border: "border-[var(--color-rag-amber)]/20",
    },
    RED: {
      bg: "bg-[var(--color-rag-red)]/5",
      text: "text-[var(--color-rag-red)]",
      border: "border-[var(--color-rag-red)]/20",
    },
    GREY: {
      bg: "bg-[var(--bg-surface-raised)]",
      text: "text-[var(--text-tertiary)]",
      border: "border-[var(--border-subtle)]",
    },
  };
  const c = colors[severity] || colors.GREY;

  return (
    <div
      className={cn(
        "rounded-xl border p-4 transition-shadow hover:shadow-md",
        c.bg,
        c.border
      )}
    >
      <div className="flex items-center gap-2 mb-3">
        <Icon size={18} className={c.text} />
        <span className="text-sm font-semibold text-[var(--text-primary)]">
          {title}
        </span>
      </div>
      <div className="flex items-baseline gap-1 mb-1">
        <span className={cn("text-2xl font-bold tabular-nums", c.text)}>
          {score}
        </span>
        <span className="text-xs text-[var(--text-tertiary)]">/100</span>
      </div>
      <p className="text-xs text-[var(--text-secondary)]">{metric}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// TrendArrow
// ---------------------------------------------------------------------------

function TrendArrow({ trend }: { trend: "up" | "down" | "stable" }) {
  if (trend === "up")
    return <ArrowUpRight size={14} className="text-[var(--color-rag-red)]" />;
  if (trend === "down")
    return (
      <ArrowDownRight size={14} className="text-[var(--color-rag-green)]" />
    );
  return <Minus size={14} className="text-[var(--text-tertiary)]" />;
}

// ---------------------------------------------------------------------------
// DeveloperHealthRow
// ---------------------------------------------------------------------------

function DeveloperHealthRow({
  dev,
  burnout,
  flow,
  expanded,
  onToggle,
}: {
  dev: WorkHoursDeveloper;
  burnout?: BurnoutDeveloper;
  flow?: FlowDeveloper;
  expanded: boolean;
  onToggle: () => void;
}) {
  const sev = mapSeverity(dev.severity);
  const color = severityColor[sev];

  return (
    <>
      <tr
        className="group cursor-pointer hover:bg-[var(--bg-surface-raised)]/60 transition-colors"
        onClick={onToggle}
      >
        <td className="py-2.5 px-3">
          <div className="flex items-center gap-2.5">
            <Avatar
              fallback={dev.name
                .split(" ")
                .map((w) => w[0])
                .join("")
                .slice(0, 2)}
              size="sm"
            />
            <span className="text-sm font-medium text-[var(--text-primary)]">
              {dev.name}
            </span>
          </div>
        </td>
        <td className="py-2.5 px-3">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium tabular-nums w-8">
              {dev.thisWeek}h
            </span>
            <div className="flex-1 h-2 rounded-full bg-[var(--bg-surface-raised)] overflow-hidden max-w-[120px]">
              <div
                className="h-full rounded-full transition-all"
                style={{
                  width: `${Math.min((dev.thisWeek / 60) * 100, 100)}%`,
                  backgroundColor: color,
                }}
              />
            </div>
          </div>
        </td>
        <td className="py-2.5 px-3">
          {burnout ? (
            <Badge
              variant={
                mapSeverity(burnout.severity) === "RED"
                  ? "rag-red"
                  : mapSeverity(burnout.severity) === "AMBER"
                    ? "rag-amber"
                    : "rag-green"
              }
              className="text-[10px] tabular-nums"
            >
              {burnout.score}/100
            </Badge>
          ) : (
            <span className="text-xs text-[var(--text-tertiary)]">--</span>
          )}
        </td>
        <td className="py-2.5 px-3 text-center">
          <span className="text-xs tabular-nums text-[var(--text-secondary)]">
            {flow?.avgWip ?? "--"}
          </span>
        </td>
        <td className="py-2.5 px-3 text-center">
          <span className="text-xs tabular-nums text-[var(--text-secondary)]">
            {dev.afterHoursRatio != null
              ? `${Math.round(dev.afterHoursRatio * 100)}%`
              : "--"}
          </span>
        </td>
        <td className="py-2.5 px-3 text-center">
          <TrendArrow trend={dev.trend} />
        </td>
        <td className="py-2.5 px-3 text-center">
          <RagIndicator severity={sev} size="sm" />
        </td>
        <td className="py-2.5 px-3 text-center">
          {expanded ? (
            <ChevronUp size={14} className="text-[var(--text-tertiary)]" />
          ) : (
            <ChevronDown size={14} className="text-[var(--text-tertiary)]" />
          )}
        </td>
      </tr>

      {/* Expanded detail row */}
      {expanded && (
        <tr className="bg-[var(--bg-surface-raised)]/40">
          <td colSpan={8} className="px-6 py-3">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-xs">
              <div>
                <span className="text-[var(--text-tertiary)] block mb-0.5">
                  Last Week
                </span>
                <span className="font-medium text-[var(--text-primary)] tabular-nums">
                  {dev.lastWeek}h
                </span>
              </div>
              <div>
                <span className="text-[var(--text-tertiary)] block mb-0.5">
                  Blocked Hours
                </span>
                <span className="font-medium text-[var(--text-primary)] tabular-nums">
                  {flow?.blockedHours ?? "--"}h
                </span>
              </div>
              <div>
                <span className="text-[var(--text-tertiary)] block mb-0.5">
                  Flow Score
                </span>
                <span className="font-medium text-[var(--text-primary)] tabular-nums">
                  {flow?.flowScore ?? "--"}/100
                </span>
              </div>
              <div>
                <span className="text-[var(--text-tertiary)] block mb-0.5">
                  Items/Day
                </span>
                <span className="font-medium text-[var(--text-primary)] tabular-nums">
                  {flow?.itemsPerDay?.toFixed(1) ?? "--"}
                </span>
              </div>
              {burnout && Object.keys(burnout.breakdown).length > 0 && (
                <div className="col-span-full">
                  <span className="text-[var(--text-tertiary)] block mb-1.5">
                    Burnout Breakdown
                  </span>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(burnout.breakdown).map(([key, val]) => (
                      <Badge key={key} variant="rag-amber" className="text-[10px]">
                        {key}: {val}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
              {dev.weeklyHistory.length > 0 && (
                <div className="col-span-full">
                  <span className="text-[var(--text-tertiary)] block mb-1.5">
                    Weekly Hours (last {dev.weeklyHistory.length} weeks)
                  </span>
                  <div className="flex items-end gap-1 h-8">
                    {dev.weeklyHistory.map((h, i) => (
                      <Tooltip key={i} content={`${h}h`}>
                        <div
                          className="w-4 rounded-sm transition-all hover:opacity-80"
                          style={{
                            height: `${Math.min((h / 60) * 100, 100)}%`,
                            backgroundColor:
                              h > 45
                                ? severityColor.RED
                                : h > 38
                                  ? severityColor.AMBER
                                  : severityColor.GREEN,
                            minHeight: "2px",
                          }}
                        />
                      </Tooltip>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// KnowledgeHeatmap
// ---------------------------------------------------------------------------

function KnowledgeHeatmap({
  features,
  matrix,
}: {
  features: BusFactorFeature[];
  matrix: Record<string, Record<string, number>>;
}) {
  const featureNames = Object.keys(matrix);
  if (featureNames.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8 gap-2">
        <Users size={24} className="text-[var(--text-tertiary)]" />
        <p className="text-sm text-[var(--text-secondary)]">
          No knowledge distribution data yet
        </p>
        <p className="text-xs text-[var(--text-tertiary)]">
          Data will appear after syncing repository activity.
        </p>
      </div>
    );
  }

  // Collect all unique developer names
  const devNames = Array.from(
    new Set(featureNames.flatMap((f) => Object.keys(matrix[f] ?? {})))
  );

  // Find max for scaling
  const allVals = featureNames.flatMap((f) =>
    Object.values(matrix[f] ?? {})
  );
  const maxVal = Math.max(...allVals, 1);

  // Get bus factor for a feature
  const getBusFactor = (featureName: string) => {
    const feat = features.find((f) => f.name === featureName);
    return feat ? feat.busFactor : null;
  };

  const getBusFactorSeverity = (featureName: string) => {
    const feat = features.find((f) => f.name === featureName);
    return feat ? mapSeverity(feat.severity) : "GREEN";
  };

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr>
            <th className="text-left py-2 px-2 text-[var(--text-secondary)] font-medium sticky left-0 bg-[var(--bg-surface)]">
              Feature
            </th>
            {devNames.map((dev) => (
              <th
                key={dev}
                className="py-2 px-2 text-center text-[var(--text-secondary)] font-medium"
                title={dev}
              >
                <span className="block max-w-[60px] truncate mx-auto">
                  {dev}
                </span>
              </th>
            ))}
            <th className="py-2 px-2 text-center text-[var(--text-secondary)] font-medium">
              Bus Factor
            </th>
          </tr>
        </thead>
        <tbody>
          {featureNames.map((feat) => (
            <tr
              key={feat}
              className="hover:bg-[var(--bg-surface-raised)]/40 transition-colors"
            >
              <td className="py-1.5 px-2 font-medium text-[var(--text-primary)] sticky left-0 bg-[var(--bg-surface)] max-w-[140px] truncate">
                {feat}
              </td>
              {devNames.map((dev) => {
                const val = matrix[feat]?.[dev] ?? 0;
                const intensity = val > 0 ? Math.max(0.15, val / maxVal) : 0;
                return (
                  <td key={dev} className="py-1.5 px-2 text-center">
                    {val > 0 ? (
                      <Tooltip content={`${dev}: ${val} contributions`}>
                        <div
                          className="w-7 h-7 rounded mx-auto flex items-center justify-center text-[10px] font-medium tabular-nums transition-all hover:scale-110"
                          style={{
                            backgroundColor: `color-mix(in srgb, var(--color-rag-green) ${Math.round(intensity * 100)}%, transparent)`,
                            color:
                              intensity > 0.5
                                ? "white"
                                : "var(--text-secondary)",
                          }}
                        >
                          {val}
                        </div>
                      </Tooltip>
                    ) : (
                      <div className="w-7 h-7 mx-auto" />
                    )}
                  </td>
                );
              })}
              <td className="py-1.5 px-2 text-center">
                {getBusFactor(feat) != null && (
                  <Badge
                    variant={
                      getBusFactorSeverity(feat) === "RED"
                        ? "rag-red"
                        : getBusFactorSeverity(feat) === "AMBER"
                          ? "rag-amber"
                          : "rag-green"
                    }
                    className="text-[10px] tabular-nums"
                  >
                    {getBusFactor(feat)}
                  </Badge>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// RecommendationCard
// ---------------------------------------------------------------------------

function RecommendationCard({ rec }: { rec: Recommendation }) {
  const sev = mapSeverity(rec.severity);
  const borderColors: Record<HealthSeverity, string> = {
    RED: "border-l-[var(--color-rag-red)]",
    AMBER: "border-l-[var(--color-rag-amber)]",
    GREEN: "border-l-[var(--color-rag-green)]",
  };

  return (
    <div
      className={cn(
        "rounded-lg border border-[var(--border-subtle)] border-l-4 p-4 transition-shadow hover:shadow-sm",
        borderColors[sev]
      )}
    >
      <div className="flex items-start gap-3">
        <AlertTriangle
          size={16}
          className={cn(
            "shrink-0 mt-0.5",
            sev === "RED"
              ? "text-[var(--color-rag-red)]"
              : sev === "AMBER"
                ? "text-[var(--color-rag-amber)]"
                : "text-[var(--color-rag-green)]"
          )}
        />
        <div className="flex-1 min-w-0 space-y-1">
          <span className="text-sm font-semibold text-[var(--text-primary)]">
            {rec.target}
          </span>
          <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
            {rec.message}
          </p>
          <p className="text-xs italic text-[var(--text-tertiary)]">
            {rec.action}
          </p>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export function TeamHealthDashboard() {
  const { selectedProject } = useSelectedProject();
  const [data, setData] = useState<HealthDashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [expandedDev, setExpandedDev] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const refreshKey = useAutoRefresh(["sync_complete", "health_evaluated"]);

  const projectId = selectedProject?.internalId;

  const fetchData = useCallback(async () => {
    if (!projectId) return; // Wait until a project is selected
    setLoading(true);
    setData(null); // Clear old data immediately on project switch
    try {
      // Use longer timeout for this heavy computation endpoint
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 90000); // 90s timeout
      const res = await fetch(
        `/api/team-health/dashboard?projectId=${projectId}`,
        { signal: controller.signal }
      );
      clearTimeout(timeout);
      if (res.ok) {
        const json = await res.json();
        setData(json as HealthDashboardData);
      }
    } catch {
      /* swallow - timeout or network error */
    }
    setLoading(false);
  }, [projectId]);

  useEffect(() => {
    fetchData();
  }, [fetchData, refreshKey]);

  const handleRefresh = async () => {
    setRefreshing(true);
    await fetchData();
    setRefreshing(false);
  };

  // Loading
  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-24 gap-4">
        <div className="relative">
          <HeartPulse size={32} className="text-[var(--color-brand-secondary)] animate-pulse" />
        </div>
        <Loader2
          size={20}
          className="animate-spin text-[var(--color-brand-secondary)]"
        />
        <div className="text-center">
          <p className="text-sm font-medium text-[var(--text-primary)]">
            Analyzing team health...
          </p>
          <p className="text-xs text-[var(--text-tertiary)] mt-1">
            Computing burnout risk, sprint sustainability, and knowledge distribution
          </p>
        </div>
      </div>
    );
  }

  // Empty state
  if (!data) {
    return (
      <DashboardPanel title="Team Health" icon={HeartPulse}>
        <div className="flex flex-col items-center justify-center py-12 gap-3">
          <HeartPulse size={32} className="text-[var(--text-tertiary)]" />
          <p className="text-sm text-[var(--text-secondary)]">
            No health data available
          </p>
          <p className="text-xs text-[var(--text-tertiary)]">
            Team health metrics will appear after syncing project data and
            running the health evaluation.
          </p>
        </div>
      </DashboardPanel>
    );
  }

  const { pillars, workHours, recommendations } = data;

  // Build lookup maps
  const burnoutByName = new Map(
    pillars.burnoutRisk.developers.map((d) => [d.name, d])
  );
  const flowByName = new Map(
    pillars.flowHealth.developers.map((d) => [d.name, d])
  );

  return (
    <div className="space-y-6">
      {/* ================================================================
          Section 1: Overall Health Score Hero
          ================================================================ */}
      <DashboardPanel
        title="Team Health Score"
        icon={HeartPulse}
        actions={
          <button
            onClick={(e) => {
              e.stopPropagation();
              handleRefresh();
            }}
            className="p-1.5 rounded-md hover:bg-[var(--bg-surface-raised)] transition-colors"
            aria-label="Refresh health data"
          >
            <RefreshCw
              size={14}
              className={cn(
                "text-[var(--text-secondary)]",
                refreshing && "animate-spin"
              )}
            />
          </button>
        }
      >
        <div className="flex flex-col sm:flex-row items-center gap-6">
          <ScoreCircle
            score={data.overallScore}
            severity={data.overallSeverity}
          />
          <div className="flex-1 space-y-3">
            <div className="flex items-center gap-3">
              <RagIndicator
                severity={mapSeverity(data.overallSeverity)}
                size="lg"
              />
            </div>
            <p className="text-sm text-[var(--text-secondary)] leading-relaxed max-w-md">
              {data.overallScore >= 75
                ? "The team is operating in a healthy, sustainable state. Continue monitoring for early warning signs."
                : data.overallScore >= 50
                  ? "Some areas need attention. Review the pillar scores below and address any amber or red indicators."
                  : "Critical health concerns detected. Immediate action is recommended to prevent burnout and delivery risks."}
            </p>
          </div>
        </div>
      </DashboardPanel>

      {/* ================================================================
          Section 2: Pillar Cards Grid
          ================================================================ */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <PillarCard
          icon={AlertTriangle}
          title="Burnout Risk"
          score={pillars.burnoutRisk.score}
          severity={mapSeverity(pillars.burnoutRisk.severity)}
          metric={`${pillars.burnoutRisk.developers.filter((d) => mapSeverity(d.severity) === "RED").length} developers at risk`}
        />
        <PillarCard
          icon={TrendingUp}
          title="Sprint Sustainability"
          score={pillars.sprintSustainability.score}
          severity={mapSeverity(pillars.sprintSustainability.severity)}
          metric={`${pillars.sprintSustainability.metrics.scopeCreepPct.toFixed(0)}% scope creep`}
        />
        <PillarCard
          icon={Users}
          title="Bus Factor"
          score={pillars.busFactor.score}
          severity={mapSeverity(pillars.busFactor.severity)}
          metric={`${pillars.busFactor.features.filter((f) => f.busFactor <= 1).length} single-contributor features`}
        />
        <PillarCard
          icon={Zap}
          title="Flow Health"
          score={pillars.flowHealth.score}
          severity={mapSeverity(pillars.flowHealth.severity)}
          metric={`${pillars.flowHealth.developers.length} developers tracked`}
        />
        <PillarCard
          icon={Shield}
          title="Team Resilience"
          score={pillars.teamResilience.score}
          severity={mapSeverity(pillars.teamResilience.severity)}
          metric={`Gini: ${pillars.teamResilience.metrics.giniCoefficient.toFixed(2)}, ${pillars.teamResilience.metrics.attritionRiskCount} attrition risks`}
        />
        <PillarCard
          icon={Clock}
          title="Work Hours"
          score={Math.round(
            100 -
              (workHours.developers.filter(
                (d) => mapSeverity(d.severity) !== "GREEN"
              ).length /
                Math.max(workHours.developers.length, 1)) *
                100
          )}
          severity={
            workHours.developers.some(
              (d) => mapSeverity(d.severity) === "RED"
            )
              ? "RED"
              : workHours.developers.some(
                    (d) => mapSeverity(d.severity) === "AMBER"
                  )
                ? "AMBER"
                : "GREEN"
          }
          metric={`${workHours.developers.filter((d) => d.thisWeek > 45).length} working overtime`}
        />
      </div>

      {/* ================================================================
          Section 3: Developer Health Table
          ================================================================ */}
      <DashboardPanel title="Developer Health" icon={Users} collapsible>
        {workHours.developers.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border-subtle)]">
                  <th className="text-left py-2 px-3 text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider">
                    Developer
                  </th>
                  <th className="text-left py-2 px-3 text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider">
                    Hours/Week
                  </th>
                  <th className="text-left py-2 px-3 text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider">
                    Burnout
                  </th>
                  <th className="text-center py-2 px-3 text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider">
                    WIP
                  </th>
                  <th className="text-center py-2 px-3 text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider">
                    After-Hrs
                  </th>
                  <th className="text-center py-2 px-3 text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider">
                    Trend
                  </th>
                  <th className="text-center py-2 px-3 text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider">
                    Status
                  </th>
                  <th className="w-8" />
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border-subtle)]/50">
                {workHours.developers.map((dev) => (
                  <DeveloperHealthRow
                    key={dev.id}
                    dev={dev}
                    burnout={burnoutByName.get(dev.name)}
                    flow={flowByName.get(dev.name)}
                    expanded={expandedDev === dev.id}
                    onToggle={() =>
                      setExpandedDev(
                        expandedDev === dev.id ? null : dev.id
                      )
                    }
                  />
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-8 gap-2">
            <Users size={24} className="text-[var(--text-tertiary)]" />
            <p className="text-sm text-[var(--text-secondary)]">
              No developer work-hour data available
            </p>
          </div>
        )}
      </DashboardPanel>

      {/* ================================================================
          Section 4: Knowledge Silo Map
          ================================================================ */}
      <DashboardPanel
        title="Knowledge Distribution"
        icon={Users}
        collapsible
        defaultCollapsed
      >
        <KnowledgeHeatmap
          features={pillars.busFactor.features}
          matrix={pillars.busFactor.matrix}
        />
      </DashboardPanel>

      {/* ================================================================
          Section 5: Sprint Sustainability
          ================================================================ */}
      <DashboardPanel
        title="Sprint Sustainability"
        icon={TrendingUp}
        collapsible
      >
        <div className="space-y-6">
          {/* Velocity Trend */}
          {pillars.sprintSustainability.metrics.velocityTrend.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] mb-3">
                Velocity Trend (Planned vs Completed)
              </h3>
              <ChartWrapper height={240}>
                <BarChart
                  data={pillars.sprintSustainability.metrics.velocityTrend}
                >
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke={chartColors.border}
                    vertical={false}
                  />
                  <XAxis
                    dataKey="sprint"
                    tick={{ fill: chartColors.text.secondary, fontSize: 11 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fill: chartColors.text.secondary, fontSize: 11 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <RechartsTooltip
                    contentStyle={{
                      backgroundColor: "var(--bg-surface)",
                      border: "1px solid var(--border-subtle)",
                      borderRadius: "8px",
                      fontSize: "12px",
                    }}
                  />
                  <Bar
                    dataKey="planned"
                    fill={chartColors.brand.secondary}
                    radius={[4, 4, 0, 0]}
                    name="Planned"
                  />
                  <Bar
                    dataKey="completed"
                    fill={chartColors.rag.green}
                    radius={[4, 4, 0, 0]}
                    name="Completed"
                  />
                </BarChart>
              </ChartWrapper>
            </div>
          )}

          {/* Carry-Over and Scope Creep Stats */}
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            <StatCard
              label="Scope Creep"
              value={`${pillars.sprintSustainability.metrics.scopeCreepPct.toFixed(1)}%`}
              severity={
                pillars.sprintSustainability.metrics.scopeCreepPct > 20
                  ? "RED"
                  : pillars.sprintSustainability.metrics.scopeCreepPct > 10
                    ? "AMBER"
                    : "GREEN"
              }
            />
            {pillars.sprintSustainability.metrics.carryOverTrend.length >
              0 && (
              <StatCard
                label="Latest Carry-Over"
                value={`${pillars.sprintSustainability.metrics.carryOverTrend[pillars.sprintSustainability.metrics.carryOverTrend.length - 1]}%`}
                severity={
                  pillars.sprintSustainability.metrics.carryOverTrend[
                    pillars.sprintSustainability.metrics.carryOverTrend
                      .length - 1
                  ] > 25
                    ? "RED"
                    : pillars.sprintSustainability.metrics.carryOverTrend[
                          pillars.sprintSustainability.metrics.carryOverTrend
                            .length - 1
                        ] > 15
                      ? "AMBER"
                      : "GREEN"
                }
              />
            )}
            <StatCard
              label="Cross-Training"
              value={pillars.teamResilience.metrics.crossTrainingIndex.toFixed(
                2
              )}
              severity={
                pillars.teamResilience.metrics.crossTrainingIndex < 0.3
                  ? "RED"
                  : pillars.teamResilience.metrics.crossTrainingIndex < 0.6
                    ? "AMBER"
                    : "GREEN"
              }
            />
          </div>
        </div>
      </DashboardPanel>

      {/* ================================================================
          Section 6: AI Recommendations
          ================================================================ */}
      <DashboardPanel title="AI Insights" icon={Brain}>
        {recommendations.length > 0 ? (
          <div className="space-y-3">
            {recommendations.map((rec, i) => (
              <RecommendationCard key={i} rec={rec} />
            ))}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-8 gap-2">
            <HeartPulse
              size={24}
              className="text-[var(--color-rag-green)]"
            />
            <p className="text-sm font-medium text-[var(--color-rag-green)]">
              No recommendations — team is healthy!
            </p>
          </div>
        )}
      </DashboardPanel>
    </div>
  );
}
