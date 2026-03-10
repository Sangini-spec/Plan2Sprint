"use client";

import { useState, useEffect, useCallback } from "react";
import { Loader2, Check, Calendar } from "lucide-react";
import { useSelectedProject } from "@/lib/project/context";
import { useAutoRefresh } from "@/lib/ws/context";
import { cachedFetch } from "@/lib/fetch-cache";
import { cn } from "@/lib/utils";
import type {
  FeatureProgressData,
  ProjectPlanData,
  FeaturePhase,
} from "@/lib/types/models";

// ── Milestone definitions ──

interface Milestone {
  id: string;
  label: string;
  phaseKey: FeaturePhase | null;
}

const MILESTONES: Milestone[] = [
  { id: "planning", label: "Planning & Design", phaseKey: "PLANNING" },
  { id: "dev", label: "Core Development", phaseKey: "DEVELOPMENT" },
  { id: "testing", label: "Testing & QA", phaseKey: "TESTING" },
  { id: "uat", label: "UAT & Staging", phaseKey: null },
  { id: "launch", label: "Production Launch", phaseKey: null },
];

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
  planData: ProjectPlanData | null
): { date: Date | null; formatted: string } {
  if (!planData || planData.features.length === 0) {
    return { date: null, formatted: "TBD" };
  }

  let latest: Date | null = null;
  for (const f of planData.features) {
    if (f.plannedEnd) {
      const d = new Date(f.plannedEnd);
      if (!latest || d > latest) latest = d;
    }
  }

  if (!latest) return { date: null, formatted: "TBD" };

  const formatted = latest.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
  return { date: latest, formatted };
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
  // Build phase completion map from progress data
  const phaseComplete: Record<string, boolean> = {};

  if (progressData && progressData.features.length > 0) {
    const phaseGroups: Record<string, number[]> = {};

    for (const f of progressData.features) {
      const phase = f.phase;
      if (!phaseGroups[phase]) phaseGroups[phase] = [];
      phaseGroups[phase].push(f.completePct);
    }

    for (const [phase, pcts] of Object.entries(phaseGroups)) {
      phaseComplete[phase] = pcts.length > 0 && pcts.every((p) => p >= 100);
    }
  }

  // Build phase date map from plan data
  const phaseDates: Record<string, string> = {};
  if (planData) {
    const phaseEndDates: Record<string, Date> = {};
    for (const f of planData.features) {
      if (f.plannedEnd && f.phase) {
        const d = new Date(f.plannedEnd);
        if (!phaseEndDates[f.phase] || d > phaseEndDates[f.phase]) {
          phaseEndDates[f.phase] = d;
        }
      }
    }
    for (const [phase, d] of Object.entries(phaseEndDates)) {
      phaseDates[phase] = d.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
      });
    }
  }

  // Determine state of each milestone
  let foundCurrent = false;
  const results: MilestoneData[] = [];

  for (const ms of MILESTONES) {
    let state: MilestoneState;
    let date: string | null = null;

    if (ms.phaseKey) {
      const isComplete = phaseComplete[ms.phaseKey] ?? false;
      date = phaseDates[ms.phaseKey] ?? null;

      if (isComplete && !foundCurrent) {
        state = "complete";
      } else if (!foundCurrent) {
        state = "current";
        foundCurrent = true;
      } else {
        state = "future";
      }
    } else {
      // UAT + Launch — always after last mapped phase
      if (!foundCurrent) {
        // All mapped phases complete but no current found yet
        state = "current";
        foundCurrent = true;
      } else {
        state = "future";
      }
    }

    results.push({ id: ms.id, label: ms.label, state, date });
  }

  return results;
}

// ── Main Component ──

export function ProjectHeroBanner() {
  const { selectedProject } = useSelectedProject();
  const [progressData, setProgressData] =
    useState<FeatureProgressData | null>(null);
  const [planData, setPlanData] = useState<ProjectPlanData | null>(null);
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
      const [progressRes, planRes] = await Promise.all([
        cachedFetch<FeatureProgressData>(
          `/api/dashboard/feature-progress${q}`
        ),
        cachedFetch<ProjectPlanData>(`/api/dashboard/project-plan${q}`),
      ]);

      if (progressRes.ok && progressRes.data) {
        setProgressData(progressRes.data);
      }
      if (planRes.ok && planRes.data) {
        setPlanData(planRes.data);
      }
    } catch {
      // fail silently
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    fetchData();
  }, [fetchData, refreshKey]);

  // Derived values
  const targetLaunch = deriveTargetLaunch(planData);
  const weeksLeft = deriveWeeksLeft(targetLaunch.date);
  const milestones = deriveMilestones(planData, progressData);

  const totalFeatures = progressData?.totalFeatures ?? 0;
  const totalStories = progressData?.totalStories ?? 0;
  const completePct = progressData?.overallCompletePct ?? 0;
  const readyForTest = progressData?.readyForTestCount ?? 0;
  const source = selectedProject?.source ?? "ado";

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
            <LiveDataBadge source={source} />
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

        {/* KPI Cards Row — white cards with dark text, green for Complete */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          <KpiCard label="Core Modules" value={totalFeatures} />
          <KpiCard label="Total Stories" value={totalStories} />
          <KpiCard
            label="Complete"
            value={`${completePct}%`}
            highlight={completePct >= 40}
          />
          <KpiCard label="Ready for Test" value={readyForTest} />
          <KpiCard label="Weeks Left" value={weeksLeft} />
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
