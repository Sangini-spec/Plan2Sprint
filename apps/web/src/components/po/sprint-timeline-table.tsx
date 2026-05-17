"use client";

import { Fragment, useState } from "react";
import { ChevronDown, AlertTriangle, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { Avatar, Badge, Progress } from "@/components/ui";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Assignment {
  id: string;
  workItemId: string;
  teamMemberId: string;
  storyPoints: number;
  confidenceScore: number;
  rationale: string;
  riskFlags: string[];
  skillMatch?: { matchedSkills: string[]; score: number } | null;
  isHumanEdited: boolean;
  sprintNumber: number;
  suggestedPriority?: number | null;
}

interface WorkItemData {
  id: string;
  externalId: string;
  title: string;
  status: string;
  storyPoints: number | null;
  priority: number;
  type: string;
  labels: string[];
}

interface TeamMemberData {
  id: string;
  displayName: string;
  email: string;
  avatarUrl: string | null;
  skillTags: string[];
}

interface SprintDetail {
  sprintNumber: number;
  startDate: string;
  endDate: string;
  totalSP: number;
  itemCount: number;
}

interface SprintTimelineTableProps {
  assignments: Assignment[];
  workItems: WorkItemData[];
  teamMembers: TeamMemberData[];
  estimatedSprints: number;
  sprintDetails?: SprintDetail[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const priorityLabels: Record<number, string> = {
  1: "Critical",
  2: "High",
  3: "Medium",
  4: "Low",
  5: "Trivial",
};

const typeColors: Record<string, string> = {
  story: "text-[var(--color-brand-secondary)]",
  bug: "text-[var(--color-rag-red)]",
  task: "text-[var(--text-secondary)]",
  feature: "text-[var(--color-brand-accent)]",
  epic: "text-[var(--color-brand-primary)]",
  spike: "text-[var(--color-rag-amber)]",
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

function formatShortDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function SprintTimelineTable({
  assignments,
  workItems,
  teamMembers,
  sprintDetails = [],
  estimatedSprints,
}: SprintTimelineTableProps) {
  const [activeSprint, setActiveSprint] = useState(1);
  const [expandedRow, setExpandedRow] = useState<string | null>(null);

  // Group assignments by sprint
  const sprintGroups = new Map<number, Assignment[]>();
  for (const a of assignments) {
    const sn = a.sprintNumber ?? 1;
    if (!sprintGroups.has(sn)) sprintGroups.set(sn, []);
    sprintGroups.get(sn)!.push(a);
  }

  // Only show sprints that have assignments (no empty sprints)
  const sprintNums = Array.from(sprintGroups.keys()).sort((a, b) => a - b);
  // If activeSprint has no assignments, default to first non-empty sprint
  const activeSprintNum = sprintGroups.has(activeSprint) ? activeSprint : (sprintNums[0] ?? 1);
  const activeAssignments = sprintGroups.get(activeSprintNum) || [];

  // Build a lookup for sprint details by number
  const detailMap = new Map(sprintDetails.map((d) => [d.sprintNumber, d]));

  const lookupWI = (id: string) => workItems.find((wi) => wi.id === id);
  const lookupTM = (id: string) => teamMembers.find((tm) => tm.id === id);

  return (
    <div className="flex flex-col h-full">
      {/* Sprint tabs with date ranges */}
      <div className="flex items-center gap-1 border-b border-[var(--border-subtle)] px-4 overflow-x-auto">
        {sprintNums.map((sn) => {
          const sprintSP = (sprintGroups.get(sn) || []).reduce(
            (s, a) => s + a.storyPoints,
            0
          );
          const detail = detailMap.get(sn);
          const itemCount = (sprintGroups.get(sn) || []).length;
          const dateRange = detail
            ? `${formatShortDate(detail.startDate)}–${formatShortDate(detail.endDate)}`
            : null;

          return (
            <button
              key={sn}
              onClick={() => setActiveSprint(sn)}
              className={cn(
                "px-4 py-2.5 text-sm font-medium whitespace-nowrap border-b-2 transition-colors cursor-pointer",
                activeSprintNum === sn
                  ? "border-[var(--color-brand-secondary)] text-[var(--text-primary)]"
                  : "border-transparent text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
              )}
            >
              <span>Sprint {sn}</span>
              {dateRange && (
                <span className="text-[10px] opacity-60 ml-1">{dateRange}</span>
              )}
              <span className="text-xs opacity-70 ml-1">
                ({sprintSP} SP · {itemCount} items)
              </span>
            </button>
          );
        })}
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 z-10 bg-[var(--bg-surface)]">
            <tr className="border-b border-[var(--border-subtle)]">
              <th className="text-left py-2.5 px-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] w-[80px]">
                ID
              </th>
              <th className="text-left py-2.5 px-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
                Title
              </th>
              <th className="text-left py-2.5 px-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] w-[70px]">
                Type
              </th>
              <th className="text-left py-2.5 px-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] w-[80px]">
                Priority
              </th>
              <th className="text-left py-2.5 px-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] w-[160px]">
                Assignee
              </th>
              <th className="text-right py-2.5 px-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] w-[50px]">
                SP
              </th>
              <th className="text-right py-2.5 px-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] w-[70px]">
                Conf.
              </th>
              <th className="text-center py-2.5 px-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] w-[50px]">
                Risk
              </th>
            </tr>
          </thead>
          <tbody>
            {activeAssignments.map((a) => {
              const wi = lookupWI(a.workItemId);
              const tm = lookupTM(a.teamMemberId);
              const confPct = Math.round(a.confidenceScore * 100);
              const isExpanded = expandedRow === a.id;
              const hasRisk = a.riskFlags.length > 0;
              const hasSuggestedPri = a.suggestedPriority != null;
              const displayPriority =
                hasSuggestedPri
                  ? a.suggestedPriority!
                  : wi?.priority ?? 0;

              return (
                <Fragment key={a.id}>
                  <tr
                    onClick={() =>
                      setExpandedRow(isExpanded ? null : a.id)
                    }
                    className={cn(
                      "border-b border-[var(--border-subtle)] cursor-pointer transition-colors h-10",
                      "hover:bg-[var(--bg-surface-raised)]",
                      hasRisk && "bg-[var(--color-rag-amber)]/[0.03]",
                      isExpanded && "bg-[var(--bg-surface-raised)]"
                    )}
                  >
                    <td className="py-2 px-4">
                      <span className="font-mono text-xs text-[var(--color-brand-secondary)]">
                        {wi?.externalId?.slice(-6) || "-"}
                      </span>
                    </td>
                    <td className="py-2 px-4">
                      <span className="text-sm text-[var(--text-primary)] truncate block max-w-[300px]">
                        {wi?.title || "Unknown"}
                      </span>
                    </td>
                    <td className="py-2 px-4">
                      <span
                        className={cn(
                          "text-xs font-medium capitalize",
                          typeColors[(wi?.type || "story").toLowerCase()] ||
                            "text-[var(--text-secondary)]"
                        )}
                      >
                        {wi?.type || "story"}
                      </span>
                    </td>
                    <td className="py-2 px-4">
                      <span className="flex items-center gap-1 text-xs text-[var(--text-secondary)]">
                        {hasSuggestedPri && (
                          <Sparkles className="h-3 w-3 text-[var(--color-brand-accent)]" />
                        )}
                        {priorityLabels[displayPriority] ||
                          (displayPriority === 0 ? "Unset" : `P${displayPriority}`)}
                      </span>
                    </td>
                    <td className="py-2 px-4">
                      <div className="flex items-center gap-2">
                        <Avatar
                          src={tm?.avatarUrl ?? undefined}
                          fallback={tm?.displayName ?? "?"}
                          size="sm"
                        />
                        <span className="text-xs text-[var(--text-primary)] truncate">
                          {tm?.displayName || "Unassigned"}
                        </span>
                      </div>
                    </td>
                    <td className="py-2 px-4 text-right">
                      <span className="text-sm font-semibold tabular-nums text-[var(--text-primary)]">
                        {a.storyPoints}
                      </span>
                    </td>
                    <td className="py-2 px-4 text-right">
                      <span
                        className={cn(
                          "text-xs font-semibold tabular-nums",
                          confPct >= 85
                            ? "text-[var(--color-rag-green)]"
                            : confPct >= 70
                              ? "text-[var(--color-rag-amber)]"
                              : "text-[var(--color-rag-red)]"
                        )}
                      >
                        {confPct}%
                      </span>
                    </td>
                    <td className="py-2 px-4 text-center">
                      {hasRisk ? (
                        <AlertTriangle className="h-3.5 w-3.5 text-[var(--color-rag-amber)] mx-auto" />
                      ) : (
                        <span className="text-xs text-[var(--text-secondary)]">
                          -
                        </span>
                      )}
                    </td>
                  </tr>

                  {/* Expanded rationale row */}
                  {isExpanded && (
                    <tr
                      key={`${a.id}-detail`}
                      className="bg-[var(--bg-surface-sunken)]"
                    >
                      <td colSpan={8} className="px-4 py-3">
                        <div className="space-y-2 max-w-3xl">
                          <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
                            {a.rationale}
                          </p>

                          {/* Confidence bar */}
                          <div className="flex items-center gap-3">
                            <span className="text-xs text-[var(--text-secondary)]">
                              Confidence
                            </span>
                            <Progress
                              value={confPct}
                              severity={
                                confPct >= 85
                                  ? "GREEN"
                                  : confPct >= 70
                                    ? "AMBER"
                                    : "RED"
                              }
                              size="sm"
                              className="max-w-[200px]"
                            />
                            <span className="text-xs font-semibold tabular-nums">
                              {confPct}%
                            </span>
                          </div>

                          {/* Risk flags */}
                          {a.riskFlags.length > 0 && (
                            <div className="flex items-center gap-2 flex-wrap">
                              {a.riskFlags.map((flag) => (
                                <Badge key={flag} variant="rag-amber">
                                  {flag.replace(/_/g, " ")}
                                </Badge>
                              ))}
                            </div>
                          )}

                          {/* Skill match */}
                          {a.skillMatch &&
                            a.skillMatch.matchedSkills.length > 0 && (
                              <div className="flex items-center gap-2">
                                <span className="text-xs text-[var(--text-secondary)]">
                                  Skills:
                                </span>
                                {a.skillMatch.matchedSkills.map((s) => (
                                  <Badge key={s} variant="rag-green">
                                    {s}
                                  </Badge>
                                ))}
                              </div>
                            )}

                          {/* AI-suggested priority indicator */}
                          {hasSuggestedPri && (
                            <div className="flex items-center gap-2 text-xs text-[var(--color-brand-accent)]">
                              <Sparkles className="h-3 w-3" />
                              AI suggested priority:{" "}
                              {priorityLabels[a.suggestedPriority!] ||
                                `P${a.suggestedPriority}`}
                            </div>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>

        {activeAssignments.length === 0 && (
          <div className="flex items-center justify-center py-12 text-sm text-[var(--text-secondary)]">
            No assignments in Sprint {activeSprint}
          </div>
        )}
      </div>
    </div>
  );
}
