"use client";

import { useState, useEffect, useCallback } from "react";
import { Zap, Loader2, Scale } from "lucide-react";
import { cn } from "@/lib/utils";
import { apiFetch } from "@/lib/api-fetch";
import { Button, Tabs } from "@/components/ui";
import { MetricStrip, type MetricItem } from "@/components/ui/metric-strip";
import { SprintForecastPanel } from "@/components/po/sprint-forecast-panel";
import { SprintRebalanceTab } from "@/components/po/sprint-rebalance-tab";
import { SprintWorkspaceToolbar } from "@/components/po/sprint-workspace-toolbar";
import { SprintTimelineTable } from "@/components/po/sprint-timeline-table";
import { AIInsightsPanel } from "@/components/po/ai-insights-panel";
import { PlanApprovalModal } from "@/components/po/plan-approval-modal";
import { WritebackConfirmationPanel } from "@/components/po/writeback-confirmation-panel";
import { useSelectedProject } from "@/lib/project/context";
import { useAutoRefresh } from "@/lib/ws/context";
import { cachedFetch, invalidateCache } from "@/lib/fetch-cache";
import type { SprintPlanStatus } from "@/lib/types/models";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PlanOverview {
  id: string;
  status: SprintPlanStatus;
  confidenceScore: number | null;
  totalStoryPoints: number | null;
  riskSummary: string | null;
  overallRationale: string | null;
  aiModelUsed: string | null;
  estimatedSprints: number | null;
  estimatedEndDate: string | null;
  successProbability: number | null;
  estimatedWeeksTotal: number | null;
  projectCompletionSummary: string | null;
  capacityRecommendations: {
    team_utilization_pct: number;
    understaffed: boolean;
    recommended_additions: number;
    bottleneck_skills: string[];
    summary: string;
  } | null;
  tool: string | null;
  isRebalanced?: boolean;
  rebalanceSourceId?: string | null;
}

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
  defaultCapacity: number;
}

// ---------------------------------------------------------------------------
// Tab config
// ---------------------------------------------------------------------------

