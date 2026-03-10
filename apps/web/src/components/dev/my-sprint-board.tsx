"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import {
  KanbanSquare,
  Loader2,
  RefreshCw,
  Bug,
  BookOpen,
  CheckSquare,
  Zap,
  User,
  Upload,
  ChevronDown,
  ChevronUp,
  Check,
  X,
  ArrowRight,
  GripVertical,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Badge, Button } from "@/components/ui";
import { useAutoRefresh } from "@/lib/ws/context";
import { useSelectedProject } from "@/lib/project/context";

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

interface BoardColumn {
  id: string;
  name: string;
  order: number;
  status: string; // unified status key: TODO, IN_PROGRESS, IN_REVIEW, DONE
}

interface WorkItemData {
  id: string;
  externalId: string;
  title: string;
  status: string;
  sourceStatus: string | null;
  type: string;
  priority: number;
  storyPoints: number | null;
  assignee: string | null;
  assigneeId: string | null;
  sourceTool: string;
  labels: string[];
}

interface PendingChange {
  workItemId: string;
  externalId: string;
  fromStatus: string;
  toStatus: string;
  title: string;
}

/* ------------------------------------------------------------------ */
/* Fixed 4-column board — Plan2Sprint owns the board                   */
/* ------------------------------------------------------------------ */

const BOARD_COLUMNS: BoardColumn[] = [
  { id: "new", name: "New", order: 0, status: "TODO" },
  { id: "in-progress", name: "In Progress", order: 1, status: "IN_PROGRESS" },
  { id: "in-review", name: "In Review", order: 2, status: "IN_REVIEW" },
  { id: "done", name: "Done", order: 3, status: "DONE" },
];

/* ------------------------------------------------------------------ */
/* Status → Column index map                                          */
/* ------------------------------------------------------------------ */

const STATUS_TO_COL: Record<string, number> = {
  BACKLOG: 0,
  TODO: 0,
  NEW: 0,
  IN_PROGRESS: 1,
  IN_REVIEW: 2,
  DONE: 3,
  CLOSED: 3,
  CANCELLED: 3,
};

/* Column → unified status (for drop targets) */
const COL_TO_STATUS: Record<number, string> = {
  0: "TODO",
  1: "IN_PROGRESS",
  2: "IN_REVIEW",
  3: "DONE",
};

/* ------------------------------------------------------------------ */
/* Column header colors                                               */
/* ------------------------------------------------------------------ */

const COL_COLORS: Record<string, string> = {
  new: "#6b7280",
  "in progress": "#06b6d4",
  "in review": "#f59e0b",
  done: "#22c55e",
};

function colColor(name: string) {
  return COL_COLORS[name.toLowerCase()] ?? "#6b7280";
}

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function TypeIcon({ type }: { type: string }) {
  const size = 13;
  const t = type.toLowerCase();
  if (t === "bug") return <Bug size={size} className="shrink-0 text-red-400" />;
  if (t === "story" || t === "user story")
    return <BookOpen size={size} className="shrink-0 text-cyan-400" />;
  if (t === "task")
    return <CheckSquare size={size} className="shrink-0 text-amber-400" />;
  if (t === "feature" || t === "epic")
    return <Zap size={size} className="shrink-0 text-violet-400" />;
  return <CheckSquare size={size} className="shrink-0 text-[var(--text-tertiary)]" />;
}

function AssigneeChip({ name }: { name: string }) {
  const initials = name
    .split(" ")
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  return (
    <span
      className="inline-flex h-[22px] items-center gap-1 rounded-full bg-violet-500/15 px-2 text-[10px] font-medium text-violet-300"
      title={name}
    >
      <User size={9} className="opacity-60" />
      {initials}
    </span>
  );
}

const PRIO: Record<number, { label: string; variant: "rag-red" | "rag-amber" | "brand" }> = {
  1: { label: "P1", variant: "rag-red" },
  2: { label: "P2", variant: "rag-amber" },
  3: { label: "P3", variant: "brand" },
};

const KNOWN_CATS = [
  "frontend",
  "backend",
  "devops",
  "design",
  "qa",
  "infrastructure",
  "mobile",
  "api",
  "database",
  "testing",
];
const CAT_CLS: Record<string, string> = {
  frontend: "bg-orange-500/15 text-orange-400 border-orange-500/20",
  backend: "bg-yellow-500/15 text-yellow-400 border-yellow-500/20",
  devops: "bg-sky-500/15 text-sky-400 border-sky-500/20",
  design: "bg-pink-500/15 text-pink-400 border-pink-500/20",
  qa: "bg-lime-500/15 text-lime-400 border-lime-500/20",
  testing: "bg-lime-500/15 text-lime-400 border-lime-500/20",
};

