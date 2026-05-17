"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  RotateCcw,
  CheckCircle2,
  Calendar,
  Loader2,
  AlertTriangle,
  TrendingDown,
  ExternalLink,
  Layers,
  Milestone,
} from "lucide-react";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Badge, Button } from "@/components/ui";
import { useSelectedProject } from "@/lib/project/context";
import { useAutoRefresh } from "@/lib/ws/context";
import { cachedFetch } from "@/lib/fetch-cache";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ActionItem {
  id: string;
  title: string;
  status: string;
  assigneeId?: string;
  assigneeName?: string;
  dueDate?: string;
}

interface RCA {
  issue: string;
  cause: string;
}

interface OverloadedDev {
  name: string;
  utilization: number;
  assignedSP?: number;
  capacitySP?: number;
}

interface FailureEvidence {
  evidence: string[];
  confidence: number;
  completionRate: number;
  totalSP: number;
  doneSP: number;
  overloadedDevs?: OverloadedDev[];
}

interface FeedForwardSignals {
  signals: string[];
  details?: { type: string; reason: string; target?: string; adjustment?: number }[];
}

interface FeatureProgress {
  id: string;
  title: string;
  completePct: number;
  totalStories: number;
  breakdown: { done: number; inProgress: number; readyForTest: number; remaining: number };
  plannedStart: string | null;
  plannedEnd: string | null;
  sourceStatus: string;
}

interface RetrospectiveData {
  id: string;
  iterationName: string;
  sprintNumber: number | null;
  sourceTool: string;
  retroSource: string;
  completionTrigger: string;
  iterationStartDate: string | null;
  iterationEndDate: string | null;
  finalizedAt: string | null;
  whatWentWell: string[];
  whatDidntGoWell: string[];
  rootCauseAnalysis: RCA[];
  actionItems: ActionItem[];
  failureClassification: string | null;
  failureEvidence: FailureEvidence | null;
  patternDetected: boolean | null;
  consecutiveFailureCount: number | null;
  feedForwardSignals: FeedForwardSignals | null;
  conclusion: string | null;
  isArchived: boolean;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

const classificationLabels: Record<string, string> = {
  OVERCOMMITMENT: "Overcommitment",
  EXECUTION: "Execution Failure",
  DEPENDENCY: "External Dependency",
  CAPACITY: "Capacity Shortage",
  SCOPE_CREEP: "Scope Creep",
};

function getSourceLabel(sourceTool: string, trigger: string): { label: string; detail: string } {
  const tool =
    sourceTool.toUpperCase() === "ADO"
      ? "Azure DevOps"
      : sourceTool.toUpperCase() === "JIRA"
        ? "Jira"
        : sourceTool || "Platform";

  if (trigger === "end_date_passed") {
    return { label: tool, detail: `${tool} sprint deadline reached` };
  }
  if (trigger === "all_items_done") {
    return { label: tool, detail: "All items completed before deadline" };
  }
  return { label: tool, detail: "Sprint manually completed" };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function RetrospectiveHubPanel() {
  const { selectedProject } = useSelectedProject();
  const [retro, setRetro] = useState<RetrospectiveData | null>(null);
  const [features, setFeatures] = useState<FeatureProgress[]>([]);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const refreshKey = useAutoRefresh(["sync_complete", "sprint_completed"]);

  const projectId = selectedProject?.internalId;

  const fetchRetro = useCallback(async () => {
    setLoading(true);
    try {
      const q = projectId ? `?projectId=${projectId}` : "";
      const res = await cachedFetch(`/api/retrospectives${q}`);
      if (res.ok) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const data = res.data as any;
        const latest = data.retrospective ?? data.latest ?? data;
        if (latest && (latest.whatWentWell?.length > 0 || latest.actionItems?.length > 0 || latest.failureClassification)) {
          setRetro({
            id: latest.id ?? "retro-1",
            iterationName: latest.iterationName ?? latest.sprintName ?? "",
            sprintNumber: latest.sprintNumber ?? null,
            sourceTool: latest.sourceTool ?? "",
            retroSource: latest.retroSource ?? "",
            completionTrigger: latest.completionTrigger ?? "end_date_passed",
            iterationStartDate: latest.iterationStartDate ?? null,
            iterationEndDate: latest.iterationEndDate ?? null,
            finalizedAt: latest.finalizedAt ?? null,
            whatWentWell: latest.whatWentWell?.items ?? latest.whatWentWell ?? [],
            whatDidntGoWell: latest.whatDidntGoWell?.items ?? latest.whatDidntGoWell ?? [],
            rootCauseAnalysis: latest.rootCauseAnalysis?.items ?? latest.rootCauseAnalysis ?? [],
            actionItems: latest.actionItems ?? [],
            failureClassification: latest.failureClassification ?? null,
            failureEvidence: latest.failureEvidence ?? null,
            patternDetected: latest.patternDetected ?? null,
            consecutiveFailureCount: latest.consecutiveFailureCount ?? null,
            feedForwardSignals: latest.feedForwardSignals ?? null,
            conclusion: latest.conclusion ?? null,
            isArchived: latest.isArchived ?? false,
          });
        } else {
          setRetro(null);
        }
      } else {
        setRetro(null);
      }
    } catch {
      setRetro(null);
    }
    setLoading(false);
  }, [projectId]);

  const fetchFeatures = useCallback(async () => {
    try {
      const q = projectId ? `?projectId=${projectId}` : "";
      const res = await cachedFetch(`/api/dashboard/feature-progress${q}`);
      if (res.ok) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const data = res.data as any;
        setFeatures(data.features ?? []);
      }
    } catch {
      // non-critical
    }
  }, [projectId]);

