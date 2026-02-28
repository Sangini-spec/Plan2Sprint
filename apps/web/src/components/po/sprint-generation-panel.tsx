"use client";

import { useState, useEffect, useCallback } from "react";
import { Zap, RefreshCw, ExternalLink, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Badge, Button, Progress } from "@/components/ui";
import { useSelectedProject } from "@/lib/project/context";
import { useAutoRefresh } from "@/lib/ws/context";
import { cachedFetch, invalidateCache } from "@/lib/fetch-cache";
import type { SprintPlanStatus } from "@/lib/types/models";

const statusBadgeVariant: Record<SprintPlanStatus, "rag-green" | "rag-amber" | "rag-red" | "brand"> = {
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
};

interface PlanData {
  id: string;
  status: SprintPlanStatus;
  confidenceScore: number | null;
  totalStoryPoints: number | null;
  riskSummary: string | null;
  aiModelUsed: string | null;
  approvedAt: string | null;
  createdAt: string | null;
  successProbability: number | null;
}

interface SprintGenerationPanelProps {
  onViewPlan?: () => void;
}

export function SprintGenerationPanel({ onViewPlan }: SprintGenerationPanelProps) {
  const { selectedProject } = useSelectedProject();
  const [plan, setPlan] = useState<PlanData | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const refreshKey = useAutoRefresh(["sprint_plan_generated", "sprint_plan_updated", "sync_complete"]);

  // ---------- Fetch sprint data from API ----------

  const projectId = selectedProject?.internalId;

  const fetchSprintData = useCallback(async () => {
    try {
      const params = projectId ? `?projectId=${projectId}` : "";
      const res = await cachedFetch(`/api/sprints${params}`);
      if (res.ok) {
        const data = res.data as { plan?: PlanData };
        if (data.plan) {
          setPlan(data.plan);
          return;
        }
      }
    } catch {
      // API unavailable — leave plan as null so "Optimize" button shows
    }

    // No real plan exists — show the generate prompt
    setPlan(null);
  }, [projectId]);

  useEffect(() => {
    setLoading(true);
    fetchSprintData().finally(() => setLoading(false));
  }, [fetchSprintData, refreshKey]);

  // ---------- Generate / Optimize sprint plan ----------

  const handleOptimize = async () => {
    if (!selectedProject) return;

    setGenerating(true);
    try {
      const res = await fetch("/api/sprints", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          projectId: selectedProject.internalId,
        }),
      });

      if (res.ok) {
        const data = await res.json();
        // Refresh the panel to show the new plan
        await fetchSprintData();
      }
    } catch (e) {
      console.error("Failed to generate sprint plan:", e);
    } finally {
      setGenerating(false);
    }
  };

  const handleRegenerate = async () => {
    if (!selectedProject || !plan) return;

    setGenerating(true);
    try {
      const res = await fetch("/api/sprints", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          projectId: selectedProject.internalId,
          feedback: plan.status === "REJECTED" ? "Regenerating after rejection" : undefined,
        }),
      });

      if (res.ok) {
        await fetchSprintData();
      }
    } catch (e) {
      console.error("Failed to regenerate sprint plan:", e);
    } finally {
      setGenerating(false);
    }
  };

  // ---------- Render ----------

  if (loading) {
    return (
      <DashboardPanel title="Sprint Plan Generation" icon={Zap}>
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-5 w-5 animate-spin text-[var(--text-secondary)]" />
        </div>
      </DashboardPanel>
    );
  }

  // No plan exists yet — show optimize button
  if (!plan) {
    return (
      <DashboardPanel
        title="Sprint Plan Generation"
        icon={Zap}
        actions={
          selectedProject ? (
            <Badge variant="brand">{selectedProject.name}</Badge>
          ) : null
        }
      >
        <div className="space-y-4">
          <p className="text-sm text-[var(--text-secondary)]">
            {selectedProject
              ? `No sprint plan generated yet for "${selectedProject.name}". Use AI to optimize assignments based on team velocity, skills, and capacity.`
              : "Select a project to generate a sprint plan."}
          </p>

          <Button
            variant="primary"
            size="md"
            className="w-full"
            onClick={handleOptimize}
            disabled={!selectedProject || generating}
          >
            {generating ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Optimizing...
              </>
            ) : (
              <>
                <Zap className="h-4 w-4" />
                Optimize Sprint Plan
              </>
            )}
          </Button>
        </div>
      </DashboardPanel>
    );
  }

  // Plan exists — show details
  // Normalize: API should return 0-1 but guard against old seed data (e.g. 82 instead of 0.82)
  const rawConfidence = plan.confidenceScore ?? 0;
  const normalizedConfidence = rawConfidence > 1 ? rawConfidence / 100 : rawConfidence;
  const confidencePct = Math.round(normalizedConfidence * 100);

  const approvedDate = plan.approvedAt
    ? new Date(plan.approvedAt).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      })
    : "N/A";

  return (
    <DashboardPanel
      title="Sprint Plan Generation"
      icon={Zap}
      actions={
        <div className="flex items-center gap-2">
          {selectedProject && (
            <Badge variant="brand">{selectedProject.name}</Badge>
          )}
          <Badge variant={statusBadgeVariant[plan.status]}>
            {plan.status.replace(/_/g, " ")}
          </Badge>
        </div>
      }
    >
      <div className="space-y-5">
        {/* Confidence score */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-[var(--text-secondary)]">
              Confidence Score
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
            size="md"
          />
        </div>

        {/* Success Estimate */}
        {plan.successProbability !== null && plan.successProbability !== undefined && (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-[var(--text-secondary)]">
                Sprint Success Estimate
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

        {/* Risk summary */}
        {plan.riskSummary && (
          <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
            {plan.riskSummary}
          </p>
        )}

        {/* Stats row */}
        <div className="grid grid-cols-3 gap-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] p-4">
          <div className="text-center">
            <p className="text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-1">
              Total SP
            </p>
            <p className="text-lg font-bold text-[var(--text-primary)] tabular-nums">
              {plan.totalStoryPoints ?? "—"}
            </p>
          </div>
          <div className="text-center border-x border-[var(--border-subtle)]">
            <p className="text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-1">
              AI Model
            </p>
            <p className="text-xs font-semibold text-[var(--text-primary)] truncate px-1">
              {plan.aiModelUsed ?? "—"}
            </p>
          </div>
          <div className="text-center">
            <p className="text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-1">
              Approved
            </p>
            <p className="text-sm font-semibold text-[var(--text-primary)]">
              {approvedDate}
            </p>
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-3">
          <Button
            variant="secondary"
            size="sm"
            className="flex-1"
            onClick={handleRegenerate}
            disabled={generating}
          >
            {generating ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
            {generating ? "Generating..." : "Regenerate Plan"}
          </Button>
          <Button variant="primary" size="sm" className="flex-1" onClick={onViewPlan}>
            <ExternalLink className="h-3.5 w-3.5" />
            View Full Plan
          </Button>
        </div>
      </div>
    </DashboardPanel>
  );
}