/* Source-status display names (for ADO/Jira specific states) */
const SOURCE_STATUS_BADGE: Record<string, string> = {
  ready: "Ready",
  migrate: "Migrate",
  proposed: "Proposed",
  resolved: "Resolved",
  "in qa": "QA",
  "selected for development": "Selected",
};

/* ------------------------------------------------------------------ */
/* Main component                                                     */
/* ------------------------------------------------------------------ */

export function MySprintBoard() {
  const { selectedProject } = useSelectedProject();
  const [items, setItems] = useState<WorkItemData[]>([]);
  const [loading, setLoading] = useState(true);
  const [pendingChanges, setPendingChanges] = useState<PendingChange[]>([]);
  const [dragOverCol, setDragOverCol] = useState<number | null>(null);
  const [draggingItemId, setDraggingItemId] = useState<string | null>(null);
  const [showChanges, setShowChanges] = useState(false);
  const [writingBack, setWritingBack] = useState(false);
  const [writebackResult, setWritebackResult] = useState<{
    ok: boolean;
    synced: number;
    failed: number;
  } | null>(null);

  const refreshKey = useAutoRefresh([
    "sync_complete",
    "writeback_success",
    "writeback_undo",
    "github_activity",
    "sprint_completed",
    "board_writeback_success",
  ]);

  const loadIdRef = useRef(0);

  /* ---- Load board items from local DB ---- */
  const loadBoard = useCallback(async () => {
    const myId = ++loadIdRef.current;

    if (!selectedProject) {
      setItems([]);
      setLoading(false);
      return;
    }

    setLoading(true);

    try {
      const params = new URLSearchParams({ limit: "500" });
      if (selectedProject.internalId) params.set("projectId", selectedProject.internalId);
      const res = await fetch(`/api/dashboard/work-items?${params.toString()}`);
      if (loadIdRef.current !== myId) return;
      if (res.ok) {
        const data = await res.json();
        setItems(data.workItems ?? []);
      }
    } catch {
      /* silent */
    }

    if (loadIdRef.current !== myId) return;
    setLoading(false);
  }, [selectedProject]);

  useEffect(() => {
    loadBoard();
  }, [loadBoard, refreshKey]);

  /* Clear writeback result after 5 seconds */
  useEffect(() => {
    if (writebackResult) {
      const t = setTimeout(() => setWritebackResult(null), 5000);
      return () => clearTimeout(t);
    }
  }, [writebackResult]);

  /* ---- Distribute items into columns ---- */
  const columnItems = useMemo(() => {
    const buckets: WorkItemData[][] = BOARD_COLUMNS.map(() => []);
    for (const item of items) {
      const norm = (item.status ?? "TODO").toUpperCase().replace(/\s+/g, "_");
      const idx = STATUS_TO_COL[norm] ?? 0;
      buckets[idx]?.push(item);
    }
    return buckets;
  }, [items]);

  /* ---- Drag & Drop handlers ---- */
  const handleDragStart = useCallback(
    (e: React.DragEvent, item: WorkItemData) => {
      e.dataTransfer.setData("text/plain", item.id);
      e.dataTransfer.effectAllowed = "move";
      setDraggingItemId(item.id);
    },
    [],
  );

  const handleDragEnd = useCallback(() => {
    setDraggingItemId(null);
    setDragOverCol(null);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent, colIdx: number) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    setDragOverCol(colIdx);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent, colIdx: number) => {
    // Only clear if we're leaving this column's area (not entering a child)
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const { clientX, clientY } = e;
    if (
      clientX < rect.left ||
      clientX > rect.right ||
      clientY < rect.top ||
      clientY > rect.bottom
    ) {
      if (dragOverCol === colIdx) setDragOverCol(null);
    }
  }, [dragOverCol]);

  const handleDrop = useCallback(
    async (e: React.DragEvent, colIdx: number) => {
      e.preventDefault();
      setDragOverCol(null);
      setDraggingItemId(null);

      const itemId = e.dataTransfer.getData("text/plain");
      if (!itemId) return;

      const newStatus = COL_TO_STATUS[colIdx];
      if (!newStatus) return;

      const item = items.find((i) => i.id === itemId);
      if (!item) return;

      // Don't move if already in this column
      const currentColIdx = STATUS_TO_COL[(item.status ?? "TODO").toUpperCase().replace(/\s+/g, "_")] ?? 0;
      if (currentColIdx === colIdx) return;

      const oldStatus = item.status;

      // Optimistic update — move card immediately
      setItems((prev) =>
        prev.map((i) => (i.id === itemId ? { ...i, status: newStatus } : i)),
      );

      // Track as pending change
      setPendingChanges((prev) => {
        // Remove any existing change for this item (in case of multiple drags)
        const filtered = prev.filter((c) => c.workItemId !== itemId);
        // Only add if the new status differs from the ORIGINAL status
        // (check if the item was already in pendingChanges)
        const originalChange = prev.find((c) => c.workItemId === itemId);
        const originalStatus = originalChange ? originalChange.fromStatus : oldStatus;

        // If we're moving it back to its original position, just remove the change
        if (originalStatus === newStatus) return filtered;

        return [
          ...filtered,
          {
            workItemId: itemId,
            externalId: item.externalId,
            fromStatus: originalStatus,
            toStatus: newStatus,
            title: item.title,
          },
        ];
      });

      // Update local DB (non-blocking)
      try {
        await fetch(`/api/work-items/${itemId}/status`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status: newStatus }),
        });
      } catch {
        /* silent — optimistic update already done */
      }
    },
    [items],
  );

  /* ---- Approve & Write Back ---- */
  const handleWriteBack = useCallback(async () => {
    if (pendingChanges.length === 0) return;
    setWritingBack(true);
    setWritebackResult(null);

    try {
      const res = await fetch("/api/board/writeback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ changes: pendingChanges }),
      });
      const data = await res.json();

      if (res.ok && data.ok) {
        setWritebackResult({ ok: true, synced: data.synced ?? 0, failed: data.failed ?? 0 });
        setPendingChanges([]);
        setShowChanges(false);
      } else {
        setWritebackResult({
          ok: false,
          synced: data.synced ?? 0,
          failed: data.failed ?? pendingChanges.length,
        });
      }
    } catch {
      setWritebackResult({ ok: false, synced: 0, failed: pendingChanges.length });
    }

    setWritingBack(false);
  }, [pendingChanges]);

  /* ---- Pending change lookup for badges ---- */
  const pendingSet = useMemo(
    () => new Set(pendingChanges.map((c) => c.workItemId)),
    [pendingChanges],
  );

  /* ---- Loading state ---- */
  if (loading) {
    return (
      <DashboardPanel title="Sprint Board" icon={KanbanSquare}>
        <div className="flex items-center justify-center py-8 gap-2">
          <Loader2 size={20} className="animate-spin text-[var(--color-brand-secondary)]" />
          <span className="text-xs text-[var(--text-tertiary)]">Loading board...</span>
        </div>
      </DashboardPanel>
    );
  }

  return (
    <DashboardPanel
      title="Sprint Board"
      icon={KanbanSquare}
      actions={
        <div className="flex items-center gap-3">
          {pendingChanges.length > 0 && (
            <span className="flex items-center gap-1 text-[10px] font-medium text-amber-400">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse" />
              {pendingChanges.length} pending
            </span>
          )}
          <button
            onClick={() => loadBoard()}
            className="flex items-center gap-1 text-[10px] text-[var(--text-tertiary)] hover:text-[var(--color-brand-secondary)] transition-colors cursor-pointer"
          >
            <RefreshCw size={10} /> Refresh
          </button>
        </div>
      }
    >
      {/* Board grid */}
      <div className="overflow-x-auto -mx-1 pb-2">
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(4, minmax(180px, 1fr))",
            gap: "0.75rem",
          }}
        >
          {BOARD_COLUMNS.map((col, colIdx) => {
            const cc = colColor(col.name);
            const ci = columnItems[colIdx] ?? [];
            const isDropTarget = dragOverCol === colIdx;

            return (
              <div
                key={col.id}
                className={cn(
                  "min-w-0 flex flex-col rounded-lg transition-all duration-200",
                  isDropTarget && "bg-cyan-500/5 ring-2 ring-cyan-500/30",
                )}
                onDragOver={(e) => handleDragOver(e, colIdx)}
                onDragLeave={(e) => handleDragLeave(e, colIdx)}
                onDrop={(e) => handleDrop(e, colIdx)}
              >
                {/* Column header */}
                <div
                  className="flex items-center justify-between mb-2 pb-2 border-b-2"
                  style={{ borderBottomColor: cc }}
                >
                  <span className="text-[11px] font-bold uppercase tracking-wider text-[var(--text-primary)]">
                    {col.name}
                  </span>
                  <span
                    className="flex h-5 min-w-[20px] items-center justify-center rounded-full text-[10px] font-bold px-1.5"
                    style={{
                      backgroundColor: `color-mix(in srgb, ${cc} 20%, transparent)`,
                      color: cc,
                    }}
                  >
                    {ci.length}
                  </span>
                </div>

                {/* Drop zone indicator */}
                {isDropTarget && ci.length === 0 && (
                  <div className="rounded-lg border-2 border-dashed border-cyan-500/40 p-4 mb-2 text-center">
                    <span className="text-[10px] text-cyan-400 font-medium">Drop here</span>
                  </div>
                )}

                {/* Cards */}
                <div className="flex flex-col gap-2 max-h-[520px] overflow-y-auto pr-0.5">
                  {ci.map((item) => {
                    const p = PRIO[item.priority];
                    const hasTitle = item.title && item.title !== "Untitled";
                    const catLabel = item.labels.find((l) =>
                      KNOWN_CATS.includes(l.toLowerCase()),
                    );
                    const catCls = catLabel
                      ? (CAT_CLS[catLabel.toLowerCase()] ??
                        "bg-slate-500/15 text-slate-400 border-slate-500/20")
                      : "";
                    const isPending = pendingSet.has(item.id);
                    const isDragging = draggingItemId === item.id;
                    const srcBadge = item.sourceStatus
                      ? SOURCE_STATUS_BADGE[item.sourceStatus.toLowerCase()]
                      : null;

                    return (
                      <div
                        key={item.id}
                        draggable
                        onDragStart={(e) => handleDragStart(e, item)}
                        onDragEnd={handleDragEnd}
                        className={cn(
                          "rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] p-3 transition-all duration-150 hover:border-cyan-500/40 hover:shadow-md hover:shadow-black/5 border-l-[3px] cursor-grab active:cursor-grabbing",
                          isDragging && "opacity-40 scale-95",
                          isPending && "ring-1 ring-amber-500/30",
                        )}
                        style={{ borderLeftColor: cc }}
                      >
                        {/* Drag handle + Title */}
                        <div className="flex items-start gap-1.5 mb-2">
                          <GripVertical
                            size={12}
                            className="shrink-0 mt-0.5 text-[var(--text-muted)] opacity-40"
                          />
                          <TypeIcon type={item.type} />
                          <p
                            className={cn(
                              "text-[12px] font-medium leading-snug line-clamp-3 flex-1",
                              hasTitle
                                ? "text-[var(--text-primary)]"
                                : "text-[var(--text-tertiary)] italic",
                            )}
                          >
                            {hasTitle ? item.title : `Work Item ${item.externalId}`}
                          </p>
                          {/* Pending change indicator */}
                          {isPending && (
                            <span
                              className="shrink-0 h-2 w-2 rounded-full bg-amber-400"
                              title="Pending write-back"
                            />
                          )}
                        </div>

                        {/* Badges row */}
                        <div className="flex flex-wrap items-center gap-1.5 mb-1.5">
                          <Badge
                            variant="brand"
                            className="text-[10px] px-1.5 py-0.5 font-mono"
                          >
                            {item.externalId}
                          </Badge>
                          {item.storyPoints != null && (
                            <span className="inline-flex h-5 min-w-[20px] items-center justify-center rounded-md bg-cyan-500/10 text-[10px] font-bold text-cyan-400 px-1">
                              {item.storyPoints}
                            </span>
                          )}
                          {p && (
                            <Badge
                              variant={p.variant}
                              className="text-[10px] px-1.5 py-0.5"
                            >
                              {p.label}
                            </Badge>
                          )}
                          {/* Source-specific status badge */}
                          {srcBadge && (
                            <span className="inline-flex h-[18px] items-center rounded-md bg-slate-500/10 px-1.5 text-[9px] font-medium text-slate-400 border border-slate-500/15">
                              {srcBadge}
                            </span>
                          )}
                        </div>

                        {/* Assignee + Category */}
                        <div className="flex flex-wrap items-center gap-1.5 mt-1.5">
                          {item.assignee && <AssigneeChip name={item.assignee} />}
                          {catLabel && (
                            <span
                              className={cn(
                                "inline-flex h-[22px] items-center rounded-full border px-2 text-[10px] font-semibold",
                                catCls,
                              )}
                            >
                              {catLabel}
                            </span>
                          )}
                        </div>

                        {/* Extra labels */}
                        {item.labels.filter((l) => !KNOWN_CATS.includes(l.toLowerCase()))
                          .length > 0 && (
                          <div className="flex flex-wrap gap-1 mt-1.5">
                            {item.labels
                              .filter((l) => !KNOWN_CATS.includes(l.toLowerCase()))
                              .slice(0, 2)
                              .map((label) => (
                                <span
                                  key={label}
                                  className="rounded bg-[var(--bg-surface-raised)] border border-[var(--border-subtle)] px-1.5 py-0.5 text-[9px] text-[var(--text-tertiary)]"
                                >
                                  {label}
                                </span>
                              ))}
                          </div>
                        )}
                      </div>
                    );
                  })}

                  {ci.length === 0 && !isDropTarget && (
                    <div className="rounded-lg border border-dashed border-[var(--border-subtle)] p-6 text-center">
                      <span className="text-xs text-[var(--text-tertiary)]">No items</span>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Footer */}
      <div className="mt-3 pt-3 border-t border-[var(--border-subtle)] flex items-center gap-4 text-[11px] text-[var(--text-tertiary)]">
        <span>{items.length} work items</span>
        <span className="opacity-40">&middot;</span>
        <span>{items.reduce((sum, i) => sum + (i.storyPoints ?? 0), 0)} SP total</span>
        <span className="opacity-40">&middot;</span>
        <span>4 columns</span>
        {pendingChanges.length > 0 && (
          <>
            <span className="opacity-40">&middot;</span>
            <span className="text-amber-400 font-medium">
              {pendingChanges.length} change{pendingChanges.length > 1 ? "s" : ""} pending
            </span>
          </>
        )}
      </div>

      {/* Writeback result toast */}
      {writebackResult && (
        <div
          className={cn(
            "mt-3 rounded-lg border p-3 flex items-center gap-2",
            writebackResult.ok
              ? "border-emerald-500/20 bg-emerald-500/5 text-emerald-400"
              : "border-red-500/20 bg-red-500/5 text-red-400",
          )}
        >
          {writebackResult.ok ? <Check size={14} /> : <X size={14} />}
          <span className="text-xs font-medium">
            {writebackResult.ok
              ? `Successfully synced ${writebackResult.synced} item${writebackResult.synced > 1 ? "s" : ""} to external tool`
              : `Write-back failed: ${writebackResult.failed} item${writebackResult.failed > 1 ? "s" : ""} could not be synced`}
          </span>
        </div>
      )}

      {/* Pending changes bar + review panel */}
      {pendingChanges.length > 0 && (
        <div className="mt-3 rounded-lg border border-amber-500/20 bg-amber-500/5 overflow-hidden">
          {/* Action bar */}
          <div className="flex items-center justify-between p-3">
            <div className="flex items-center gap-2">
              <Upload size={14} className="text-amber-400" />
              <span className="text-xs font-medium text-[var(--text-primary)]">
                {pendingChanges.length} change{pendingChanges.length > 1 ? "s" : ""} ready
                to sync
              </span>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setShowChanges((v) => !v)}
                className="flex items-center gap-1 text-[10px] text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer"
              >
                {showChanges ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                Review
              </button>
              <button
                onClick={() => {
                  setPendingChanges([]);
                  loadBoard();
                }}
                className="text-[10px] text-[var(--text-muted)] hover:text-red-400 transition-colors cursor-pointer"
              >
                Discard
              </button>
              <Button
                variant="primary"
                size="sm"
                onClick={handleWriteBack}
                disabled={writingBack}
                className="text-[11px] px-3 py-1"
              >
                {writingBack ? (
                  <>
                    <Loader2 size={12} className="animate-spin" /> Syncing...
                  </>
                ) : (
                  <>
                    <Upload size={12} /> Approve & Sync
                  </>
                )}
              </Button>
            </div>
          </div>

          {/* Expandable change list */}
          {showChanges && (
            <div className="border-t border-amber-500/10 p-3 space-y-1.5">
              {pendingChanges.map((change) => (
                <div
                  key={change.workItemId}
                  className="flex items-center gap-2 text-[11px] text-[var(--text-secondary)]"
                >
                  <span className="font-mono text-[10px] text-[var(--text-muted)]">
                    {change.externalId}
                  </span>
                  <span className="line-clamp-1 flex-1">{change.title}</span>
                  <span className="shrink-0 rounded bg-slate-500/10 px-1.5 py-0.5 text-[9px] font-medium text-slate-400">
                    {change.fromStatus}
                  </span>
                  <ArrowRight size={10} className="shrink-0 text-amber-400" />
                  <span className="shrink-0 rounded bg-cyan-500/10 px-1.5 py-0.5 text-[9px] font-medium text-cyan-400">
                    {change.toStatus}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </DashboardPanel>
  );
}