const TAB_ITEMS = [
  { id: "planning", label: "Planning" },
  { id: "forecast", label: "Forecast" },
  { id: "rebalance", label: "Rebalance" },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function PlanningPage() {
  const { selectedProject } = useSelectedProject();
  const refreshKey = useAutoRefresh([
    "sprint_plan_generated",
    "sprint_plan_updated",
    "sync_complete",
  ]);

  // Tab state
  const [activeTab, setActiveTab] = useState("planning");

  // State
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [plan, setPlan] = useState<PlanOverview | null>(null);
  // Hotfix 32 — Step E: separate "inflight" state for the GENERATING /
  // FAILED stub. ``plan`` always holds the most recent READY plan so
  // the dashboard data (SP, sprints, rebalance flag, insights) stays
  // visible during regeneration. ``inflight`` drives the status badge
  // when a generation is queued, and is null otherwise.
  const [inflight, setInflight] = useState<{
    id: string;
    status: "GENERATING" | "FAILED";
    riskSummary: string | null;
    createdAt: string | null;
  } | null>(null);
  // Hotfix 33b — when the user kicked off the current generation
  // (millis epoch). Drives the live MM:SS timer in the toolbar.
  // Cleared when generation completes (success or failure).
  const [generationStartedAtMs, setGenerationStartedAtMs] = useState<number | null>(null);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [workItems, setWorkItems] = useState<WorkItemData[]>([]);
  const [teamMembers, setTeamMembers] = useState<TeamMemberData[]>([]);
  const [excludedMembers, setExcludedMembers] = useState<TeamMemberData[]>([]);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [sprintDetails, setSprintDetails] = useState<any[]>([]);

  // Modal state
  const [modalOpen, setModalOpen] = useState(false);
  const [modalMode, setModalMode] = useState<"approve" | "reject">("approve");

  const projectId = selectedProject?.internalId;

  // -----------------------------------------------------------------------
  // Fetch plan data
  // -----------------------------------------------------------------------

  const fetchPlanData = useCallback(async () => {
    if (!projectId) {
      setPlan(null);
      setInflight(null);
      setAssignments([]);
      setWorkItems([]);
      setTeamMembers([]);
      setLoading(false);
      return;
    }

    try {
      // Invalidate cache to always get fresh data
      invalidateCache(`/api/sprints?projectId=${projectId}`);
      invalidateCache(`/api/sprints/plan?projectId=${projectId}`);

      // Fetch overview first to see if a plan exists (bypass cache with fresh fetch)
      const overviewRes = await fetch(`/api/sprints?projectId=${projectId}`);
      if (!overviewRes.ok) {
        setPlan(null);
        setInflight(null);
        setAssignments([]);
        setLoading(false);
        return;
      }
      const overviewData = await overviewRes.json();
      // Hotfix 32 — Step E: capture the GENERATING/FAILED stub if any.
      // The backend now sends ``inflight`` separately so the previous
      // READY plan stays visible during regeneration.
      setInflight(overviewData?.inflight ?? null);
      if (!overviewData?.plan) {
        // No ready plan yet (first-ever generation, or only an in-flight
        // stub exists). Clear plan-level data; UI will show the empty
        // state while the inflight badge stays visible.
        setPlan(null);
        setAssignments([]);
        setWorkItems([]);
        setTeamMembers([]);
        setSprintDetails([]);
        setLoading(false);
        return;
      }

      // Fetch full plan details
      const detailRes = await fetch(`/api/sprints/plan?projectId=${projectId}`);
      if (detailRes.ok) {
        const data = await detailRes.json();
        // Detail endpoint returns inflight too — prefer it (more recent)
        if (data.inflight !== undefined) {
          setInflight(data.inflight);
        }
        if (data.plan) {
          setPlan(data.plan);
          setAssignments(data.assignments || []);
          setWorkItems(data.workItems || []);
          setTeamMembers(data.teamMembers || []);
          setSprintDetails(data.sprintDetails || []);
        } else {
          setPlan(null);
          setAssignments([]);
          setSprintDetails([]);
        }
      }
    } catch {
      // API unavailable — preserve any prior plan/inflight state to
      // avoid blank-flickering between fetches when the API is
      // mid-coldstart. The retry logic in project context handles
      // genuine outages.
    }

    setLoading(false);
  }, [projectId]);

  const fetchExcludedMembers = useCallback(async () => {
    if (!projectId) { setExcludedMembers([]); return; }
    try {
      // Fetch ALL org members (from Team page API) + explicitly excluded members
      const [orgRes, exclRes] = await Promise.all([
        fetch("/api/organizations/current/members"),
        fetch(`/api/sprints/excluded-members?projectId=${projectId}`),
      ]);

      // Build set of IDs already in the plan's teamMembers
      const planMemberIds = new Set(teamMembers.map((tm) => tm.id));
      const planMemberEmails = new Set(teamMembers.map((tm) => tm.email.toLowerCase()));

      const available: TeamMemberData[] = [];

      // Hotfix 33h — dedupe by display name. The user has multiple
      // accounts under the same display name (one per email/role) and
      // doesn't want to see them all separately. Priority:
      //   1. Excluded TeamMember for THIS project — re-including this
      //      one is preferable because it preserves the existing row's
      //      email/avatar/skills history rather than creating a new
      //      one with a different email.
      //   2. Org member with role='developer' — only fallback when no
      //      excluded row exists for the same display name.
      // Anything not 'developer' (PO, stakeholder, owner, admin) is
      // dropped entirely — they're not assignable in sprint planning.
      const seenNames = new Set<string>();
      const planMemberNames = new Set(
        teamMembers.map((tm) => (tm.displayName || "").toLowerCase()),
      );

      // Pass 1: excluded-for-this-project candidates (highest priority).
      if (exclRes.ok) {
        const exclData = await exclRes.json();
        for (const m of exclData.members || []) {
          if (planMemberIds.has(m.id)) continue;
          const name = (m.displayName || "").toLowerCase();
          if (planMemberNames.has(name)) continue;  // already on team under this name
          if (seenNames.has(name)) continue;
          seenNames.add(name);
          available.push(m);
        }
      }

      // Pass 2: org-level developers, skipping any name we've already covered.
      if (orgRes.ok) {
        const orgData = await orgRes.json();
        for (const m of orgData.members || []) {
          const email = (m.email || "").toLowerCase();
          const name = (m.displayName || "").toLowerCase();
          // Skip if already on team (by email or name)
          if (planMemberEmails.has(email)) continue;
          if (planMemberNames.has(name)) continue;
          // Skip if we already added this name from the excluded pass
          if (seenNames.has(name)) continue;
          // Skip non-developer roles
          const role = (m.role || "").toLowerCase();
          if (role && role !== "developer") continue;
          seenNames.add(name);
          available.push({
            id: m.teamMemberId || m.id,
            displayName: m.displayName,
            email: m.email,
            avatarUrl: m.avatarUrl,
            skillTags: [],
            defaultCapacity: 40,
          });
        }
      }

      setExcludedMembers(available);
    } catch { setExcludedMembers([]); }
  }, [projectId, teamMembers]);

  useEffect(() => {
    setLoading(true);
    fetchPlanData();
  }, [fetchPlanData, refreshKey]);

  // Fetch available-to-add members after plan data loads (needs teamMembers)
  useEffect(() => {
    if (teamMembers.length > 0 || !loading) {
      fetchExcludedMembers();
    }
  }, [teamMembers, fetchExcludedMembers, loading]);

  // -----------------------------------------------------------------------
  // Actions
  // -----------------------------------------------------------------------

  // Sprint plan generation is a slow AI call (60-120s). The Next.js rewrite
  // proxy times out around 50-60s which is what was causing "Sprint
  // generation failed: Internal Server Error". Prefer NEXT_PUBLIC_API_URL
  // so the browser POSTs straight to the API (CORS already allows it) and
  // the web container never has to hold the long upstream request open.
  // Falls back to the relative URL for local dev where the proxy is fine.
  const sprintApiBase =
    typeof window !== "undefined" && process.env.NEXT_PUBLIC_API_URL
      ? process.env.NEXT_PUBLIC_API_URL
      : "";

  // Hotfix 33 — shared poller for in-flight generation. Watches the
  // ``inflight`` field returned by GET /api/sprints?projectId=… and
  // returns when it clears (success) or transitions to FAILED.
  // Caller is responsible for setGenerating + fetchPlanData refresh.
  const pollUntilInflightClears = useCallback(async () => {
    if (!projectId) return;
    const POLL_INTERVAL_MS = 3000;
    const POLL_TIMEOUT_MS = 5 * 60 * 1000;
    const startedAt = Date.now();
    while (Date.now() - startedAt < POLL_TIMEOUT_MS) {
      await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
      try {
        invalidateCache(`/api/sprints?projectId=${projectId}`);
        const r = await fetch(`/api/sprints?projectId=${projectId}`);
        if (!r.ok) continue;
        const body = await r.json();
        const inflightStub = body?.inflight ?? null;
        if (!inflightStub) {
          await fetchPlanData();
          setGenerationStartedAtMs(null);  // Hotfix 33b — stop timer
          return;
        }
        if (inflightStub?.status === "FAILED") {
          await fetchPlanData();
          setGenerationStartedAtMs(null);  // Hotfix 33b — stop timer
          return;
        }
      } catch { /* network blip, keep polling */ }
    }
    await fetchPlanData();
    setGenerationStartedAtMs(null);  // Hotfix 33b — timed out, clear timer
  }, [projectId, fetchPlanData]);

  const handleGenerate = async () => {
    if (!projectId) return;
    setGenerating(true);
    setGenerationStartedAtMs(Date.now());  // Hotfix 33b — start timer
    try {
      // apiFetch auto-attaches the Supabase token so we can hit the API
      // directly (bypassing Next.js proxy whose 50-60s rewrite timeout
      // was what was making AI sprint generation fail with 500).
      const res = await apiFetch(`${sprintApiBase}/api/sprints`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ projectId }),
      });
      if (res.ok) {
        // Invalidate all sprint caches to ensure fresh data
        invalidateCache("/api/sprints");
        invalidateCache(`/api/sprints?projectId=${projectId}`);
        invalidateCache(`/api/sprints/plan?projectId=${projectId}`);
        await fetchPlanData();
        // Hotfix 33 — POLL until the BG task actually finishes; the
        // POST returned 202 in <1s but the AI call runs for 60-180s.
        await pollUntilInflightClears();
      } else {
        const errData = await res.json().catch(() => ({}));
        console.error("Generation failed:", errData);
      }
    } catch (e) {
      console.error("Generation failed:", e);
    } finally {
      setGenerating(false);
    }
  };

  const handleRegenerate = async (feedback?: string) => {
    if (!projectId) return;
    setGenerating(true);
    setGenerationStartedAtMs(Date.now());  // Hotfix 33b — start timer
    try {
      // Default optimization: pack 2-3 features per sprint to minimize total sprints
      const defaultFeedback = feedback ||
        "CRITICAL: Pack 2-3 features/epics into EACH sprint. Do NOT put only 1 feature per sprint. " +
        "Group related features together (e.g., registration + onboarding in Sprint 1, booking + consultation in Sprint 2). " +
        "Each sprint must contain ALL stories from its assigned features. " +
        "Target the minimum number of sprints possible — aim for half the number of features.";

      // apiFetch — same reason as handleGenerate above.
      const res = await apiFetch(`${sprintApiBase}/api/sprints`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          projectId,
          feedback: defaultFeedback,
        }),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        let errData;
        try { errData = JSON.parse(text); } catch { errData = { raw: text.slice(0, 200) }; }
        console.error(`Regeneration failed (${res.status}):`, errData);
        alert(`Sprint generation failed: ${errData?.detail || errData?.raw || `HTTP ${res.status}`}`);
        return;
      }

      // Refresh once immediately so the inline "Generating new plan…"
      // indicator appears instantly.
      invalidateCache("/api/sprints");
      invalidateCache(`/api/sprints?projectId=${projectId}`);
      invalidateCache(`/api/sprints/plan?projectId=${projectId}`);
      invalidateCache("/api/sprints/plan");
      await fetchPlanData();

      // Hotfix 33 — POLL until the BG task finishes. POST returned 202
      // in <1s but the AI call runs for 60-180s.
      await pollUntilInflightClears();
    } catch (e) {
      console.error("Regeneration failed:", e);
    } finally {
      setGenerating(false);
    }
  };

  const handleExcludeMember = async (memberId: string, displayName: string) => {
    if (!confirm(`Remove ${displayName} from sprint planning?`)) return;
    try {
      const res = await fetch("/api/sprints/team-member", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ memberId, action: "exclude" }),
      });
      if (res.ok) {
        const excluded = teamMembers.find((tm) => tm.id === memberId);
        setTeamMembers((prev) => prev.filter((tm) => tm.id !== memberId));
        setAssignments((prev) => prev.filter((a) => a.teamMemberId !== memberId));
        if (excluded) setExcludedMembers((prev) => [...prev, excluded]);
      }
    } catch (e) {
      console.error("Failed to exclude member:", e);
    }
  };

  const handleIncludeMember = async (memberId: string, displayName: string) => {
    try {
      // Hotfix 33c — pass projectId so the backend can create a
      // project-bound team_member row when the candidate came from the
      // org-members list (i.e. has no TeamMember row for this project
      // yet). Without projectId the backend can only toggle existing
      // rows, which silently affected the wrong project.
      const res = await fetch("/api/sprints/team-member", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ memberId, projectId, action: "include" }),
      });
      if (res.ok) {
        const data = await res.json().catch(() => null);
        const newId: string = data?.memberId ?? memberId;
        const included = excludedMembers.find((tm) => tm.id === memberId);
        setExcludedMembers((prev) => prev.filter((tm) => tm.id !== memberId));
        if (included) {
          // If the backend created a brand-new row for this project, use
          // its new id (so subsequent exclude/include works). Otherwise
          // keep the original.
          setTeamMembers((prev) => [...prev, { ...included, id: newId }]);
        }
        // Refetch plan data so the new dev shows in Team Capacity card
        // immediately. Without this the card stays stale until next regen.
        await fetchPlanData();
      } else {
        const errData = await res.json().catch(() => ({}));
        console.error("Failed to include member:", errData);
        alert(`Could not add ${displayName}: ${errData?.detail || "unknown error"}`);
      }
    } catch (e) {
      console.error("Failed to include member:", e);
    }
  };

  const handleApprove = () => {
    setModalMode("approve");
    setModalOpen(true);
  };

  const handleReject = () => {
    setModalMode("reject");
    setModalOpen(true);
  };

  const handleModalClose = () => {
    setModalOpen(false);
    // Refresh data after approve/reject
    fetchPlanData();
  };

  // -----------------------------------------------------------------------
  // Metrics for the strip (no model name)
  // -----------------------------------------------------------------------

  const metricItems: MetricItem[] = [];
  if (plan) {
    metricItems.push({
      label: "SP Total",
      value: plan.totalStoryPoints ?? 0,
    });
    metricItems.push({
      label: "Sprints",
      value: plan.estimatedSprints ?? 1,
    });
    if (plan.estimatedWeeksTotal) {
      metricItems.push({
        label: "Weeks",
        value: `~${plan.estimatedWeeksTotal}`,
      });
    }
    if (plan.confidenceScore != null) {
      const confPct = Math.round(
        (plan.confidenceScore > 1
          ? plan.confidenceScore / 100
          : plan.confidenceScore) * 100
      );
      metricItems.push({
        label: "Confidence",
        value: `${confPct}%`,
        severity:
          confPct >= 80 ? "green" : confPct >= 60 ? "amber" : "red",
      });
    }
    if (plan.successProbability != null) {
      metricItems.push({
        label: "Success",
        value: `${plan.successProbability}%`,
        severity:
          plan.successProbability >= 75
            ? "green"
            : plan.successProbability >= 50
              ? "amber"
              : "red",
      });
    }
    // Model name intentionally omitted
  }

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------

  // Loading state
  if (loading) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-180px)]">
        <Loader2 className="h-6 w-6 animate-spin text-[var(--text-secondary)]" />
      </div>
    );
  }

  // No project selected
  if (!selectedProject) {
    return (
      <div className="flex flex-col items-center justify-center h-[calc(100vh-180px)] gap-3">
        <Zap className="h-10 w-10 text-[var(--text-secondary)]" />
        <p className="text-sm font-medium text-[var(--text-primary)]">
          Select a Project
        </p>
        <p className="text-xs text-[var(--text-secondary)] text-center max-w-sm">
          Choose a project from the selector above to view or generate a sprint
          plan.
        </p>
      </div>
    );
  }

  // No plan exists — empty state. Hotfix 32 — Step E: if a generation
  // is in flight (project's first plan being created right now, or a
  // FAILED stub awaiting retry), surface that here so the user isn't
  // looking at "Generate" while a job is already running.
  if (!plan) {
    const isGenerating = inflight?.status === "GENERATING" || generating;
    const failedSummary = inflight?.status === "FAILED" ? inflight.riskSummary : null;
    return (
      <div className="flex flex-col items-center justify-center h-[calc(100vh-180px)] gap-4">
        <div className="flex h-16 w-16 items-center justify-center rounded-xl bg-[var(--color-brand-secondary)]/10">
          <Zap className="h-8 w-8 text-[var(--color-brand-secondary)]" />
        </div>
        <p className="text-sm font-semibold text-[var(--text-primary)]">
          {isGenerating ? "Generating Sprint Plan…" : failedSummary ? "Generation Failed" : "No Sprint Plan Yet"}
        </p>
        <p className="text-xs text-[var(--text-secondary)] text-center max-w-md">
          {isGenerating
            ? `The AI is analyzing the backlog for "${selectedProject.name}". This typically takes 30-90 seconds. The page will refresh automatically when ready.`
            : failedSummary
              ? failedSummary
              : `Generate an AI-powered sprint plan for "${selectedProject.name}". The AI will analyze your backlog, team capacity, velocity, and skills to create optimal assignments across multiple sprints.`}
        </p>
        <Button
          variant="primary"
          size="md"
          onClick={handleGenerate}
          disabled={isGenerating}
        >
          {isGenerating ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Zap className="h-4 w-4" />
          )}
          {isGenerating
            ? "Generating..."
            : failedSummary
              ? "Try Again"
              : "Generate Sprint Plan"}
        </Button>
      </div>
    );
  }

  // Plan exists — full workspace layout with tabs
  return (
    <div className="space-y-4">
      {/* Tab bar — same pattern as PO Dashboard */}
      <Tabs
        items={TAB_ITEMS}
        activeId={activeTab}
        onChange={setActiveTab}
        className="max-w-xs"
      />

      {/* ── Sprint Planning Tab ── */}
      {activeTab === "planning" && (
        <div className="flex flex-col h-[calc(100vh-180px)]">
          {/* Rebalance shift banner */}
          {plan.isRebalanced && (
            <div className="mb-3 flex items-center gap-3 p-3 rounded-lg bg-orange-500/5 border border-orange-500/20">
              <Scale size={18} className="text-orange-400 shrink-0" />
              <div className="flex-1">
                <p className="text-sm font-medium text-[var(--text-primary)]">
                  Plan has been shifted to Rebalance
                </p>
                <p className="text-xs text-[var(--text-secondary)]">
                  This sprint plan was created from a rebalancing proposal. View details in the Rebalance tab.
                </p>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setActiveTab("rebalance")}
                className="text-orange-400 text-xs shrink-0"
              >
                View Rebalance
              </Button>
            </div>
          )}
          {/* Toolbar */}
          <SprintWorkspaceToolbar
            status={plan.status}
            inflightStatus={inflight?.status ?? null}
            inflightRiskSummary={inflight?.riskSummary ?? null}
            inflightStartedAtMs={generationStartedAtMs}
            generating={generating}
            projectName={selectedProject.name}
            onGenerate={handleGenerate}
            onRegenerate={handleRegenerate}
            onApprove={handleApprove}
            onReject={handleReject}
          />

          {/* Metric strip */}
          {metricItems.length > 0 && (
            <div className="px-4 py-2.5 border-b border-[var(--border-subtle)]">
              <MetricStrip items={metricItems} />
            </div>
          )}

          {/* AI Insights — full-width collapsible overview */}
          <AIInsightsPanel
            estimatedSprints={plan.estimatedSprints}
            estimatedWeeksTotal={plan.estimatedWeeksTotal}
            estimatedEndDate={plan.estimatedEndDate}
            projectCompletionSummary={plan.projectCompletionSummary}
            capacityRecommendations={plan.capacityRecommendations}
            totalStoryPoints={plan.totalStoryPoints}
            riskSummary={plan.riskSummary}
            assignments={assignments}
            teamMembers={teamMembers}
            overallRationale={plan.overallRationale}
            onExcludeMember={handleExcludeMember}
            excludedMembers={excludedMembers}
            onIncludeMember={handleIncludeMember}
          />

          {/* Sprint Timeline Table — full width */}
          <div className="flex-1 min-h-0">
            <SprintTimelineTable
              assignments={assignments}
              workItems={workItems}
              teamMembers={teamMembers}
              estimatedSprints={plan.estimatedSprints ?? 1}
              sprintDetails={sprintDetails}
            />
          </div>

          {/* Writeback status — always visible when plan exists */}
          <div className="border-t border-[var(--border-subtle)]">
            <WritebackConfirmationPanel />
          </div>

          {/* Slim confirmation modal */}
          <PlanApprovalModal
            open={modalOpen}
            onClose={handleModalClose}
            mode={modalMode}
            planId={plan.id}
            totalSP={plan.totalStoryPoints}
            estimatedSprints={plan.estimatedSprints}
            tool={plan.tool}
          />
        </div>
      )}

      {/* ── Sprint Forecast Tab ── */}
      {activeTab === "forecast" && (
        <div className="space-y-4">
          <SprintForecastPanel onRebalance={() => setActiveTab("rebalance")} />
        </div>
      )}

      {/* ── Sprint Rebalance Tab ── */}
      {activeTab === "rebalance" && (
        <div className="space-y-4">
          <SprintRebalanceTab
            planId={plan?.id || null}
            rebalancingRecommended={(plan?.successProbability ?? 100) < 65}
            successProbability={plan?.successProbability ?? 0}
            isRebalanced={plan?.isRebalanced ?? false}
          />
        </div>
      )}
    </div>
  );
}
