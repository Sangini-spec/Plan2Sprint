"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Calendar,
  Loader2,
  RefreshCw,
  CheckCircle2,
  Clock,
  AlertCircle,
  ChevronDown,
  ChevronRight,
  Settings2,
  Sparkles,
  Database,
  Pencil,
} from "lucide-react";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Button } from "@/components/ui";
import { useSelectedProject } from "@/lib/project/context";
import { useAutoRefresh } from "@/lib/ws/context";
import { cachedFetch } from "@/lib/fetch-cache";
import { cn } from "@/lib/utils";
import type {
  ProjectPlanData,
  ProjectPlanRow,
  ProjectPhase,
  GanttStatus,
} from "@/lib/types/models";
import { PhaseManagerSheet } from "./phase-manager-sheet";

type ViewMode = "fetched" | "optimized";

interface ScheduleOverride {
  startWeek: number;
  durationWeeks: number;
}

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

/** Generate bg/text classes from a hex color for phase section headers. */
function phaseHeaderClasses(hex: string) {
  return {
    bg: `border-b`,
    style: {
      backgroundColor: `${hex}15`,
      borderColor: `${hex}40`,
      color: hex,
    },
  };
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

// ── Legend item ──

function LegendItem({
  label,
  type,
  color,
  dashed,
}: {
  label: string;
  type: "bar" | "dot";
  color: string;
  dashed?: boolean;
}) {
  return (
    <div className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
      {type === "bar" ? (
        <span className={cn("h-2 w-6 rounded-sm", color, dashed && "border border-dashed border-[var(--text-secondary)]/40")} />
      ) : (
        <span className={cn("h-2.5 w-2.5 rounded-full", color)} />
      )}
      {label}
    </div>
  );
}

// ── Edit Schedule Modal ──

interface EditScheduleModalProps {
  row: ProjectPlanRow;
  totalWeeks: number;
  weekLabels: string[];
  currentStartWeek: number;
  currentDuration: number;
  onSave: (rowId: string, startWeek: number, durationWeeks: number) => void;
  onClose: () => void;
}

function EditScheduleModal({
  row,
  totalWeeks,
  weekLabels,
  currentStartWeek,
  currentDuration,
  onSave,
  onClose,
}: EditScheduleModalProps) {
  const [startWeek, setStartWeek] = useState(currentStartWeek);
  const [duration, setDuration] = useState(currentDuration);

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex items-center justify-center">
        {/* Backdrop */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="absolute inset-0 bg-black/40 backdrop-blur-sm"
          onClick={onClose}
        />

        {/* Dialog */}
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: 10 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 10 }}
          transition={{ duration: 0.15 }}
          className="relative w-full max-w-md mx-4 rounded-xl bg-[var(--bg-surface)] border border-[var(--border-subtle)] shadow-xl p-6"
        >
          <div className="flex items-center gap-2 mb-5">
            <Pencil className="h-4 w-4 text-[var(--color-brand-secondary)]" />
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">
              Edit Planned: {row.title}
            </h3>
          </div>

          {/* Start Week */}
          <div className="mb-4">
            <label className="block text-xs font-semibold text-[var(--text-primary)] mb-1.5">
              Start Week
            </label>
            <select
              value={startWeek}
              onChange={(e) => setStartWeek(Number(e.target.value))}
              className="w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] px-3 py-2.5 text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)]/40"
            >
              {Array.from({ length: totalWeeks }).map((_, i) => (
                <option key={i} value={i + 1}>
                  Week {i + 1} ({weekLabels[i]})
                </option>
              ))}
            </select>
          </div>

          {/* Duration */}
          <div className="mb-6">
            <label className="block text-xs font-semibold text-[var(--text-primary)] mb-1.5">
              Duration (weeks)
            </label>
            <select
              value={duration}
              onChange={(e) => setDuration(Number(e.target.value))}
              className="w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] px-3 py-2.5 text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)]/40"
            >
              {Array.from({ length: 12 }).map((_, i) => (
                <option key={i} value={i + 1}>
                  {i + 1} {i === 0 ? "week" : "weeks"}
                </option>
              ))}
            </select>
          </div>

          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={() => onSave(row.id, startWeek, duration)}
            >
              Save
            </Button>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}

