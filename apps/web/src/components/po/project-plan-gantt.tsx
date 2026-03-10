"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import {
  Calendar,
  Loader2,
  RefreshCw,
  CheckCircle2,
  Clock,
  AlertCircle,
} from "lucide-react";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { useSelectedProject } from "@/lib/project/context";
import { useAutoRefresh } from "@/lib/ws/context";
import { cachedFetch } from "@/lib/fetch-cache";
import { cn } from "@/lib/utils";
import type {
  ProjectPlanData,
  ProjectPlanRow,
  FeaturePhase,
  GanttStatus,
} from "@/lib/types/models";

// ── Utilities ──

/** Round a date back to the preceding Monday (or itself if already Monday). */
function toMonday(date: Date): Date {
  const d = new Date(date);
  const day = d.getDay(); // 0=Sun … 6=Sat
  const diff = day === 0 ? 6 : day - 1; // days since Monday
  d.setDate(d.getDate() - diff);
  d.setHours(0, 0, 0, 0);
  return d;
}

/** 0-based week column index from gridStart (a Monday). */
function weekIndex(date: Date, gridStart: Date): number {
  const ms = date.getTime() - gridStart.getTime();
  return Math.floor(ms / (7 * 24 * 60 * 60 * 1000));
}

/** Number of calendar weeks between two dates (at least 1). */
function weeksBetween(start: Date, end: Date): number {
  const ms = end.getTime() - start.getTime();
  return Math.max(1, Math.ceil(ms / (7 * 24 * 60 * 60 * 1000)));
}

