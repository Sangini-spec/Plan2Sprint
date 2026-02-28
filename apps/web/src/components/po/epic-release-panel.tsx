"use client";

import { Milestone, CheckCircle2, Clock, AlertTriangle } from "lucide-react";
import { format } from "date-fns";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { RagIndicator } from "@/components/dashboard/rag-indicator";
import { Badge, Progress } from "@/components/ui";
import type { HealthSeverity } from "@/lib/types/models";

// ---------------------------------------------------------------------------
// Local mock data
// ---------------------------------------------------------------------------

interface Epic {
  id: string;
  name: string;
  totalTickets: number;
  completedTickets: number;
  projectedCompletion: string;
  riskFlag: HealthSeverity;
}

interface MilestoneItem {
  id: string;
  name: string;
  date: string;
  status: HealthSeverity;
}

const epics: Epic[] = [
  { id: "e-1", name: "Checkout Redesign", totalTickets: 24, completedTickets: 18, projectedCompletion: "2026-03-07", riskFlag: "GREEN" as const },
  { id: "e-2", name: "Search V2", totalTickets: 32, completedTickets: 14, projectedCompletion: "2026-04-15", riskFlag: "AMBER" as const },
  { id: "e-3", name: "Mobile App V3", totalTickets: 40, completedTickets: 12, projectedCompletion: "2026-05-01", riskFlag: "RED" as const },
  { id: "e-4", name: "Real-time Analytics", totalTickets: 18, completedTickets: 15, projectedCompletion: "2026-02-28", riskFlag: "GREEN" as const },
];

const milestones: MilestoneItem[] = [
  { id: "m-1", name: "Checkout Beta Launch", date: "2026-03-01", status: "GREEN" as const },
  { id: "m-2", name: "Search V2 Alpha", date: "2026-03-15", status: "AMBER" as const },
  { id: "m-3", name: "Mobile V3 TestFlight", date: "2026-04-01", status: "RED" as const },
  { id: "m-4", name: "Analytics Dashboard GA", date: "2026-02-28", status: "GREEN" as const },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const severityToBadge: Record<HealthSeverity, "rag-green" | "rag-amber" | "rag-red"> = {
  GREEN: "rag-green",
  AMBER: "rag-amber",
  RED: "rag-red",
};

function MilestoneStatusIcon({ status }: { status: HealthSeverity }) {
  switch (status) {
    case "GREEN":
      return <CheckCircle2 className="h-4 w-4 text-[var(--color-rag-green)]" />;
    case "AMBER":
      return <Clock className="h-4 w-4 text-[var(--color-rag-amber)]" />;
    case "RED":
      return <AlertTriangle className="h-4 w-4 text-[var(--color-rag-red)]" />;
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function EpicReleasePanel() {
  return (
    <DashboardPanel
      title="Epic & Release Tracking"
      icon={Milestone}
      collapsible
    >
      <div className="space-y-6">
        {/* ── Epics table ────────────────────────────────────── */}
        <div>
          <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3">
            Epics
          </h3>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border-subtle)]">
                  <th className="pb-2 text-left font-medium text-[var(--text-secondary)]">
                    Epic
                  </th>
                  <th className="pb-2 text-left font-medium text-[var(--text-secondary)] min-w-[140px]">
                    Progress
                  </th>
                  <th className="pb-2 text-left font-medium text-[var(--text-secondary)]">
                    Projected
                  </th>
                  <th className="pb-2 text-left font-medium text-[var(--text-secondary)]">
                    Risk
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border-subtle)]">
                {epics.map((epic) => {
                  const pct = Math.round(
                    (epic.completedTickets / epic.totalTickets) * 100
                  );
                  return (
                    <tr key={epic.id}>
                      <td className="py-3 pr-4">
                        <span className="font-medium text-[var(--text-primary)]">
                          {epic.name}
                        </span>
                      </td>
                      <td className="py-3 pr-4">
                        <div className="flex items-center gap-2">
                          <Progress
                            value={epic.completedTickets}
                            max={epic.totalTickets}
                            severity={epic.riskFlag}
                            size="sm"
                            className="flex-1"
                          />
                          <span className="text-xs tabular-nums text-[var(--text-secondary)] whitespace-nowrap">
                            {epic.completedTickets}/{epic.totalTickets} ({pct}%)
                          </span>
                        </div>
                      </td>
                      <td className="py-3 pr-4 text-[var(--text-secondary)] whitespace-nowrap">
                        {format(new Date(epic.projectedCompletion), "MMM d, yyyy")}
                      </td>
                      <td className="py-3">
                        <RagIndicator severity={epic.riskFlag} size="sm" />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* ── Milestones list ────────────────────────────────── */}
        <div>
          <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3">
            Milestones
          </h3>

          <ul className="space-y-2">
            {milestones.map((ms) => (
              <li
                key={ms.id}
                className={cn(
                  "flex items-center justify-between rounded-xl px-4 py-3",
                  "bg-[var(--bg-surface-raised)]/60 border border-[var(--border-subtle)]"
                )}
              >
                <div className="flex items-center gap-3">
                  <MilestoneStatusIcon status={ms.status} />
                  <span className="text-sm font-medium text-[var(--text-primary)]">
                    {ms.name}
                  </span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-[var(--text-secondary)]">
                    {format(new Date(ms.date), "MMM d, yyyy")}
                  </span>
                  <Badge variant={severityToBadge[ms.status]}>
                    {ms.status === "GREEN"
                      ? "On Track"
                      : ms.status === "AMBER"
                        ? "At Risk"
                        : "Critical"}
                  </Badge>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </DashboardPanel>
  );
}
