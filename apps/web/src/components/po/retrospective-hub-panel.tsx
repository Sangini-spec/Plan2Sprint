"use client";

import { useState, useEffect, useCallback } from "react";
import {
  RotateCcw,
  CheckCircle2,
  XCircle,
  ArrowRight,
  ExternalLink,
  Calendar,
  User,
  Loader2,
  AlertTriangle,
  TrendingDown,
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

interface FailureEvidence {
  evidence: string[];
  confidence: number;
  completionRate: number;
  totalSP: number;
  doneSP: number;
  overloadedDevs?: { name: string; utilization: number }[];
}

interface FeedForwardSignals {
  signals: string[];
  details?: { type: string; reason: string }[];
}

interface RetrospectiveData {
  id: string;
  iterationName: string;
  finalizedAt: string | null;
  whatWentWell: string[];
  whatDidntGoWell: string[];
  rootCauseAnalysis: RCA[];
  actionItems: ActionItem[];
  // Failure analysis
  failureClassification: string | null;
  failureEvidence: FailureEvidence | null;
  patternDetected: boolean | null;
  consecutiveFailureCount: number | null;
  feedForwardSignals: FeedForwardSignals | null;
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

const statusConfig: Record<
  string,
  { label: string; variant: "brand" | "rag-green" | "rag-amber" | "rag-red" }
> = {
  open: { label: "Open", variant: "brand" },
  in_progress: { label: "In Progress", variant: "rag-amber" },
  done: { label: "Done", variant: "rag-green" },
  closed: { label: "Closed", variant: "rag-green" },
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function RetrospectiveHubPanel() {
  const { selectedProject } = useSelectedProject();
  const [retro, setRetro] = useState<RetrospectiveData | null>(null);
  const [loading, setLoading] = useState(true);
  const refreshKey = useAutoRefresh(["sync_complete"]);

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

  useEffect(() => { fetchRetro(); }, [fetchRetro, refreshKey]);

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
        {retro.whatWentWell.length > 0 && (
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-rag-green)] mb-3 flex items-center gap-1.5">
              <CheckCircle2 className="h-3.5 w-3.5" />
              What Went Well
            </h3>
            <ul className="space-y-2">
              {retro.whatWentWell.map((item, idx) => (
                <li
                  key={idx}
                  className="flex items-start gap-2.5 rounded-lg border border-[var(--color-rag-green)]/20 bg-[var(--color-rag-green)]/5 px-3 py-2.5"
                >
                  <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5 text-[var(--color-rag-green)]" />
                  <span className="text-sm text-[var(--text-primary)] leading-snug">{item}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {retro.whatDidntGoWell.length > 0 && (
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-rag-red)] mb-3 flex items-center gap-1.5">
              <XCircle className="h-3.5 w-3.5" />
              What Didn&apos;t Go Well
            </h3>
            <ul className="space-y-2">
              {retro.whatDidntGoWell.map((item, idx) => (
                <li
                  key={idx}
                  className="flex items-start gap-2.5 rounded-lg border border-[var(--color-rag-red)]/20 bg-[var(--color-rag-red)]/5 px-3 py-2.5"
                >
                  <XCircle className="h-4 w-4 shrink-0 mt-0.5 text-[var(--color-rag-red)]" />
                  <span className="text-sm text-[var(--text-primary)] leading-snug">{item}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {retro.rootCauseAnalysis.length > 0 && (
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] mb-3">
              Root Cause Analysis
            </h3>
            <div className="space-y-2">
              {retro.rootCauseAnalysis.map((rca, idx) => (
                <div
                  key={idx}
                  className="flex items-center gap-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/40 px-3 py-2.5"
                >
                  <span className="text-sm font-medium text-[var(--text-primary)] flex-1 min-w-0">{rca.issue}</span>
                  <ArrowRight className="h-4 w-4 shrink-0 text-[var(--text-secondary)]" />
                  <span className="text-sm text-[var(--text-secondary)] flex-1 min-w-0">{rca.cause}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {retro.actionItems.length > 0 && (
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] mb-3">
              Action Items
            </h3>
            <div className="space-y-2">
              {retro.actionItems.map((action) => {
                const cfg = statusConfig[action.status] ?? {
                  label: action.status,
                  variant: "brand" as const,
                };
                return (
                  <div
                    key={action.id}
                    className="flex items-center gap-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/40 px-3 py-2.5"
                  >
                    <span className="text-sm text-[var(--text-primary)] flex-1 min-w-0 truncate">{action.title}</span>
                    <Badge variant={cfg.variant} className="text-[10px] shrink-0">{cfg.label}</Badge>
                    {action.assigneeName && (
                      <span className="flex items-center gap-1 text-xs text-[var(--text-secondary)] shrink-0">
                        <User className="h-3 w-3" />
                        {action.assigneeName.split(" ")[0]}
                      </span>
                    )}
                    {action.dueDate && (
                      <span className="flex items-center gap-1 text-xs text-[var(--text-secondary)] shrink-0 tabular-nums">
                        <Calendar className="h-3 w-3" />
                        {formatDate(action.dueDate)}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Sprint Failure Analysis — only shown when failureClassification exists */}
        {retro.failureClassification && (
          <div className="pt-4 mt-2 border-t border-[var(--border-subtle)]">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-rag-amber)] mb-3 flex items-center gap-1.5">
              <TrendingDown className="h-3.5 w-3.5" />
              Sprint Failure Analysis
            </h3>

            {/* Primary cause */}
            <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/40 p-4 space-y-3">
              <div className="flex items-center gap-2">
                <span className="text-sm text-[var(--text-secondary)]">Primary Cause:</span>
                <Badge variant="rag-amber" className="font-mono text-[10px]">
                  {retro.failureClassification}
                </Badge>
                {retro.failureEvidence?.confidence && (
                  <span className="text-xs text-[var(--text-tertiary)]">
                    ({retro.failureEvidence.confidence}% confidence)
                  </span>
                )}
              </div>

              {/* Evidence */}
              {retro.failureEvidence?.evidence && retro.failureEvidence.evidence.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-[var(--text-secondary)] mb-2">Evidence:</p>
                  <ul className="space-y-1.5">
                    {retro.failureEvidence.evidence.map((item, idx) => (
                      <li
                        key={idx}
                        className="flex items-start gap-2 text-xs text-[var(--text-primary)]"
                      >
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
                        sprint with {retro.failureClassification} classification.
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
                      <li
                        key={idx}
                        className="flex items-start gap-2 text-xs text-[var(--color-rag-green)]"
                      >
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

        <div className="pt-2 border-t border-[var(--border-subtle)]">
          <Button variant="ghost" size="sm" className="gap-1.5">
            View Full Retrospective
            <ExternalLink className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </DashboardPanel>
  );
}
