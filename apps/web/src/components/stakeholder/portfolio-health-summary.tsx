"use client";

/* ========================================================================= */
/*  STAKEHOLDER OVERVIEW - Executive dashboard (colorful, dense, gradient)   */
/*                                                                            */
/*  Four rows:                                                                */
/*    1. Sprint Completion hero - Actual vs Expected vs Delta                 */
/*    2. Section summaries: Delivery · Epics · Team Health (with conclusions) */
/*    3. Velocity trend (full width)                                          */
/*    4. Top risks + Upcoming milestones                                      */
/* ========================================================================= */

import { useState, useEffect, useCallback, useRef } from "react";
import {
  Loader2,
  TrendingDown,
  TrendingUp,
  Minus,
  Calendar,
  Activity,
  Flag,
  BarChart3,
  Users,
  Target,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { cachedFetch, invalidateCache } from "@/lib/fetch-cache";
import { useSelectedProject } from "@/lib/project/context";
import { useAutoRefresh } from "@/lib/ws/context";

/* ─── ROOT-CAUSE NOTE ───────────────────────────────────────────────────────
   Two issues this section fixes:

   1. Wrong iteration / stale data. The PO ProjectHeroBanner kicks off
      `/api/integrations/sync/auto` whenever it sees an empty dashboard,
      then polls until fresh data lands. The Stakeholder page never had
      that trigger. SYNC_SCHEDULER_ENABLED is false in production, so if no
      PO opened the dashboard recently, ADO/Jira changes (new iterations,
      story-point updates, etc.) don't propagate to Plan2Sprint's DB. A
      stakeholder visiting the page sees whatever was last synced - which
      is why Iteration 1 (oldest, ended 21d ago) was being shown instead
      of the current Iteration 3.

   2. Predictability flicker. `predictabilityV2 === null` was overloaded
      to mean both "still loading" and "v2 returned no data". During the
      first ~200ms of the fetch the local fallback (`computePredictability`)
      produced a number, then the v2 response arrived with `{score: null}`
      and the bar went blank. We now use a separate `predictabilityLoaded`
      flag so the bar stays in skeleton state until v2's authoritative
      answer is in.
   ─────────────────────────────────────────────────────────────────────── */

/* ------------------------------------------------------------------------- */
/*  Types                                                                     */
/* ------------------------------------------------------------------------- */

type Severity = "GREEN" | "AMBER" | "RED";

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
}

interface DashboardSummary {
  totalStoryPoints?: number;
  completedStoryPoints?: number;
  teamSize?: number;
  activeSprintCount?: number;
}

interface TeamHealthPillar {
  score: number;
  severity: string;
}

interface VelocitySprint {
  // Backend returns `name`, not `sprint` - fixed here.
  name: string;
  planned: number;
  completed: number;
  // Hotfix 93 - track which unit this entry's numbers are in.
  // Velocity Δ only makes sense when comparing two sprints in the
  // SAME unit. Without this flag, a sprint reporting in "items"
  // could get compared against one in "SP" and produce nonsense
  // like "+33200%" growth (the Plan2Sprint Iter-1 vs Iter-3 case).
  // Optional so existing callers that don't set it still type-check.
  unit?: "SP" | "items";
}

interface TeamHealthData {
  overallScore: number;
  overallSeverity: string;
  pillars: {
    workHours: TeamHealthPillar;
    burnoutRisk: TeamHealthPillar & { developers?: { name: string; score: number; severity: string }[] };
    sprintSustainability: TeamHealthPillar & {
      metrics?: { velocityTrend?: VelocitySprint[] };
    };
    busFactor: TeamHealthPillar;
    flowHealth: TeamHealthPillar;
    teamResilience: TeamHealthPillar;
  };
}

interface WorkItem {
  id: string;
  type?: string;
  status?: string;
  story_points?: number;
  storyPoints?: number;
}

interface MilestoneRow {
  id: string;
  name: string;
  plannedEndDate: string | null;
  status: string;
}

interface PlanFeature {
  id: string;
  title: string;
  status: string;
  completePct: number;
  plannedStart: string | null;
  plannedEnd: string | null;
  phaseInfo?: { name?: string } | null;
}

interface ProjectPlan {
  features?: PlanFeature[];
  unassigned?: PlanFeature[];
}

/* ------------------------------------------------------------------------- */
/*  Helpers                                                                   */
/* ------------------------------------------------------------------------- */

function severityColor(s: Severity): string {
  if (s === "GREEN") return "var(--color-rag-green)";
  if (s === "AMBER") return "var(--color-rag-amber)";
  return "var(--color-rag-red)";
}

function normalizeSeverity(s: string): Severity {
  const up = (s || "").toUpperCase();
  if (up === "GREEN" || up === "AMBER" || up === "RED") return up as Severity;
  return "AMBER";
}

function deltaToSeverity(delta: number): Severity {
  if (delta >= -5) return "GREEN";
  if (delta >= -15) return "AMBER";
  return "RED";
}

function daysFromNow(iso: string | null): number | null {
  if (!iso) return null;
  const ms = new Date(iso).getTime() - Date.now();
  return Math.round(ms / (1000 * 60 * 60 * 24));
}

function expectedPct(start: string | null, end: string | null): number {
  if (!start || !end) return 0;
  const s = new Date(start).getTime();
  const e = new Date(end).getTime();
  const now = Date.now();
  if (now <= s) return 0;
  if (now >= e) return 100;
  return Math.round(((now - s) / (e - s)) * 100);
}

/* ========================================================================= */
/*  Main component                                                            */
/* ========================================================================= */