  useEffect(() => { fetchRetro(); fetchFeatures(); }, [fetchRetro, fetchFeatures, refreshKey]);

  if (loading) {
    return (
      <DashboardPanel title="Retrospective" icon={RotateCcw}>
        <div className="flex items-center justify-center py-8">
          <Loader2 size={20} className="animate-spin text-[var(--color-brand-secondary)]" />
        </div>
      </DashboardPanel>
    );
  }

  if (!retro) {
    return (
      <DashboardPanel title="Retrospective" icon={RotateCcw}>
        <div className="flex flex-col items-center justify-center py-8 gap-2">
          <RotateCcw size={24} className="text-[var(--text-tertiary)]" />
          <p className="text-sm text-[var(--text-secondary)]">No retrospective data available</p>
          <p className="text-xs text-[var(--text-tertiary)]">
            Retrospective data will appear after completing a sprint cycle.
          </p>
        </div>
      </DashboardPanel>
    );
  }

  // Build sprint label
  const sprintLabel = retro.sprintNumber
    ? `Sprint ${retro.sprintNumber}`
    : retro.iterationName || "Sprint";

  // Source info
  const source = getSourceLabel(retro.sourceTool, retro.completionTrigger);

  // Compute derived metrics
  const evidence = retro.failureEvidence;
  const completionRate = evidence?.completionRate ?? 0;

  // Filter features overlapping with sprint date range
  const sprintStart = retro.iterationStartDate ? new Date(retro.iterationStartDate).getTime() : null;
  const sprintEnd = retro.iterationEndDate ? new Date(retro.iterationEndDate).getTime() : null;

  const sprintFeatures = features.filter((f) => {
    if (!sprintStart || !sprintEnd) return true;
    const fStart = f.plannedStart ? new Date(f.plannedStart).getTime() : 0;
    const fEnd = f.plannedEnd ? new Date(f.plannedEnd).getTime() : Infinity;
    return fStart <= sprintEnd && fEnd >= sprintStart;
  });

  const completedFeatures = sprintFeatures.filter((f) => f.completePct === 100);
  const atRiskFeatures = sprintFeatures.filter(
    (f) => f.completePct < 100 && f.plannedEnd && new Date(f.plannedEnd).getTime() <= (sprintEnd ?? Date.now())
  );

  // ── Project-Complete Mode ── When latest retro is archived, show conclusion only
  if (retro.isArchived) {
    return (
      <DashboardPanel title="Retrospective" icon={RotateCcw} collapsible>
        <div className="space-y-4">
          <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/60 p-4">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-base font-semibold text-[var(--text-primary)]">
                {sprintLabel}
              </h2>
              <Badge variant="brand" className="text-[10px]">Project Complete</Badge>
            </div>
            {retro.iterationStartDate && retro.iterationEndDate && (
              <span className="flex items-center gap-1 text-xs text-[var(--text-secondary)] mb-3">
                <Calendar className="h-3 w-3" />
                {formatDate(retro.iterationStartDate)} - {formatDate(retro.iterationEndDate)}
              </span>
            )}
            <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
              {retro.conclusion || "Sprint completed."}
            </p>
            {retro.failureClassification && (
              <div className="mt-2">
                <Badge variant="rag-amber" className="text-[9px]">
                  {classificationLabels[retro.failureClassification] ?? retro.failureClassification}
                </Badge>
              </div>
            )}
          </div>
          <p className="text-xs text-[var(--text-tertiary)] text-center">
            All sprints have been completed. Detailed analysis is no longer available.
          </p>
        </div>
      </DashboardPanel>
    );
  }

