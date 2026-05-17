"use client";

import { useState, useEffect, useCallback } from "react";
import {
  History,
  Calendar,
  Loader2,
} from "lucide-react";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Badge } from "@/components/ui";
import { useSelectedProject } from "@/lib/project/context";
import { useAutoRefresh } from "@/lib/ws/context";
import { cachedFetch } from "@/lib/fetch-cache";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ArchivedRetro {
  id: string;
  iterationName: string;
  sprintNumber: number | null;
  startDate: string | null;
  endDate: string | null;
  conclusion: string;
  failureClassification: string | null;
  finalizedAt: string | null;
}

const classificationLabels: Record<string, string> = {
  OVERCOMMITMENT: "Overcommitment",
  EXECUTION: "Execution",
  DEPENDENCY: "Dependency",
  CAPACITY: "Capacity",
  SCOPE_CREEP: "Scope Creep",
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function SprintHistoryTimeline() {
  const { selectedProject } = useSelectedProject();
  const [items, setItems] = useState<ArchivedRetro[]>([]);
  const [loading, setLoading] = useState(true);
  const refreshKey = useAutoRefresh(["sync_complete", "sprint_completed"]);
  const projectId = selectedProject?.internalId;

  const fetchHistory = useCallback(async () => {
    setLoading(true);
    try {
      const q = projectId ? `?projectId=${projectId}` : "";
      const res = await cachedFetch(`/api/retrospectives/history${q}`);
      if (res.ok) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const data = res.data as any;
        setItems(data.history ?? []);
      }
    } catch {
      // non-critical
    }
    setLoading(false);
  }, [projectId]);

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory, refreshKey]);

  // Don't render if loading or no history
  if (loading) {
    return (
      <DashboardPanel title="Sprint History" icon={History} collapsible>
        <div className="flex items-center justify-center py-6">
          <Loader2 size={18} className="animate-spin text-[var(--color-brand-secondary)]" />
        </div>
      </DashboardPanel>
    );
  }

  if (items.length === 0) {
    return null; // Don't show the panel if there's no history
  }

  return (
    <DashboardPanel title="Sprint History" icon={History} collapsible>
      <div className="space-y-2">
        {items.map((retro, idx) => {
          const sprintLabel = retro.sprintNumber
            ? `Sprint ${retro.sprintNumber}`
            : retro.iterationName || "Sprint";

          return (
            <div
              key={retro.id}
              className="flex items-center gap-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/40 px-3 py-2.5"
            >
              {/* Timeline dot */}
              <div className="flex flex-col items-center shrink-0">
                <span className="h-2.5 w-2.5 rounded-full bg-[var(--text-tertiary)]" />
                {idx < items.length - 1 && (
                  <span className="w-px h-3 bg-[var(--border-subtle)] mt-0.5" />
                )}
              </div>

              {/* Sprint label + conclusion */}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 mb-0.5">
                  <span className="text-sm font-medium text-[var(--text-primary)]">
                    {sprintLabel}
                  </span>
                  {retro.failureClassification && (
                    <Badge variant="rag-amber" className="text-[9px]">
                      {classificationLabels[retro.failureClassification] ?? retro.failureClassification}
                    </Badge>
                  )}
                </div>
                <p className="text-xs text-[var(--text-secondary)] leading-snug">
                  {retro.conclusion}
                </p>
                {retro.startDate && retro.endDate && (
                  <span className="flex items-center gap-1 text-[10px] text-[var(--text-tertiary)] mt-0.5">
                    <Calendar className="h-2.5 w-2.5" />
                    {formatDate(retro.startDate)} - {formatDate(retro.endDate)}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </DashboardPanel>
  );
}
