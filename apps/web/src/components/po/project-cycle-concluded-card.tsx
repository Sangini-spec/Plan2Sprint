"use client";

/**
 * Project Cycle Concluded card (Hotfix 83).
 *
 * Surfaces a warning at the top of the Retrospective page when the
 * selected project has passed its target launch date. Renders nothing
 * for healthy projects, so the card disappears automatically once a PO
 * sets a new target via the dashboard or approves a fresh plan.
 *
 * Pulls the same data shape that the overdue email uses
 * (services/overdue_alert.py → routers/retrospectives._build_project_summary)
 * so the in-app card and the email body always reflect identical stats.
 */

import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronUp, ExternalLink } from "lucide-react";
import { useSelectedProject } from "@/lib/project/context";
import { useAutoRefresh } from "@/lib/ws/context";
import { Button } from "@/components/ui";
import { cn } from "@/lib/utils";

type LifecycleStatus = "on_track" | "overdue" | "delivered_late";

interface ProjectSummary {
  projectId: string;
  projectName: string;
  lifecycleStatus: LifecycleStatus;
  daysPastTarget: number;
  targetLaunchDate: string | null;
  completionPct: number;
  totals: {
    stories: number;
    completed: number;
    inProgress: number;
    notStarted: number;
  };
  completedItems: { title: string; ticketId?: string }[];
  outstandingItems: { title: string; ticketId?: string; status?: string; phase?: string | null }[];
  outstandingPhases: { slug: string; name: string; outstandingCount: number }[];
}

function fmtDateShort(iso: string | null): string {
  if (!iso) return "(unknown)";
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      month: "short", day: "numeric", year: "numeric", timeZone: "UTC",
    });
  } catch {
    return "(unknown)";
  }
}