  return (
    <DashboardPanel
      title="Retrospective"
      icon={RotateCcw}
      collapsible
      actions={
        retro.finalizedAt ? (
          <span className="text-xs text-[var(--text-secondary)]">
            Finalized {formatDate(retro.finalizedAt)}
          </span>
        ) : (
          <Badge variant="rag-amber">Draft</Badge>
        )
      }
    >
      <div className="space-y-6">
        {/* ── Sprint Ended Heading ── */}
        <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/60 p-4">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-base font-semibold text-[var(--text-primary)]">
              {sprintLabel} has ended
            </h2>
            <Badge variant="brand" className="text-[10px] font-mono">
              {source.label}
            </Badge>
          </div>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--text-secondary)]">
            {retro.iterationName && (
              <span>
                <span className="font-medium text-[var(--text-primary)]">Iteration:</span>{" "}
                {retro.iterationName}
              </span>
            )}
            {retro.iterationStartDate && retro.iterationEndDate && (
              <span className="flex items-center gap-1">
                <Calendar className="h-3 w-3" />
                {formatDate(retro.iterationStartDate)} - {formatDate(retro.iterationEndDate)}
              </span>
            )}
          </div>

          {/* Trigger reason */}
          <div className="mt-2 flex items-center gap-2">
            <span className="text-[11px] px-2 py-0.5 rounded-md bg-[var(--bg-surface)]/80 border border-[var(--border-subtle)] text-[var(--text-secondary)]">
              {source.detail}
            </span>
            {evidence && (
              <span className="text-[11px] font-medium">
                Completion:{" "}
                <span
                  className={
                    completionRate >= 85
                      ? "text-[var(--color-rag-green)]"
                      : completionRate >= 50
                        ? "text-[var(--color-rag-amber)]"
                        : "text-[var(--color-rag-red)]"
                  }
                >
                  {completionRate.toFixed(0)}%
                </span>
                <span className="text-[var(--text-tertiary)] ml-1">
                  ({evidence.doneSP?.toFixed(0)}/{evidence.totalSP?.toFixed(0)} SP)
                </span>
              </span>
            )}
          </div>
        </div>

        {/* ── Quick Summary Stats ── */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div className="rounded-lg border border-[var(--color-rag-green)]/20 bg-[var(--color-rag-green)]/5 px-3 py-2.5 text-center">
            <p className="text-lg font-bold text-[var(--color-rag-green)]">{retro.whatWentWell.length}</p>
            <p className="text-[10px] text-[var(--text-secondary)] uppercase tracking-wider">Went Well</p>
          </div>
          <div className="rounded-lg border border-[var(--color-rag-red)]/20 bg-[var(--color-rag-red)]/5 px-3 py-2.5 text-center">
            <p className="text-lg font-bold text-[var(--color-rag-red)]">{retro.whatDidntGoWell.length}</p>
            <p className="text-[10px] text-[var(--text-secondary)] uppercase tracking-wider">Issues</p>
          </div>
          <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/40 px-3 py-2.5 text-center">
            <p className="text-lg font-bold text-[var(--text-primary)]">{retro.actionItems.length}</p>
            <p className="text-[10px] text-[var(--text-secondary)] uppercase tracking-wider">Actions</p>
          </div>
        </div>

        {/* ── Sprint Failure Analysis (summary) ── */}
        {retro.failureClassification && (
          <div className="pt-4 mt-2 border-t border-[var(--border-subtle)]">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-rag-amber)] mb-3 flex items-center gap-1.5">
              <TrendingDown className="h-3.5 w-3.5" />
              Sprint Failure Analysis
            </h3>

            <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/40 p-4 space-y-3">
              <div className="flex items-center gap-2">
                <span className="text-sm text-[var(--text-secondary)]">Primary Cause:</span>
                <Badge variant="rag-amber" className="font-mono text-[10px]">
                  {classificationLabels[retro.failureClassification] ?? retro.failureClassification}
                </Badge>
                {evidence?.confidence && (
                  <span className="text-xs text-[var(--text-tertiary)]">
                    ({evidence.confidence}% confidence)
                  </span>
                )}
              </div>

              {evidence?.evidence && evidence.evidence.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-[var(--text-secondary)] mb-2">Evidence:</p>
                  <ul className="space-y-1.5">
                    {evidence.evidence.map((item, idx) => (
                      <li key={idx} className="flex items-start gap-2 text-xs text-[var(--text-primary)]">
                        <span className="h-1 w-1 mt-1.5 rounded-full bg-[var(--text-secondary)] shrink-0" />
                        {item}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Pattern warning */}
              {retro.patternDetected && (
                <div className="rounded-lg border border-[var(--color-rag-amber)]/30 bg-[var(--color-rag-amber)]/5 p-3">
                  <div className="flex items-start gap-2">
                    <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5 text-[var(--color-rag-amber)]" />
                    <div className="space-y-1">
                      <p className="text-xs font-medium text-[var(--text-primary)]">
                        Pattern Detected: This is the {retro.consecutiveFailureCount ?? 2}
                        {retro.consecutiveFailureCount === 2 ? "nd" : retro.consecutiveFailureCount === 3 ? "rd" : "th"} consecutive
                        sprint with {classificationLabels[retro.failureClassification] ?? retro.failureClassification} classification.
                      </p>
                      <p className="text-xs text-[var(--text-secondary)]">
                        This pattern has been sent to the next sprint generation as a planning constraint.
                      </p>
                    </div>
                  </div>
                </div>
              )}

              {/* Feed-forward signals */}
              {retro.feedForwardSignals?.signals && retro.feedForwardSignals.signals.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-[var(--text-secondary)] mb-2">
                    Feed-forward to next sprint:
                  </p>
                  <ul className="space-y-1.5">
                    {retro.feedForwardSignals.signals.map((signal, idx) => (
                      <li key={idx} className="flex items-start gap-2 text-xs text-[var(--color-rag-green)]">
                        <CheckCircle2 className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                        {signal}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── View Full Retrospective (navigates to detail page) ── */}
        <div className="pt-2 border-t border-[var(--border-subtle)]">
          <Button
            variant="ghost"
            size="sm"
            className="gap-1.5 w-full justify-center"
            onClick={() => router.push(`/po/retro/${retro.id}`)}
          >
            View Full Retrospective
            <ExternalLink className="h-3.5 w-3.5" />
          </Button>
        </div>

        {/* ── Epic Progress During Sprint ── */}
        {sprintFeatures.length > 0 && (
          <div className="pt-4 mt-2 border-t border-[var(--border-subtle)]">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] mb-3 flex items-center gap-1.5">
              <Layers className="h-3.5 w-3.5" />
              Epic Progress During {sprintLabel}
            </h3>

            {/* Milestone badges */}
            {(completedFeatures.length > 0 || atRiskFeatures.length > 0) && (
              <div className="flex flex-wrap gap-2 mb-3">
                {completedFeatures.map((f) => (
                  <div
                    key={f.id}
                    className="flex items-center gap-1.5 rounded-lg border border-[var(--color-rag-green)]/20 bg-[var(--color-rag-green)]/5 px-2.5 py-1"
                  >
                    <Milestone className="h-3 w-3 text-[var(--color-rag-green)]" />
                    <span className="text-[11px] font-medium text-[var(--color-rag-green)]">
                      {f.title}
                    </span>
                    <Badge variant="rag-green" className="text-[9px]">Done</Badge>
                  </div>
                ))}
                {atRiskFeatures.map((f) => (
                  <div
                    key={f.id}
                    className="flex items-center gap-1.5 rounded-lg border border-[var(--color-rag-red)]/20 bg-[var(--color-rag-red)]/5 px-2.5 py-1"
                  >
                    <AlertTriangle className="h-3 w-3 text-[var(--color-rag-red)]" />
                    <span className="text-[11px] font-medium text-[var(--color-rag-red)]">
                      {f.title}
                    </span>
                    <Badge variant="rag-red" className="text-[9px]">Overdue</Badge>
                  </div>
                ))}
              </div>
            )}

            {/* Feature progress bars */}
            <div className="space-y-2.5">
              {sprintFeatures.map((feature) => {
                const pctColor =
                  feature.completePct === 100
                    ? "var(--color-rag-green)"
                    : feature.completePct >= 50
                      ? "var(--color-rag-amber)"
                      : "var(--color-rag-red)";
                return (
                  <div
                    key={feature.id}
                    className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/40 p-2.5"
                  >
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-xs font-medium text-[var(--text-primary)] truncate flex-1 min-w-0 mr-2">
                        {feature.title}
                      </span>
                      <div className="flex items-center gap-1.5 shrink-0">
                        <span className="text-[10px] text-[var(--text-secondary)]">
                          {feature.breakdown.done}/{feature.totalStories}
                        </span>
                        <span
                          className="text-[11px] font-bold tabular-nums"
                          style={{ color: pctColor }}
                        >
                          {feature.completePct}%
                        </span>
                      </div>
                    </div>
                    <div className="h-1.5 rounded-full bg-[var(--bg-surface)] overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{
                          width: `${feature.completePct}%`,
                          backgroundColor: pctColor,
                        }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </DashboardPanel>
  );
}
