"use client";

import { useState, useEffect, useCallback } from "react";
import { Loader2, Check, Calendar, Sparkles, AlertTriangle, RefreshCw } from "lucide-react";
import { useSelectedProject } from "@/lib/project/context";
import { useAutoRefresh } from "@/lib/ws/context";
import { cachedFetch } from "@/lib/fetch-cache";
import { cn } from "@/lib/utils";
import type {
  FeatureProgressData,
  ProjectPlanData,
  ProjectPhase,
  PlanSummaryData,
} from "@/lib/types/models";

type MilestoneState = "complete" | "current" | "future";

interface MilestoneData {
  id: string;
  label: string;
  state: MilestoneState;
  date: string | null;
}

// ── Live Data Badge ──

function LiveDataBadge({ source }: { source: string }) {
  const label =
    source === "ado"
      ? "Live Data from Azure DevOps"
      : source === "jira"
        ? "Live Data from Jira"
        : "Live Data";

  return (
    <span className="inline-flex items-center gap-2 rounded-full bg-white/10 border border-white/15 px-3 py-1 text-xs font-medium text-white/80">
      <span className="relative flex h-2 w-2">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[var(--color-rag-green)] opacity-75" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-[var(--color-rag-green)]" />
      </span>
      {label}
    </span>
  );
}

// ── Plan Source Badge ──

function PlanSourceBadge({ isOptimized }: { isOptimized: boolean }) {
  if (isOptimized) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-[var(--color-rag-green)]/20 border border-[var(--color-rag-green)]/30 px-2.5 py-0.5 text-[10px] font-semibold text-[var(--color-rag-green)] uppercase tracking-wide">
        <Sparkles className="h-3 w-3" />
        AI-Optimized
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-[var(--color-rag-amber)]/20 border border-[var(--color-rag-amber)]/30 px-2.5 py-0.5 text-[10px] font-semibold text-[var(--color-rag-amber)] uppercase tracking-wide">
      <AlertTriangle className="h-3 w-3" />
      Raw Estimate
    </span>
  );
}

// ── KPI Card ──

function KpiCard({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string | number;
  highlight?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-xl px-5 py-4 text-center",
        highlight
          ? "bg-[var(--color-rag-green)] text-white"
          : "bg-white/90 text-[#1e293b]"
      )}
    >
      <div
        className={cn(
          "text-3xl font-extrabold tabular-nums leading-tight",
          highlight ? "text-white" : "text-[#1e293b]"
        )}
      >
        {value}
      </div>
      <div
        className={cn(
          "text-[11px] font-medium uppercase tracking-wider mt-1",
          highlight ? "text-white/80" : "text-[#64748b]"
        )}
      >
        {label}
      </div>
    </div>
  );
}

// ── Project Timeline Stepper ──

