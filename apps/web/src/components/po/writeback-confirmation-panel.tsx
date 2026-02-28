"use client";

import { useState, useEffect, useCallback } from "react";
import {
  RefreshCw,
  CheckCircle2,
  Clock,
  AlertTriangle,
  Undo2,
  Loader2,
  XCircle,
} from "lucide-react";
import { format } from "date-fns";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Badge, Button } from "@/components/ui";
import { useAutoRefresh } from "@/lib/ws/context";
import { cachedFetch } from "@/lib/fetch-cache";

// ---------------------------------------------------------------------------
// Types for API response
// ---------------------------------------------------------------------------

interface WritebackEntry {
  id: string;
  eventType: string;
  resourceType: string;
  resourceId: string;
  beforeState: Record<string, unknown> | null;
  afterState: Record<string, unknown> | null;
  success: boolean;
  metadata: {
    tool?: string;
    itemTitle?: string;
    changes?: { field: string; from: unknown; to: unknown }[];
    undoable?: boolean;
    undone?: boolean;
    error?: string;
    originalEntryId?: string;
  } | null;
  createdAt: string | null;
  undoable: boolean;
}

// ---------------------------------------------------------------------------
// Local mock fallback
// ---------------------------------------------------------------------------

type SyncStatus = "synced" | "pending" | "discrepancy";

interface WritebackItem {
  id: string;
  ticketId: string;
  title: string;
  syncStatus: SyncStatus;
  syncedAt: string | undefined;
  undoable: boolean;
}


function apiEntryToItem(entry: WritebackEntry): WritebackItem {
  let syncStatus: SyncStatus = "pending";
  if (entry.eventType === "writeback" && entry.success) {
    syncStatus = "synced";
  } else if (entry.eventType === "writeback_failed" || !entry.success) {
    syncStatus = "discrepancy";
  } else if (entry.eventType === "writeback_undo" && entry.success) {
    syncStatus = "synced";
  }

  const title =
    entry.metadata?.itemTitle || entry.resourceId || "Unknown Item";
  const ticketId = entry.resourceId || "N/A";

  return {
    id: entry.id,
    ticketId,
    title,
    syncStatus,
    syncedAt: entry.createdAt ?? undefined,
    undoable: entry.undoable,
  };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function SyncStatusIcon({ status }: { status: SyncStatus }) {
  switch (status) {
    case "synced":
      return <CheckCircle2 className="h-4 w-4 text-[var(--color-rag-green)]" />;
    case "pending":
      return <Clock className="h-4 w-4 text-[var(--color-rag-amber)]" />;
    case "discrepancy":
      return <AlertTriangle className="h-4 w-4 text-[var(--color-rag-red)]" />;
  }
}

const statusBadgeVariant: Record<SyncStatus, "rag-green" | "rag-amber" | "rag-red"> = {
  synced: "rag-green",
  pending: "rag-amber",
  discrepancy: "rag-red",
};

const statusLabel: Record<SyncStatus, string> = {
  synced: "Synced",
  pending: "Pending",
  discrepancy: "Discrepancy",
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function WritebackConfirmationPanel() {
  const [items, setItems] = useState<WritebackItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [undoing, setUndoing] = useState<string | null>(null);
  const refreshKey = useAutoRefresh([
    "writeback_success",
    "writeback_undo",
    "sync_complete",
  ]);

  const fetchLog = useCallback(async () => {
    try {
      const res = await cachedFetch("/api/writeback/log?limit=20");
      if (res.ok) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const data = res.data as any;
        if (data.entries && data.entries.length > 0) {
          setItems(data.entries.map(apiEntryToItem));
          setLoading(false);
          return;
        }
      }
    } catch {
      // API unavailable — show empty state
    }
    // No write-back entries yet — show empty
    setItems([]);
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchLog();
  }, [fetchLog, refreshKey]);

  const handleUndo = async (itemId: string) => {
    setUndoing(itemId);
    try {
      const res = await fetch("/api/writeback/undo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ auditEntryId: itemId }),
      });
      if (res.ok) {
        // Refresh log after undo
        await fetchLog();
      } else {
        const err = await res.json().catch(() => ({ detail: "Undo failed" }));
        console.error("Undo failed:", err.detail);
      }
    } catch (e) {
      console.error("Undo error:", e);
    } finally {
      setUndoing(null);
    }
  };

  const syncedCount = items.filter((i) => i.syncStatus === "synced").length;
  const pendingCount = items.filter((i) => i.syncStatus === "pending").length;
  const discrepancyCount = items.filter((i) => i.syncStatus === "discrepancy").length;
  const latestUndoable = items.find((i) => i.undoable);

  return (
    <DashboardPanel
      title="Write-back Sync Status"
      icon={RefreshCw}
      collapsible
      actions={
        <Button
          variant="ghost"
          size="sm"
          disabled={!latestUndoable || undoing !== null}
          onClick={() => latestUndoable && handleUndo(latestUndoable.id)}
          className="gap-1.5"
        >
          {undoing ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Undo2 className="h-3.5 w-3.5" />
          )}
          Undo Last Sync
        </Button>
      }
    >
      <div className="space-y-4">
        {/* ── Summary stats ──────────────────────────────────── */}
        <div className="flex flex-wrap items-center gap-3">
          <Badge variant="rag-green">
            <CheckCircle2 className="mr-1 h-3 w-3" />
            {syncedCount} synced
          </Badge>
          <Badge variant="rag-amber">
            <Clock className="mr-1 h-3 w-3" />
            {pendingCount} pending
          </Badge>
          <Badge variant="rag-red">
            <AlertTriangle className="mr-1 h-3 w-3" />
            {discrepancyCount} discrepancies
          </Badge>
        </div>

        {/* ── Item list ──────────────────────────────────────── */}
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-[var(--text-secondary)]" />
          </div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 gap-2">
            <RefreshCw className="h-8 w-8 text-[var(--text-tertiary)]" />
            <p className="text-sm text-[var(--text-secondary)]">
              No write-back activity yet
            </p>
          </div>
        ) : (
          <ul className="space-y-2">
            {items.map((item) => (
              <li
                key={item.id}
                className={cn(
                  "flex items-center justify-between gap-4 rounded-xl px-4 py-3",
                  "bg-[var(--bg-surface-raised)]/60 border border-[var(--border-subtle)]"
                )}
              >
                {/* Left: ticket ID + title */}
                <div className="flex items-center gap-3 min-w-0">
                  <SyncStatusIcon status={item.syncStatus} />
                  <Badge variant="brand" className="shrink-0">
                    {item.ticketId}
                  </Badge>
                  <span className="text-sm text-[var(--text-primary)] truncate">
                    {item.title}
                  </span>
                </div>

                {/* Right: status + time + undo */}
                <div className="flex items-center gap-3 shrink-0">
                  {item.syncedAt && (
                    <span className="text-xs text-[var(--text-secondary)] whitespace-nowrap">
                      {format(new Date(item.syncedAt), "MMM d, yyyy h:mm a")}
                    </span>
                  )}
                  <Badge variant={statusBadgeVariant[item.syncStatus]}>
                    {statusLabel[item.syncStatus]}
                  </Badge>
                  {item.undoable && (
                    <button
                      onClick={() => handleUndo(item.id)}
                      disabled={undoing === item.id}
                      className="flex items-center gap-1 text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer"
                    >
                      {undoing === item.id ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Undo2 className="h-3 w-3" />
                      )}
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </DashboardPanel>
  );
}
