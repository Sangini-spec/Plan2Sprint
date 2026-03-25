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
  ArrowUpRight,
  ArrowDownRight,
  Minus,
  Brain,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { RagIndicator } from "@/components/dashboard/rag-indicator";
import { Badge, Avatar } from "@/components/ui";
import { useSelectedProject } from "@/lib/project/context";
import { useAutoRefresh } from "@/lib/ws/context";
import { cachedFetch } from "@/lib/fetch-cache";
import type { HealthSeverity } from "@/lib/types/models";

// ---------------------------------------------------------------------------
// Types (subset of the full dashboard data)
// ---------------------------------------------------------------------------

type DashboardSeverity = HealthSeverity | "GREY";

interface BurnoutDeveloper {
  name: string;
  score: number;
  severity: string;
  breakdown: Record<string, number>;
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
        velocityTrend: Array<{
          sprint: string;
          planned: number;
          completed: number;
        }>;
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
        workloadDistribution: Array<{
          name: string;
          assignedSp: number;
          pctOfTotal: number;
        }>;
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
        <span className="text-3xl font-bold tabular-nums" style={{ color }}>
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

export function TeamHealthOverview() {
  const { selectedProject } = useSelectedProject();
  const [data, setData] = useState<HealthDashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const refreshKey = useAutoRefresh([
    "sync_complete",
    "health_evaluated",
  ]);

  const projectId = selectedProject?.internalId;

  const fetchData = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setData(null);
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 90000);
      const res = await fetch(
        `/api/team-health/dashboard?projectId=${projectId}`,
        { signal: controller.signal }
      );
      clearTimeout(timeout);
      if (res.ok) {
        const json = await res.json();
        setData(json as HealthDashboardData);
      }
    } catch { /* swallow */ }
    setLoading(false);
  }, [projectId]);

  useEffect(() => {
    fetchData();
  }, [fetchData, refreshKey]);

  // Loading
  if (loading) {
    return (
      <DashboardPanel title="Team Health" icon={HeartPulse}>
        <div className="flex items-center justify-center py-8">
          <Loader2
            size={20}
            className="animate-spin text-[var(--color-brand-secondary)]"
          />
        </div>
      </DashboardPanel>
    );
  }

  // Empty state
  if (!data) {
    return (
      <DashboardPanel title="Team Health" icon={HeartPulse}>
        <div className="flex flex-col items-center justify-center py-8 gap-2">
          <HeartPulse size={24} className="text-[var(--text-tertiary)]" />
          <p className="text-sm text-[var(--text-secondary)]">
            No health data available
          </p>
          <p className="text-xs text-[var(--text-tertiary)]">
            Health signals will appear after syncing project data.
          </p>
        </div>
      </DashboardPanel>
    );
  }

  const { pillars, workHours, recommendations } = data;

  return (
    <div className="space-y-6">
      {/* ================================================================
          Section 1: Overall Health Score Hero
          ================================================================ */}
      <DashboardPanel
        title="Team Health Score"
        icon={HeartPulse}
        collapsible
        actions={
          <span
            className={cn(
              "text-sm font-bold tabular-nums",
              data.overallScore >= 75
                ? "text-[var(--color-rag-green)]"
                : data.overallScore >= 50
                  ? "text-[var(--color-rag-amber)]"
                  : "text-[var(--color-rag-red)]"
            )}
          >
            {data.overallScore}/100
          </span>
        }
      >
        <div className="flex flex-col sm:flex-row items-center gap-6">
          <ScoreCircle
            score={data.overallScore}
            severity={data.overallSeverity}
          />
          <div className="flex-1 space-y-3">
            <RagIndicator
              severity={mapSeverity(data.overallSeverity)}
              size="lg"
            />
            <p className="text-sm text-[var(--text-secondary)] leading-relaxed max-w-md">
              {data.overallScore >= 75
                ? "The team is in a healthy state. All key indicators are within normal ranges."
                : data.overallScore >= 50
                  ? "Some health indicators need attention. Review the breakdown below for details."
                  : "Critical health concerns detected across the team. Review recommended actions."}
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
          metric={`${pillars.teamResilience.metrics.attritionRiskCount} attrition risks`}
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
          Section 3: Developer Hours Table (read-only, no expand)
          ================================================================ */}
      <DashboardPanel title="Developer Hours" icon={Clock} collapsible>
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
                  <th className="text-center py-2 px-3 text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider">
                    After-Hrs
                  </th>
                  <th className="text-center py-2 px-3 text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider">
                    Trend
                  </th>
                  <th className="text-center py-2 px-3 text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border-subtle)]/50">
                {workHours.developers.map((dev) => {
                  const sev = mapSeverity(dev.severity);
                  const color = severityColor[sev];
                  return (
                    <tr
                      key={dev.id}
                      className="hover:bg-[var(--bg-surface-raised)]/60 transition-colors"
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
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-8 gap-2">
            <Users size={24} className="text-[var(--text-tertiary)]" />
            <p className="text-sm text-[var(--text-secondary)]">
              No developer hours data available
            </p>
          </div>
        )}
      </DashboardPanel>

      {/* ================================================================
          Section 4: AI Recommendations
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