export function PortfolioHealthSummary() {
  const { selectedProject } = useSelectedProject();
  const projectId = selectedProject?.internalId;
  const refreshKey = useAutoRefresh(["sync_complete", "health_analysis_complete"]);

  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [sprints, setSprints] = useState<Sprint[]>([]);
  const [workItems, setWorkItems] = useState<WorkItem[]>([]);
  const [health, setHealth] = useState<TeamHealthData | null>(null);
  const [projectPlan, setProjectPlan] = useState<ProjectPlan | null>(null);
  const [blockerCount, setBlockerCount] = useState(0);
  const [loading, setLoading] = useState(true);
  // v2 composite predictability from /api/analytics - authoritative value
  // computed by services.predictability_engine. We track the full block so
  // we can distinguish:
  //   - v2 was returned with a numeric score  -> use it
  //   - v2 was returned with score=null       -> honour null (e.g. no
  //                                              completed sprints yet);
  //                                              DO NOT silently fall back
  //                                              to the flawed local calc
  //                                              which used to return 100%
  //                                              from a single
  //                                              over-delivered sprint
  //   - v2 was not returned at all (error)    -> fall back to local
  const [predictabilityV2, setPredictabilityV2] = useState<{
    score: number | null;
  } | null>(null);
  // Tracks whether at least one fetch has fully resolved. Lets us
  // distinguish "predictabilityV2 is null because we haven't fetched yet"
  // (skeleton) from "v2 returned no v2 block at all" (compute local
  // fallback). Without this the first paint flickers a local-computed
  // number before the authoritative v2 null arrives and blanks the bar.
  const [predictabilityLoaded, setPredictabilityLoaded] = useState(false);

  // One-shot guard: only fire the auto-sync trigger once per project per
  // session. Without this the stakeholder page reads whatever DB state was
  // last synced (no SYNC_SCHEDULER in production), which means a stakeholder
  // gets stuck on iteration N while iteration N+1 already exists in ADO.
  const autoSyncAttempted = useRef<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    const q = projectId ? `?projectId=${projectId}` : "";
    const qAmp = projectId ? `&projectId=${projectId}` : "";
    try {
      const [summaryRes, sprintsRes, healthRes, standupsRes, wiRes, planRes, analyticsRes] = await Promise.all([
        cachedFetch(`/api/dashboard/summary${q}`),
        cachedFetch(`/api/dashboard/sprints${q}`),
        cachedFetch(`/api/team-health/dashboard${q}`),
        cachedFetch(`/api/standups${q}`),
        cachedFetch(`/api/dashboard/work-items?limit=500${qAmp}`),
        cachedFetch(`/api/dashboard/project-plan${q}`),
        cachedFetch(`/api/analytics${q}`),
      ]);

      if (summaryRes.ok) setSummary(summaryRes.data as DashboardSummary);
      let sprintsData: Sprint[] | null = null;
      if (sprintsRes.ok) {
        const data = sprintsRes.data as { sprints?: Sprint[] };
        sprintsData = data.sprints ?? [];
        setSprints(sprintsData);
      }
      if (healthRes.ok) setHealth(healthRes.data as TeamHealthData);
      if (standupsRes.ok) {
        const data = standupsRes.data as { blockerCount?: number };
        setBlockerCount(data.blockerCount ?? 0);
      }
      if (wiRes.ok) {
        const data = wiRes.data as { workItems?: WorkItem[] };
        setWorkItems(data.workItems ?? []);
      }
      if (planRes.ok) setProjectPlan(planRes.data as ProjectPlan);
      if (analyticsRes.ok) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const v2 = (analyticsRes.data as any)?.predictability?.v2;
        if (v2 && typeof v2 === "object") {
          // v2 was returned (even if score is null) - capture the whole
          // block so downstream can distinguish "authoritative null" from
          // "no response".
          setPredictabilityV2({
            score: typeof v2.score === "number" ? v2.score : null,
          });
        } else {
          setPredictabilityV2(null);
        }
      } else {
        setPredictabilityV2(null);
      }
      setPredictabilityLoaded(true);

      // Auto-sync: trigger an ADO/Jira pull when the DB looks stale, then
      // poll briefly for fresh data. Mirrors PO ProjectHeroBanner. We
      // consider the data stale when:
      //   (a) there are zero sprints in the DB, OR
      //   (b) the most recent sprint already ended (its end_date is in
      //       the past) - meaning the project has likely advanced to a
      //       newer iteration that hasn't been synced yet.
      if (projectId && autoSyncAttempted.current !== projectId && sprintsData) {
        const now = Date.now();
        const mostRecent = sprintsData[0]; // backend orders by start_date desc
        const mostRecentEnded =
          mostRecent?.endDate
            ? new Date(mostRecent.endDate).getTime() < now
            : true;
        const shouldSync =
          sprintsData.length === 0 || mostRecentEnded;

        if (shouldSync) {
          autoSyncAttempted.current = projectId;
          fetch("/api/integrations/sync/auto", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ projectId }),
          }).catch(() => {});

          // Poll up to 6 times (~30s) for a newer sprint to land.
          let attempts = 0;
          const pollInterval = setInterval(async () => {
            attempts += 1;
            if (attempts > 6) {
              clearInterval(pollInterval);
              return;
            }
            invalidateCache("/api/dashboard/");
            invalidateCache("/api/analytics");
            const q2 = projectId ? `?projectId=${projectId}` : "";
            const sRes = await cachedFetch(`/api/dashboard/sprints${q2}`);
            if (sRes.ok) {
              const sData = sRes.data as { sprints?: Sprint[] };
              const fresh = sData.sprints?.[0];
              const freshEnded =
                fresh?.endDate
                  ? new Date(fresh.endDate).getTime() < now
                  : true;
              // Stop polling once we see a sprint that ends in the future
              // OR once we see a different sprint than before.
              if (
                fresh &&
                (!freshEnded || fresh.id !== mostRecent?.id)
              ) {
                clearInterval(pollInterval);
                fetchData();
              }
            }
          }, 5000);
        }
      }
    } catch {}
    setLoading(false);
  }, [projectId]);

  useEffect(() => {
    fetchData();
  }, [fetchData, refreshKey]);

  if (loading && !summary && !health) {
    return (
      <div className="flex items-center justify-center py-24">
        <Loader2 size={28} className="animate-spin text-[var(--color-brand-secondary)]" />
      </div>
    );
  }

  // -------------- Derived metrics --------------

  // Active sprint detection - prefer the iteration that ACTUALLY has work.
  //
  // Real-world ADO setups do not always keep `timeFrame=current` on the
  // sprint where the team is actually working. We've observed projects
  // where ADO has Iteration 1 marked `current` (zero work) while
  // Iteration 3 has 56 items / 340 SP and is marked `future`. Trusting
  // ADO's state field there results in a "0% progress, sprint ended 22d
  // ago" dashboard while the actual work is one tab over.
  //
  // We also can't rely on time-window matching alone: many ADO projects
  // import iterations all sharing the project's date range, so today
  // either falls in all of them or none.
  //
  // Resolution order:
  //   1. Iteration with story points or items AND today within window.
  //   2. Iteration with state = "active" AND non-zero work.
  //   3. Iteration with the most story points (descending), tie-broken
  //      by latest start_date. This is what brings Iteration 3 back when
  //      it's where the work lives.
  //   4. Iteration whose [start, end] window contains today.
  //   5. ADO's nominal "active" iteration.
  //   6. sprints[0] (backend orders by start_date desc).
  const __nowMs = Date.now();
  const __hasWork = (s: Sprint) =>
    (s.totalStoryPoints || 0) > 0 || (s.totalItems || 0) > 0;
  const __containsToday = (s: Sprint) => {
    const sd = s.startDate ? new Date(s.startDate).getTime() : NaN;
    const ed = s.endDate ? new Date(s.endDate).getTime() : NaN;
    return !isNaN(sd) && !isNaN(ed) && sd <= __nowMs && __nowMs <= ed;
  };
  const __byMostWork = (a: Sprint, b: Sprint) => {
    const sa = a.totalStoryPoints || 0;
    const sb = b.totalStoryPoints || 0;
    if (sb !== sa) return sb - sa;
    const ta = a.totalItems || 0;
    const tb = b.totalItems || 0;
    if (tb !== ta) return tb - ta;
    const da = a.startDate ? new Date(a.startDate).getTime() : 0;
    const db = b.startDate ? new Date(b.startDate).getTime() : 0;
    return db - da;
  };

  const sprintsWithSP = sprints.filter(
    (s) => (s.totalStoryPoints || 0) > 0,
  );
  const sprintsWithItems = sprints.filter(
    (s) => (s.totalItems || 0) > 0,
  );

  // Resolution order - designed to be stable across project shapes:
  //
  //   1. Today is inside [startDate, endDate]. Most authoritative answer
  //      to "what sprint are we in right now?" - works for healthy
  //      projects with proper iteration date ranges, AND covers the
  //      brand-new-sprint case where today is in window but no work
  //      has been assigned yet (we still want to show that sprint).
  //
  //   2. Sprint with the most story points (recency-tie-broken). Picks
  //      up the case where ADO has its calendar dates wrong but the work
  //      is clearly concentrated in one iteration (the Iter-3-with-340-SP
  //      case). SP is preferred over items because a single stub item
  //      shouldn't outvote a real loaded sprint.
  //
  //   3. Items-based fallback for teams that don't track SP.
  //
  //   4. ADO's state=active marker - only trusted last because we've
  //      seen it pinned to empty stub iterations.
  //
  //   5. sprints[0] (backend orders by start_date desc).
  const activeSprint =
    sprints.find(__containsToday) ||
    [...sprintsWithSP].sort(__byMostWork)[0] ||
    [...sprintsWithItems].sort(__byMostWork)[0] ||
    sprints.find((s) => s.state === "active") ||
    sprints[0];

  const actualPct = activeSprint ? activeSprint.completionPct : 0;
  const expectedP = activeSprint
    ? expectedPct(activeSprint.startDate, activeSprint.endDate)
    : 0;
  const delta = actualPct - expectedP;
  const deltaSev = deltaToSeverity(delta);

  // ===== VELOCITY TREND =====
  // Per-sprint fallback: if a sprint has story points, use them; otherwise
  // fall back to item counts for that sprint. This ensures any sprint with
  // any tracked activity renders bars.
  const anySprintHasSp = sprints.some((s) => (s.totalStoryPoints || 0) > 0);
  const velocityUnit: "SP" | "items" = anySprintHasSp ? "SP" : "items";

  const velocityTrend: VelocitySprint[] = sprints
    .slice(0, 6)
    .reverse() // oldest first for chart
    .map((s) => {
      const sp = s.totalStoryPoints || 0;
      // Per-sprint unit choice: SP when available for this sprint, else items
      if (sp > 0) {
        return {
          name: s.name,
          planned: s.totalStoryPoints,
          completed: s.completedStoryPoints,
          unit: "SP" as const,
        };
      }
      return {
        name: s.name,
        planned: s.totalItems || 0,
        completed: s.completedItems || 0,
        unit: "items" as const,
      };
    })
    .filter((t) => t.planned > 0 || t.completed > 0);

  // Last-resort: if sprints have absolutely no data, fall back to the backend
  // sustainability trend (may also be empty - in which case chart hides).
  const finalVelocityTrend =
    velocityTrend.length > 0
      ? velocityTrend
      : (health?.pillars?.sprintSustainability?.metrics?.velocityTrend ?? []).filter(
          (t) => t.planned > 0 || t.completed > 0
        );

  // ===== PREDICTABILITY =====
  // Preferred: the v2 composite score from /api/analytics - symmetric
  // (over-delivery penalised), recency-weighted, variance-aware. Single
  // source of truth shared with the Delivery page and the weekly PDF.
  //
  // When v2 has been returned we honour its answer verbatim - including a
  // null score meaning "no completed sprints yet". Historically the UI
  // silently fell back to a local capped-at-1 avg which produced a
  // meaningless 100% for any project whose sole sprint over-delivered by
  // even one story. We never do that silent fallback again.
  //
  // Local fallbacks only fire when v2 wasn't returned at all (API error,
  // old backend revision):
  //   (a) local avg(completed/planned) over velocity trend
  //   (b) current sprint's actual% vs expected% when nothing else is
  //       measurable yet
  let predictability: number | null;
  if (!predictabilityLoaded) {
    // First fetch hasn't resolved yet. Don't compute a local fallback -
    // doing so produces a number that gets immediately overwritten when
    // the authoritative v2 response lands a tick later, which is the
    // flicker the user reported.
    predictability = null;
  } else if (predictabilityV2 !== null) {
    // Authoritative - even if the score is null, the product answer is
    // "not enough sprint history". Don't paper over it.
    predictability = predictabilityV2.score;
  } else {
    // v2 wasn't returned at all (older backend or transient error).
    predictability = computePredictability(finalVelocityTrend);
    if (predictability === null && activeSprint && expectedP > 0) {
      predictability = Math.min(100, Math.round((actualPct / expectedP) * 100));
    }
  }

  // Overall portfolio SP
  const totalSP = summary?.totalStoryPoints ?? 0;
  const completedSP = summary?.completedStoryPoints ?? 0;
  const teamSize = summary?.teamSize ?? 0;

  // Team health
  const overallHealthScore = Math.round(health?.overallScore ?? 0);
  const overallHealthSev = normalizeSeverity(health?.overallSeverity ?? "AMBER");
  const burnout = health?.pillars?.burnoutRisk;
  const sustainability = health?.pillars?.sprintSustainability;
  const busFactor = health?.pillars?.busFactor;

  // ===== UPCOMING MILESTONES =====
  // Stakeholder definition: upcoming timeline states + features not yet complete.
  // Hotfix 37 - loosened the filters so projects whose dates are stale
  // (e.g. all sprint end dates in the past, features lacking plannedEnd
  // because they haven't been included in a plan yet) still surface as
  // legitimate upcoming work. The previous strict ``plannedEnd > now``
  // filter showed empty for MediCare even though the entire project
  // still needs to be delivered. Now we include:
  //   1. Any sprint not yet completed (active, future, planned)
  //   2. Any feature whose status isn't ``complete`` AND completePct < 100,
  //      regardless of whether plannedEnd is set. Date-less features
  //      sort to the end of the list.
  const allFeatures: PlanFeature[] = [
    ...(projectPlan?.features ?? []),
    ...(projectPlan?.unassigned ?? []),
  ];

  const sprintMilestones: MilestoneRow[] = sprints
    .filter((s) => {
      const state = (s.state || "").toLowerCase();
      // Treat anything not explicitly closed as still upcoming. This
      // handles "future", "active", "planned", "scheduled" etc.
      return state !== "completed" && state !== "closed";
    })
    .map((s) => ({
      id: `sprint-${s.id}`,
      name: `${s.name} ends`,
      plannedEndDate: s.endDate,
      status: s.state,
    }));

  const featureMilestones: MilestoneRow[] = allFeatures
    .filter((f) => {
      const status = (f.status || "").toLowerCase();
      if (status === "complete") return false;
      if (typeof f.completePct === "number" && f.completePct >= 100) return false;
      return true;
    })
    .map((f) => ({
      id: `feat-${f.id}`,
      name: f.title.length > 60 ? f.title.slice(0, 57) + "…" : f.title,
      plannedEndDate: f.plannedEnd,
      status: f.status,
    }));

  // Sort by plannedEnd ascending (nulls last), so dated work shows
  // first and undated/TBD work shows after.
  const upcomingMilestones = [...sprintMilestones, ...featureMilestones]
    .sort((a, b) => {
      const at = a.plannedEndDate ? new Date(a.plannedEndDate).getTime() : Number.POSITIVE_INFINITY;
      const bt = b.plannedEndDate ? new Date(b.plannedEndDate).getTime() : Number.POSITIVE_INFINITY;
      return at - bt;
    })
    .slice(0, 5);

  const atRiskMilestones = upcomingMilestones.filter((m) => {
    const d = daysFromNow(m.plannedEndDate);
    return d != null && d <= 7;
  }).length;

  // Epic-like summaries = group work items by type (Epic / Feature / Story / Task)
  const typeGroups: Record<string, { total: number; done: number }> = {};
  for (const wi of workItems) {
    const t = wi.type || "Other";
    if (!typeGroups[t]) typeGroups[t] = { total: 0, done: 0 };
    typeGroups[t].total++;
    if ((wi.status || "").toUpperCase() === "DONE") typeGroups[t].done++;
  }
  const epicLikeTypes = Object.entries(typeGroups).filter(([t]) =>
    ["EPIC", "FEATURE"].includes(t.toUpperCase())
  );
  const totalEpics = epicLikeTypes.reduce((sum, [, g]) => sum + g.total, 0);
  const completedEpics = epicLikeTypes.reduce((sum, [, g]) => sum + g.done, 0);
  const activeEpics = totalEpics - completedEpics;

  // Risks composite
  const risks = computeTopRisks({
    deltaPct: delta,
    blockerCount,
    burnoutDevs: burnout?.developers ?? [],
    sustainabilityScore: sustainability?.score ?? 0,
    hasActiveSprint: !!activeSprint,
  });

  // Conclusions for section cards
  const deliveryConclusion = makeDeliveryConclusion(predictability, finalVelocityTrend);
  const epicsConclusion = makeEpicsConclusion(activeEpics, atRiskMilestones, upcomingMilestones);
  const healthConclusion = makeHealthConclusion(overallHealthScore, burnout?.developers ?? []);

  return (
    <div className="space-y-5">
      {/* ===== ROW 1: Sprint Completion Hero ===== */}
      <SprintCompletionHero
        sprint={activeSprint}
        actualPct={actualPct}
        expectedPct={expectedP}
        delta={delta}
        deltaSev={deltaSev}
      />

      {/* ===== ROW 2: 3 Section Summary Cards ===== */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
        <DeliveryCard
          predictability={predictability}
          velocityTrend={finalVelocityTrend}
          totalSP={totalSP}
          completedSP={completedSP}
          teamSize={teamSize}
          conclusion={deliveryConclusion}
        />
        <EpicsCard
          active={activeEpics}
          completed={completedEpics}
          total={totalEpics}
          atRisk={atRiskMilestones}
          conclusion={epicsConclusion}
        />
        <TeamHealthCard
          score={overallHealthScore}
          severity={overallHealthSev}
          burnout={burnout}
          sustainability={sustainability}
          busFactor={busFactor}
          conclusion={healthConclusion}
        />
      </div>

      {/* ===== ROW 3: Velocity Trend Full-Width ===== */}
      {finalVelocityTrend.length > 0 && (
        <VelocityTrendStrip trend={finalVelocityTrend} unit={velocityUnit} />
      )}

      {/* ===== ROW 4: Top Risks + Upcoming Milestones ===== */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        <TopRisksPanel risks={risks} />
        <UpcomingMilestonesPanel milestones={upcomingMilestones} />
      </div>
    </div>
  );
}

/* ========================================================================= */
/*  SPRINT COMPLETION HERO - Actual vs Expected vs Delta (colorful gradient) */
/* ========================================================================= */

function SprintCompletionHero({
  sprint,
  actualPct,
  expectedPct,
  delta,
  deltaSev,
}: {
  sprint?: Sprint;
  actualPct: number;
  expectedPct: number;
  delta: number;
  deltaSev: Severity;
}) {
  // Sprint phase determines which tiles to show. The original layout
  // (Actual / Expected / Behind) only makes intuitive sense for an
  // ACTIVE sprint, where Expected = elapsed time. For an ended sprint
  // it always reads "Expected 100% / Behind X%" regardless of what
  // actually happened, which buries the real story (planned vs
  // delivered). For a future sprint there is no completion to show.
  const phase: "active" | "ended" | "future" | "unknown" = (() => {
    if (!sprint || !sprint.startDate || !sprint.endDate) return "unknown";
    const now = Date.now();
    const s = new Date(sprint.startDate).getTime();
    const e = new Date(sprint.endDate).getTime();
    if (now < s) return "future";
    if (now > e) return "ended";
    return "active";
  })();

  // Severity selection: only colour the hero when the comparison is
  // meaningful (active sprint). For an ended sprint we colour by
  // attainment band instead. For a future sprint, neutral.
  const heroSev: Severity =
    phase === "ended"
      ? actualPct >= 95 ? "GREEN" : actualPct >= 75 ? "AMBER" : "RED"
      : phase === "active" ? deltaSev
      : "GREEN";

  // Gradient stops based on severity
  const gradientStart =
    heroSev === "GREEN" ? "rgba(34,197,94,0.18)" :
    heroSev === "AMBER" ? "rgba(245,158,11,0.18)" :
    "rgba(239,68,68,0.18)";

  const accentColor =
    heroSev === "GREEN" ? "rgba(34,197,94,0.30)" :
    heroSev === "AMBER" ? "rgba(245,158,11,0.30)" :
    "rgba(239,68,68,0.30)";

  const daysLeft = sprint ? daysFromNow(sprint.endDate) : null;
  const totalSP = sprint?.totalStoryPoints ?? 0;
  const completedSP = sprint?.completedStoryPoints ?? 0;
  const totalItems = sprint?.totalItems ?? 0;
  const completedItems = sprint?.completedItems ?? 0;
  const startsIn =
    phase === "future" && sprint?.startDate
      ? daysFromNow(sprint.startDate)
      : null;

  // Phase-specific eyebrow label so stakeholders read the right story
  // immediately. ("Sprint Completion" was the same string regardless,
  // implying we were always reporting on a finished sprint.)
  //
  // For the "ended" phase we use "Current Sprint" rather than "Last
  // Sprint Result". Reasoning: the activeSprint resolver picks the
  // iteration the team is actually working on. When ADO's calendar
  // dates have lapsed but no new sprint has started, the team is
  // still conceptually in that sprint - calling it "last sprint"
  // implies a fresh one has begun, which it hasn't.
  const eyebrow =
    phase === "ended" ? "Current Sprint"
    : phase === "future" ? "Upcoming Sprint"
    : "Sprint Progress";

  // Story point unit fallback - some projects have items but no SP.
  const planned = totalSP > 0 ? totalSP : totalItems;
  const delivered = totalSP > 0 ? completedSP : completedItems;
  const unit = totalSP > 0 ? "SP" : "items";
  const attainment = planned > 0 ? Math.round((delivered / planned) * 100) : 0;

  return (
    <div
      className="relative overflow-hidden rounded-2xl border p-8"
      style={{
        background: `linear-gradient(135deg, ${gradientStart} 0%, transparent 60%), var(--bg-surface)`,
        borderColor: "var(--border-subtle)",
      }}
    >
      {/* Decorative blur accent */}
      <div
        aria-hidden
        className="absolute top-0 right-0 w-80 h-80 rounded-full opacity-40 pointer-events-none"
        style={{
          background: accentColor,
          filter: "blur(80px)",
          transform: "translate(30%, -40%)",
        }}
      />

      <div className="relative flex flex-wrap items-start justify-between gap-4 mb-6">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-[var(--text-tertiary)]">
            {eyebrow}
          </p>
          <h2 className="mt-2 text-2xl font-bold text-[var(--text-primary)]">
            {sprint?.name || "No active sprint"}
          </h2>
          {sprint && (
            <p className="text-xs text-[var(--text-secondary)] mt-1">
              {delivered.toFixed(0)} of {planned.toFixed(0)} {unit}
              {phase === "active" && daysLeft != null && daysLeft > 0 && ` · ${daysLeft} days remaining`}
              {phase === "active" && daysLeft != null && daysLeft === 0 && ` · ends today`}
              {phase === "ended" && daysLeft != null && ` · ended ${Math.abs(daysLeft)}d ago`}
              {phase === "future" && startsIn != null && startsIn > 0 && ` · starts in ${startsIn}d`}
            </p>
          )}
        </div>
      </div>

      {/* 3 tiles - content depends on sprint phase */}
      <div className="relative grid grid-cols-1 sm:grid-cols-3 gap-4">
        {phase === "active" && (
          <>
            <RatioTile
              label="Actual"
              value={actualPct}
              color="var(--color-brand-secondary)"
              emphasis
            />
            <RatioTile
              label="Expected"
              value={expectedPct}
              color="var(--text-secondary)"
            />
            <RatioTile
              label={delta >= 0 ? "Ahead" : "Behind"}
              value={delta}
              suffix="%"
              color={severityColor(deltaSev)}
              emphasis
              showSign
            />
          </>
        )}

        {phase === "ended" && (
          <>
            <RatioTile
              label={`Planned ${unit}`}
              value={planned}
              suffix=""
              color="var(--text-secondary)"
              emphasis
              showBar={false}
            />
            <RatioTile
              label={`Delivered ${unit}`}
              value={delivered}
              suffix=""
              color="var(--color-brand-secondary)"
              emphasis
              showBar={false}
            />
            <RatioTile
              label="Plan Attainment"
              value={attainment}
              color={severityColor(heroSev)}
              emphasis
            />
          </>
        )}

        {phase === "future" && (
          <>
            <RatioTile
              label={`Planned ${unit}`}
              value={planned}
              suffix=""
              color="var(--text-secondary)"
              emphasis
              showBar={false}
            />
            <RatioTile
              label="Starts In"
              value={startsIn ?? 0}
              suffix="d"
              color="var(--color-brand-secondary)"
              emphasis
              showBar={false}
            />
            <RatioTile
              label="Status"
              value={0}
              suffix=""
              color="var(--text-secondary)"
              emphasis
              showBar={false}
            />
          </>
        )}

        {phase === "unknown" && (
          <>
            <RatioTile label="Actual" value={actualPct} color="var(--color-brand-secondary)" emphasis />
            <RatioTile label="Expected" value={expectedPct} color="var(--text-secondary)" />
            <RatioTile
              label={delta >= 0 ? "Ahead" : "Behind"}
              value={delta}
              suffix="%"
              color={severityColor(deltaSev)}
              emphasis
              showSign
            />
          </>
        )}
      </div>
    </div>
  );
}

function RatioTile({
  label,
  value,
  color,
  emphasis,
  showSign,
  suffix = "%",
  showBar = true,
}: {
  label: string;
  value: number;
  color: string;
  emphasis?: boolean;
  showSign?: boolean;
  suffix?: string;
  showBar?: boolean;
}) {
  const displayValue = Math.abs(value).toFixed(0);
  const sign = showSign ? (value > 0 ? "+" : value < 0 ? "−" : "") : "";
  // Bar only makes sense for percentage values. For raw counts (story
  // points, day counts) capping at 100 produces a meaningless full bar.
  const barWidth = Math.min(Math.abs(value), 100);

  return (
    <div
      className={cn(
        "rounded-xl p-5 border",
        emphasis ? "bg-[var(--bg-surface-raised)]" : "bg-transparent",
      )}
      style={{
        borderColor: emphasis ? color + "40" : "var(--border-subtle)",
      }}
    >
      <p className="text-[10px] font-semibold uppercase tracking-widest text-[var(--text-tertiary)]">
        {label}
      </p>
      <div className="mt-1 flex items-baseline gap-1">
        <span
          className="text-4xl font-bold leading-none tabular-nums"
          style={{ color }}
        >
          {sign}
          {displayValue}
        </span>
        <span className="text-lg font-light" style={{ color }}>
          {suffix}
        </span>
      </div>
      {showBar && (
        <div className="mt-3 h-1.5 rounded-full bg-[var(--bg-surface-sunken)] overflow-hidden">
          <div
            className="h-full rounded-full transition-all"
            style={{ width: `${barWidth}%`, backgroundColor: color }}
          />
        </div>
      )}
    </div>
  );
}

/* ========================================================================= */
/*  SECTION SUMMARY CARDS (Delivery · Epics · Team Health)                    */
/* ========================================================================= */

function SectionCard({
  title,
  icon: Icon,
  gradientFrom,
  gradientTo,
  children,
  conclusion,
}: {
  title: string;
  icon: typeof BarChart3;
  gradientFrom: string;
  gradientTo: string;
  children: React.ReactNode;
  conclusion: string;
}) {
  return (
    <div className="relative overflow-hidden rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] flex flex-col">
      {/* Colored gradient top strip */}
      <div
        className="h-1.5"
        style={{
          background: `linear-gradient(90deg, ${gradientFrom}, ${gradientTo})`,
        }}
      />

      <div className="p-6 flex-1 flex flex-col">
        {/* Header */}
        <div className="flex items-center gap-2 mb-4">
          <span
            className="flex h-8 w-8 items-center justify-center rounded-lg"
            style={{
              background: `linear-gradient(135deg, ${gradientFrom}, ${gradientTo})`,
            }}
          >
            <Icon size={15} className="text-white" />
          </span>
          <h3 className="text-sm font-semibold text-[var(--text-primary)] uppercase tracking-wider">
            {title}
          </h3>
        </div>

        {/* Body */}
        <div className="flex-1">{children}</div>

        {/* AI conclusion footer */}
        <div className="mt-5 pt-4 border-t border-[var(--border-subtle)]">
          <div className="flex items-start gap-2">
            <Sparkles size={12} className="mt-0.5 shrink-0 text-[var(--color-brand-secondary)]" />
            <p className="text-[11px] leading-relaxed text-[var(--text-secondary)]">
              {conclusion}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

/* -------------------------- Delivery Card -------------------------------- */

function DeliveryCard({
  predictability,
  velocityTrend,
  totalSP,
  completedSP,
  teamSize,
  conclusion,
}: {
  predictability: number | null;
  velocityTrend: VelocitySprint[];
  totalSP: number;
  completedSP: number;
  teamSize: number;
  conclusion: string;
}) {
  const hasData = predictability !== null;
  const predSeverity: Severity = !hasData ? "AMBER" :
    predictability >= 85 ? "GREEN" : predictability >= 60 ? "AMBER" : "RED";
  const predColor = severityColor(predSeverity);
  const overallPct = totalSP > 0 ? Math.round((completedSP / totalSP) * 100) : 0;

  // Hotfix 93 - Velocity Δ guards.
  //
  // The original ((last - prev) / prev) × 100 produced absurd
  // numbers ("+33,200%") in two failure modes:
  //
  //   1) Unit mismatch - the velocityTrend builder picks SP per
  //      sprint when SP > 0, else items. So a "stub" sprint with
  //      1 item completed could sit next to a real sprint with
  //      333 SP completed, and the formula treated 1 and 333 as
  //      the same unit. Now we require last.unit === prev.unit
  //      before computing anything.
  //
  //   2) Tiny baseline - even with matching units, dividing 333
  //      by 1 produces 33,200%. We require prev.completed to
  //      meet a minimum (5 SP or 3 items) before reporting a
  //      meaningful percentage.
  //
  //   3) Plus a defensive ±200% display cap so future edge cases
  //      we haven't anticipated never render four-digit deltas.
  const last = velocityTrend[velocityTrend.length - 1];
  const prev = velocityTrend[velocityTrend.length - 2];
  const MIN_BASELINE_SP = 5;
  const MIN_BASELINE_ITEMS = 3;
  const DISPLAY_CAP_PCT = 200;

  let velDelta: number | null = null;
  let velDeltaTooltip: string | undefined;

  if (last && prev && last.unit === prev.unit) {
    const minBaseline = last.unit === "SP" ? MIN_BASELINE_SP : MIN_BASELINE_ITEMS;
    if (prev.completed >= minBaseline) {
      velDelta = Math.round(((last.completed - prev.completed) / prev.completed) * 100);
    } else {
      velDeltaTooltip = `Previous sprint completed only ${prev.completed} ${prev.unit ?? ""} - too small a baseline to compute a meaningful velocity change.`;
    }
  } else if (last && prev && last.unit !== prev.unit) {
    velDeltaTooltip = `The previous sprint was measured in ${prev.unit}, this one in ${last.unit}. Need two sprints in the same unit to compute Δ.`;
  } else if (!prev) {
    velDeltaTooltip = "Need at least two completed sprints to compute velocity change.";
  }

  // Apply ±200% display cap with overflow indicator.
  let velDeltaLabel: string;
  let velDeltaIsCapped = false;
  if (velDelta === null) {
    velDeltaLabel = "N/A";
  } else if (velDelta > DISPLAY_CAP_PCT) {
    velDeltaLabel = `>+${DISPLAY_CAP_PCT}%`;
    velDeltaIsCapped = true;
  } else if (velDelta < -DISPLAY_CAP_PCT) {
    velDeltaLabel = `<−${DISPLAY_CAP_PCT}%`;
    velDeltaIsCapped = true;
  } else {
    velDeltaLabel = `${velDelta >= 0 ? "+" : ""}${velDelta}%`;
  }
  if (velDeltaIsCapped) {
    velDeltaTooltip = `Raw value is ${velDelta}% - capped at ±${DISPLAY_CAP_PCT}% for readability.`;
  }

  return (
    <SectionCard
      title="Delivery"
      icon={BarChart3}
      gradientFrom="#3b82f6"
      gradientTo="#06b6d4"
      conclusion={conclusion}
    >
      <p className="text-[10px] font-semibold uppercase tracking-widest text-[var(--text-tertiary)]">
        Predictability
      </p>
      <div className="mt-1 flex items-baseline gap-1">
        {hasData ? (
          <>
            <span className="text-5xl font-bold leading-none tabular-nums" style={{ color: predColor }}>
              {predictability}
            </span>
            <span className="text-xl font-light" style={{ color: predColor }}>%</span>
          </>
        ) : (
          <span className="text-5xl font-bold leading-none text-[var(--text-tertiary)]">-</span>
        )}
      </div>
      {!hasData && (
        <p className="mt-1 text-[11px] text-[var(--text-tertiary)]">
          Sync project data to compute
        </p>
      )}

      <div className="mt-4 grid grid-cols-3 gap-3" data-onboarding="predictability-row">
        <MiniStat label="Portfolio" value={`${overallPct}%`} />
        <MiniStat
          label="Velocity Δ"
          value={velDeltaLabel}
          emphasis={
            velDelta === null
              ? "var(--text-tertiary)"
              : velDelta < -5
                ? "var(--color-rag-red)"
                : velDelta > 5
                  ? "var(--color-rag-green)"
                  : undefined
          }
          title={velDeltaTooltip}
        />
        <MiniStat label="Team" value={`${teamSize}`} />
      </div>
    </SectionCard>
  );
}

/* -------------------------- Epics Card ----------------------------------- */

function EpicsCard({
  active,
  completed,
  total,
  atRisk,
  conclusion,
}: {
  active: number;
  completed: number;
  total: number;
  atRisk: number;
  conclusion: string;
}) {
  const completionPct = total > 0 ? Math.round((completed / total) * 100) : 0;

  return (
    <SectionCard
      title="Epics & Milestones"
      icon={Target}
      gradientFrom="#a855f7"
      gradientTo="#ec4899"
      conclusion={conclusion}
    >
      <p className="text-[10px] font-semibold uppercase tracking-widest text-[var(--text-tertiary)]">
        Progress
      </p>
      <div className="mt-1 flex items-baseline gap-2">
        <span className="text-5xl font-bold leading-none tabular-nums text-[var(--text-primary)]">
          {completed}
        </span>
        <span className="text-lg font-light text-[var(--text-tertiary)]">/ {total}</span>
      </div>
      <p className="text-xs text-[var(--text-secondary)] mt-1">
        {completionPct}% of milestones completed
      </p>

      <div className="mt-4 grid grid-cols-3 gap-3">
        <MiniStat label="Active" value={`${active}`} />
        <MiniStat label="At Risk" value={`${atRisk}`} emphasis={atRisk > 0 ? "var(--color-rag-amber)" : undefined} />
        <MiniStat label="Done" value={`${completed}`} />
      </div>
    </SectionCard>
  );
}

/* -------------------------- Team Health Card ----------------------------- */

function TeamHealthCard({
  score,
  severity,
  burnout,
  sustainability,
  busFactor,
  conclusion,
}: {
  score: number;
  severity: Severity;
  burnout?: TeamHealthPillar;
  sustainability?: TeamHealthPillar;
  busFactor?: TeamHealthPillar;
  conclusion: string;
}) {
  const color = severityColor(severity);
  const label = severity === "GREEN" ? "Healthy" : severity === "AMBER" ? "At Risk" : "Critical";

  return (
    <SectionCard
      title="Team Health"
      icon={Users}
      gradientFrom="#10b981"
      gradientTo="#14b8a6"
      conclusion={conclusion}
    >
      <p className="text-[10px] font-semibold uppercase tracking-widest text-[var(--text-tertiary)]">
        Overall Score
      </p>
      <div className="mt-1 flex items-baseline gap-2">
        <span className="text-5xl font-bold leading-none tabular-nums" style={{ color }}>
          {score}
        </span>
        <span className="text-lg font-light text-[var(--text-tertiary)]">/ 100</span>
      </div>
      <p
        className="mt-1 text-[11px] font-bold uppercase tracking-widest"
        style={{ color }}
      >
        {label}
      </p>

      <div className="mt-4 space-y-2.5">
        {burnout && (
          <PillarBar label="Burnout" value={Math.round(burnout.score)} severity={normalizeSeverity(burnout.severity)} invert />
        )}
        {sustainability && (
          <PillarBar label="Sustainability" value={Math.round(sustainability.score)} severity={normalizeSeverity(sustainability.severity)} />
        )}
        {busFactor && (
          <PillarBar label="Bus factor" value={Math.round(busFactor.score)} severity={normalizeSeverity(busFactor.severity)} />
        )}
      </div>
    </SectionCard>
  );
}

/* -------------------------- Helpers -------------------------------------- */

function MiniStat({
  label,
  value,
  emphasis,
  title,
}: {
  label: string;
  value: string;
  emphasis?: string;
  /** Hover tooltip - used by Velocity Δ to explain "N/A" / capped values. */
  title?: string;
}) {
  return (
    <div
      className="rounded-lg bg-[var(--bg-surface-raised)]/50 border border-[var(--border-subtle)] p-2.5"
      title={title}
    >
      <p className="text-[9px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
        {label}
      </p>
      <p
        className="mt-1 text-sm font-semibold tabular-nums"
        style={{ color: emphasis || "var(--text-primary)" }}
      >
        {value}
      </p>
    </div>
  );
}

function PillarBar({
  label,
  value,
  severity,
  invert,
}: {
  label: string;
  value: number;
  severity: Severity;
  invert?: boolean;
}) {
  const color = severityColor(severity);
  const fill = invert ? 100 - value : value;
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-[11px] text-[var(--text-secondary)]">{label}</span>
        <span className="text-[10px] font-semibold tabular-nums" style={{ color }}>
          {value}
        </span>
      </div>
      <div className="h-1 rounded-full bg-[var(--bg-surface-sunken)] overflow-hidden">
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${Math.max(4, Math.min(100, fill))}%`, backgroundColor: color }}
        />
      </div>
    </div>
  );
}

/* ========================================================================= */
/*  VELOCITY TREND STRIP (same as before, slight color polish)                */
/* ========================================================================= */

function VelocityTrendStrip({
  trend,
  unit = "SP",
}: {
  trend: VelocitySprint[];
  unit?: "SP" | "items";
}) {
  const avgCompleted = trend.length
    ? Math.round(trend.reduce((a, b) => a + b.completed, 0) / trend.length)
    : 0;
  const last = trend[trend.length - 1];
  const prev = trend[trend.length - 2];
  // Cap delta so mixed-unit sprints (e.g. one using items, another using SP)
  // don't display absurd % swings like +19200%. Above ±500%, show "-".
  const rawDelta = prev && prev.completed > 0
    ? Math.round(((last.completed - prev.completed) / prev.completed) * 100)
    : 0;
  const deltaOutOfRange = Math.abs(rawDelta) > 500;
  const delta = deltaOutOfRange ? 0 : rawDelta;

  const maxValue = Math.max(...trend.map((t) => Math.max(t.planned, t.completed)), 1);

  const TrendIcon = delta > 5 ? TrendingUp : delta < -5 ? TrendingDown : Minus;
  const trendColor = delta > 5 ? "var(--color-rag-green)" : delta < -5 ? "var(--color-rag-red)" : "var(--text-secondary)";

  return (
    <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-7">
      <div className="flex items-start justify-between mb-6 flex-wrap gap-4">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-[var(--text-tertiary)]">
            Velocity Trend
          </p>
          <p className="mt-2 text-xs text-[var(--text-secondary)]">
            Last {trend.length} sprints
          </p>
        </div>
        <div className="flex items-center gap-5">
          <div className="text-right">
            <p className="text-[10px] uppercase tracking-wider text-[var(--text-tertiary)]">Average</p>
            <p className="text-sm font-semibold tabular-nums text-[var(--text-primary)]">
              {avgCompleted} {unit}
            </p>
          </div>
          <div className="text-right">
            <p className="text-[10px] uppercase tracking-wider text-[var(--text-tertiary)]">Δ Last</p>
            <p
              className="text-sm font-semibold tabular-nums flex items-center gap-1 justify-end"
              style={{ color: trendColor }}
            >
              {deltaOutOfRange ? (
                <span className="text-[var(--text-tertiary)]">-</span>
              ) : (
                <>
                  <TrendIcon size={12} />
                  {delta > 0 ? "+" : ""}{delta}%
                </>
              )}
            </p>
          </div>
        </div>
      </div>

      {/* Bars row - explicit fixed height so percentage heights resolve */}
      <div className="flex items-end gap-3" style={{ height: "120px" }}>
        {trend.map((t, idx) => {
          const completedH = Math.max((t.completed / maxValue) * 100, 2);
          const plannedH = Math.max((t.planned / maxValue) * 100, 2);
          const isLast = idx === trend.length - 1;
          return (
            <div
              key={`bar-${t.name}-${idx}`}
              className="flex-1 flex items-end gap-0.5"
              style={{ height: "100%" }}
            >
              {/* Planned (ghost bar) */}
              <div
                className="flex-1 rounded-t-sm opacity-30 bg-[var(--text-tertiary)]"
                style={{ height: `${plannedH}%`, minHeight: "3px" }}
              />
              {/* Delivered */}
              <div
                className="flex-1 rounded-t-sm transition-all"
                style={{
                  height: `${completedH}%`,
                  minHeight: "3px",
                  background: isLast
                    ? "linear-gradient(to top, #3b82f6, #06b6d4)"
                    : "var(--text-secondary)",
                  opacity: isLast ? 1 : 0.7,
                }}
              />
            </div>
          );
        })}
      </div>
      {/* Labels row - separate, no height interplay with bars */}
      <div className="flex gap-3 mt-2">
        {trend.map((t, idx) => (
          <span
            key={`lbl-${t.name}-${idx}`}
            className="flex-1 text-[10px] text-[var(--text-tertiary)] truncate text-center"
          >
            {t.name}
          </span>
        ))}
      </div>

      <div className="mt-4 flex items-center gap-4 text-[10px] text-[var(--text-tertiary)]">
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-2 h-2 rounded-sm bg-[var(--text-tertiary)] opacity-30" />
          Planned
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-2 h-2 rounded-sm bg-gradient-to-r from-[#3b82f6] to-[#06b6d4]" />
          Delivered
        </span>
      </div>
    </div>
  );
}

/* ========================================================================= */
/*  TOP RISKS + MILESTONES                                                    */
/* ========================================================================= */

interface RiskItem {
  severity: Severity;
  title: string;
  detail: string;
}

function computeTopRisks(args: {
  deltaPct: number;
  blockerCount: number;
  burnoutDevs: { name: string; score: number; severity: string }[];
  sustainabilityScore: number;
  hasActiveSprint: boolean;
}): RiskItem[] {
  const risks: RiskItem[] = [];

  if (args.hasActiveSprint && args.deltaPct < -15) {
    risks.push({
      severity: "RED",
      title: `Sprint behind pace by ${Math.abs(args.deltaPct)}%`,
      detail: "Current sprint delivery is lagging the expected burn rate. Sprint goal at risk.",
    });
  } else if (args.hasActiveSprint && args.deltaPct < -5) {
    risks.push({
      severity: "AMBER",
      title: `Sprint pace ${Math.abs(args.deltaPct)}% below expected`,
      detail: "Early warning - catch up in the next 2–3 days or rebalance scope.",
    });
  }

  if (args.blockerCount >= 3) {
    risks.push({
      severity: "RED",
      title: `${args.blockerCount} blockers open`,
      detail: "Multiple active blockers - review with engineering leads.",
    });
  } else if (args.blockerCount > 0) {
    risks.push({
      severity: "AMBER",
      title: `${args.blockerCount} blocker${args.blockerCount > 1 ? "s" : ""} open`,
      detail: "Blockers affecting sprint flow.",
    });
  }

  const highBurnout = args.burnoutDevs.filter((d) => (d.severity || "").toUpperCase() === "RED");
  if (highBurnout.length > 0) {
    const names = highBurnout.slice(0, 3).map((d) => d.name).join(", ");
    risks.push({
      severity: "RED",
      title: `${highBurnout.length} developer${highBurnout.length > 1 ? "s" : ""} at burnout risk`,
      detail: names,
    });
  }

  if (args.sustainabilityScore > 0 && args.sustainabilityScore < 50) {
    risks.push({
      severity: "AMBER",
      title: "Sprint sustainability low",
      detail: "Work volume and pace not sustainable over multiple cycles.",
    });
  }

  return risks.slice(0, 4);
}

function TopRisksPanel({ risks }: { risks: RiskItem[] }) {
  return (
    <div className="lg:col-span-7 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] overflow-hidden">
      <div
        className="h-1"
        style={{ background: "linear-gradient(90deg, #f59e0b, #ef4444)" }}
      />
      <div className="p-7">
        <div className="flex items-center gap-2 mb-5">
          <Activity size={14} className="text-[var(--text-secondary)]" />
          <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-[var(--text-tertiary)]">
            Top Risks
          </p>
        </div>

        {risks.length === 0 ? (
          <div className="flex items-center gap-2 py-6 text-sm text-[var(--color-rag-green)]">
            <Flag size={14} />
            No critical risks flagged right now.
          </div>
        ) : (
          <ul className="space-y-3.5">
            {risks.map((r, i) => (
              <li key={i} className="flex items-start gap-3">
                <span
                  className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full"
                  style={{ backgroundColor: severityColor(r.severity) }}
                />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold" style={{ color: severityColor(r.severity) }}>
                    {r.title}
                  </p>
                  <p className="text-xs text-[var(--text-secondary)] mt-0.5 leading-relaxed">
                    {r.detail}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function UpcomingMilestonesPanel({ milestones }: { milestones: MilestoneRow[] }) {
  return (
    <div className="lg:col-span-5 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] overflow-hidden">
      <div
        className="h-1"
        style={{ background: "linear-gradient(90deg, #3b82f6, #8b5cf6)" }}
      />
      <div className="p-7">
        <div className="flex items-center gap-2 mb-5">
          <Calendar size={14} className="text-[var(--text-secondary)]" />
          <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-[var(--text-tertiary)]">
            Upcoming Milestones
          </p>
        </div>

        {milestones.length === 0 ? (
          <p className="text-sm text-[var(--text-tertiary)] py-4 italic">
            No upcoming milestones scheduled.
          </p>
        ) : (
          <ul className="space-y-4">
            {milestones.map((m) => {
              const days = daysFromNow(m.plannedEndDate);
              // Overdue (past-due, still not complete) = most urgent red.
              // Otherwise RAG by days remaining.
              const isOverdue = days != null && days < 0;
              const urgency =
                days == null ? "var(--text-tertiary)" :
                isOverdue ? "var(--color-rag-red)" :
                days <= 7 ? "var(--color-rag-red)" :
                days <= 21 ? "var(--color-rag-amber)" :
                "var(--color-rag-green)";
              const dateLabel = m.plannedEndDate
                ? new Date(m.plannedEndDate).toLocaleDateString("en-US", { month: "short", day: "numeric" })
                : "-";
              // Humanize the day delta
              const dayLabel =
                days == null ? "" :
                isOverdue ? ` · ${Math.abs(days)}d overdue` :
                days === 0 ? " · due today" :
                days === 1 ? " · tomorrow" :
                ` · in ${days}d`;
              return (
                <li key={m.id} className="flex items-center justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-[var(--text-primary)] truncate">
                      {m.name}
                    </p>
                    <p className="text-[11px] tabular-nums" style={{ color: urgency }}>
                      {dateLabel}{dayLabel}
                    </p>
                  </div>
                  <span className="h-2 w-2 rounded-full shrink-0" style={{ backgroundColor: urgency }} />
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}

/* ========================================================================= */
/*  CONCLUSION COMPUTERS                                                      */
/* ========================================================================= */

function computePredictability(
  trend: VelocitySprint[]
): number | null {
  if (trend.length === 0) return null;
  const ratios = trend
    .filter((t) => t.planned > 0)
    .map((t) => Math.min(1, t.completed / t.planned));
  if (ratios.length === 0) return null;
  const avg = ratios.reduce((a, b) => a + b, 0) / ratios.length;
  return Math.round(avg * 100);
}

function makeDeliveryConclusion(
  predictability: number | null,
  trend: VelocitySprint[]
): string {
  if (predictability === null) {
    if (trend.length === 0) {
      return "No completed sprints yet - syncing the project will unlock delivery analytics.";
    }
    return "Not enough sprint history with story points to compute predictability.";
  }
  if (predictability >= 85) {
    return "Team is delivering what it commits to. Healthy cadence - safe to plan ambitious sprints.";
  }
  if (predictability >= 60) {
    return "Team delivers most commitments but frequently runs over. Consider slightly lighter sprints or tighter scoping.";
  }
  return "Commitments routinely missed. Immediate scope re-calibration or sprint-rebalancing advised.";
}

function makeEpicsConclusion(
  active: number,
  atRisk: number,
  upcoming: MilestoneRow[]
): string {
  if (upcoming.length === 0 && active === 0) {
    return "No active milestones. Add milestones in the Epics section to track delivery.";
  }
  if (atRisk > 0) {
    const next = upcoming[0]?.name;
    return `${atRisk} milestone${atRisk > 1 ? "s" : ""} at risk - soonest is ${next || "upcoming"}.`;
  }
  if (active > 0) {
    return `${active} milestone${active > 1 ? "s" : ""} in progress. No imminent risks flagged.`;
  }
  return "All milestones on track. Next checkpoint approaching normally.";
}

function makeHealthConclusion(
  score: number,
  burnoutDevs: { name: string; score: number; severity: string }[]
): string {
  const highBurnout = burnoutDevs.filter((d) => (d.severity || "").toUpperCase() === "RED").length;
  if (score >= 75 && highBurnout === 0) {
    return "Team is performing sustainably. No immediate wellness concerns.";
  }
  if (highBurnout > 0) {
    return `${highBurnout} developer${highBurnout > 1 ? "s" : ""} at burnout risk. 1:1s recommended this week.`;
  }
  if (score < 50) {
    return "Team health is deteriorating. Review workload distribution and sustainability metrics.";
  }
  return "Team is stable with minor watch-outs. Monitor burnout and sustainability trends.";
}
