"use client";

import { useState } from "react";
import {
  Calendar,
  AlertTriangle,
  Users,
  Sparkles,
  ChevronDown,
  ChevronUp,
  CheckCircle2,
  Zap,
  ArrowRight,
  TrendingUp,
  Brain,
  X,
  UserPlus,
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
  aiSummary?: string | null;
  onExcludeMember?: (memberId: string, displayName: string) => void;
  excludedMembers?: TeamMemberData[];
  onIncludeMember?: (memberId: string, displayName: string) => void;
}

// ---------------------------------------------------------------------------
// Component — Horizontal full-width overview (collapsible)
// ---------------------------------------------------------------------------

export function AIInsightsPanel({
  estimatedSprints,
  estimatedWeeksTotal,
  estimatedEndDate,
  capacityRecommendations,
  totalStoryPoints,
  assignments,
  teamMembers,
  overallRationale,
  aiSummary,
  onExcludeMember,
  excludedMembers = [],
  onIncludeMember,
}: AIInsightsPanelProps) {
  const [expanded, setExpanded] = useState(true);
  const [rationaleExpanded, setRationaleExpanded] = useState(false);
  const [showExcluded, setShowExcluded] = useState(false);

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
  const totalRiskFlags = Array.from(riskCounts.values()).reduce(
    (sum, c) => sum + c,
    0
  );

  // Risk severity
  const riskLevel: "green" | "amber" | "red" =
    totalRiskFlags === 0 ? "green" : totalRiskFlags <= 3 ? "amber" : "red";

  const riskDotColor =
    riskLevel === "green"
      ? "bg-[var(--color-rag-green)]"
      : riskLevel === "amber"
        ? "bg-[var(--color-rag-amber)]"
        : "bg-[var(--color-rag-red)]";

  // Truncate rationale
  const RATIONALE_LIMIT = 300;
  const rationaleText = overallRationale || "";
  const isRationaleLong = rationaleText.length > RATIONALE_LIMIT;
  const displayRationale =
    isRationaleLong && !rationaleExpanded
      ? rationaleText.slice(0, RATIONALE_LIMIT) + "…"
      : rationaleText;

  // Auto-generated summary fallback when Grok API summary is not available
  const summaryText = aiSummary || (() => {
    const parts: string[] = [];
    if (estimatedSprints && totalStoryPoints) {
      parts.push(
        `This sprint plan targets ${totalStoryPoints} story points across ${estimatedSprints} sprint${estimatedSprints !== 1 ? "s" : ""}.`
      );
    }
    if (teamMembers.length > 0 && estimatedEndDate) {
      const endFormatted = new Date(estimatedEndDate).toLocaleDateString("en-US", {
        month: "long",
        day: "numeric",
        year: "numeric",
      });
      parts.push(
        `A team of ${teamMembers.length} developer${teamMembers.length !== 1 ? "s" : ""} is projected to complete delivery by ${endFormatted}.`
      );
    }
    if (cap) {
      if (cap.understaffed) {
        parts.push("The team is currently understaffed for this backlog size.");
      } else if (utilPct > 0) {
        parts.push(`Team utilization is at ${utilPct}%.`);
      }
    }
    return parts.length > 0 ? parts.join(" ") : null;
  })();

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
          expanded ? "max-h-[900px] opacity-100" : "max-h-0 opacity-0"
        )}
      >
        <div className="px-5 pb-4 pt-1">
          {/* Row 1 — Project metrics (3 columns) */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {/* ── Card 1: Project Summary ── */}
            <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-sunken)] p-4 min-h-[180px] flex flex-col">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-[var(--text-primary)] mb-3">
                <Calendar className="h-3.5 w-3.5" />
                Project Summary
              </div>

              {/* Metric tiles — larger, cleaner */}
              <div className="grid grid-cols-2 gap-3 flex-1">
                <div className="rounded-md bg-[var(--bg-surface)]/60 p-2.5 text-center">
                  <p className="text-[10px] text-[var(--text-secondary)] uppercase tracking-wide">
                    Sprints
                  </p>
                  <p className="text-lg font-bold tabular-nums text-[var(--text-primary)]">
                    {estimatedSprints ?? "—"}
                  </p>
                </div>
                <div className="rounded-md bg-[var(--bg-surface)]/60 p-2.5 text-center">
                  <p className="text-[10px] text-[var(--text-secondary)] uppercase tracking-wide">
                    Weeks
                  </p>
                  <p className="text-lg font-bold tabular-nums text-[var(--text-primary)]">
                    ~{estimatedWeeksTotal ?? "—"}
                  </p>
                </div>
                <div className="rounded-md bg-[var(--bg-surface)]/60 p-2.5 text-center">
                  <p className="text-[10px] text-[var(--text-secondary)] uppercase tracking-wide">
                    Total SP
                  </p>
                  <p className="text-lg font-bold tabular-nums text-[var(--text-primary)]">
                    {totalStoryPoints ?? "—"}
                  </p>
                </div>
                <div className="rounded-md bg-[var(--bg-surface)]/60 p-2.5 text-center">
                  <p className="text-[10px] text-[var(--text-secondary)] uppercase tracking-wide">
                    Est. Done
                  </p>
                  <p className="text-sm font-bold text-[var(--text-primary)]">
                    {estimatedEndDate
                      ? new Date(estimatedEndDate).toLocaleDateString(
                          "en-US",
                          { month: "short", day: "numeric" }
                        )
                      : "—"}
                  </p>
                </div>
              </div>

              {/* Timeline one-liner */}
              {estimatedEndDate && (
                <div className="mt-3 flex items-center gap-1.5 text-[11px] text-[var(--text-secondary)]">
                  <ArrowRight className="h-3 w-3" />
                  <span>
                    Project completion →{" "}
                    <span className="font-semibold text-[var(--text-primary)]">
                      {new Date(estimatedEndDate).toLocaleDateString(
                        "en-US",
                        { month: "short", day: "numeric", year: "numeric" }
                      )}
                    </span>
                  </span>
                </div>
              )}
            </div>

            {/* ── Card 2: Team Capacity ── */}
            <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-sunken)] p-4 min-h-[180px] flex flex-col">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-[var(--text-primary)]">
                  <Users className="h-3.5 w-3.5" />
                  Team Capacity
                </div>
                {onIncludeMember && (
                  <div className="relative">
                    <button
                      onClick={() => setShowExcluded(!showExcluded)}
                      className="flex items-center gap-1 text-[10px] text-[var(--color-brand)] hover:text-[var(--color-brand-hover)] transition-colors cursor-pointer"
                      title="Add developer to sprint plan"
                    >
                      <UserPlus className="h-3 w-3" />
                      <span>{excludedMembers.length > 0 ? `Add (${excludedMembers.length})` : "Add"}</span>
                    </button>
                    {showExcluded && (
                      <div className="absolute right-0 top-full mt-1 z-10 w-52 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-lg py-1 max-h-48 overflow-y-auto">
                        {excludedMembers.length > 0 ? (
                          excludedMembers.map((tm) => (
                            <button
                              key={tm.id}
                              onClick={() => {
                                onIncludeMember(tm.id, tm.displayName);
                                setShowExcluded(false);
                              }}
                              className="w-full px-3 py-1.5 text-left text-[11px] text-[var(--text-primary)] hover:bg-[var(--bg-surface-hover)] flex items-center justify-between cursor-pointer"
                            >
                              <span className="truncate">{tm.displayName}</span>
                              <span className="text-[var(--color-rag-green)] text-[10px] shrink-0">+ Include</span>
                            </button>
                          ))
                        ) : (
                          <p className="px-3 py-2 text-[11px] text-[var(--text-secondary)]">
                            All org members are included in the plan.
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Utilization bar */}
              {!!cap && (
                <div className="space-y-1.5 mb-2">
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
                  {cap.understaffed && (
                    <p className="text-[11px] text-[var(--color-rag-red)]">
                      Team is understaffed for this backlog
                    </p>
                  )}
                  {cap.bottleneck_skills.length > 0 && (
                    <div className="flex items-center gap-1 flex-wrap">
                      <span className="text-[10px] text-[var(--text-secondary)]">
                        Bottlenecks:
                      </span>
                      {cap.bottleneck_skills.map((s) => (
                        <Badge key={s} variant="rag-amber">
                          {s}
                        </Badge>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Per-developer bars — pushed to bottom */}
              <div className="space-y-1.5 mt-auto">
                {teamMembers.map((tm) => {
                  const load = devLoad.get(tm.id) || 0;
                  const maxSp = Math.max(load, 30);
                  const pct = Math.min(
                    100,
                    Math.round((load / maxSp) * 100)
                  );

                  return (
                    <div key={tm.id} className="space-y-0.5 group">
                      <div className="flex items-center justify-between gap-1">
                        <span className="text-[11px] text-[var(--text-primary)] truncate max-w-[120px]">
                          {tm.displayName}
                        </span>
                        <div className="flex items-center gap-1">
                          <span className="text-[10px] font-semibold tabular-nums text-[var(--text-secondary)]">
                            {load} SP
                          </span>
                          {onExcludeMember && (
                            <button
                              onClick={() => onExcludeMember(tm.id, tm.displayName)}
                              className="opacity-0 group-hover:opacity-100 transition-opacity p-0.5 rounded hover:bg-[var(--bg-surface-hover)] text-[var(--text-tertiary)] hover:text-[var(--color-rag-red)]"
                              title={`Remove ${tm.displayName} from planning`}
                            >
                              <X className="h-3 w-3" />
                            </button>
                          )}
                        </div>
                      </div>
                      <Progress value={pct} size="sm" />
                    </div>
                  );
                })}
              </div>
            </div>

            {/* ── Card 3: Risks & Gaps ── */}
            <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-sunken)] p-4 min-h-[180px] flex flex-col">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-[var(--text-primary)]">
                  <AlertTriangle className="h-3.5 w-3.5" />
                  Risks &amp; Gaps
                </div>
                {/* Risk score dot */}
                <div className="flex items-center gap-1.5">
                  <span
                    className={cn(
                      "h-2.5 w-2.5 rounded-full",
                      riskDotColor
                    )}
                  />
                  <span
                    className={cn(
                      "text-[11px] font-semibold",
                      riskLevel === "green"
                        ? "text-[var(--color-rag-green)]"
                        : riskLevel === "amber"
                          ? "text-[var(--color-rag-amber)]"
                          : "text-[var(--color-rag-red)]"
                    )}
                  >
                    {totalRiskFlags === 0
                      ? "All Clear"
                      : `${totalRiskFlags} flag${totalRiskFlags > 1 ? "s" : ""}`}
                  </span>
                </div>
              </div>

              {riskLevel === "green" && suggestedPriorityCount === 0 ? (
                /* All clear state */
                <div className="flex-1 flex flex-col items-center justify-center gap-2 text-center">
                  <CheckCircle2 className="h-8 w-8 text-[var(--color-rag-green)] opacity-60" />
                  <p className="text-xs text-[var(--color-rag-green)] font-medium">
                    No risks or gaps detected
                  </p>
                </div>
              ) : (
                <div className="space-y-3 flex-1">
                  {/* Risk flag badges */}
                  {riskCounts.size > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {Array.from(riskCounts.entries()).map(
                        ([flag, count]) => (
                          <Badge
                            key={flag}
                            variant={
                              flag === "burnout_risk" ||
                              flag === "overloaded"
                                ? "rag-red"
                                : "rag-amber"
                            }
                          >
                            {count} {flag.replace(/_/g, " ")}
                          </Badge>
                        )
                      )}
                    </div>
                  )}

                  {/* Auto-prioritized items — compact */}
                  {suggestedPriorityCount > 0 && (
                    <div className="flex items-center gap-1.5 text-[11px] text-[var(--text-secondary)]">
                      <Zap className="h-3 w-3 text-[var(--color-brand-accent)]" />
                      <span>
                        <span className="font-semibold text-[var(--color-brand-accent)]">
                          {suggestedPriorityCount}
                        </span>{" "}
                        item{suggestedPriorityCount !== 1 ? "s" : ""}{" "}
                        auto-prioritized by AI
                      </span>
                    </div>
                  )}
                </div>
              )}
            </div>

          </div>

          {/* Row 2 — AI cards (2 columns) */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3">
            {/* ── Card 4: AI Summary ── */}
            <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-sunken)] p-4 min-h-[180px] flex flex-col">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-[var(--text-primary)] mb-3">
                <Brain className="h-3.5 w-3.5 text-[var(--color-brand-secondary)]" />
                AI Summary
              </div>

              <div className="flex-1 flex flex-col">
                {summaryText ? (
                  <p className="text-[12px] leading-relaxed text-[var(--text-secondary)]">
                    {summaryText}
                  </p>
                ) : (
                  <div className="flex-1 flex items-center justify-center">
                    <p className="text-[11px] text-[var(--text-secondary)]">
                      Generate a sprint plan to see the AI summary.
                    </p>
                  </div>
                )}
              </div>
            </div>

            {/* ── Card 5: AI Recommendations ── */}
            <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-sunken)] p-4 min-h-[180px] flex flex-col">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-[var(--text-primary)] mb-3">
                <Sparkles className="h-3.5 w-3.5 text-[var(--color-brand-secondary)]" />
                AI Recommendations
              </div>

              <div className="space-y-3 flex-1">
                {/* Highlighted recommendation */}
                {cap && cap.recommended_additions > 0 && (
                  <div className="rounded-md bg-[var(--color-brand-secondary)]/10 border border-[var(--color-brand-secondary)]/20 px-3 py-2">
                    <p className="text-[11px] font-semibold text-[var(--color-brand-secondary)]">
                      + Add {cap.recommended_additions} developer
                      {cap.recommended_additions > 1 ? "s" : ""} to reduce
                      risk
                    </p>
                  </div>
                )}

                {/* Utilization metric inline */}
                {cap && (
                  <div className="flex items-center gap-1.5 text-[11px] text-[var(--text-secondary)]">
                    <TrendingUp className="h-3 w-3" />
                    <span>
                      <span className="font-semibold text-[var(--text-primary)]">
                        {utilPct}%
                      </span>{" "}
                      capacity ·{" "}
                      <span className="font-semibold text-[var(--text-primary)]">
                        {estimatedSprints ?? "—"}
                      </span>{" "}
                      sprints
                    </span>
                  </div>
                )}

                {/* Truncated rationale */}
                {rationaleText && (
                  <div className="border-t border-[var(--border-subtle)] pt-2">
                    <p className="text-[11px] text-[var(--text-secondary)] leading-relaxed">
                      {displayRationale}
                    </p>
                    {isRationaleLong && (
                      <button
                        type="button"
                        onClick={() =>
                          setRationaleExpanded(!rationaleExpanded)
                        }
                        className="text-[11px] font-medium text-[var(--color-brand-secondary)] hover:underline mt-1 cursor-pointer"
                      >
                        {rationaleExpanded ? "Show less" : "Show more"}
                      </button>
                    )}
                  </div>
                )}

                {/* Empty state */}
                {!cap && !rationaleText && (
                  <p className="text-[11px] text-[var(--text-secondary)]">
                    No additional recommendations at this time.
                  </p>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
