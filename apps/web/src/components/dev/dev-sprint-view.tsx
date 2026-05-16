"use client";

import { useState, useEffect, useCallback } from "react";
import {
  CalendarClock,
  ChevronDown,
  ChevronRight,
  Loader2,
  RefreshCw,
  Sparkles,
  Database,
  User as UserIcon,
  Users,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge, Avatar, Progress } from "@/components/ui";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { useSelectedProject } from "@/lib/project/context";
import { useAuth } from "@/lib/auth/context";
import { cachedFetch } from "@/lib/fetch-cache";

/* -------------------------------------------------------------------------- */
/*  TYPES                                                                      */
/* -------------------------------------------------------------------------- */

interface Sprint {
  id: string;
  name: string;
  state: string;
  startDate: string | null;
  endDate: string | null;
  totalItems: number;
  completedItems: number;
  totalStoryPoints: number;
  completedStoryPoints: number;
  completionPct: number;
  sourceTool?: string;
}

interface WorkItem {
  id: string;
  externalId: string;
  title: string;
  status: string;
  type: string;
  priority: number | null;
  storyPoints: number | null;
  assignee: string | null;
  assigneeId: string | null;
  iterationId: string | null;
  sourceStatus: string | null;
  labels: string[];
}

interface PlanAssignment {
  workItemId: string;
  teamMemberId: string;
  sprintNumber: number;
  storyPoints: number;
  teamMemberName?: string;
  workItemTitle?: string;
}

interface PlanData {
  plan: { id: string; name: string; sprintCount: number } | null;
  assignments: PlanAssignment[];
  workItems: { id: string; title: string; storyPoints: number; status: string }[];
  teamMembers: { id: string; displayName: string; email: string }[];
}

interface TeamMember {
  id: string;
  displayName: string;
  email: string;
}

/* -------------------------------------------------------------------------- */
/*  STATUS HELPERS                                                             */
/* -------------------------------------------------------------------------- */

type DisplayStatus = "Done" | "Active" | "To Do";

function mapStatus(raw: string): DisplayStatus {
  const upper = raw.toUpperCase();
  if (upper === "DONE" || upper === "CLOSED" || upper === "RESOLVED") return "Done";
  if (
    upper === "IN_PROGRESS" ||
    upper === "IN_REVIEW" ||
    upper === "ACTIVE" ||
    upper === "COMMITTED"
  )
    return "Active";
  return "To Do";
}

function statusBadge(status: DisplayStatus) {
  switch (status) {
    case "Done":
      return (
        <span className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold bg-[var(--color-rag-green)]/10 text-[var(--color-rag-green)]">
          Done
        </span>
      );
    case "Active":
      return (
        <span className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold bg-[var(--color-brand-secondary)]/10 text-[var(--color-brand-secondary)]">
          Active
        </span>
      );
    default:
      return (
        <span className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold bg-[var(--text-tertiary)]/10 text-[var(--text-tertiary)]">
          To Do
        </span>
      );
  }
}

