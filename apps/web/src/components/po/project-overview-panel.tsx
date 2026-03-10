"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Layers,
  BookOpen,
  CheckCircle2,
  FlaskConical,
  AlertTriangle,
  ArrowRight,
  RefreshCw,
  Loader2,
} from "lucide-react";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { StatCard } from "@/components/dashboard/stat-card";
import { Badge, Progress } from "@/components/ui";
import { useSelectedProject } from "@/lib/project/context";
import { useAutoRefresh } from "@/lib/ws/context";
import { cachedFetch } from "@/lib/fetch-cache";
import { cn } from "@/lib/utils";
import type {
  FeatureProgressData,
  FeatureProgressCard,
  FeaturePhase,
} from "@/lib/types/models";

// ── Phase badge styling ──

const PHASE_CONFIG: Record<
  FeaturePhase,
  { label: string; badgeClass: string; barClass: string }
> = {
  TESTING: {
    label: "TESTING",
    badgeClass:
      "bg-[var(--color-rag-amber)]/10 text-[var(--color-rag-amber)] border-[var(--color-rag-amber)]/30",
    barClass: "AMBER" as const,
  },
  DEVELOPMENT: {
    label: "DEVELOPMENT",
    badgeClass:
      "bg-[var(--color-brand-secondary)]/10 text-[var(--color-brand-secondary)] border-[var(--color-brand-secondary)]/30",
    barClass: "GREEN" as const,
  },
  PLANNING: {
    label: "PLANNING",
    badgeClass:
      "bg-[var(--color-rag-green)]/10 text-[var(--color-rag-green)] border-[var(--color-rag-green)]/30",
    barClass: "GREEN" as const,
  },
};

// ── Risk derivation ──

interface DerivedRisk {
  title: string;
  description: string;
  severity: "red" | "amber" | "green";
}

function deriveRisks(features: FeatureProgressCard[]): DerivedRisk[] {
  const risks: DerivedRisk[] = [];
  const now = new Date();

  for (const f of features) {
    // Feature behind schedule (past planned end but below 80%)
    if (f.plannedEnd && new Date(f.plannedEnd) < now && f.completePct < 80) {
      risks.push({
        title: f.title,
        description: `Only ${f.completePct}% complete past planned end date`,
        severity: f.completePct < 50 ? "red" : "amber",
      });
    }
    // Feature with zero progress
    else if (f.totalStories > 0 && f.completePct === 0) {
      risks.push({
        title: f.title,
        description: `${f.totalStories} stories with no progress yet`,
        severity: "amber",
      });
    }
  }

  return risks.slice(0, 5);
}

// ── Dependency derivation (features sharing most assignees → likely coupled) ──

interface DerivedDep {
  from: string;
  to: string;
  description: string;
}

function deriveDependencies(features: FeatureProgressCard[]): DerivedDep[] {
  // Simple heuristic: features in PLANNING that block features in TESTING
  const deps: DerivedDep[] = [];
  const planning = features.filter((f) => f.phase === "PLANNING");
  const testing = features.filter((f) => f.phase === "TESTING");

  for (const p of planning) {
    for (const t of testing) {
      if (p.breakdown.remaining > 5 && t.breakdown.readyForTest > 0) {
        deps.push({
          from: p.title,
          to: t.title,
          description: `${p.title} still in planning may delay ${t.title} testing`,
        });
      }
    }
  }
  return deps.slice(0, 4);
}

// ── Severity dot ──

function SeverityDot({ severity }: { severity: "red" | "amber" | "green" }) {
  return (
    <span
      className={cn(
        "inline-block h-2.5 w-2.5 rounded-full shrink-0 mt-0.5",
        severity === "red" && "bg-[var(--color-rag-red)]",
        severity === "amber" && "bg-[var(--color-rag-amber)]",
        severity === "green" && "bg-[var(--color-rag-green)]"
      )}
    />
  );
}

// ── Feature Card ──