/** Format a Monday date as "Mar 9". */
function formatWeekLabel(date: Date): string {
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

// ── Status colours & icons ──

const STATUS_COLOR: Record<GanttStatus, string> = {
  not_started: "bg-[var(--text-secondary)]/30",
  in_progress: "bg-[var(--color-brand-secondary)]",
  blocked: "bg-[var(--color-rag-red)]",
  complete: "bg-[var(--color-rag-green)]",
};

const STATUS_DOT: Record<GanttStatus, string> = {
  not_started: "bg-[var(--text-secondary)]/50",
  in_progress: "bg-[var(--color-brand-secondary)]",
  blocked: "bg-[var(--color-rag-red)]",
  complete: "bg-[var(--color-rag-green)]",
};

// ── Phase section header colours ──

const PHASE_SECTION_BG: Record<FeaturePhase, string> = {
  TESTING: "bg-[var(--color-rag-amber)]/10 border-[var(--color-rag-amber)]/30",
  DEVELOPMENT:
    "bg-[var(--color-brand-secondary)]/10 border-[var(--color-brand-secondary)]/30",
  PLANNING: "bg-[var(--color-rag-green)]/10 border-[var(--color-rag-green)]/30",
};

const PHASE_SECTION_TEXT: Record<FeaturePhase, string> = {
  TESTING: "text-[var(--color-rag-amber)]",
  DEVELOPMENT: "text-[var(--color-brand-secondary)]",
  PLANNING: "text-[var(--color-rag-green)]",
};

// ── Legend item ──

function LegendItem({
  label,
  type,
  color,
}: {
  label: string;
  type: "bar" | "dot";
  color: string;
}) {
  return (
    <div className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
      {type === "bar" ? (
        <span className={cn("h-2 w-6 rounded-sm", color)} />
      ) : (
        <span className={cn("h-2.5 w-2.5 rounded-full", color)} />
      )}
      {label}
    </div>
  );
}

// ── Gantt Row ──

interface GanttRowProps {
  row: ProjectPlanRow;
  gridStart: Date;
  totalWeeks: number;
}

function GanttRow({ row, gridStart, totalWeeks }: GanttRowProps) {
  const hasPlanned = !!(row.plannedStart && row.plannedEnd);

  let startCol = 1;
  let spanCols = 1;
  let durationLabel = "";

  if (hasPlanned) {
    const ps = new Date(row.plannedStart!);
    const pe = new Date(row.plannedEnd!);
    startCol = Math.max(0, weekIndex(ps, gridStart)) + 1; // CSS grid is 1-based
    spanCols = Math.max(1, weeksBetween(ps, pe));
    durationLabel = `${spanCols}w`;
  }

  // Actual bar width = completePct of planned bar
  const actualWidthPct = row.completePct;

  return (
    <>
      {/* Left column — feature name + assignees */}
      <div
        className="px-3 py-2.5 border-b border-[var(--border-subtle)] flex flex-col justify-center min-h-[56px]"
        style={{ gridColumn: "1 / 2" }}
      >
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "h-2 w-2 rounded-full shrink-0",
              STATUS_DOT[row.status]
            )}
          />
          <span className="text-sm font-medium text-[var(--text-primary)] truncate">
            {row.title}
          </span>
        </div>
        {row.assignees.length > 0 && (
          <span className="text-[10px] text-[var(--text-secondary)] mt-0.5 pl-4 truncate">
            {row.assignees.join(", ")}
          </span>
        )}
      </div>

      {/* Week cells — we render a single spanning cell for the timeline area */}
      <div
        className="relative border-b border-[var(--border-subtle)] min-h-[56px]"
        style={{ gridColumn: `2 / ${totalWeeks + 2}` }}
      >
        {/* Grid lines for weeks */}
        <div className="absolute inset-0 flex">
          {Array.from({ length: totalWeeks }).map((_, i) => (
            <div
              key={i}
              className="flex-1 border-r border-[var(--border-subtle)]/50"
            />
          ))}
        </div>

        {hasPlanned && (
          <div className="absolute inset-y-0 flex flex-col justify-center px-1">
            {/* Planned bar (gray) */}
            <div
              className="relative h-5 rounded-sm flex items-center"
              style={{
                marginLeft: `${((startCol - 1) / totalWeeks) * 100}%`,
                width: `${(spanCols / totalWeeks) * 100}%`,
              }}
            >
              <div
                className={cn(
                  "absolute inset-0 rounded-sm",
                  row.status === "not_started"
                    ? "border border-dashed border-[var(--text-secondary)]/40 bg-[var(--text-secondary)]/5"
                    : "bg-[var(--text-secondary)]/25"
                )}
              />
              {/* Duration label */}
              <span className="relative z-10 text-[10px] font-medium text-[var(--text-secondary)] px-2 whitespace-nowrap">
                P: {durationLabel}
              </span>
            </div>

            {/* Actual bar (colored) — only if there's progress */}
            {actualWidthPct > 0 && (
              <div
                className="relative h-5 rounded-sm flex items-center mt-0.5 overflow-hidden"
                style={{
                  marginLeft: `${((startCol - 1) / totalWeeks) * 100}%`,
                  width: `${(spanCols / totalWeeks) * 100 * (actualWidthPct / 100)}%`,
                  minWidth: "20px",
                }}
              >
                <div
                  className={cn(
                    "absolute inset-0 rounded-sm",
                    STATUS_COLOR[row.status]
                  )}
                />
                <span className="relative z-10 text-[10px] font-bold text-white px-2 whitespace-nowrap drop-shadow-sm">
                  A: {actualWidthPct}%
                </span>
              </div>
            )}
          </div>
        )}

        {/* Unscheduled indicator */}
        {!hasPlanned && (
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="text-[10px] text-[var(--text-secondary)] italic">
              Unscheduled
            </span>
          </div>
        )}
      </div>
    </>
  );
}

// ── Main Component ──