function ProjectTimelineStepper({
  milestones,
}: {
  milestones: MilestoneData[];
}) {
  return (
    <div className="flex items-start justify-between w-full overflow-x-auto pb-2">
      {milestones.map((m, i) => {
        const isLast = i === milestones.length - 1;

        return (
          <div key={m.id} className="flex items-start flex-1 min-w-0">
            {/* Node + Label */}
            <div className="flex flex-col items-center min-w-[80px]">
              {/* Circle */}
              <div
                className={cn(
                  "relative flex items-center justify-center h-9 w-9 rounded-full border-2 shrink-0 transition-all",
                  m.state === "complete" &&
                    "bg-[var(--color-rag-green)] border-[var(--color-rag-green)]",
                  m.state === "current" &&
                    "bg-transparent border-[var(--color-rag-amber)] ring-4 ring-[var(--color-rag-amber)]/20",
                  m.state === "future" &&
                    "bg-transparent border-[var(--text-secondary)]/30"
                )}
              >
                {m.state === "complete" && (
                  <Check className="h-4.5 w-4.5 text-white" strokeWidth={3} />
                )}
                {m.state === "current" && (
                  <div className="h-3 w-3 rounded-full bg-[var(--color-rag-amber)]" />
                )}
                {m.state === "future" && (
                  <div className="h-2.5 w-2.5 rounded-full bg-[var(--text-secondary)]/25" />
                )}
              </div>

              {/* Label */}
              <span
                className={cn(
                  "text-[11px] font-medium text-center mt-2 leading-tight max-w-[90px]",
                  m.state === "complete" && "text-[var(--text-primary)]",
                  m.state === "current" && "text-[var(--color-rag-amber)]",
                  m.state === "future" && "text-[var(--text-secondary)]"
                )}
              >
                {m.label}
              </span>

              {/* Date */}
              {m.date && (
                <span className="text-[10px] text-[var(--text-secondary)] mt-0.5">
                  {m.date}
                </span>
              )}
            </div>

            {/* Connecting line */}
            {!isLast && (
              <div className="flex-1 flex items-center pt-[18px] px-1 min-w-[20px]">
                <div
                  className={cn(
                    "h-0.5 w-full rounded-full",
                    m.state === "complete"
                      ? "bg-[var(--color-rag-green)]"
                      : "border-t-2 border-dashed border-[var(--text-secondary)]/25 bg-transparent"
                  )}
                />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Phase derivation helpers ──

function deriveTargetLaunch(
  planData: ProjectPlanData | null,
  planSummary: PlanSummaryData | null,
): { date: Date | null; formatted: string; isOptimized: boolean } {
  // If an approved plan exists, use the AI-computed end date
  if (
    planSummary?.hasPlan &&
    ["APPROVED", "SYNCED", "SYNCED_PARTIAL"].includes(planSummary.status ?? "") &&
    planSummary.estimatedEndDate
  ) {
    const d = new Date(planSummary.estimatedEndDate);
    const formatted = d.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    });
    return { date: d, formatted, isOptimized: true };
  }

  // Fallback: derive from raw ADO feature dates
  const allFeatures = [
    ...(planData?.features ?? []),
    ...(planData?.unassigned ?? []),
  ];
  if (allFeatures.length === 0) {
    return { date: null, formatted: "TBD", isOptimized: false };
  }

  let latest: Date | null = null;
  for (const f of allFeatures) {
    if (f.plannedEnd) {
      const d = new Date(f.plannedEnd);
      if (!latest || d > latest) latest = d;
    }
  }

  if (!latest) return { date: null, formatted: "TBD", isOptimized: false };

  const formatted = latest.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
  return { date: latest, formatted, isOptimized: false };
}

function deriveWeeksLeft(targetDate: Date | null): number {
  if (!targetDate) return 0;
  const now = new Date();
  const diffMs = targetDate.getTime() - now.getTime();
  return Math.max(0, Math.ceil(diffMs / (7 * 24 * 60 * 60 * 1000)));
}

function deriveMilestones(
  planData: ProjectPlanData | null,
  progressData: FeatureProgressData | null
): MilestoneData[] {
  // Use phases from plan data (API-driven, sorted by sortOrder)
  const phases: ProjectPhase[] = planData?.phases ?? [];

  if (phases.length === 0) {
    return [{ id: "empty", label: "No phases configured", state: "future", date: null }];
  }

  // ── Build phase date map ──
  // Uses real Gantt plannedStart dates per phase. First phase is anchored to
  // "Feb 1" of the project year. Trailing phases without features are evenly
  // spread toward ~3 months after the last real date (landing near June).
  const phaseDates: Record<string, string> = {};
  if (planData) {
    const allFeatures = [...(planData.features ?? []), ...(planData.unassigned ?? [])];
    const ONE_WEEK = 7 * 24 * 60 * 60 * 1000;

    // Collect earliest plannedStart per phase (matches Gantt bar start)
    const phaseStartDates: Record<string, Date> = {};
    let earliestOverall: Date | null = null;
    let latestOverall: Date | null = null;

    for (const f of allFeatures) {
      const startStr = f.plannedStart ?? f.plannedEnd;
      if (startStr && f.phaseId) {
        const d = new Date(startStr);
        if (!phaseStartDates[f.phaseId] || d < phaseStartDates[f.phaseId]) {
          phaseStartDates[f.phaseId] = d;
        }
      }
      // Track global earliest/latest across ALL features (including unassigned)
      if (f.plannedStart) {
        const ds = new Date(f.plannedStart);
        if (!earliestOverall || ds < earliestOverall) earliestOverall = ds;
      }
      if (f.plannedEnd) {
        const de = new Date(f.plannedEnd);
        if (!latestOverall || de > latestOverall) latestOverall = de;
      }
    }

    // Project start = Feb 1 of the same year as the earliest feature
    const refYear = earliestOverall ? earliestOverall.getFullYear() : new Date().getFullYear();
    const projectStart = new Date(refYear, 1, 1); // Feb 1

    // Project target end = ~3 months after the latest feature date (lands near June)
    const projectEnd = latestOverall
      ? new Date(latestOverall.getTime() + 8 * ONE_WEEK) // +~2 months
      : new Date(refYear, 5, 1); // Jun 1 fallback

    // Evenly space ALL phases from projectStart to projectEnd.
    // For phases with real Gantt data, nudge toward it if close; otherwise
    // use even spacing to guarantee clean incremental dates.
    const totalSpan = projectEnd.getTime() - projectStart.getTime();
    const n = phases.length;
    const resolvedDates: Date[] = [];

    for (let i = 0; i < n; i++) {
      const evenDate = new Date(projectStart.getTime() + (i / n) * totalSpan);
      const realDate = phaseStartDates[phases[i].id] ?? null;

      // Use the real Gantt date if it exists and is within ±3 weeks of the even
      // slot; otherwise use even spacing for clean incremental dates.
      let d: Date;
      if (realDate) {
        const diff = Math.abs(realDate.getTime() - evenDate.getTime());
        d = diff < 3 * ONE_WEEK ? realDate : evenDate;
      } else {
        d = evenDate;
      }

      // Ensure strictly after previous phase (at least 1 week gap)
      if (i > 0 && d <= resolvedDates[i - 1]) {
        d = new Date(resolvedDates[i - 1].getTime() + ONE_WEEK);
      }

      resolvedDates.push(d);
      phaseDates[phases[i].id] = d.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
      });
    }
  }

  // ── Determine current phase using overall project completion % ──
  // This avoids issues where individual phase features might have 0% progress
  // even though the project is clearly past that phase conceptually.
  const overallPct = progressData?.overallCompletePct ?? 0;

  // Find how many phases have features assigned (these are "real" phases)
  const phasesWithFeatures: number[] = [];
  if (progressData && progressData.features.length > 0) {
    const phaseIdSet = new Set<string>();
    for (const f of progressData.features) {
      if (f.phaseId) phaseIdSet.add(f.phaseId);
    }
    for (let i = 0; i < phases.length; i++) {
      if (phaseIdSet.has(phases[i].id)) phasesWithFeatures.push(i);
    }
  }

  // Use overall completion to estimate which phase we're in:
  // Map 0-100% across all phases. E.g., 56% complete with 7 phases → phase index ~3.9
  const totalPhases = phases.length;
  const estimatedPhaseFloat = (overallPct / 100) * totalPhases;
  // The current phase is the one we're "in" — clamp to valid range
  let currentPhaseIndex = Math.min(
    Math.floor(estimatedPhaseFloat),
    totalPhases - 1
  );

  // If completion is very low (< 5%), keep at phase 0
  if (overallPct < 5) currentPhaseIndex = 0;

  // Build results: phases before current = complete, current = current, after = future
  const results: MilestoneData[] = [];
  for (let i = 0; i < phases.length; i++) {
    const phase = phases[i];
    const date = phaseDates[phase.id] ?? null;
    let state: MilestoneState;

    if (i < currentPhaseIndex) {
      state = "complete";
    } else if (i === currentPhaseIndex) {
      state = "current";
    } else {
      state = "future";
    }

    results.push({ id: phase.id, label: phase.name, state, date });
  }

  return results;
}

// ── Main Component ──

export function ProjectHeroBanner() {
  const { selectedProject } = useSelectedProject();
  const [progressData, setProgressData] =
    useState<FeatureProgressData | null>(null);
  const [planData, setPlanData] = useState<ProjectPlanData | null>(null);
  const [planSummary, setPlanSummary] = useState<PlanSummaryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const refreshKey = useAutoRefresh([
    "sync_complete",
    "writeback_success",
    "writeback_undo",
    "sprint_plan_generated",
    "sprint_plan_updated",
    "work_item_updated",
  ]);

  const projectId = selectedProject?.internalId;

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const q = projectId ? `?projectId=${projectId}` : "";
      const [progressRes, planRes, summaryRes] = await Promise.all([
        cachedFetch<FeatureProgressData>(
          `/api/dashboard/feature-progress${q}`
        ),
        cachedFetch<ProjectPlanData>(`/api/dashboard/project-plan${q}`),
        cachedFetch<PlanSummaryData>(`/api/dashboard/plan-summary${q}`),
      ]);

      if (progressRes.ok && progressRes.data) {
        setProgressData(progressRes.data);
      }
      if (planRes.ok && planRes.data) {
        setPlanData(planRes.data);
      }
      if (summaryRes.ok && summaryRes.data) {
        setPlanSummary(summaryRes.data);
      }
    } catch {
      // fail silently
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    // Don't fetch until a project is selected — avoids fetching ALL data
    if (!projectId) return;
    fetchData();
  }, [fetchData, refreshKey, projectId]);

  // Derived values
  const targetLaunch = deriveTargetLaunch(planData, planSummary);
  const weeksLeft = deriveWeeksLeft(targetLaunch.date);
  const milestones = deriveMilestones(planData, progressData);

  const totalFeatures = progressData?.totalFeatures ?? 0;
  const totalStories = progressData?.totalStories ?? 0;
  const completePct = progressData?.overallCompletePct ?? 0;
  const readyForTest = progressData?.readyForTestCount ?? 0;
  const source = selectedProject?.source ?? "ado";

  // Plan-derived values
  const hasApprovedPlan =
    planSummary?.hasPlan === true &&
    ["APPROVED", "SYNCED", "SYNCED_PARTIAL"].includes(planSummary.status ?? "");
  const hasPendingPlan =
    planSummary?.hasPlan === true && planSummary.status === "PENDING_REVIEW";
  const confidence = planSummary?.confidenceScore ?? null;
  const estWeeks = planSummary?.estimatedWeeksTotal ?? null;

  // Loading state
  if (loading && !progressData && !planData) {
    return (
      <div className="rounded-xl bg-gradient-to-br from-[#1e293b] to-[#334155] flex items-center justify-center py-16">
        <Loader2 className="h-6 w-6 animate-spin text-white/50" />
      </div>
    );
  }

  return (
    <div className="rounded-xl overflow-hidden">
      {/* ── Dark Gradient Hero Section ── */}
      <div className="bg-gradient-to-br from-[#1e293b] to-[#334155] px-6 py-6 space-y-6">
        {/* Top row: Project info (left) + Target Launch (right) */}
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
          <div className="space-y-2.5">
            <h1 className="text-2xl font-bold text-white">
              {selectedProject?.name ?? "Project Dashboard"}
            </h1>
            {selectedProject?.description && (
              <p className="text-sm text-white/60 max-w-lg">
                {selectedProject.description}
              </p>
            )}
            <div className="flex items-center gap-2 flex-wrap">
              <LiveDataBadge source={source} />
              <PlanSourceBadge isOptimized={targetLaunch.isOptimized} />
              <button
                onClick={async () => {
                  setRefreshing(true);
                  await fetchData();
                  setRefreshing(false);
                }}
                disabled={refreshing}
                className="ml-2 flex items-center gap-1.5 rounded-full bg-white/10 hover:bg-white/20 px-3 py-1 text-xs text-white/70 hover:text-white transition-colors disabled:opacity-50"
              >
                <RefreshCw className={`h-3 w-3 ${refreshing ? "animate-spin" : ""}`} />
                {refreshing ? "Refreshing..." : "Refresh"}
              </button>
            </div>
          </div>

          {/* Target Launch */}
          <div className="flex flex-col items-end shrink-0">
            <span className="text-[10px] font-bold uppercase tracking-widest text-white/50">
              Target Launch
            </span>
            <div className="flex items-center gap-2 mt-1">
              <Calendar className="h-4 w-4 text-white/50" />
              <span className="text-3xl font-extrabold text-[var(--color-rag-green)] tabular-nums">
                {targetLaunch.formatted}
              </span>
            </div>
          </div>
        </div>

        {/* Pending plan banner */}
        {hasPendingPlan && (
          <div className="flex items-center gap-2 rounded-lg bg-[var(--color-rag-amber)]/15 border border-[var(--color-rag-amber)]/30 px-4 py-2.5 text-sm text-[var(--color-rag-amber)]">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            Sprint plan pending review — approve to see AI-optimized timeline
          </div>
        )}

        {/* KPI Cards Row */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          <KpiCard label="Core Modules" value={totalFeatures} />
          <KpiCard label="Total Stories" value={totalStories} />
          <KpiCard
            label="Complete"
            value={`${completePct}%`}
            highlight={completePct >= 40}
          />
          {hasApprovedPlan && confidence !== null ? (
            <KpiCard label="Confidence" value={`${Math.round(confidence)}%`} />
          ) : (
            <KpiCard label="Ready for Test" value={readyForTest} />
          )}
          {hasApprovedPlan && estWeeks !== null ? (
            <KpiCard label="Est. Weeks" value={estWeeks} />
          ) : (
            <KpiCard label="Weeks Left" value={weeksLeft} />
          )}
        </div>
      </div>

      {/* ── Project Timeline Stepper ── */}
      <div className="bg-[var(--bg-surface)] border border-[var(--border-subtle)] border-t-0 rounded-b-xl px-6 py-5">
        <h3 className="text-xs font-bold uppercase tracking-[0.15em] text-[var(--text-secondary)] mb-4">
          Project Timeline
        </h3>
        <ProjectTimelineStepper milestones={milestones} />
      </div>
    </div>
  );
}
