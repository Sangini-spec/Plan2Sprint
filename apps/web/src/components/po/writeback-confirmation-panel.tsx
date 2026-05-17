"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import {
  MessageSquare,
  CheckCircle2,
  Clock,
  XCircle,
  Loader2,
  Search,
  ChevronDown,
} from "lucide-react";
import { format } from "date-fns";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Badge, Input } from "@/components/ui";
import { useAutoRefresh } from "@/lib/ws/context";
import { cachedFetch } from "@/lib/fetch-cache";
import { useSelectedProject } from "@/lib/project/context";

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
    action?: string;
    commentSummary?: {
      recommendedSprint?: number;
      aiEstimatedSP?: number;
      confidence?: number;
      riskFlags?: string[];
    };
    error?: string;
  } | null;
  createdAt: string | null;
  undoable: boolean;
}

// ---------------------------------------------------------------------------
// Local types
// ---------------------------------------------------------------------------

type SyncStatus = "commented" | "synced" | "pending" | "failed";

interface WritebackItem {
  id: string;
  ticketId: string;
  title: string;
  syncStatus: SyncStatus;
  syncedAt: string | undefined;
}

function apiEntryToItem(entry: WritebackEntry): WritebackItem {
  let syncStatus: SyncStatus = "pending";

  // New comment-based entries
  if (entry.eventType === "comment_posted" && entry.success) {
    syncStatus = "commented";
  } else if (entry.eventType === "comment_failed" || !entry.success) {
    syncStatus = "failed";
  }
  // Legacy field-based entries (backward compat)
  else if (entry.eventType === "writeback" && entry.success) {
    syncStatus = "synced";
  } else if (entry.eventType === "writeback_failed") {
    syncStatus = "failed";
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
  };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const INITIAL_VISIBLE = 6;
const LOAD_MORE_INCREMENT = 10;

function SyncStatusIcon({ status }: { status: SyncStatus }) {
  switch (status) {
    case "commented":
      return <MessageSquare className="h-4 w-4 text-[var(--color-rag-green)]" />;
    case "synced":
      return <CheckCircle2 className="h-4 w-4 text-[var(--color-rag-green)]" />;
    case "pending":
      return <Clock className="h-4 w-4 text-[var(--color-rag-amber)]" />;
    case "failed":
      return <XCircle className="h-4 w-4 text-[var(--color-rag-red)]" />;
  }
}

const statusBadgeVariant: Record<SyncStatus, "rag-green" | "rag-amber" | "rag-red"> = {
  commented: "rag-green",
  synced: "rag-green",
  pending: "rag-amber",
  failed: "rag-red",
};

const statusLabel: Record<SyncStatus, string> = {
  commented: "Commented",
  synced: "Synced",
  pending: "Pending",
  failed: "Failed",
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function WritebackConfirmationPanel() {
  const [items, setItems] = useState<WritebackItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [visibleCount, setVisibleCount] = useState(INITIAL_VISIBLE);
  const { selectedProject } = useSelectedProject();
  const projectId = selectedProject?.internalId;
  const refreshKey = useAutoRefresh([
    "writeback_success",
    "sync_complete",
    "comment_posted",
  ]);

  const fetchLog = useCallback(async () => {
    try {
      const q = projectId ? `&projectId=${projectId}` : "";
      const res = await cachedFetch(`/api/writeback/log?limit=20${q}`);
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
      // API unavailable - show empty state
    }
    setItems([]);
    setLoading(false);
  }, [projectId]);

  useEffect(() => {
    fetchLog();
  }, [fetchLog, refreshKey]);

  // Reset visible count when search changes
  useEffect(() => {
    setVisibleCount(INITIAL_VISIBLE);
  }, [searchQuery]);

  // Filter items by search query
  const filteredItems = useMemo(() => {
    if (!searchQuery.trim()) return items;
    const q = searchQuery.toLowerCase();
    return items.filter(
      (item) =>
        item.ticketId.toLowerCase().includes(q) ||
        item.title.toLowerCase().includes(q) ||
        item.syncStatus.toLowerCase().includes(q)
    );
  }, [items, searchQuery]);

  const visibleItems = filteredItems.slice(0, visibleCount);
  const hasMore = visibleCount < filteredItems.length;
  const remainingCount = filteredItems.length - visibleCount;

  const commentedCount = items.filter(
    (i) => i.syncStatus === "commented" || i.syncStatus === "synced"
  ).length;
  const pendingCount = items.filter((i) => i.syncStatus === "pending").length;
  const failedCount = items.filter((i) => i.syncStatus === "failed").length;

  return (
    <DashboardPanel
      title="AI Comment Sync Status"
      icon={MessageSquare}
      collapsible
    >
      <div className="space-y-4">
        {/* ── Summary stats ──────────────────────────────────── */}
        <div className="flex flex-wrap items-center gap-3">
          <Badge variant="rag-green">
            <CheckCircle2 className="mr-1 h-3 w-3" />
            {commentedCount} commented
          </Badge>
          <Badge variant="rag-amber">
            <Clock className="mr-1 h-3 w-3" />
            {pendingCount} pending
          </Badge>
          <Badge variant="rag-red">
            <XCircle className="mr-1 h-3 w-3" />
            {failedCount} failed
          </Badge>
          {items.length > 0 && (
            <span className="text-xs text-[var(--text-secondary)] ml-auto">
              {filteredItems.length} of {items.length} records
            </span>
          )}
        </div>

        {/* ── Search bar ─────────────────────────────────────── */}
        {items.length > 0 && (
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-[var(--text-secondary)] pointer-events-none" />
            <Input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search by ticket ID, title, or status..."
              className="pl-9 h-9 text-sm"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery("")}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer"
              >
                <span className="text-xs">Clear</span>
              </button>
            )}
          </div>
        )}

        {/* ── Item list ──────────────────────────────────────── */}
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-[var(--text-secondary)]" />
          </div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 gap-2">
            <MessageSquare className="h-8 w-8 text-[var(--text-tertiary)]" />
            <p className="text-sm text-[var(--text-secondary)]">
              No AI comment activity yet
            </p>
          </div>
        ) : filteredItems.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-6 gap-2">
            <Search className="h-6 w-6 text-[var(--text-tertiary)]" />
            <p className="text-sm text-[var(--text-secondary)]">
              No records match &ldquo;{searchQuery}&rdquo;
            </p>
          </div>
        ) : (
          <>
            <ul className="space-y-2">
              {visibleItems.map((item) => (
                <li
                  key={item.id}
                  className={cn(
                    "flex items-center justify-between gap-4 rounded-lg px-4 py-2.5",
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

                  {/* Right: status + time */}
                  <div className="flex items-center gap-3 shrink-0">
                    {item.syncedAt && (
                      <span className="text-xs text-[var(--text-secondary)] whitespace-nowrap">
                        {format(new Date(item.syncedAt), "MMM d, yyyy h:mm a")}
                      </span>
                    )}
                    <Badge variant={statusBadgeVariant[item.syncStatus]}>
                      {statusLabel[item.syncStatus]}
                    </Badge>
                  </div>
                </li>
              ))}
            </ul>

            {/* ── Show More button ──────────────────────────────── */}
            {hasMore && (
              <div className="flex justify-center pt-1">
                <button
                  onClick={() =>
                    setVisibleCount((prev) => prev + LOAD_MORE_INCREMENT)
                  }
                  className="flex items-center gap-1.5 text-sm font-medium text-[var(--color-brand-secondary)] hover:text-[var(--color-brand-secondary)]/80 transition-colors cursor-pointer px-4 py-2 rounded-lg hover:bg-[var(--color-brand-secondary)]/5"
                >
                  <ChevronDown className="h-4 w-4" />
                  Show more ({remainingCount} remaining)
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </DashboardPanel>
  );
}