export function ProjectCycleConcludedCard() {
  const { selectedProject } = useSelectedProject();
  const projectId = selectedProject?.internalId ?? "";
  const [data, setData] = useState<ProjectSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [completedOpen, setCompletedOpen] = useState(false);
  const [outstandingOpen, setOutstandingOpen] = useState(true);

  // Auto-refresh on the same WS events the hero banner listens to so the
  // moment a new plan is approved or the target date is changed, this card
  // re-fetches and disappears.
  const wsKey = useAutoRefresh([
    "sprint_plan_generated", "sprint_plan_updated", "work_item_updated",
    "sync_complete",
  ]);

  useEffect(() => {
    if (!projectId) { setData(null); return; }
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const res = await fetch(
          `/api/retrospectives/project-summary?projectId=${projectId}`
        );
        if (res.ok && !cancelled) {
          setData(await res.json());
        }
      } catch { /* fail closed - no card */ }
      if (!cancelled) setLoading(false);
    })();
    return () => { cancelled = true; };
  }, [projectId, wsKey]);

  // Only render for projects that have actually crossed the line.
  if (loading || !data || data.lifecycleStatus === "on_track") return null;

  const isOverdue = data.lifecycleStatus === "overdue";
  const accent = isOverdue ? "rag-red" : "rag-amber";
  const accentVar = `var(--color-${accent})`;
  const headline = isOverdue
    ? `Project Cycle Concluded - Overdue`
    : `Project Cycle Concluded - Delivered Late`;
  const explainer = isOverdue
    ? `${data.projectName} was scheduled to launch on ${fmtDateShort(data.targetLaunchDate)}. That date has now passed ${data.daysPastTarget} day${data.daysPastTarget === 1 ? "" : "s"} ago with the project at ${data.completionPct}% complete. All sprints scheduled before this date have run their course; outstanding work is summarised below. Generate a new plan with a fresh launch date to clear this alert.`
    : `${data.projectName} reached 100% completion, but landed ${data.daysPastTarget} day${data.daysPastTarget === 1 ? "" : "s"} past its committed launch (${fmtDateShort(data.targetLaunchDate)}). Useful context for the post-mortem; update the target date when the next plan is set.`;

  return (
    <div
      className="rounded-xl border-2 overflow-hidden"
      style={{
        borderColor: accentVar,
        background: `color-mix(in srgb, ${accentVar} 5%, var(--bg-surface))`,
      }}
    >
      {/* Header */}
      <div
        className="px-5 py-4 flex items-start gap-3"
        style={{
          background: `color-mix(in srgb, ${accentVar} 12%, transparent)`,
          borderBottom: `1px solid color-mix(in srgb, ${accentVar} 25%, transparent)`,
        }}
      >
        <AlertTriangle
          className="h-5 w-5 shrink-0 mt-0.5"
          style={{ color: accentVar }}
        />
        <div className="flex-1 min-w-0">
          <h2
            className="text-base font-bold leading-tight"
            style={{ color: accentVar }}
          >
            {headline}
          </h2>
          <p className="text-sm text-[var(--text-secondary)] mt-1 leading-relaxed">
            {explainer}
          </p>
        </div>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 p-4 bg-[var(--bg-surface-raised)]/30">
        <Stat label="Total stories" value={data.totals.stories} />
        <Stat label="Completed" value={data.totals.completed} tone="green" />
        <Stat label="In progress" value={data.totals.inProgress} tone="amber" />
        <Stat label="Not started" value={data.totals.notStarted} tone="red" />
      </div>

      {/* Outstanding phases */}
      {data.outstandingPhases.length > 0 && (
        <div className="px-5 py-3 border-t border-[var(--border-subtle)]">
          <div className="text-[11px] font-bold uppercase tracking-widest text-[var(--text-secondary)] mb-2">
            Where the work sits
          </div>
          <ul className="text-sm text-[var(--text-primary)] space-y-1">
            {data.outstandingPhases.map((p) => (
              <li key={p.slug} className="flex items-center justify-between">
                <span className="font-medium">{p.name}</span>
                <span className="text-xs text-[var(--text-secondary)]">
                  {p.outstandingCount} item{p.outstandingCount === 1 ? "" : "s"} in flight
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Outstanding items list */}
      {data.outstandingItems.length > 0 && (
        <CollapsibleList
          title={`What is still left (${data.outstandingItems.length})`}
          isOpen={outstandingOpen}
          onToggle={() => setOutstandingOpen((v) => !v)}
          items={data.outstandingItems.map((i) => ({
            label: i.title,
            badge: i.ticketId,
            sub: i.status,
          }))}
          color={accentVar}
        />
      )}

      {/* Completed items list */}
      {data.completedItems.length > 0 && (
        <CollapsibleList
          title={`What was completed (${data.completedItems.length})`}
          isOpen={completedOpen}
          onToggle={() => setCompletedOpen((v) => !v)}
          items={data.completedItems.map((i) => ({
            label: i.title,
            badge: i.ticketId,
          }))}
          color="var(--color-rag-green)"
          icon={CheckCircle2}
        />
      )}

      {/* CTA */}
      <div className="px-5 py-4 flex items-center justify-between border-t border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/40">
        <p className="text-xs text-[var(--text-secondary)]">
          {isOverdue
            ? "This alert clears as soon as a new target launch date is set."
            : "Captured for the retrospective record. Update the target when the next plan is set."}
        </p>
        <a href="/po/planning">
          <Button size="sm" variant="primary">
            Generate New Plan
            <ExternalLink className="ml-1.5 h-3.5 w-3.5" />
          </Button>
        </a>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "green" | "amber" | "red";
}) {
  const colorMap = {
    green: "var(--color-rag-green)",
    amber: "var(--color-rag-amber)",
    red: "var(--color-rag-red)",
  } as const;
  const color = tone ? colorMap[tone] : "var(--text-primary)";
  return (
    <div className="rounded-lg p-3 text-center bg-[var(--bg-surface)]/60">
      <div
        className="text-2xl font-bold tabular-nums leading-tight"
        style={{ color }}
      >
        {value}
      </div>
      <div className="text-[10px] font-medium uppercase tracking-wider mt-0.5 text-[var(--text-secondary)]">
        {label}
      </div>
    </div>
  );
}

function CollapsibleList({
  title,
  isOpen,
  onToggle,
  items,
  color,
  icon: Icon,
}: {
  title: string;
  isOpen: boolean;
  onToggle: () => void;
  items: { label: string; badge?: string; sub?: string }[];
  color: string;
  icon?: React.ComponentType<{ className?: string }>;
}) {
  return (
    <div className="border-t border-[var(--border-subtle)]">
      <button
        onClick={onToggle}
        className="w-full px-5 py-3 flex items-center justify-between text-left hover:bg-[var(--bg-surface-raised)]/40 transition-colors cursor-pointer"
      >
        <div className="flex items-center gap-2">
          {Icon ? <Icon className="h-4 w-4" /> : null}
          <span
            className="text-[11px] font-bold uppercase tracking-widest"
            style={{ color }}
          >
            {title}
          </span>
        </div>
        {isOpen ? <ChevronUp className="h-4 w-4 text-[var(--text-tertiary)]" /> : <ChevronDown className="h-4 w-4 text-[var(--text-tertiary)]" />}
      </button>
      {isOpen && (
        <ul className="px-5 pb-3 space-y-1.5 max-h-64 overflow-y-auto">
          {items.map((it, i) => (
            <li
              key={`${it.label}-${i}`}
              className="text-sm text-[var(--text-primary)] flex flex-wrap items-center gap-2"
            >
              <span>{it.label}</span>
              {it.badge && (
                <span className="text-[10px] font-mono text-[var(--text-tertiary)]">
                  #{it.badge}
                </span>
              )}
              {it.sub && (
                <span className="text-[10px] text-[var(--text-tertiary)]">
                  · {it.sub}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