function typeBadge(type: string) {
  const colors: Record<string, string> = {
    bug: "bg-[var(--color-rag-red)]/10 text-[var(--color-rag-red)]",
    story: "bg-[var(--color-brand-secondary)]/10 text-[var(--color-brand-secondary)]",
    task: "bg-[var(--color-rag-amber)]/10 text-[var(--color-rag-amber)]",
    feature: "bg-[#a78bfa]/10 text-[#a78bfa]",
    epic: "bg-[#e879f9]/10 text-[#e879f9]",
  };
  const color = colors[type.toLowerCase()] ?? "bg-[var(--text-tertiary)]/10 text-[var(--text-tertiary)]";
  return (
    <span className={cn("inline-flex items-center rounded px-1.5 py-0.5 text-[9px] font-bold uppercase", color)}>
      {type}
    </span>
  );
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "—";
  return new Date(dateStr).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/* -------------------------------------------------------------------------- */
/*  WORK ITEM ROW                                                              */
/* -------------------------------------------------------------------------- */

function WorkItemRow({ item }: { item: WorkItem }) {
  const display = mapStatus(item.status);
  const sortOrder = display === "Active" ? 0 : display === "To Do" ? 1 : 2;

  return (
    <div
      className={cn(
        "flex items-center gap-3 px-4 py-2.5 rounded-lg transition-colors",
        "hover:bg-[var(--bg-surface-raised)]/50"
      )}
      data-sort={sortOrder}
    >
      {/* Type badge */}
      <div className="w-14 shrink-0">{typeBadge(item.type)}</div>

      {/* Title */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-[var(--text-primary)] truncate">
          {item.title}
        </p>
      </div>

      {/* Story Points */}
      <div className="w-12 text-right shrink-0">
        {item.storyPoints != null ? (
          <span className="inline-flex items-center justify-center h-6 min-w-[24px] rounded-md bg-[var(--color-brand-secondary)]/10 px-1.5 text-[11px] font-bold text-[var(--color-brand-secondary)] tabular-nums">
            {item.storyPoints}
          </span>
        ) : (
          <span className="text-xs text-[var(--text-tertiary)]">—</span>
        )}
      </div>

      {/* Status */}
      <div className="w-16 shrink-0 text-center">{statusBadge(display)}</div>

      {/* Assignee */}
      <div className="w-28 shrink-0 flex items-center gap-1.5">
        {item.assignee ? (
          <>
            <Avatar fallback={item.assignee} size="sm" />
            <span className="text-xs text-[var(--text-secondary)] truncate">
              {item.assignee.split(" ")[0]}
            </span>
          </>
        ) : (
          <span className="text-xs text-[var(--text-tertiary)]">Unassigned</span>
        )}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  SPRINT GROUP (collapsible)                                                 */
/* -------------------------------------------------------------------------- */

function SprintGroup({
  sprint,
  items,
  defaultOpen,
}: {
  sprint: Sprint;
  items: WorkItem[];
  defaultOpen: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  // Sort: Active → To Do → Done
  const sorted = [...items].sort((a, b) => {
    const order = { Active: 0, "To Do": 1, Done: 2 };
    return (order[mapStatus(a.status)] ?? 1) - (order[mapStatus(b.status)] ?? 1);
  });

  const isActive = sprint.state === "active" || sprint.state === "current";
  const severity =
    sprint.completionPct >= 70 ? "GREEN" : sprint.completionPct >= 40 ? "AMBER" : "RED";

  return (
    <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setOpen(!open)}
        className={cn(
          "w-full flex items-center gap-3 px-4 py-3 text-left cursor-pointer transition-colors",
          "hover:bg-[var(--bg-surface-raised)]/50",
          isActive && "bg-[var(--color-brand-secondary)]/5"
        )}
      >
        {open ? (
          <ChevronDown size={16} className="text-[var(--text-secondary)] shrink-0" />
        ) : (
          <ChevronRight size={16} className="text-[var(--text-secondary)] shrink-0" />
        )}

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-[var(--text-primary)] truncate">
              {sprint.name}
            </h3>
            {isActive && (
              <Badge variant="brand">Current</Badge>
            )}
          </div>
          <p className="text-xs text-[var(--text-secondary)] mt-0.5">
            {formatDate(sprint.startDate)} — {formatDate(sprint.endDate)}
          </p>
        </div>

        {/* Stats */}
        <div className="hidden sm:flex items-center gap-4 shrink-0">
          <span className="text-xs text-[var(--text-secondary)] tabular-nums">
            {sprint.totalItems} items
          </span>
          <span className="text-xs font-medium text-[var(--color-brand-secondary)] tabular-nums">
            {sprint.totalStoryPoints} SP
          </span>
          <div className="w-24">
            <Progress value={sprint.completionPct} severity={severity} size="sm" />
          </div>
          <span className="text-xs font-bold text-[var(--text-primary)] tabular-nums w-10 text-right">
            {sprint.completionPct}%
          </span>
        </div>
      </button>

      {/* Items */}
      {open && (
        <div className="border-t border-[var(--border-subtle)]">
          {/* Mobile stats bar */}
          <div className="sm:hidden flex items-center gap-3 px-4 py-2 bg-[var(--bg-surface-raised)]/30">
            <span className="text-xs text-[var(--text-secondary)]">
              {sprint.totalItems} items · {sprint.totalStoryPoints} SP
            </span>
            <div className="flex-1">
              <Progress value={sprint.completionPct} severity={severity} size="sm" />
            </div>
            <span className="text-xs font-bold">{sprint.completionPct}%</span>
          </div>

          {/* Column headers */}
          <div className="hidden sm:flex items-center gap-3 px-4 py-1.5 text-[9px] font-bold uppercase tracking-[0.15em] text-[var(--text-tertiary)] border-b border-[var(--border-subtle)]/50">
            <div className="w-14">Type</div>
            <div className="flex-1">Title</div>
            <div className="w-12 text-right">SP</div>
            <div className="w-16 text-center">Status</div>
            <div className="w-28">Assignee</div>
          </div>

          {sorted.length > 0 ? (
            <div className="divide-y divide-[var(--border-subtle)]/30">
              {sorted.map((item) => (
                <WorkItemRow key={item.id} item={item} />
              ))}
            </div>
          ) : (
            <p className="px-4 py-6 text-center text-sm text-[var(--text-secondary)]">
              No work items in this sprint.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  AI SPRINT GROUP (from plan assignments)                                    */
/* -------------------------------------------------------------------------- */

function AiSprintGroup({
  sprintNumber,
  assignments,
  defaultOpen,
}: {
  sprintNumber: number;
  assignments: (PlanAssignment & { status?: string; type?: string })[];
  defaultOpen: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  const totalSP = assignments.reduce((s, a) => s + (a.storyPoints || 0), 0);
  const doneCount = assignments.filter(
    (a) => a.status && mapStatus(a.status) === "Done"
  ).length;
  const pct = assignments.length > 0 ? Math.round((doneCount / assignments.length) * 100) : 0;
  const severity = pct >= 70 ? "GREEN" : pct >= 40 ? "AMBER" : "RED";

  return (
    <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 px-4 py-3 text-left cursor-pointer hover:bg-[var(--bg-surface-raised)]/50 transition-colors"
      >
        {open ? (
          <ChevronDown size={16} className="text-[var(--text-secondary)] shrink-0" />
        ) : (
          <ChevronRight size={16} className="text-[var(--text-secondary)] shrink-0" />
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <Sparkles size={14} className="text-[var(--color-brand-secondary)]" />
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">
              Sprint {sprintNumber}
            </h3>
            <Badge variant="brand">AI Planned</Badge>
          </div>
        </div>
        <div className="hidden sm:flex items-center gap-4 shrink-0">
          <span className="text-xs text-[var(--text-secondary)] tabular-nums">
            {assignments.length} items
          </span>
          <span className="text-xs font-medium text-[var(--color-brand-secondary)] tabular-nums">
            {totalSP} SP
          </span>
          <div className="w-24">
            <Progress value={pct} severity={severity} size="sm" />
          </div>
          <span className="text-xs font-bold text-[var(--text-primary)] tabular-nums w-10 text-right">
            {pct}%
          </span>
        </div>
      </button>

      {open && (
        <div className="border-t border-[var(--border-subtle)]">
          <div className="hidden sm:flex items-center gap-3 px-4 py-1.5 text-[9px] font-bold uppercase tracking-[0.15em] text-[var(--text-tertiary)] border-b border-[var(--border-subtle)]/50">
            <div className="w-14">Type</div>
            <div className="flex-1">Title</div>
            <div className="w-12 text-right">SP</div>
            <div className="w-16 text-center">Status</div>
            <div className="w-28">Assignee</div>
          </div>
          {assignments.length > 0 ? (
            <div className="divide-y divide-[var(--border-subtle)]/30">
              {assignments.map((a) => (
                <div
                  key={a.workItemId}
                  className="flex items-center gap-3 px-4 py-2.5 hover:bg-[var(--bg-surface-raised)]/50 transition-colors"
                >
                  <div className="w-14">{typeBadge(a.type || "task")}</div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-[var(--text-primary)] truncate">
                      {a.workItemTitle || "Untitled"}
                    </p>
                  </div>
                  <div className="w-12 text-right">
                    <span className="inline-flex items-center justify-center h-6 min-w-[24px] rounded-md bg-[var(--color-brand-secondary)]/10 px-1.5 text-[11px] font-bold text-[var(--color-brand-secondary)] tabular-nums">
                      {a.storyPoints}
                    </span>
                  </div>
                  <div className="w-16 text-center">
                    {statusBadge(mapStatus(a.status || "TODO"))}
                  </div>
                  <div className="w-28 flex items-center gap-1.5">
                    {a.teamMemberName ? (
                      <>
                        <Avatar fallback={a.teamMemberName} size="sm" />
                        <span className="text-xs text-[var(--text-secondary)] truncate">
                          {a.teamMemberName.split(" ")[0]}
                        </span>
                      </>
                    ) : (
                      <span className="text-xs text-[var(--text-tertiary)]">Unassigned</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="px-4 py-6 text-center text-sm text-[var(--text-secondary)]">
              No items in this sprint.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  MAIN COMPONENT                                                             */
/* -------------------------------------------------------------------------- */

export function DevSprintView() {
  const { selectedProject } = useSelectedProject();
  const { appUser } = useAuth();
  const projectId = selectedProject?.internalId;

  const [viewMode, setViewMode] = useState<"source" | "ai">("source");
  const [myItemsOnly, setMyItemsOnly] = useState(true);
  const [loading, setLoading] = useState(true);

  // Source data
  const [sprints, setSprints] = useState<Sprint[]>([]);
  const [workItems, setWorkItems] = useState<WorkItem[]>([]);

  // AI plan data
  const [planData, setPlanData] = useState<PlanData | null>(null);

  // Team member mapping (to resolve "my items")
  const [myTeamMemberId, setMyTeamMemberId] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const q = projectId ? `?projectId=${projectId}` : "";
      const [sprintsRes, itemsRes, planRes, teamRes] = await Promise.all([
        cachedFetch<{ sprints: Sprint[] }>(`/api/dashboard/sprints${q}`),
        cachedFetch<{ workItems: WorkItem[] }>(
          `/api/dashboard/work-items${q}&limit=500`
        ),
        cachedFetch<PlanData>(`/api/sprints/plan${q}`),
        cachedFetch<{ members: TeamMember[] }>(`/api/dashboard/team${q}`),
      ]);

      if (sprintsRes.ok && sprintsRes.data) setSprints(sprintsRes.data.sprints);
      if (itemsRes.ok && itemsRes.data) setWorkItems(itemsRes.data.workItems);
      if (planRes.ok && planRes.data) setPlanData(planRes.data);

      // Resolve current user's team member ID
      if (teamRes.ok && teamRes.data && appUser?.email) {
        const me = teamRes.data.members.find(
          (m) => m.email.toLowerCase() === appUser.email.toLowerCase()
        );
        if (me) setMyTeamMemberId(me.id);
      }
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [projectId, appUser?.email]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Group work items by sprint
  const itemsBySprint = new Map<string, WorkItem[]>();
  for (const wi of workItems) {
    const key = wi.iterationId || "__unassigned__";
    if (!itemsBySprint.has(key)) itemsBySprint.set(key, []);
    itemsBySprint.get(key)!.push(wi);
  }

  // Filter for "my items"
  const filterItems = (items: WorkItem[]) => {
    if (!myItemsOnly || !myTeamMemberId) return items;
    return items.filter((i) => i.assigneeId === myTeamMemberId);
  };

  // AI plan: enrich assignments
  const aiSprintGroups = new Map<number, (PlanAssignment & { status?: string; type?: string })[]>();
  if (planData?.plan) {
    const wiMap = new Map(planData.workItems.map((w) => [w.id, w]));
    const tmMap = new Map(planData.teamMembers.map((t) => [t.id, t]));

    for (const a of planData.assignments) {
      const wi = wiMap.get(a.workItemId);
      const tm = tmMap.get(a.teamMemberId);

      // Filter "my items" in AI view
      if (myItemsOnly && myTeamMemberId && a.teamMemberId !== myTeamMemberId) continue;

      const enriched = {
        ...a,
        workItemTitle: wi?.title || a.workItemTitle,
        teamMemberName: tm?.displayName || a.teamMemberName,
        status: wi?.status || "TODO",
        type: "task",
      };

      if (!aiSprintGroups.has(a.sprintNumber)) aiSprintGroups.set(a.sprintNumber, []);
      aiSprintGroups.get(a.sprintNumber)!.push(enriched);
    }
  }

  // Sort sprints: active first, then by start date desc
  const sortedSprints = [...sprints].sort((a, b) => {
    const aActive = a.state === "active" || a.state === "current" ? 0 : 1;
    const bActive = b.state === "active" || b.state === "current" ? 0 : 1;
    if (aActive !== bActive) return aActive - bActive;
    return (b.startDate || "").localeCompare(a.startDate || "");
  });

  return (
    // The ``data-onboarding="dev-sprint-board"`` hook moved here from
    // the /dev dashboard. The developer-tour ``sprint-board`` step
    // now navigates to /dev/sprint and anchors on this panel — which
    // is the actual Sprint section the user sees in the sidebar (with
    // the SOURCE vs AI-OPTIMIZED toggle), not a slimmer dashboard
    // widget. Keep the attribute on the OUTER wrapper so it's
    // measurable even before the panel's inner content has data.
    <div data-onboarding="dev-sprint-board">
    <DashboardPanel
      title="Sprint View"
      icon={CalendarClock}
      actions={
        <button
          onClick={fetchData}
          className="p-1 rounded hover:bg-[var(--bg-surface-raised)] transition-colors"
          title="Refresh"
        >
          <RefreshCw className={cn("h-3.5 w-3.5 text-[var(--text-secondary)]", loading && "animate-spin")} />
        </button>
      }
    >
      {/* ── Toolbar ── */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        {/* View mode toggle */}
        <div className="flex items-center rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/50 p-0.5">
          <button
            onClick={() => setViewMode("source")}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-all cursor-pointer",
              viewMode === "source"
                ? "bg-[var(--color-brand-secondary)] text-white shadow-sm"
                : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            )}
          >
            <Database size={12} />
            Source
          </button>
          <button
            onClick={() => setViewMode("ai")}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-all cursor-pointer",
              viewMode === "ai"
                ? "bg-[var(--color-brand-secondary)] text-white shadow-sm"
                : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            )}
          >
            <Sparkles size={12} />
            AI Optimized
          </button>
        </div>

        {/* My items toggle */}
        <button
          onClick={() => setMyItemsOnly(!myItemsOnly)}
          className={cn(
            "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium border transition-all cursor-pointer",
            myItemsOnly
              ? "border-[var(--color-brand-secondary)]/40 bg-[var(--color-brand-secondary)]/10 text-[var(--color-brand-secondary)]"
              : "border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
          )}
        >
          {myItemsOnly ? <UserIcon size={12} /> : <Users size={12} />}
          {myItemsOnly ? "My Items" : "Full Sprint"}
        </button>
      </div>

      {/* ── Content ── */}
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-[var(--color-brand-secondary)]" />
        </div>
      ) : viewMode === "source" ? (
        /* ── Source View ── */
        (() => {
          const unassignedItems = filterItems(itemsBySprint.get("__unassigned__") || []);
          const hasSprintItems = sortedSprints.some((s) => (itemsBySprint.get(s.id) || []).length > 0);
          const hasAnyItems = hasSprintItems || unassignedItems.length > 0;

          return hasAnyItems || sortedSprints.length > 0 ? (
            <div className="space-y-3">
              {sortedSprints.map((sprint, idx) => {
                const items = filterItems(itemsBySprint.get(sprint.id) || []);
                return (
                  <SprintGroup
                    key={sprint.id}
                    sprint={{ ...sprint, totalItems: items.length }}
                    items={items}
                    defaultOpen={idx === 0 && items.length > 0}
                  />
                );
              })}
              {/* Show unassigned items (not linked to any iteration) */}
              {unassignedItems.length > 0 && (
                <SprintGroup
                  key="__backlog__"
                  sprint={{
                    id: "__backlog__",
                    name: "Backlog",
                    state: "active",
                    sourceTool: "",
                    startDate: null,
                    endDate: null,
                    totalItems: unassignedItems.length,
                    completedItems: unassignedItems.filter((i) => i.status === "DONE").length,
                    totalStoryPoints: unassignedItems.reduce((s, i) => s + (i.storyPoints || 0), 0),
                    completedStoryPoints: unassignedItems.filter((i) => i.status === "DONE").reduce((s, i) => s + (i.storyPoints || 0), 0),
                    completionPct: Math.round(
                      (unassignedItems.filter((i) => i.status === "DONE").length / unassignedItems.length) * 100
                    ),
                  }}
                  items={unassignedItems}
                  defaultOpen={!hasSprintItems}
                />
              )}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <CalendarClock size={32} className="text-[var(--text-tertiary)] mb-3" />
              <p className="text-sm font-medium text-[var(--text-primary)] mb-1">
                No sprints found
              </p>
              <p className="text-xs text-[var(--text-secondary)] max-w-xs">
                Connect your project tools (ADO/Jira) and sync data to see sprint iterations here.
              </p>
            </div>
          );
        })()
      ) : (
        /* ── AI Optimized View ── */
        planData?.plan ? (
          <div className="space-y-3">
            {[...aiSprintGroups.entries()]
              .sort(([a], [b]) => a - b)
              .map(([num, assignments], idx) => (
                <AiSprintGroup
                  key={num}
                  sprintNumber={num}
                  assignments={assignments}
                  defaultOpen={idx === 0}
                />
              ))}
            {aiSprintGroups.size === 0 && (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <UserIcon size={24} className="text-[var(--text-tertiary)] mb-2" />
                <p className="text-sm text-[var(--text-secondary)]">
                  No items assigned to you in the AI plan.
                </p>
                <button
                  onClick={() => setMyItemsOnly(false)}
                  className="mt-2 text-xs text-[var(--color-brand-secondary)] hover:underline cursor-pointer"
                >
                  View full sprint plan
                </button>
              </div>
            )}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <Sparkles size={32} className="text-[var(--text-tertiary)] mb-3" />
            <p className="text-sm font-medium text-[var(--text-primary)] mb-1">
              No AI sprint plan yet
            </p>
            <p className="text-xs text-[var(--text-secondary)] max-w-xs">
              Your Product Owner hasn&apos;t generated an AI-optimized sprint plan for this project yet.
            </p>
          </div>
        )
      )}
    </DashboardPanel>
    </div>
  );
}