export function ProjectPlanGantt() {
  const { selectedProject } = useSelectedProject();
  const [data, setData] = useState<ProjectPlanData | null>(null);
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
      const res = await cachedFetch<ProjectPlanData>(
        `/api/dashboard/project-plan${q}`
      );
      if (res.ok && res.data) {
        setData(res.data);
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

  // ── Derive grid parameters ──

  const { gridStart, totalWeeks, weekLabels, currentWeekIdx } = useMemo(() => {
    if (!data || data.features.length === 0) {
      const now = toMonday(new Date());
      return {
        gridStart: now,
        totalWeeks: 12,
        weekLabels: Array.from({ length: 12 }).map((_, i) => {
          const d = new Date(now);
          d.setDate(d.getDate() + i * 7);
          return formatWeekLabel(d);
        }),
        currentWeekIdx: 0,
      };
    }

    // Find earliest start and latest end
    const starts = data.features
      .filter((f) => f.plannedStart)
      .map((f) => new Date(f.plannedStart!));
    const ends = data.features
      .filter((f) => f.plannedEnd)
      .map((f) => new Date(f.plannedEnd!));

    const earliest = starts.length > 0 ? toMonday(new Date(Math.min(...starts.map((d) => d.getTime())))) : toMonday(new Date());
    const latest = ends.length > 0 ? new Date(Math.max(...ends.map((d) => d.getTime()))) : new Date(earliest.getTime() + 12 * 7 * 24 * 60 * 60 * 1000);

    // Pad 1 week before and 2 weeks after
    const gs = new Date(earliest);
    gs.setDate(gs.getDate() - 7);
    const tw = Math.max(8, weeksBetween(gs, latest) + 2);

    const wl = Array.from({ length: tw }).map((_, i) => {
      const d = new Date(gs);
      d.setDate(d.getDate() + i * 7);
      return formatWeekLabel(d);
    });

    const cwi = weekIndex(toMonday(new Date()), gs);

    return { gridStart: gs, totalWeeks: tw, weekLabels: wl, currentWeekIdx: cwi };
  }, [data]);

  // ── Group features by phase ──

  const grouped = useMemo(() => {
    if (!data) return new Map<FeaturePhase, ProjectPlanRow[]>();
    const map = new Map<FeaturePhase, ProjectPlanRow[]>();
    const phaseOrder: FeaturePhase[] = ["TESTING", "DEVELOPMENT", "PLANNING"];

    for (const phase of phaseOrder) {
      const rows = data.features.filter((f) => f.phase === phase);
      if (rows.length > 0) {
        map.set(phase, rows);
      }
    }

    // Add any unmatched
    const scheduled = new Set(data.features.filter((f) => [...map.values()].flat().includes(f)).map((f) => f.id));
    const remaining = data.features.filter((f) => !scheduled.has(f.id));
    if (remaining.length > 0) {
      const existing = map.get("PLANNING") ?? [];
      map.set("PLANNING", [...existing, ...remaining]);
    }

    return map;
  }, [data]);

  // ── Loading state ──

  if (loading && !data) {
    return (
      <DashboardPanel title="Project Plan" icon={Calendar}>
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-[var(--color-brand-secondary)]" />
        </div>
      </DashboardPanel>
    );
  }

  if (!data || data.features.length === 0) {
    return (
      <DashboardPanel title="Project Plan" icon={Calendar}>
        <div className="flex flex-col items-center justify-center py-16 text-[var(--text-secondary)]">
          <Calendar className="h-10 w-10 mb-3 opacity-40" />
          <p className="text-sm">No features with planned dates found.</p>
          <p className="text-xs mt-1">
            Sync your project from ADO/Jira to populate the timeline.
          </p>
        </div>
      </DashboardPanel>
    );
  }

  return (
    <div className="space-y-0">
      {/* ── Header Banner ── */}
      <div className="rounded-t-lg bg-[var(--bg-surface)] border border-[var(--border-subtle)] border-b-0 px-6 py-5">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-lg font-bold text-[var(--text-primary)]">
              {selectedProject?.name ?? "Project"} Plan
            </h2>
            <p className="text-sm text-[var(--text-secondary)] mt-0.5">
              Feature timeline — Planned vs Actual progress
            </p>
          </div>
          <button
            onClick={fetchData}
            className="p-1.5 rounded-lg hover:bg-[var(--bg-surface-raised)] transition-colors"
            title="Refresh"
          >
            <RefreshCw
              className={cn(
                "h-4 w-4 text-[var(--text-secondary)]",
                loading && "animate-spin"
              )}
            />
          </button>
        </div>

        {/* KPI Row */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4">
          <div className="flex items-center gap-2 rounded-lg bg-[var(--bg-surface-raised)] px-3 py-2">
            <Calendar className="h-4 w-4 text-[var(--color-brand-secondary)]" />
            <div>
              <div className="text-xs text-[var(--text-secondary)]">
                Total Phases
              </div>
              <div className="text-sm font-bold text-[var(--text-primary)] tabular-nums">
                {data.totalPhases}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2 rounded-lg bg-[var(--bg-surface-raised)] px-3 py-2">
            <CheckCircle2 className="h-4 w-4 text-[var(--color-rag-green)]" />
            <div>
              <div className="text-xs text-[var(--text-secondary)]">
                Complete
              </div>
              <div className="text-sm font-bold text-[var(--color-rag-green)] tabular-nums">
                {data.complete}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2 rounded-lg bg-[var(--bg-surface-raised)] px-3 py-2">
            <Clock className="h-4 w-4 text-[var(--color-brand-secondary)]" />
            <div>
              <div className="text-xs text-[var(--text-secondary)]">
                In Progress
              </div>
              <div className="text-sm font-bold text-[var(--color-brand-secondary)] tabular-nums">
                {data.inProgress}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2 rounded-lg bg-[var(--bg-surface-raised)] px-3 py-2">
            <AlertCircle className="h-4 w-4 text-[var(--text-secondary)]" />
            <div>
              <div className="text-xs text-[var(--text-secondary)]">
                Est. Duration
              </div>
              <div className="text-sm font-bold text-[var(--text-primary)] tabular-nums">
                {data.estDurationWeeks
                  ? `~${data.estDurationWeeks} wks`
                  : "N/A"}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── Legend ── */}
      <div className="flex flex-wrap items-center gap-4 px-6 py-2.5 border-x border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]">
        <LegendItem label="Planned" type="bar" color="bg-[var(--text-secondary)]/20" />
        <LegendItem
          label="Actual"
          type="bar"
          color="bg-[var(--color-brand-secondary)]"
        />
        <LegendItem
          label="Not Started"
          type="dot"
          color="bg-[var(--text-secondary)]/50"
        />
        <LegendItem
          label="In Progress"
          type="dot"
          color="bg-[var(--color-brand-secondary)]"
        />
        <LegendItem
          label="Blocked"
          type="dot"
          color="bg-[var(--color-rag-red)]"
        />
        <LegendItem
          label="Complete"
          type="dot"
          color="bg-[var(--color-rag-green)]"
        />
      </div>

      {/* ── Gantt Grid ── */}
      <div className="rounded-b-lg border border-[var(--border-subtle)] border-t-0 bg-[var(--bg-surface)] overflow-x-auto">
        <div
          className="min-w-[800px]"
          style={{
            display: "grid",
            gridTemplateColumns: `280px repeat(${totalWeeks}, minmax(60px, 1fr))`,
          }}
        >
          {/* ── Week header row ── */}
          <div className="px-3 py-2 border-b border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] text-xs font-medium text-[var(--text-secondary)] flex items-center">
            Feature / Task
          </div>
          {weekLabels.map((label, i) => (
            <div
              key={i}
              className={cn(
                "px-2 py-2 border-b border-l border-[var(--border-subtle)] text-center text-[10px] font-medium",
                i === currentWeekIdx
                  ? "bg-[var(--color-brand-secondary)]/10 text-[var(--color-brand-secondary)] font-bold"
                  : "bg-[var(--bg-surface-raised)] text-[var(--text-secondary)]"
              )}
            >
              <div>Week {i + 1}</div>
              <div className="text-[9px] opacity-70">{label}</div>
            </div>
          ))}

          {/* ── Phase sections + rows ── */}
          {Array.from(grouped.entries()).map(([phase, rows]) => (
            <div
              key={phase}
              className="contents"
            >
              {/* Phase section header */}
              <div
                className={cn(
                  "px-3 py-2 border-b font-semibold text-xs uppercase tracking-wider flex items-center",
                  PHASE_SECTION_BG[phase],
                  PHASE_SECTION_TEXT[phase]
                )}
                style={{ gridColumn: `1 / ${totalWeeks + 2}` }}
              >
                {phase} ({rows.length})
              </div>

              {/* Feature rows */}
              {rows.map((row) => (
                <GanttRow
                  key={row.id}
                  row={row}
                  gridStart={gridStart}
                  totalWeeks={totalWeeks}
                />
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