function FeatureCard({ feature }: { feature: FeatureProgressCard }) {
  const phase = PHASE_CONFIG[feature.phase] ?? PHASE_CONFIG.PLANNING;
  const severity =
    feature.completePct >= 70 ? "GREEN" : feature.completePct >= 40 ? "AMBER" : "RED";

  return (
    <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] p-4 flex flex-col gap-3">
      {/* Title + Phase badge */}
      <div className="flex items-start justify-between gap-2">
        <h4 className="text-sm font-semibold text-[var(--text-primary)] leading-tight">
          {feature.title}
        </h4>
        <span
          className={cn(
            "shrink-0 inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider border",
            phase.badgeClass
          )}
        >
          {phase.label}
        </span>
      </div>

      {/* Description */}
      {feature.description && (
        <p className="text-xs text-[var(--text-secondary)] line-clamp-1">
          {feature.description}
        </p>
      )}

      {/* Progress bar + story count */}
      <div className="flex items-center gap-3">
        <div className="flex-1">
          <Progress value={feature.completePct} severity={severity} size="sm" />
        </div>
        <span className="text-xs font-medium text-[var(--text-secondary)] tabular-nums whitespace-nowrap">
          {feature.completePct}%
        </span>
        <span className="text-xs text-[var(--text-secondary)] tabular-nums whitespace-nowrap">
          {feature.totalStories} Stories
        </span>
      </div>

      {/* 4-column breakdown */}
      <div className="grid grid-cols-4 gap-1 text-center">
        <div className="rounded bg-[var(--color-rag-green)]/10 px-1 py-1">
          <div className="text-xs font-bold text-[var(--color-rag-green)] tabular-nums">
            {feature.breakdown.done}
          </div>
          <div className="text-[9px] uppercase tracking-wider text-[var(--text-secondary)]">
            Done
          </div>
        </div>
        <div className="rounded bg-[var(--color-brand-secondary)]/10 px-1 py-1">
          <div className="text-xs font-bold text-[var(--color-brand-secondary)] tabular-nums">
            {feature.breakdown.inProgress}
          </div>
          <div className="text-[9px] uppercase tracking-wider text-[var(--text-secondary)]">
            In Progress
          </div>
        </div>
        <div className="rounded bg-[var(--color-rag-amber)]/10 px-1 py-1">
          <div className="text-xs font-bold text-[var(--color-rag-amber)] tabular-nums">
            {feature.breakdown.readyForTest}
          </div>
          <div className="text-[9px] uppercase tracking-wider text-[var(--text-secondary)]">
            Ready Test
          </div>
        </div>
        <div className="rounded bg-[var(--bg-surface)]/80 px-1 py-1">
          <div className="text-xs font-bold text-[var(--text-secondary)] tabular-nums">
            {feature.breakdown.remaining}
          </div>
          <div className="text-[9px] uppercase tracking-wider text-[var(--text-secondary)]">
            Remaining
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Main Component ──

export function ProjectOverviewPanel({ hideKpiRow }: { hideKpiRow?: boolean } = {}) {
  const { selectedProject } = useSelectedProject();
  const [data, setData] = useState<FeatureProgressData | null>(null);
  const [loading, setLoading] = useState(true);
  const refreshKey = useAutoRefresh([
    "sync_complete",
    "writeback_success",
    "writeback_undo",
  ]);

  const projectId = selectedProject?.internalId;

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const q = projectId ? `?projectId=${projectId}` : "";
      const res = await cachedFetch<FeatureProgressData>(
        `/api/dashboard/feature-progress${q}`
      );
      if (res.ok && res.data) {
        setData(res.data);
      }
    } catch {
      // fail silently — panel will show empty state
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    fetchData();
  }, [fetchData, refreshKey]);

  // Don't render if no features
  if (!loading && (!data || data.totalFeatures === 0)) {
    return null;
  }

  const risks = data ? deriveRisks(data.features) : [];
  const deps = data ? deriveDependencies(data.features) : [];

  return (
    <DashboardPanel
      title="Project Overview"
      icon={Layers}
      collapsible
      actions={
        <button
          onClick={fetchData}
          className="p-1 rounded hover:bg-[var(--bg-surface-raised)] transition-colors"
          title="Refresh data"
        >
          <RefreshCw
            className={cn(
              "h-3.5 w-3.5 text-[var(--text-secondary)]",
              loading && "animate-spin"
            )}
          />
        </button>
      }
    >
      {loading && !data ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-[var(--color-brand-secondary)]" />
        </div>
      ) : data ? (
        <div className="space-y-6">
          {/* ── KPI Row (hidden when hero banner shows KPIs) ── */}
          {!hideKpiRow && (
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <StatCard
                label="Total Features"
                value={data.totalFeatures}
                icon={Layers}
              />
              <StatCard
                label="Total Stories"
                value={data.totalStories}
                icon={BookOpen}
              />
              <StatCard
                label="Complete"
                value={`${data.overallCompletePct}%`}
                icon={CheckCircle2}
                severity={
                  data.overallCompletePct >= 70
                    ? "GREEN"
                    : data.overallCompletePct >= 40
                      ? "AMBER"
                      : "RED"
                }
              />
              <StatCard
                label="Ready for Test"
                value={data.readyForTestCount}
                icon={FlaskConical}
                severity="AMBER"
              />
            </div>
          )}

          {/* ── Feature Cards Grid ── */}
          <div>
            <h3 className="text-xs font-bold uppercase tracking-[0.15em] text-[var(--text-secondary)] mb-3">
              Module Status
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {data.features.map((f) => (
                <FeatureCard key={f.id} feature={f} />
              ))}
            </div>
          </div>

          {/* ── Key Risks ── */}
          {risks.length > 0 && (
            <div>
              <h3 className="text-xs font-bold uppercase tracking-[0.15em] text-[var(--text-secondary)] mb-3">
                Key Risks
              </h3>
              <div className="space-y-2">
                {risks.map((r, i) => (
                  <div key={i} className="flex items-start gap-2.5">
                    <SeverityDot severity={r.severity} />
                    <div>
                      <span className="text-sm font-medium text-[var(--text-primary)]">
                        {r.title}
                      </span>
                      <span className="text-sm text-[var(--text-secondary)]">
                        {" "}
                        — {r.description}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ── Critical Dependencies ── */}
          {deps.length > 0 && (
            <div>
              <h3 className="text-xs font-bold uppercase tracking-[0.15em] text-[var(--text-secondary)] mb-3">
                Critical Dependencies
              </h3>
              <div className="space-y-2">
                {deps.map((d, i) => (
                  <div
                    key={i}
                    className="flex items-center gap-2 text-sm"
                  >
                    <span className="font-medium text-[var(--text-primary)]">
                      {d.from}
                    </span>
                    <ArrowRight className="h-3.5 w-3.5 text-[var(--text-secondary)] shrink-0" />
                    <span className="font-medium text-[var(--text-primary)]">
                      {d.to}
                    </span>
                    <span className="text-[var(--text-secondary)] text-xs">
                      — {d.description}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ── Footer ── */}
          <div className="flex items-center justify-between text-xs text-[var(--text-secondary)] pt-2 border-t border-[var(--border-subtle)]">
            <span>Last updated: {new Date().toLocaleString()}</span>
            <button
              onClick={fetchData}
              className="flex items-center gap-1.5 hover:text-[var(--text-primary)] transition-colors"
            >
              <RefreshCw className="h-3 w-3" />
              Refresh Data
            </button>
          </div>
        </div>
      ) : null}
    </DashboardPanel>
  );
}
