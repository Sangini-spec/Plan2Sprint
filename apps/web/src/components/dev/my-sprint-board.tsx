"use client";

import { useState, useEffect, useCallback } from "react";
import { KanbanSquare, Loader2, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Badge } from "@/components/ui";
import type { WorkItemStatus } from "@/lib/types/models";
import { useAutoRefresh } from "@/lib/ws/context";
import { cachedFetch } from "@/lib/fetch-cache";

interface WorkItemData {
  id: string;
  externalId: string;
  title: string;
  status: WorkItemStatus;
  type: string;
  priority: number;
  storyPoints: number | null;
  assignee: string | null;
  labels: string[];
}

const columns: { key: WorkItemStatus; label: string; color: string }[] = [
  { key: "TODO", label: "To Do", color: "var(--text-secondary)" },
  { key: "IN_PROGRESS", label: "In Progress", color: "var(--color-brand-secondary)" },
  { key: "IN_REVIEW", label: "In Review", color: "var(--color-rag-amber)" },
  { key: "DONE", label: "Done", color: "var(--color-rag-green)" },
];

const priorityLabels: Record<number, { label: string; variant: "rag-red" | "rag-amber" | "brand" }> = {
  1: { label: "P1", variant: "rag-red" },
  2: { label: "P2", variant: "rag-amber" },
  3: { label: "P3", variant: "brand" },
};

export function MySprintBoard() {
  const [items, setItems] = useState<WorkItemData[]>([]);
  const [loading, setLoading] = useState(true);
  const refreshKey = useAutoRefresh(["sync_complete", "writeback_success", "writeback_undo"]);

  const fetchItems = useCallback(async () => {
    setLoading(true);
    try {
      const res = await cachedFetch<{ workItems?: WorkItemData[] }>("/api/dashboard/work-items?limit=100");
      if (res.ok) {
        setItems(res.data?.workItems ?? []);
      } else {
        setItems([]);
      }
    } catch {
      setItems([]);
    }
    setLoading(false);
  }, []);

  useEffect(() => { fetchItems(); }, [fetchItems, refreshKey]);

  if (loading) {
    return (
      <DashboardPanel title="Sprint Board" icon={KanbanSquare}>
        <div className="flex items-center justify-center py-8">
          <Loader2 size={20} className="animate-spin text-[var(--color-brand-secondary)]" />
        </div>
      </DashboardPanel>
    );
  }

  return (
    <DashboardPanel
      title="Sprint Board"
      icon={KanbanSquare}
      actions={
        <button onClick={fetchItems}
          className="flex items-center gap-1 text-[10px] text-[var(--text-tertiary)] hover:text-[var(--color-brand-secondary)] transition-colors cursor-pointer">
          <RefreshCw size={10} /> Refresh
        </button>
      }
    >
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {columns.map((col) => {
          const colItems = items.filter((wi) => wi.status === col.key);
          return (
            <div key={col.key} className="space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div className="h-2 w-2 rounded-full" style={{ backgroundColor: col.color }} />
                  <span className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
                    {col.label}
                  </span>
                </div>
                <span
                  className="flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold"
                  style={{
                    backgroundColor: `color-mix(in srgb, ${col.color} 15%, transparent)`,
                    color: col.color,
                  }}
                >
                  {colItems.length}
                </span>
              </div>

              <div className="space-y-2">
                {colItems.map((item) => {
                  const prio = priorityLabels[item.priority];
                  return (
                    <div
                      key={item.id}
                      className={cn(
                        "rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] p-3",
                        "transition-all duration-200",
                        "hover:border-[var(--color-brand-secondary)]/40 hover:shadow-md hover:shadow-black/5"
                      )}
                    >
                      <p className="text-sm font-medium text-[var(--text-primary)] leading-snug mb-2">
                        {item.title}
                      </p>
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Badge variant="brand" className="text-[10px] px-2 py-0.5">
                          {item.externalId}
                        </Badge>
                        {item.storyPoints != null && (
                          <span className="inline-flex h-5 w-5 items-center justify-center rounded-md bg-[var(--color-brand-secondary)]/10 text-[10px] font-bold text-[var(--color-brand-secondary)]">
                            {item.storyPoints}
                          </span>
                        )}
                        {prio && (
                          <Badge variant={prio.variant} className="text-[10px] px-2 py-0.5">
                            {prio.label}
                          </Badge>
                        )}
                      </div>
                      {item.labels.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-2">
                          {item.labels.map((label) => (
                            <span
                              key={label}
                              className="rounded-md bg-[var(--bg-surface-raised)] border border-[var(--border-subtle)] px-1.5 py-0.5 text-[10px] text-[var(--text-secondary)]"
                            >
                              {label}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
                {colItems.length === 0 && (
                  <div className="rounded-xl border border-dashed border-[var(--border-subtle)] p-4 text-center">
                    <span className="text-xs text-[var(--text-secondary)]">No items</span>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </DashboardPanel>
  );
}