// ── View Mode Toggle ──

function ViewModeToggle({
  viewMode,
  onChange,
}: {
  viewMode: ViewMode;
  onChange: (mode: ViewMode) => void;
}) {
  return (
    <div className="flex items-center gap-0.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] p-0.5">
      <button
        onClick={() => onChange("fetched")}
        className={cn(
          "flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors",
          viewMode === "fetched"
            ? "bg-[var(--color-brand-secondary)] text-white shadow-sm"
            : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
        )}
      >
        <Database className="h-3 w-3" />
        Original
      </button>
      <button
        onClick={() => onChange("optimized")}
        className={cn(
          "flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors",
          viewMode === "optimized"
            ? "bg-[var(--color-brand-secondary)] text-white shadow-sm"
            : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
        )}
      >
        <Sparkles className="h-3 w-3" />
        Optimized Plan
      </button>
    </div>
  );
}

// ── Gantt Row ──

interface GanttRowProps {
  row: ProjectPlanRow;
  gridStart: Date;
  totalWeeks: number;
  onDragStart?: (e: React.DragEvent, itemId: string) => void;
  draggable?: boolean;
  onEditPlanned?: (row: ProjectPlanRow, startCol: number, spanCols: number) => void;
  scheduleOverride?: ScheduleOverride;
}

