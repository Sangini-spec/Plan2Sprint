"use client";

import { useState, useEffect, useCallback } from "react";
import { AlertTriangle, CheckCircle2, ShieldAlert, ArrowUpRight, Loader2 } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Badge, Button } from "@/components/ui";
import type { BlockerStatus } from "@/lib/types/models";
import { useAutoRefresh } from "@/lib/ws/context";
import { cachedFetch } from "@/lib/fetch-cache";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface BlockerData {
  id: string;
  description: string;
  status: BlockerStatus;
  ticketReference?: string;
  flaggedAt: string;
  flaggedBy: string;
  resolvedAt?: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const statusBadgeVariant: Record<BlockerStatus, "rag-red" | "rag-amber" | "rag-green" | "brand"> = {
  OPEN: "rag-red",
  ACKNOWLEDGED: "rag-amber",
  ESCALATED: "rag-amber",
  RESOLVED: "rag-green",
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function BlockerActionPanel() {
  const [blockers, setBlockers] = useState<BlockerData[]>([]);
  const [loading, setLoading] = useState(true);
  const refreshKey = useAutoRefresh(["sync_complete", "standup_generated", "github_activity"]);

  const fetchBlockers = useCallback(async () => {
    setLoading(true);
    try {
      const res = await cachedFetch("/api/standups");
      if (res.ok) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const data = res.data as any;
        // Extract blockers from individual reports
        const extracted: BlockerData[] = [];
        const reports = data.individualReports ?? [];
        for (const report of reports) {
          if (report.blockers && Array.isArray(report.blockers)) {
            for (const b of report.blockers) {
              extracted.push({
                id: b.id ?? `blocker-${extracted.length}`,
                description: b.description ?? "Unknown blocker",
                status: (b.status as BlockerStatus) ?? "OPEN",
                ticketReference: b.ticketReference,
                flaggedAt: b.flaggedAt ?? report.reportDate ?? new Date().toISOString(),
                flaggedBy: report.displayName ?? report.teamMember ?? "Unknown",
                resolvedAt: b.resolvedAt,
              });
            }
          }
        }
        setBlockers(extracted);
      } else {
        setBlockers([]);
      }
    } catch {
      setBlockers([]);
    }
    setLoading(false);
  }, []);

  useEffect(() => { fetchBlockers(); }, [fetchBlockers, refreshKey]);

  const updateStatus = useCallback(async (id: string, newStatus: BlockerStatus) => {
    // Optimistic update
    setBlockers((prev) =>
      prev.map((b) =>
        b.id === id
          ? {
              ...b,
              status: newStatus,
              ...(newStatus === "RESOLVED" ? { resolvedAt: new Date().toISOString() } : {}),
            }
          : b
      )
    );

    // Call backend to persist the status change
    try {
      await fetch("/api/standups/blocker", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          blockerId: id,
          status: newStatus,
        }),
      });
    } catch {
      // Revert on failure
      fetchBlockers();
    }
  }, [fetchBlockers]);

  // Active blockers are those that are not yet resolved
  const activeBlockers = blockers.filter((b) => b.status !== "RESOLVED");

  if (loading) {
    return (
      <DashboardPanel title="Active Blockers" icon={AlertTriangle}>
        <div className="flex items-center justify-center py-8">
          <Loader2 size={20} className="animate-spin text-[var(--color-brand-secondary)]" />
        </div>
      </DashboardPanel>
    );
  }

  return (
    <DashboardPanel title="Active Blockers" icon={AlertTriangle}>
      {activeBlockers.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-8 gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-[var(--color-rag-green)]/10">
            <CheckCircle2 className="h-6 w-6 text-[var(--color-rag-green)]" />
          </div>
          <p className="text-sm font-medium text-[var(--color-rag-green)]">
            No active blockers
          </p>
          <p className="text-xs text-[var(--text-secondary)]">
            {blockers.length > 0 ? "All blockers have been resolved." : "No blockers have been reported yet."}
          </p>
        </div>
      ) : (
        <ul className="space-y-3">
          {activeBlockers.map((blocker) => {
            const relativeTime = formatDistanceToNow(
              new Date(blocker.flaggedAt),
              { addSuffix: true }
            );

            return (
              <li
                key={blocker.id}
                className={cn(
                  "rounded-xl border border-[var(--border-subtle)] p-4",
                  "bg-[var(--bg-surface-raised)]/60"
                )}
              >
                <p className="text-sm font-medium text-[var(--text-primary)] mb-2">
                  {blocker.description}
                </p>

                <div className="flex flex-wrap items-center gap-2 mb-3">
                  {blocker.ticketReference && (
                    <Badge variant="brand">{blocker.ticketReference}</Badge>
                  )}
                  <Badge variant={statusBadgeVariant[blocker.status]}>
                    {blocker.status}
                  </Badge>
                  <span className="text-xs text-[var(--text-secondary)]">
                    Flagged by {blocker.flaggedBy}
                  </span>
                  <span className="text-xs text-[var(--text-secondary)]">
                    &middot; {relativeTime}
                  </span>
                </div>

                <div className="flex items-center gap-2">
                  {blocker.status === "OPEN" && (
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => updateStatus(blocker.id, "ACKNOWLEDGED")}
                    >
                      Acknowledge
                    </Button>
                  )}
                  <Button
                    variant="secondary"
                    size="sm"
                    className="border-[var(--color-rag-amber)]/40 text-[var(--color-rag-amber)] hover:bg-[var(--color-rag-amber)]/10"
                    onClick={() => updateStatus(blocker.id, "ESCALATED")}
                  >
                    <ArrowUpRight className="mr-1 h-3.5 w-3.5" />
                    Escalate
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    className="border-[var(--color-rag-green)]/40 text-[var(--color-rag-green)] hover:bg-[var(--color-rag-green)]/10"
                    onClick={() => updateStatus(blocker.id, "RESOLVED")}
                  >
                    <ShieldAlert className="mr-1 h-3.5 w-3.5" />
                    Resolve
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </DashboardPanel>
  );
}
