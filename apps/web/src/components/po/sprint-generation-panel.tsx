"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Zap, RefreshCw, ExternalLink, Loader2, AlertCircle } from "lucide-react";
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
  FAILED: "rag-red",
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

// Hotfix 32 — Step E: in-flight stub returned alongside the READY plan
// so the badge stays correct while the data continues to display.
interface InflightStub {
  id: string;
  status: "GENERATING" | "FAILED";
  riskSummary: string | null;
  createdAt: string | null;
}

interface SprintGenerationPanelProps {
  onViewPlan?: () => void;
}

export function SprintGenerationPanel({ onViewPlan }: SprintGenerationPanelProps) {
  const router = useRouter();
  const { selectedProject } = useSelectedProject();
  const [plan, setPlan] = useState<PlanData | null>(null);
  const [inflight, setInflight] = useState<InflightStub | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const refreshKey = useAutoRefresh(["sprint_plan_generated", "sprint_plan_updated", "sync_complete"]);

  // ---------- Fetch sprint data from API ----------

  const projectId = selectedProject?.internalId;

  const fetchSprintData = useCallback(async () => {
    try {
      const params = projectId ? `?projectId=${projectId}` : "";
      // Invalidate cache to always get fresh sprint data
      invalidateCache(`/api/sprints${params}`);
      const res = await cachedFetch(`/api/sprints${params}`);
      if (res.ok) {
        const data = res.data as { plan?: PlanData; inflight?: InflightStub | null };
        // Hotfix 32 — Step E: read inflight stub if present (GENERATING / FAILED).
        setInflight(data.inflight ?? null);
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

  // Hotfix 24 — backend now accepts the request and runs generation in
  // the background, returning 202 immediately. We poll the existing
  // ``/api/sprints/plan`` endpoint until the latest plan flips out of
  // GENERATING. This avoids the 30-60s proxy connection drop that used
  // to surface as "Sprint generation failed: Internal Server Error"
  // even though the plan was successfully landing in DB.
  const POLL_INTERVAL_MS = 3000;
  const POLL_TIMEOUT_MS = 5 * 60 * 1000; // 5 min hard cap

  // Hotfix 27 — poll a SPECIFIC plan id returned by the POST handler.
  // Previously we waited for "any new plan id different from the one
  // we knew about", which falsely matched stale FAILED rows from earlier
  // attempts and killed the spinner before the new generation began.
  const pollUntilDone = async (
    projectId: string,
    targetPlanId: string,
    onSuccess: () => void,
    onFailure: (msg: string) => void,
  ) => {
    const startedAt = Date.now();
    while (Date.now() - startedAt < POLL_TIMEOUT_MS) {
      await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
      try {
        invalidateCache(`/api/sprints?projectId=${projectId}`);
        const r = await fetch(`/api/sprints?projectId=${projectId}`);
        if (!r.ok) continue;
        const wrap = (await r.json().catch(() => null)) as
          | { plan?: PlanData }
          | null;
        const latest = wrap?.plan;
        if (!latest || !latest.id) continue;
        // Only react when the response shows OUR plan id (the stub the
        // POST just created). Anything else is leftover state.
        if (latest.id !== targetPlanId) continue;
        if (latest.status && latest.status !== "GENERATING") {
          await fetchSprintData();
          if (latest.status === "FAILED") {
            onFailure(
              latest.riskSummary ||
                "Sprint generation failed. Try again or check API logs.",
            );
          } else {
            onSuccess();
          }
          return;
        }
      } catch {
        // network blip — keep polling until timeout
      }
    }
    onFailure(
      "Sprint generation is still running after 5 minutes. " +
        "Refresh the page to see the latest status.",
    );
  };

  const handleOptimize = async () => {
    if (!selectedProject) return;

    setGenerating(true);
    setError(null);
    try {
      const res = await fetch("/api/sprints", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          projectId: selectedProject.internalId,
        }),
      });

      // Backend returns 202 Accepted (Hotfix 24) — kick off polling.
      if (res.ok) {
        const acceptedBody = (await res.json().catch(() => null)) as
          | { planId?: string }
          | null;
        const targetPlanId = acceptedBody?.planId;
        if (!targetPlanId) {
          // Defensive — shouldn't happen post-Hotfix-27, but if backend
          // didn't return a planId, fall back to refresh-only behaviour.
          invalidateCache("/api/sprints");
          await fetchSprintData();
          setGenerating(false);
          return;
        }
        invalidateCache("/api/sprints");
        await pollUntilDone(
          selectedProject.internalId,
          targetPlanId,
          () => setGenerating(false),
          (msg) => {
            setError(msg);
            setGenerating(false);
          },
        );
        return;
      }
      const data = await res.json().catch(() => ({}));
      setError(data.detail || data.error || `Generation failed (${res.status})`);
      setGenerating(false);
    } catch {
      setError("Cannot reach backend. Ensure the API server is running on port 8000.");
      setGenerating(false);
    }
  };

  const handleRegenerate = async () => {
    if (!selectedProject || !plan) return;

    setGenerating(true);
    setError(null);
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
        const acceptedBody = (await res.json().catch(() => null)) as
          | { planId?: string }
          | null;
        const targetPlanId = acceptedBody?.planId;
        if (!targetPlanId) {
          invalidateCache("/api/sprints");
          await fetchSprintData();
          setGenerating(false);
          return;
        }
        invalidateCache("/api/sprints");
        await pollUntilDone(
          selectedProject.internalId,
          targetPlanId,
          () => setGenerating(false),
          (msg) => {
            setError(msg);
            setGenerating(false);
          },
        );
        return;
      }
      const data = await res.json().catch(() => ({}));
      setError(data.detail || data.error || `Regeneration failed (${res.status})`);
      setGenerating(false);
    } catch {
      setError("Cannot reach backend. Ensure the API server is running on port 8000.");
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

  // No plan exists yet — show optimize button. Hotfix 32 — Step E:
  // surface inflight state so the user sees "Generating..." instead of
  // "Optimize" while the first plan is being created.
  if (!plan) {
    const isGenerating = inflight?.status === "GENERATING" || generating;
    const failedSummary = inflight?.status === "FAILED" ? inflight.riskSummary : null;
    return (
      <DashboardPanel
        title="Sprint Plan Generation"
        icon={Zap}
        actions={
          <div className="flex items-center gap-2">
            {selectedProject && <Badge variant="brand">{selectedProject.name}</Badge>}
            {inflight?.status === "GENERATING" && (
              <Badge variant="brand">GENERATING</Badge>
            )}
            {inflight?.status === "FAILED" && (
              <Badge variant="rag-red">GENERATION FAILED</Badge>
            )}
          </div>
        }
      >
        <div className="space-y-4">
          <p className="text-sm text-[var(--text-secondary)]">
            {!selectedProject
              ? "Select a project to generate a sprint plan."
              : isGenerating
                ? `The AI is analyzing the backlog for "${selectedProject.name}". This typically takes 30-90 seconds.`
                : failedSummary
                  ? failedSummary
                  : `No sprint plan generated yet for "${selectedProject.name}". Use AI to optimize assignments based on team velocity, skills, and capacity.`}
          </p>

          <Button
            variant="primary"
            size="md"
            className="w-full"
            onClick={handleOptimize}
            disabled={!selectedProject || isGenerating}
          >
            {isGenerating ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Generating...
              </>
            ) : failedSummary ? (
              <>
                <RefreshCw className="h-4 w-4" />
                Try Again
              </>
            ) : (
              <>
                <Zap className="h-4 w-4" />
                Optimize Sprint Plan
              </>
            )}
          </Button>

          {error && (
            <div className="flex items-start gap-2 rounded-lg bg-[var(--color-rag-red)]/10 border border-[var(--color-rag-red)]/20 px-3 py-2">
              <AlertCircle size={14} className="text-[var(--color-rag-red)] shrink-0 mt-0.5" />
              <span className="text-xs text-[var(--color-rag-red)]">{error}</span>
            </div>
          )}
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
          {/* Hotfix 32 (revised) — subtle inline inflight indicator,
              does NOT override the plan status badge */}
          {inflight?.status === "GENERATING" && (
            <span className="flex items-center gap-1 text-[10px] text-[var(--color-brand-secondary)]">
              <Loader2 className="h-2.5 w-2.5 animate-spin" />
              Generating
            </span>
          )}
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
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] p-3">
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
          <Button variant="primary" size="sm" className="flex-1" onClick={() => onViewPlan ? onViewPlan() : router.push("/po/planning")}>
            <ExternalLink className="h-3.5 w-3.5" />
            View Full Plan
          </Button>
        </div>

        {error && (
          <div className="flex items-start gap-2 rounded-lg bg-[var(--color-rag-red)]/10 border border-[var(--color-rag-red)]/20 px-3 py-2">
            <AlertCircle size={14} className="text-[var(--color-rag-red)] shrink-0 mt-0.5" />
            <span className="text-xs text-[var(--color-rag-red)]">{error}</span>
          </div>
        )}
      </div>
    </DashboardPanel>
  );
}
