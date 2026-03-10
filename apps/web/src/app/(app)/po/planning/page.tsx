"use client";

import { useState, useEffect, useCallback } from "react";
import { Zap, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui";
import { MetricStrip, type MetricItem } from "@/components/ui/metric-strip";
import { SprintWorkspaceToolbar } from "@/components/po/sprint-workspace-toolbar";
import { SprintTimelineTable } from "@/components/po/sprint-timeline-table";
import { AIInsightsPanel } from "@/components/po/ai-insights-panel";
import { SprintForecastPanel } from "@/components/po/sprint-forecast-panel";
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
// Component
// ---------------------------------------------------------------------------

export default function PlanningPage() {
  const { selectedProject } = useSelectedProject();
  const refreshKey = useAutoRefresh([
    "sprint_plan_generated",
    "sprint_plan_updated",
    "sync_complete",
  ]);

  // State
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [plan, setPlan] = useState<PlanOverview | null>(null);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [workItems, setWorkItems] = useState<WorkItemData[]>([]);
  const [teamMembers, setTeamMembers] = useState<TeamMemberData[]>([]);

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
        setAssignments([]);
        setLoading(false);
        return;
      }
      const overviewData = await overviewRes.json();
      if (!overviewData?.plan) {
        setPlan(null);
        setAssignments([]);
        setLoading(false);
        return;
      }

      // Fetch full plan details
      const detailRes = await fetch(`/api/sprints/plan?projectId=${projectId}`);
      if (detailRes.ok) {
        const data = await detailRes.json();
        if (data.plan) {
          setPlan(data.plan);
          setAssignments(data.assignments || []);
          setWorkItems(data.workItems || []);
          setTeamMembers(data.teamMembers || []);
        } else {
          setPlan(null);
          setAssignments([]);
        }
      }
    } catch {
      // API unavailable
      setPlan(null);
      setAssignments([]);
    }

    setLoading(false);
  }, [projectId]);

  useEffect(() => {
    setLoading(true);
    fetchPlanData();
  }, [fetchPlanData, refreshKey]);

  // -----------------------------------------------------------------------
  // Actions
  // -----------------------------------------------------------------------

  const handleGenerate = async () => {
    if (!projectId) return;
    setGenerating(true);
    try {
      const res = await fetch("/api/sprints", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ projectId }),
      });
      if (res.ok) {
        // Invalidate all sprint caches to ensure fresh data
        invalidateCache("/api/sprints");
        await fetchPlanData();
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

  const handleRegenerate = async () => {
    if (!projectId) return;
    setGenerating(true);
    try {
      const res = await fetch("/api/sprints", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          projectId,
          feedback:
            plan?.status === "REJECTED"
              ? "Regenerating after rejection"
              : undefined,
        }),
      });
      if (res.ok) {
        invalidateCache("/api/sprints");
        await fetchPlanData();
      }
    } catch (e) {
      console.error("Regeneration failed:", e);
    } finally {
      setGenerating(false);
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

  // No plan exists — empty state
  if (!plan) {
    return (
      <div className="flex flex-col items-center justify-center h-[calc(100vh-180px)] gap-4">
        <div className="flex h-16 w-16 items-center justify-center rounded-xl bg-[var(--color-brand-secondary)]/10">
          <Zap className="h-8 w-8 text-[var(--color-brand-secondary)]" />
        </div>
        <p className="text-sm font-semibold text-[var(--text-primary)]">
          No Sprint Plan Yet
        </p>
        <p className="text-xs text-[var(--text-secondary)] text-center max-w-md">
          Generate an AI-powered sprint plan for &ldquo;{selectedProject.name}&rdquo;.
          The AI will analyze your backlog, team capacity, velocity, and skills
          to create optimal assignments across multiple sprints.
        </p>
        <Button
          variant="primary"
          size="md"
          onClick={handleGenerate}
          disabled={generating}
        >
          {generating ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Zap className="h-4 w-4" />
          )}
          {generating ? "Generating..." : "Generate Sprint Plan"}
        </Button>
      </div>
    );
  }

  // Plan exists — full workspace layout
  return (
    <div className="flex flex-col h-[calc(100vh-120px)]">
      {/* Toolbar */}
      <SprintWorkspaceToolbar
        status={plan.status}
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
      />

      {/* Sprint Forecast — AI-powered prediction */}
      <div className="px-4 py-3 overflow-y-auto max-h-[420px]">
        <SprintForecastPanel />
      </div>

      {/* Sprint Timeline Table — full width now */}
      <div className="flex-1 min-h-0">
        <SprintTimelineTable
          assignments={assignments}
          workItems={workItems}
          teamMembers={teamMembers}
          estimatedSprints={plan.estimatedSprints ?? 1}
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
  );
}
