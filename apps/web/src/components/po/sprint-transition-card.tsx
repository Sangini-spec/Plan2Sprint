"use client";

import { useState, useEffect, useCallback } from "react";
import {
  CheckCircle2,
  ArrowRight,
  TrendingUp,
  AlertTriangle,
  BarChart3,
  Loader2,
  X,
} from "lucide-react";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Badge, Button } from "@/components/ui";
import { useAutoRefresh } from "@/lib/ws/context";
import { useSelectedProject } from "@/lib/project/context";
import { cachedFetch } from "@/lib/fetch-cache";
import Link from "next/link";

interface SprintCompletionData {
  iterationId: string;
  iterationName: string;
  completionRate: number;
  doneSP: number;
  totalSP: number;
  doneItems: number;
  totalItems: number;
  spilloverCount: number;
  spilloverSP: number;
  nextIteration: string | null;
  retroGenerated: boolean;
  retroType: string | null;
}

/**
 * Sprint Transition Card — appears on the PO dashboard when the platform
 * has auto-completed a sprint. Shows completion summary, spillover info,
 * and links to retrospective & next sprint planning.
 *
 * Auto-dismisses when there's no recently completed sprint or user dismisses it.
 */
export function SprintTransitionCard() {
  const { selectedProject } = useSelectedProject();
  const [data, setData] = useState<SprintCompletionData | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [loading, setLoading] = useState(true);
  const refreshKey = useAutoRefresh(["sprint_completed", "sync_complete", "github_activity"]);

  const projectId = selectedProject?.internalId;

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const q = projectId ? `?projectId=${projectId}` : "";
      // Check if there's a recently completed sprint with a retrospective
      const [sprintRes, retroRes] = await Promise.all([
        cachedFetch(`/api/dashboard/sprints${q}`),
        cachedFetch(`/api/retrospectives${q}`),
      ]);

      if (sprintRes.ok && retroRes.ok) {
        const sprints = sprintRes.data as {
          sprints?: Array<{
            id: string;
            name: string;
            state: string;
            totalStoryPoints: number;
            completedStoryPoints: number;
            totalItems: number;
            completedItems: number;
            completionPct: number;
          }>;
        };

        const retro = retroRes.data as {
          retrospective?: {
            iterationId: string;
            failureClassification: string | null;
            whatWentWell: { items?: string[] };
            whatDidntGoWell: { items?: string[] };
            failureEvidence?: {
              type?: string;
              completionRate?: number;
            };
          };
        };

        // Find the most recently completed sprint
        const completedSprint = (sprints.sprints ?? []).find(
          (s) => s.state === "completed"
        );

        // Find active sprint (the next one after completion)
        const activeSprint = (sprints.sprints ?? []).find(
          (s) => s.state === "active"
        );

        if (completedSprint && retro.retrospective) {
          const completionRate =
            retro.retrospective.failureEvidence?.completionRate ??
            completedSprint.completionPct;

          const spilloverCount =
            completedSprint.totalItems - completedSprint.completedItems;

          setData({
            iterationId: completedSprint.id,
            iterationName: completedSprint.name,
            completionRate,
            doneSP: completedSprint.completedStoryPoints,
            totalSP: completedSprint.totalStoryPoints,
            doneItems: completedSprint.completedItems,
            totalItems: completedSprint.totalItems,
            spilloverCount: Math.max(0, spilloverCount),
            spilloverSP: Math.max(
              0,
              completedSprint.totalStoryPoints -
                completedSprint.completedStoryPoints
            ),
            nextIteration: activeSprint?.name ?? null,
            retroGenerated: true,
            retroType:
              retro.retrospective.failureEvidence?.type ??
              (retro.retrospective.failureClassification
                ? "failure_analysis"
                : "success"),
          });
        } else {
          setData(null);
        }
      }
    } catch {
      // Silent fail — card just won't show
    }
    setLoading(false);
  }, [projectId]);

  useEffect(() => {
    fetchData();
  }, [fetchData, refreshKey]);

  // Don't render if dismissed, loading, or no data
  if (dismissed || loading || !data) return null;

  const isSuccess = data.retroType === "success";
  const rateColor =
    data.completionRate >= 85
      ? "text-emerald-400"
      : data.completionRate >= 60
        ? "text-amber-400"
        : "text-red-400";

  return (
    <DashboardPanel
      title={isSuccess ? "Sprint Completed — All Items Done!" : "Sprint Completed"}
      icon={CheckCircle2}
      actions={
        <div className="flex items-center gap-2">
          <Badge variant={isSuccess ? "rag-green" : "rag-amber"}>
            {isSuccess ? "Successful" : "Needs Improvement"}
          </Badge>
          <button
            onClick={() => setDismissed(true)}
            className="p-1 rounded-lg hover:bg-[var(--bg-surface-raised)] text-[var(--text-muted)] transition-colors"
            title="Dismiss"
          >
            <X size={16} />
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        {/* Sprint name and completion rate */}
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-[var(--text-primary)]">
              {data.iterationName}
            </h3>
            <p className="text-sm text-[var(--text-secondary)]">
              {isSuccess
                ? "All work items completed — sprint auto-closed by Plan2Sprint"
                : "Sprint deadline reached — auto-closed by Plan2Sprint"}
            </p>
          </div>
          <div className="text-right">
            <div className={`text-3xl font-bold tabular-nums ${rateColor}`}>
              {data.completionRate.toFixed(0)}%
            </div>
            <div className="text-xs text-[var(--text-muted)]">completion</div>
          </div>
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="rounded-lg bg-[var(--bg-surface-raised)]/50 p-3 text-center">
            <div className="text-lg font-bold text-[var(--text-primary)] tabular-nums">
              {data.doneSP}/{data.totalSP}
            </div>
            <div className="text-xs text-[var(--text-muted)]">SP Completed</div>
          </div>
          <div className="rounded-lg bg-[var(--bg-surface-raised)]/50 p-3 text-center">
            <div className="text-lg font-bold text-[var(--text-primary)] tabular-nums">
              {data.doneItems}/{data.totalItems}
            </div>
            <div className="text-xs text-[var(--text-muted)]">Items Done</div>
          </div>
          <div className="rounded-lg bg-[var(--bg-surface-raised)]/50 p-3 text-center">
            <div className="text-lg font-bold text-amber-400 tabular-nums">
              {data.spilloverCount}
            </div>
            <div className="text-xs text-[var(--text-muted)]">Spillovers</div>
          </div>
          <div className="rounded-lg bg-[var(--bg-surface-raised)]/50 p-3 text-center">
            <div className="text-lg font-bold text-[var(--color-brand-secondary)] tabular-nums">
              {data.spilloverSP}
            </div>
            <div className="text-xs text-[var(--text-muted)]">Spill SP</div>
          </div>
        </div>

        {/* Spillover info */}
        {data.spilloverCount > 0 && data.nextIteration && (
          <div className="flex items-center gap-2 rounded-lg border border-amber-500/20 bg-amber-500/5 p-3">
            <AlertTriangle size={16} className="shrink-0 text-amber-400" />
            <span className="text-sm text-[var(--text-secondary)]">
              {data.spilloverCount} item{data.spilloverCount > 1 ? "s" : ""} ({data.spilloverSP} SP)
              auto-moved to <strong>{data.nextIteration}</strong>
            </span>
          </div>
        )}

        {/* Action links */}
        <div className="flex flex-wrap gap-3">
          <Link href="/po/retro">
            <Button variant="primary" size="sm">
              <BarChart3 size={16} />
              View Retrospective
            </Button>
          </Link>
          <Link href="/po/planning">
            <Button variant="secondary" size="sm">
              <TrendingUp size={16} />
              Plan Next Sprint
              <ArrowRight size={14} />
            </Button>
          </Link>
        </div>
      </div>
    </DashboardPanel>
  );
}
