"use client";

import { useState } from "react";
import {
  Calendar,
  AlertTriangle,
  Info,
  Users,
  Sparkles,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge, Progress } from "@/components/ui";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CapacityRecommendations {
  team_utilization_pct: number;
  understaffed: boolean;
  recommended_additions: number;
  bottleneck_skills: string[];
  summary: string;
}

interface Assignment {
  suggestedPriority?: number | null;
  storyPoints: number;
  riskFlags: string[];
  teamMemberId: string;
  sprintNumber: number;
}

interface TeamMemberData {
  id: string;
  displayName: string;
  defaultCapacity: number;
}

interface AIInsightsPanelProps {
  estimatedSprints: number | null;
  estimatedWeeksTotal: number | null;
  estimatedEndDate: string | null;
  projectCompletionSummary: string | null;
  capacityRecommendations: CapacityRecommendations | null;
  totalStoryPoints: number | null;
  riskSummary: string | null;
  assignments: Assignment[];
  teamMembers: TeamMemberData[];
  overallRationale: string | null;
}

// ---------------------------------------------------------------------------
// Component — Horizontal full-width overview (collapsible)
// ---------------------------------------------------------------------------

export function AIInsightsPanel({
  estimatedSprints,
  estimatedWeeksTotal,
  estimatedEndDate,
  projectCompletionSummary,
  capacityRecommendations,
  totalStoryPoints,
  riskSummary,
  assignments,
  teamMembers,
  overallRationale,
}: AIInsightsPanelProps) {
  const [expanded, setExpanded] = useState(true);

  // Calculate per-developer load
  const devLoad = new Map<string, number>();
  for (const a of assignments) {
    devLoad.set(
      a.teamMemberId,
      (devLoad.get(a.teamMemberId) || 0) + a.storyPoints
    );
  }

  // Count suggested priorities
  const suggestedPriorityCount = assignments.filter(
    (a) => a.suggestedPriority != null
  ).length;

  // Aggregate risk flags
  const riskCounts = new Map<string, number>();
  for (const a of assignments) {
    for (const f of a.riskFlags) {
      riskCounts.set(f, (riskCounts.get(f) || 0) + 1);
    }
  }

  const cap = capacityRecommendations;
  const utilPct = cap?.team_utilization_pct ?? 0;

  // Determine whether there's meaningful content to show
  const hasRisks = riskCounts.size > 0;
  const hasMissingData = suggestedPriorityCount > 0;
  const hasCapacity = !!cap;
  const hasRecommendations = !!(cap?.summary || overallRationale);

  return (
    <div className="border-b border-[var(--border-subtle)] bg-[var(--bg-surface)]">
      {/* Toggle header */}
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className="w-full flex items-center justify-between px-5 py-2.5 hover:bg-[var(--bg-surface-sunken)]/50 transition-colors cursor-pointer"
      >
        <span className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
          <Sparkles className="h-3.5 w-3.5 text-[var(--color-brand-secondary)]" />
          Plan2Sprint Insights
        </span>
        {expanded ? (
          <ChevronUp className="h-3.5 w-3.5 text-[var(--text-secondary)]" />
        ) : (
          <ChevronDown className="h-3.5 w-3.5 text-[var(--text-secondary)]" />
        )}
      </button>

      {/* Collapsible content */}
      <div
        className={cn(
          "transition-all duration-200 overflow-hidden",
          expanded ? "max-h-[600px] opacity-100" : "max-h-0 opacity-0"
        )}
      >
        <div className="px-5 pb-4 pt-1">
          {/* Row of cards — responsive grid layout */}
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
            {/* Card 1: Project Summary */}
            <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-sunken)] p-3 space-y-2">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-[var(--text-primary)]">
                <Calendar className="h-3.5 w-3.5" />
                Project Summary
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <p className="text-[10px] text-[var(--text-secondary)] uppercase">
                    Sprints
                  </p>
                  <p className="text-sm font-semibold tabular-nums text-[var(--text-primary)]">
                    {estimatedSprints ?? "\u2014"}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] text-[var(--text-secondary)] uppercase">
                    Weeks
                  </p>
                  <p className="text-sm font-semibold tabular-nums text-[var(--text-primary)]">
                    ~{estimatedWeeksTotal ?? "\u2014"}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] text-[var(--text-secondary)] uppercase">
                    Total SP
                  </p>
                  <p className="text-sm font-semibold tabular-nums text-[var(--text-primary)]">
                    {totalStoryPoints ?? "\u2014"}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] text-[var(--text-secondary)] uppercase">
                    Est. Done
                  </p>
                  <p className="text-xs font-semibold text-[var(--text-primary)]">
                    {estimatedEndDate
                      ? new Date(estimatedEndDate).toLocaleDateString("en-US", {
                          month: "short",
                          day: "numeric",
                        })
                      : "\u2014"}
                  </p>
                </div>
              </div>
              {projectCompletionSummary && (
                <p className="text-[11px] text-[var(--text-secondary)] leading-relaxed">
                  {projectCompletionSummary}
                </p>
              )}
            </div>

            {/* Card 2: Team Capacity */}
            <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-sunken)] p-3 space-y-2">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-[var(--text-primary)]">
                <Users className="h-3.5 w-3.5" />
                Team Capacity
              </div>

              {/* Utilization bar */}
              {hasCapacity && (
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] text-[var(--text-secondary)]">
                      Utilization
                    </span>
                    <span
                      className={cn(
                        "text-xs font-semibold tabular-nums",
                        utilPct > 90
                          ? "text-[var(--color-rag-red)]"
                          : utilPct > 70
                            ? "text-[var(--color-rag-amber)]"
                            : "text-[var(--color-rag-green)]"
                      )}
                    >
                      {utilPct}%
                    </span>
                  </div>
                  <Progress
                    value={utilPct}
                    severity={
                      utilPct > 90
                        ? "RED"
                        : utilPct > 70
                          ? "AMBER"
                          : "GREEN"
                    }
                    size="sm"
                  />
                  {cap!.understaffed && (
                    <p className="text-[11px] text-[var(--color-rag-red)]">
                      Team is understaffed for this backlog
                    </p>
                  )}
                  {cap!.bottleneck_skills.length > 0 && (
                    <div className="flex items-center gap-1 flex-wrap">
                      <span className="text-[10px] text-[var(--text-secondary)]">
                        Bottlenecks:
                      </span>
                      {cap!.bottleneck_skills.map((s) => (
                        <Badge key={s} variant="rag-amber">
                          {s}
                        </Badge>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Per-developer bars */}
              <div className="space-y-1.5 mt-1">
                {teamMembers.map((tm) => {
                  const load = devLoad.get(tm.id) || 0;
                  const maxSp = Math.max(load, 30);
                  const pct = Math.min(100, Math.round((load / maxSp) * 100));

                  return (
                    <div key={tm.id} className="space-y-0.5">
                      <div className="flex items-center justify-between">
                        <span className="text-[11px] text-[var(--text-primary)] truncate max-w-[140px]">
                          {tm.displayName}
                        </span>
                        <span className="text-[10px] font-semibold tabular-nums text-[var(--text-secondary)]">
                          {load} SP
                        </span>
                      </div>
                      <Progress value={pct} size="sm" />
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Card 3: Risks & Missing Data */}
            <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-sunken)] p-3 space-y-2">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-[var(--text-primary)]">
                <AlertTriangle className="h-3.5 w-3.5" />
                Risks &amp; Gaps
              </div>

              {hasRisks ? (
                <div className="flex flex-wrap gap-1.5">
                  {Array.from(riskCounts.entries()).map(([flag, count]) => (
                    <Badge
                      key={flag}
                      variant={
                        flag === "burnout_risk" || flag === "overloaded"
                          ? "rag-red"
                          : "rag-amber"
                      }
                    >
                      {count} {flag.replace(/_/g, " ")}
                    </Badge>
                  ))}
                </div>
              ) : (
                <p className="text-[11px] text-[var(--text-secondary)]">
                  No risk flags detected.
                </p>
              )}

              {hasMissingData && (
                <div className="pt-1 border-t border-[var(--border-subtle)] space-y-1">
                  <div className="flex items-center gap-1.5 text-[11px] font-medium text-[var(--text-primary)]">
                    <Info className="h-3 w-3" />
                    Missing Data Handled
                  </div>
                  <p className="text-[11px] text-[var(--text-secondary)]">
                    AI assigned priority to{" "}
                    <span className="font-semibold text-[var(--color-brand-accent)]">
                      {suggestedPriorityCount}
                    </span>{" "}
                    item{suggestedPriorityCount !== 1 ? "s" : ""} that had no
                    priority set.
                  </p>
                </div>
              )}

              {!hasRisks && !hasMissingData && (
                <p className="text-[11px] text-[var(--color-rag-green)]">
                  All data complete, no gaps.
                </p>
              )}
            </div>

            {/* Card 4: Plan2Sprint Optimized Sprint */}
            <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-sunken)] p-3 space-y-2">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-[var(--text-primary)]">
                <Sparkles className="h-3.5 w-3.5 text-[var(--color-brand-secondary)]" />
                Plan2Sprint Optimized Sprint
              </div>
              {hasRecommendations ? (
                <>
                  {cap?.summary && (
                    <p className="text-[11px] text-[var(--text-secondary)] leading-relaxed">
                      {cap.summary}
                    </p>
                  )}
                  {cap?.recommended_additions ? (
                    <p className="text-[11px] text-[var(--color-brand-accent)]">
                      Recommendation: add {cap.recommended_additions} developer
                      {cap.recommended_additions > 1 ? "s" : ""} to reduce risk.
                    </p>
                  ) : null}
                  {overallRationale && (
                    <p className="text-[11px] text-[var(--text-secondary)] leading-relaxed border-t border-[var(--border-subtle)] pt-2 mt-1">
                      {overallRationale}
                    </p>
                  )}
                </>
              ) : (
                <p className="text-[11px] text-[var(--text-secondary)]">
                  No additional recommendations at this time.
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
