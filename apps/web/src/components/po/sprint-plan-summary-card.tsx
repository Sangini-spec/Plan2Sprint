"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { ClipboardCheck, ExternalLink, Loader2 } from "lucide-react";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Badge, Button, Progress } from "@/components/ui";
import { useSelectedProject } from "@/lib/project/context";
import { useAutoRefresh } from "@/lib/ws/context";
import { cachedFetch, invalidateCache } from "@/lib/fetch-cache";
import type { SprintPlanStatus } from "@/lib/types/models";

const statusBadgeVariant: Record<
  SprintPlanStatus,
  "rag-green" | "rag-amber" | "rag-red" | "brand"
> = {
  GENERATING: "brand",
  PENDING_REVIEW: "rag-amber",
  APPROVED: "rag-green",
  REJECTED: "rag-red",
  REGENERATING: "brand",
  SYNCING: "rag-amber",
  SYNCED: "rag-green",
  SYNCED_PARTIAL: "rag-amber",
  UNDONE: "rag-red",
  EXPIRED: "rag-red",
  FAILED: "rag-red",
};

interface PlanData {
  id: string;
  status: SprintPlanStatus;
  confidenceScore: number | null;
  totalStoryPoints: number | null;
  successProbability: number | null;
  estimatedSprints: number | null;
  riskSummary: string | null;
}

export function SprintPlanSummaryCard() {
  const router = useRouter();
  const { selectedProject } = useSelectedProject();
  const [plan, setPlan] = useState<PlanData | null>(null);
  const [loading, setLoading] = useState(true);
  const refreshKey = useAutoRefresh([
    "sprint_plan_generated",
    "sprint_plan_updated",
    "sync_complete",
    "github_activity",
    "sprint_completed",
  ]);

  const projectId = selectedProject?.internalId;

  const fetchPlan = useCallback(async () => {
    try {
      const params = projectId ? `?projectId=${projectId}` : "";
      invalidateCache(`/api/sprints${params}`);
      const res = await cachedFetch(`/api/sprints${params}`);
      if (res.ok) {
        const data = res.data as { plan?: PlanData };
        if (data.plan) {
          setPlan(data.plan);
          return;
        }
      }
    } catch {
      // API unavailable
    }
    setPlan(null);
  }, [projectId]);

  useEffect(() => {
    setLoading(true);
    fetchPlan().finally(() => setLoading(false));
  }, [fetchPlan, refreshKey]);

  // Loading state
  if (loading) {
    return (
      <DashboardPanel title="Sprint Plan" icon={ClipboardCheck}>
        <div className="flex items-center justify-center py-10">
          <Loader2 className="h-5 w-5 animate-spin text-[var(--text-secondary)]" />
        </div>
      </DashboardPanel>
    );
  }

  // No plan exists
  if (!plan) {
    return (
      <DashboardPanel title="Sprint Plan" icon={ClipboardCheck}>
        <div className="flex flex-col items-center justify-center py-8 gap-3">
          <ClipboardCheck
            size={28}
            className="text-[var(--text-tertiary)]"
          />
          <p className="text-sm text-[var(--text-secondary)]">
            No sprint plan generated yet
          </p>
          <Button
            variant="primary"
            size="sm"
            onClick={() => router.push("/po/planning")}
          >
            <ExternalLink className="h-3.5 w-3.5" />
            Go to Planning
          </Button>
        </div>
      </DashboardPanel>
    );
  }

  // Normalize confidence
  const rawConf = plan.confidenceScore ?? 0;
  const normalizedConf = rawConf > 1 ? rawConf / 100 : rawConf;
  const confidencePct = Math.round(normalizedConf * 100);

  return (
    <DashboardPanel
      title="Sprint Plan"
      icon={ClipboardCheck}
      actions={
        <Badge variant={statusBadgeVariant[plan.status]}>
          {plan.status.replace(/_/g, " ")}
        </Badge>
      }
    >
      <div className="space-y-4">
        {/* Confidence Score */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[var(--text-secondary)]">
              Confidence
            </span>
            <span className="text-sm font-bold tabular-nums text-[var(--text-primary)]">
              {confidencePct}%
            </span>
          </div>
          <Progress
            value={confidencePct}
            severity={
              confidencePct >= 80
                ? "GREEN"
                : confidencePct >= 60
                  ? "AMBER"
                  : "RED"
            }
            size="sm"
          />
        </div>

        {/* Success Probability */}
        {plan.successProbability != null && (
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-[var(--text-secondary)]">
                Success Probability
              </span>
              <span className="text-sm font-bold tabular-nums text-[var(--text-primary)]">
                {plan.successProbability}%
              </span>
            </div>
            <Progress
              value={plan.successProbability}
              severity={
                plan.successProbability >= 75
                  ? "GREEN"
                  : plan.successProbability >= 50
                    ? "AMBER"
                    : "RED"
              }
              size="sm"
            />
          </div>
        )}

        {/* Stats row */}
        <div className="grid grid-cols-2 gap-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] p-3">
          <div className="text-center">
            <p className="text-[10px] font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-0.5">
              Total SP
            </p>
            <p className="text-lg font-bold text-[var(--text-primary)] tabular-nums">
              {plan.totalStoryPoints ?? "-"}
            </p>
          </div>
          <div className="text-center border-l border-[var(--border-subtle)]">
            <p className="text-[10px] font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-0.5">
              Sprints
            </p>
            <p className="text-lg font-bold text-[var(--text-primary)] tabular-nums">
              {plan.estimatedSprints ?? "-"}
            </p>
          </div>
        </div>

        {/* View Full Plan */}
        <Button
          variant="secondary"
          size="sm"
          className="w-full"
          onClick={() => router.push("/po/planning")}
        >
          <ExternalLink className="h-3.5 w-3.5" />
          View Full Plan
        </Button>
      </div>
    </DashboardPanel>
  );
}