function GanttRow({
  row,
  gridStart,
  totalWeeks,
  onDragStart,
  draggable = true,
  onEditPlanned,
  scheduleOverride,
}: GanttRowProps) {
  const [hoveringPlanned, setHoveringPlanned] = useState(false);

  // Determine planned bar position — override takes priority
  let hasPlanned: boolean;
  let startCol: number;
  let spanCols: number;
  let durationLabel: string;

  if (scheduleOverride) {
    hasPlanned = true;
    startCol = scheduleOverride.startWeek;
    spanCols = scheduleOverride.durationWeeks;
    durationLabel = `${spanCols}w`;
  } else if (row.plannedStart && row.plannedEnd) {
    hasPlanned = true;
    const ps = new Date(row.plannedStart);
    const pe = new Date(row.plannedEnd);
    startCol = Math.max(0, weekIndex(ps, gridStart)) + 1; // CSS grid is 1-based
    spanCols = Math.max(1, weeksBetween(ps, pe));
    durationLabel = `${spanCols}w`;
  } else {
    hasPlanned = false;
    startCol = 1;
    spanCols = 1;
    durationLabel = "";
  }

  // Determine actual bar position — independent of planned
  let hasActualDates = !!(row.actualStart && row.actualEnd);
  let actualStartCol = startCol;
  let actualSpanCols = spanCols;
  let actualLabel = "---";
  let isOverrun = false;

  if (hasActualDates) {
    const as = new Date(row.actualStart!);
    const ae = new Date(row.actualEnd!);
    actualStartCol = Math.max(0, weekIndex(as, gridStart)) + 1;
    actualSpanCols = Math.max(1, weeksBetween(as, ae));
    actualLabel = `${actualSpanCols}w`;

    // Overrun: actual end beyond planned end
    if (hasPlanned && !scheduleOverride && row.plannedEnd) {
      isOverrun = ae.getTime() > new Date(row.plannedEnd).getTime();
    } else if (hasPlanned && scheduleOverride) {
      // Compare actual end week vs override end week
      const overrideEndWeek = scheduleOverride.startWeek + scheduleOverride.durationWeeks - 1;
      const actualEndWeek = actualStartCol + actualSpanCols - 1;
      isOverrun = actualEndWeek > overrideEndWeek;
    }
  } else if (row.completePct > 0 && hasPlanned) {
    // Fallback: percentage of planned bar
    hasActualDates = false; // keep false for rendering logic
    actualStartCol = startCol;
    actualSpanCols = Math.max(1, Math.round(spanCols * (row.completePct / 100)));
    actualLabel = `${actualSpanCols}w`;
  }

  const showActualBar = hasActualDates || (row.completePct > 0 && hasPlanned);

  return (
    <>
      {/* Left column — feature name + assignees */}
      <div
        className={cn(
          "px-3 py-2.5 border-b border-[var(--border-subtle)] flex flex-col justify-center min-h-[72px]",
          draggable && "cursor-grab active:cursor-grabbing"
        )}
        style={{ gridColumn: "1 / 2" }}
        draggable={draggable}
        onDragStart={(e) => draggable && onDragStart?.(e, row.id)}
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
        className="relative border-b border-[var(--border-subtle)] min-h-[72px]"
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

        {hasPlanned && (() => {
          const leftPct = ((startCol - 1) / totalWeeks) * 100;
          const widthPct = (spanCols / totalWeeks) * 100;

          // Actual bar positioning (independent)
          const actualLeftPct = ((actualStartCol - 1) / totalWeeks) * 100;
          const actualWidthPct = (actualSpanCols / totalWeeks) * 100;

          return (
            <div className="absolute inset-0">
              {/* ── Planned bar (P) ── */}
              <div
                className={cn(
                  "absolute flex items-center group",
                  onEditPlanned && "cursor-pointer"
                )}
                style={{
                  left: `${leftPct}%`,
                  width: `${widthPct}%`,
                  top: "12px",
                  height: "28px",
                }}
                onClick={() => onEditPlanned?.(row, startCol, spanCols)}
                onMouseEnter={() => setHoveringPlanned(true)}
                onMouseLeave={() => setHoveringPlanned(false)}
              >
                <span className="absolute text-[9px] font-semibold text-[var(--text-secondary)]/60 -left-3 top-1/2 -translate-y-1/2">
                  P
                </span>
                <div className="relative w-full h-full rounded">
                  <div
                    className={cn(
                      "absolute inset-0 rounded transition-all",
                      row.status === "not_started"
                        ? "border border-dashed border-[var(--text-secondary)]/40 bg-[var(--text-secondary)]/5"
                        : "bg-[var(--text-secondary)]/25",
                      onEditPlanned && hoveringPlanned && "ring-2 ring-[var(--color-brand-secondary)]/50"
                    )}
                  />
                  <span className="absolute inset-0 flex items-center justify-center text-xs font-semibold text-[var(--text-secondary)] whitespace-nowrap z-10">
                    {durationLabel}
                  </span>
                </div>

                {/* Hover tooltip */}
                {onEditPlanned && hoveringPlanned && (
                  <div className="absolute -top-8 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-md bg-[var(--bg-surface-raised)] border border-[var(--border-subtle)] px-2 py-1 text-[10px] text-[var(--text-secondary)] shadow-lg z-20">
                    Planned: Week {startCol} – {startCol + spanCols - 1} (Click to edit)
                  </div>
                )}
              </div>

              {/* ── Actual bar (A) ── */}
              <div
                className="absolute flex items-center"
                style={{
                  left: `${showActualBar ? actualLeftPct : leftPct}%`,
                  width: `${showActualBar ? actualWidthPct : widthPct}%`,
                  bottom: "12px",
                  height: "28px",
                  minWidth: showActualBar ? "32px" : undefined,
                }}
              >
                <span className="absolute text-[9px] font-semibold text-[var(--text-secondary)]/60 -left-3 top-1/2 -translate-y-1/2">
                  A
                </span>
                {showActualBar ? (
                  <div className={cn(
                    "relative w-full h-full rounded overflow-hidden",
                    isOverrun && "border-r-4 border-[var(--color-rag-amber)]"
                  )}>
                    <div
                      className={cn(
                        "absolute inset-0 rounded",
                        STATUS_COLOR[row.status]
                      )}
                    />
                    <span className={cn(
                      "absolute inset-0 flex items-center justify-center text-xs font-bold whitespace-nowrap drop-shadow-sm z-10",
                      isOverrun ? "text-[var(--color-rag-amber)]" : "text-white"
                    )}>
                      {actualLabel}
                    </span>
                  </div>
                ) : (
                  <div className="relative w-full h-full rounded">
                    <div className="absolute inset-0 rounded border border-dashed border-[var(--text-secondary)]/30 bg-[var(--text-secondary)]/5" />
                    <span className="absolute inset-0 flex items-center justify-center text-[10px] text-[var(--text-secondary)]/50">
                      ---
                    </span>
                  </div>
                )}
              </div>
            </div>
          );
        })()}

        {/* TBD indicator — for features without planned dates */}
        {!hasPlanned && (
          <div className="absolute inset-0 flex items-center" style={{ justifyContent: "flex-end", paddingRight: "8%" }}>
            <div className="flex items-center gap-1.5 px-4 py-1.5 rounded-md bg-[var(--text-secondary)]/8 border border-dashed border-[var(--text-secondary)]/25">
              <span className="text-[11px] font-bold text-[var(--text-secondary)]/60 uppercase tracking-widest">
                TBD
              </span>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

// ── Phase Section Header ──

interface PhaseSectionHeaderProps {
  phase: ProjectPhase;
  count: number;
  collapsed: boolean;
  onToggle: () => void;
  totalWeeks: number;
  onDrop?: (e: React.DragEvent, phaseId: string) => void;
  dropEnabled?: boolean;
}

function PhaseSectionHeader({ phase, count, collapsed, onToggle, totalWeeks, onDrop, dropEnabled = true }: PhaseSectionHeaderProps) {
  const [dragOver, setDragOver] = useState(false);
  const hdr = phaseHeaderClasses(phase.color);
  const Icon = collapsed ? ChevronRight : ChevronDown;

  return (
    <div
      className={cn(
        "px-3 py-2 font-semibold text-xs uppercase tracking-wider flex items-center gap-2 cursor-pointer select-none transition-all",
        hdr.bg,
        dragOver && dropEnabled && "ring-2 ring-[var(--color-brand-secondary)] ring-inset"
      )}
      style={{ gridColumn: `1 / ${totalWeeks + 2}`, ...hdr.style }}
      onClick={onToggle}
      onDragOver={(e) => { if (dropEnabled) { e.preventDefault(); setDragOver(true); } }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => { if (dropEnabled) { e.preventDefault(); setDragOver(false); onDrop?.(e, phase.id); } }}
    >
      <Icon className="h-3.5 w-3.5" />
      <span
        className="h-2.5 w-2.5 rounded-full shrink-0"
        style={{ backgroundColor: phase.color }}
      />
      {phase.name} ({count})
    </div>
  );
}

// ── Main Component ──

export function ProjectPlanGantt() {
  const { selectedProject } = useSelectedProject();
  const [data, setData] = useState<ProjectPlanData | null>(null);
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState<ViewMode>("fetched");
  const [collapsedPhases, setCollapsedPhases] = useState<Set<string>>(new Set());
  const [phaseManagerOpen, setPhaseManagerOpen] = useState(false);

  // ── Editable Gantt state ──
  const [scheduleOverrides, setScheduleOverrides] = useState<Map<string, ScheduleOverride>>(new Map());
  const [editingRow, setEditingRow] = useState<{ row: ProjectPlanRow; startCol: number; spanCols: number } | null>(null);

  // Subscribe to real-time events including GitHub activity for dynamic updates
  const refreshKey = useAutoRefresh([
    "sync_complete",
    "writeback_success",
    "writeback_undo",
    "sprint_plan_generated",
    "sprint_plan_updated",
    "github_activity",
    "work_item_updated",
  ]);

  const projectId = selectedProject?.internalId;
  const isOptimized = viewMode === "optimized";

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const q = projectId ? `?projectId=${projectId}` : "";
      const endpoint = isOptimized
        ? `/api/dashboard/project-plan/optimized${q}`
        : `/api/dashboard/project-plan${q}`;
      const res = await cachedFetch<ProjectPlanData>(endpoint);
      if (res.ok && res.data) {
        setData(res.data);
      }
    } catch {
      // fail silently
    } finally {
      setLoading(false);
    }
  }, [projectId, isOptimized]);

  useEffect(() => {
    fetchData();
  }, [fetchData, refreshKey]);

  // Reset collapsed phases when switching view modes
  useEffect(() => {
    setCollapsedPhases(new Set());
  }, [viewMode]);

  const handleDragStart = useCallback((e: React.DragEvent, itemId: string) => {
    e.dataTransfer.setData("text/plain", itemId);
    e.dataTransfer.effectAllowed = "move";
  }, []);

  const handleDropOnPhase = useCallback(async (e: React.DragEvent, phaseId: string) => {
    const itemId = e.dataTransfer.getData("text/plain");
    if (!itemId) return;
    try {
      await fetch(`/api/work-items/${itemId}/phase`, {
        method: "PATCH",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phaseId }),
      });
      fetchData();
    } catch {
      // fail silently
    }
  }, [fetchData]);

  const togglePhase = useCallback((phaseId: string) => {
    setCollapsedPhases((prev) => {
      const next = new Set(prev);
      if (next.has(phaseId)) next.delete(phaseId);
      else next.add(phaseId);
      return next;
    });
  }, []);

  // ── Edit schedule handlers ──

  const handleOpenEdit = useCallback((row: ProjectPlanRow, startCol: number, spanCols: number) => {
    // Check if there's already an override for this row
    const override = scheduleOverrides.get(row.id);
    if (override) {
      setEditingRow({ row, startCol: override.startWeek, spanCols: override.durationWeeks });
    } else {
      setEditingRow({ row, startCol, spanCols });
    }
  }, [scheduleOverrides]);

  const handleSaveSchedule = useCallback((rowId: string, startWeek: number, durationWeeks: number) => {
    setScheduleOverrides((prev) => {
      const next = new Map(prev);
      next.set(rowId, { startWeek, durationWeeks });
      return next;
    });
    setEditingRow(null);
  }, []);

  // ── Derive grid parameters ──

  const allFeatures = useMemo(() => {
    if (!data) return [];
    return [...data.features, ...(data.unassigned ?? [])];
  }, [data]);

  const { gridStart, totalWeeks, weekLabels, currentWeekIdx } = useMemo(() => {
    if (!allFeatures || allFeatures.length === 0) {
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

    // Find earliest start and latest end — include actual dates too
    const starts = allFeatures
      .filter((f) => f.plannedStart)
      .map((f) => new Date(f.plannedStart!));
    const actualStarts = allFeatures
      .filter((f) => f.actualStart)
      .map((f) => new Date(f.actualStart!));

    const ends = allFeatures
      .filter((f) => f.plannedEnd)
      .map((f) => new Date(f.plannedEnd!));
    const actualEnds = allFeatures
      .filter((f) => f.actualEnd)
      .map((f) => new Date(f.actualEnd!));

    const allStarts = [...starts, ...actualStarts];
    const allEnds = [...ends, ...actualEnds];

    const earliest = allStarts.length > 0 ? toMonday(new Date(Math.min(...allStarts.map((d) => d.getTime())))) : toMonday(new Date());
    const latest = allEnds.length > 0 ? new Date(Math.max(...allEnds.map((d) => d.getTime()))) : new Date(earliest.getTime() + 12 * 7 * 24 * 60 * 60 * 1000);

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
  }, [allFeatures]);

  // ── Group features by phase (sorted by sortOrder) ──

  const grouped = useMemo(() => {
    if (!data) return [];

    // Sort phases by sortOrder
    const sortedPhases = [...(data.phases ?? [])].sort(
      (a, b) => a.sortOrder - b.sortOrder
    );

    const sections: { phase: ProjectPhase; rows: ProjectPlanRow[] }[] = [];

    for (const phase of sortedPhases) {
      const rows = data.features.filter((f) => f.phaseId === phase.id);
      // In optimized (AI sprint) view, skip empty phases/sprints
      if (isOptimized && rows.length === 0) continue;
      sections.push({ phase, rows });
    }

    return sections;
  }, [data]);

  const unassignedRows = useMemo(() => {
    if (!data) return [];
    return data.unassigned ?? [];
  }, [data]);

  // Check if optimized view has no plan
  const noOptimizedPlan = isOptimized && data?.hasPlan === false;

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

  if (!data || (allFeatures.length === 0 && !noOptimizedPlan)) {
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
              {isOptimized
                ? "AI-optimized sprint plan — features grouped by sprint"
                : "Feature timeline — Planned vs Actual progress"}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {/* View Mode Toggle */}
            <ViewModeToggle viewMode={viewMode} onChange={setViewMode} />

            {/* Phase Manager — only in fetched mode */}
            {!isOptimized && (
              <button
                onClick={() => {
                  setPhaseManagerOpen(true);
                }}
                className="p-1.5 rounded-lg hover:bg-[var(--bg-surface-raised)] transition-colors"
                title="Customize Phases"
              >
                <Settings2 className="h-4 w-4 text-[var(--text-secondary)]" />
              </button>
            )}
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
        </div>

        {/* KPI Row */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4">
          <div className="flex items-center gap-2 rounded-lg bg-[var(--bg-surface-raised)] px-3 py-2">
            <Calendar className="h-4 w-4 text-[var(--color-brand-secondary)]" />
            <div>
              <div className="text-xs text-[var(--text-secondary)]">
                {isOptimized ? "Total Sprints" : "Total Phases"}
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

      {/* ── Optimized mode info banner ── */}
      {isOptimized && !noOptimizedPlan && (
        <div className="flex items-center gap-2 px-6 py-2 border-x border-[var(--border-subtle)] bg-[var(--color-brand-secondary)]/5 text-xs text-[var(--color-brand-secondary)]">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[var(--color-brand-secondary)] opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-[var(--color-brand-secondary)]" />
          </span>
          Live — updates automatically from GitHub activity and developer progress
        </div>
      )}

      {/* ── No approved plan state ── */}
      {noOptimizedPlan && (
        <>
          <div className="flex flex-wrap items-center gap-4 px-6 py-2.5 border-x border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]">
            <LegendItem label="Planned" type="bar" color="bg-[var(--text-secondary)]/20" />
            <LegendItem label="Actual" type="bar" color="bg-[var(--color-brand-secondary)]" />
          </div>
          <div className="rounded-b-lg border border-[var(--border-subtle)] border-t-0 bg-[var(--bg-surface)]">
            <div className="flex flex-col items-center justify-center py-20 text-[var(--text-secondary)]">
              <Sparkles className="h-10 w-10 mb-3 opacity-40" />
              <p className="text-sm font-medium">No approved sprint plan available</p>
              <p className="text-xs mt-1 max-w-sm text-center">
                Generate and approve a sprint plan from the Sprint Optimization panel
                to see features grouped by AI-optimized sprints.
              </p>
              <button
                onClick={() => setViewMode("fetched")}
                className="mt-4 px-4 py-2 rounded-lg bg-[var(--color-brand-secondary)] text-white text-xs font-medium hover:opacity-90 transition-opacity"
              >
                Switch to Fetched Data
              </button>
            </div>
          </div>
        </>
      )}

      {/* ── Legend ── */}
      {!noOptimizedPlan && (
        <>
          <div className="flex flex-wrap items-center gap-4 px-6 py-2.5 border-x border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]">
            <LegendItem label="Planned" type="bar" color="bg-[var(--text-secondary)]/20" />
            <LegendItem
              label="Actual"
              type="bar"
              color="bg-[var(--color-brand-secondary)]"
            />
            <LegendItem
              label="Overrun"
              type="bar"
              color="bg-[var(--color-rag-amber)]/60"
            />
            <LegendItem
              label="TBD"
              type="bar"
              color="bg-[var(--text-secondary)]/10"
              dashed
            />
            <div className="w-px h-4 bg-[var(--border-subtle)]" />
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
              {grouped.map(({ phase, rows }) => {
                const isCollapsed = collapsedPhases.has(phase.id);
                return (
                  <div key={phase.id} className="contents">
                    <PhaseSectionHeader
                      phase={phase}
                      count={rows.length}
                      collapsed={isCollapsed}
                      onToggle={() => togglePhase(phase.id)}
                      totalWeeks={totalWeeks}
                      onDrop={!isOptimized ? handleDropOnPhase : undefined}
                      dropEnabled={!isOptimized}
                    />
                    {!isCollapsed && rows.length === 0 && (
                      <div
                        className="px-6 py-3 text-xs text-[var(--text-secondary)] italic border-b border-[var(--border-subtle)]"
                        style={{ gridColumn: `1 / ${totalWeeks + 2}` }}
                      >
                        {isOptimized
                          ? "No features assigned to this sprint"
                          : "No features assigned — drag features here or set up assignment rules"}
                      </div>
                    )}
                    {!isCollapsed &&
                      rows.map((row) => (
                        <GanttRow
                          key={row.id}
                          row={row}
                          gridStart={gridStart}
                          totalWeeks={totalWeeks}
                          onDragStart={!isOptimized ? handleDragStart : undefined}
                          draggable={!isOptimized}
                          onEditPlanned={!isOptimized ? handleOpenEdit : undefined}
                          scheduleOverride={scheduleOverrides.get(row.id)}
                        />
                      ))}
                  </div>
                );
              })}

              {/* ── Unassigned section ── */}
              {unassignedRows.length > 0 && (
                <div className="contents">
                  <div
                    className="px-3 py-2 border-b font-semibold text-xs uppercase tracking-wider flex items-center gap-2 cursor-pointer select-none bg-[var(--text-secondary)]/5 border-[var(--border-subtle)] text-[var(--text-secondary)]"
                    style={{ gridColumn: `1 / ${totalWeeks + 2}` }}
                    onClick={() => togglePhase("__unassigned__")}
                  >
                    {collapsedPhases.has("__unassigned__") ? (
                      <ChevronRight className="h-3.5 w-3.5" />
                    ) : (
                      <ChevronDown className="h-3.5 w-3.5" />
                    )}
                    Unassigned ({unassignedRows.length})
                  </div>
                  {!collapsedPhases.has("__unassigned__") &&
                    unassignedRows.map((row) => (
                      <GanttRow
                        key={row.id}
                        row={row}
                        gridStart={gridStart}
                        totalWeeks={totalWeeks}
                        onDragStart={!isOptimized ? handleDragStart : undefined}
                        draggable={!isOptimized}
                        onEditPlanned={!isOptimized ? handleOpenEdit : undefined}
                        scheduleOverride={scheduleOverrides.get(row.id)}
                      />
                    ))}
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {/* Phase Manager Sheet — only in fetched mode */}
      {!isOptimized && (
        <PhaseManagerSheet
          open={phaseManagerOpen}
          onClose={() => setPhaseManagerOpen(false)}
          onPhasesChanged={fetchData}
        />
      )}

      {/* Edit Schedule Modal */}
      {editingRow && (
        <EditScheduleModal
          row={editingRow.row}
          totalWeeks={totalWeeks}
          weekLabels={weekLabels}
          currentStartWeek={editingRow.startCol}
          currentDuration={editingRow.spanCols}
          onSave={handleSaveSchedule}
          onClose={() => setEditingRow(null)}
        />
      )}
    </div>
  );
}
