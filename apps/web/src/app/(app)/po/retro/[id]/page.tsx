"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  RotateCcw,
  CheckCircle2,
  XCircle,
  ArrowRight,
  Calendar,
  User,
  Loader2,
  AlertTriangle,
  TrendingDown,
  BarChart3,
  Users,
  Clock,
  Zap,
  Target,
  Brain,
} from "lucide-react";
import { Badge } from "@/components/ui";
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

interface RetrospectiveData {
  id: string;
  iterationName: string;
  sprintNumber: number | null;
  sourceTool: string;
  retroSource: string;
  completionTrigger: string;
  iterationStartDate: string | null;
  iterationEndDate: string | null;
  iterationState: string;
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

const statusConfig: Record<
  string,
  { label: string; variant: "brand" | "rag-green" | "rag-amber" | "rag-red" }
> = {
  open: { label: "Open", variant: "brand" },
  in_progress: { label: "In Progress", variant: "rag-amber" },
  done: { label: "Done", variant: "rag-green" },
  closed: { label: "Closed", variant: "rag-green" },
};

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

function ordinalSuffix(n: number): string {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

// ---------------------------------------------------------------------------
// Metric Tile
// ---------------------------------------------------------------------------

function MetricTile({
  icon: Icon,
  label,
  value,
  color,
  subtext,
}: {
  icon: typeof BarChart3;
  label: string;
  value: string;
  color: string;
  subtext?: string;
}) {
  return (
    <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/60 p-4">
      <div className="flex items-center gap-2 mb-2">
        <div
          className="flex h-8 w-8 items-center justify-center rounded-lg"
          style={{
            backgroundColor: `color-mix(in srgb, ${color} 15%, transparent)`,
          }}
        >
          <Icon className="h-4 w-4" style={{ color }} />
        </div>
        <span className="text-xs font-medium text-[var(--text-secondary)]">{label}</span>
      </div>
      <p className="text-xl font-bold text-[var(--text-primary)]">{value}</p>
      {subtext && (
        <p className="text-xs text-[var(--text-tertiary)] mt-1">{subtext}</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function RetroDetailPage() {
  const params = useParams();
  const router = useRouter();
  const retroId = params.id as string;

  const [retro, setRetro] = useState<RetrospectiveData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchRetro = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await cachedFetch(`/api/retrospectives/${retroId}`);
      if (res.ok) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const data = res.data as any;
        const r = data.retrospective;
        if (r) {
          setRetro({
            id: r.id,
            iterationName: r.iterationName ?? "",
            sprintNumber: r.sprintNumber ?? null,
            sourceTool: r.sourceTool ?? "",
            retroSource: r.retroSource ?? "",
            completionTrigger: r.completionTrigger ?? "end_date_passed",
            iterationStartDate: r.iterationStartDate ?? null,
            iterationEndDate: r.iterationEndDate ?? null,
            iterationState: r.iterationState ?? "",
            finalizedAt: r.finalizedAt ?? null,
            whatWentWell: r.whatWentWell?.items ?? r.whatWentWell ?? [],
            whatDidntGoWell: r.whatDidntGoWell?.items ?? r.whatDidntGoWell ?? [],
            rootCauseAnalysis: r.rootCauseAnalysis?.items ?? r.rootCauseAnalysis ?? [],
            actionItems: r.actionItems ?? [],
            failureClassification: r.failureClassification ?? null,
            failureEvidence: r.failureEvidence ?? null,
            patternDetected: r.patternDetected ?? null,
            consecutiveFailureCount: r.consecutiveFailureCount ?? null,
            feedForwardSignals: r.feedForwardSignals ?? null,
            conclusion: r.conclusion ?? null,
            isArchived: r.isArchived ?? false,
          });
        } else {
          setError("Retrospective not found");
        }
      } else {
        setError("Failed to load retrospective");
      }
    } catch {
      setError("Failed to load retrospective");
    }
    setLoading(false);
  }, [retroId]);

  useEffect(() => {
    fetchRetro();
  }, [fetchRetro]);

  // ── Loading ──
  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Loader2 className="h-6 w-6 animate-spin text-[var(--color-brand-secondary)]" />
      </div>
    );
  }

  // ── Error ──
  if (error || !retro) {
    return (
      <div className="space-y-6">
        <button
          onClick={() => router.back()}
          className="flex items-center gap-1.5 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Retrospective
        </button>
        <div className="flex flex-col items-center justify-center py-16 gap-3">
          <RotateCcw className="h-8 w-8 text-[var(--text-tertiary)]" />
          <p className="text-sm text-[var(--text-secondary)]">{error ?? "Retrospective not found"}</p>
        </div>
      </div>
    );
  }

  // ── Archived guard ── redirect to overview if this retro is archived
  if (retro.isArchived) {
    return (
      <div className="space-y-6">
        <button
          onClick={() => router.push("/po/retro")}
          className="flex items-center gap-1.5 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Retrospective
        </button>
        <div className="flex flex-col items-center justify-center py-16 gap-4">
          <RotateCcw className="h-8 w-8 text-[var(--text-tertiary)]" />
          <div className="text-center space-y-2">
            <p className="text-sm font-medium text-[var(--text-primary)]">Sprint Archived</p>
            <p className="text-sm text-[var(--text-secondary)] max-w-md">
              {retro.conclusion || "This sprint has been archived."}
            </p>
            <p className="text-xs text-[var(--text-tertiary)]">
              Detailed analysis is only available for the most recent sprint.
            </p>
          </div>
        </div>
      </div>
    );
  }

  // ── Derived values ──
  const sprintLabel = retro.sprintNumber
    ? `Sprint ${retro.sprintNumber}`
    : retro.iterationName || "Sprint";
  const source = getSourceLabel(retro.sourceTool, retro.completionTrigger);
  const evidence = retro.failureEvidence;
  const completionRate = evidence?.completionRate ?? 0;
  const spilloverSP = evidence ? evidence.totalSP - evidence.doneSP : 0;
  const isFailed = !!retro.failureClassification;
  const overloadedDevs = evidence?.overloadedDevs ?? [];

  let sprintDays: number | null = null;
  if (retro.iterationStartDate && retro.iterationEndDate) {
    sprintDays = Math.ceil(
      (new Date(retro.iterationEndDate).getTime() - new Date(retro.iterationStartDate).getTime()) /
        (1000 * 60 * 60 * 24)
    );
  }

  return (
    <div className="space-y-6 max-w-5xl">
      {/* ── Back nav ── */}
      <button
        onClick={() => router.back()}
        className="flex items-center gap-1.5 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Retrospective
      </button>

      {/* ── Header ── */}
      <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]/80 backdrop-blur-sm p-6">
        <div className="flex items-start justify-between mb-3">
          <div>
            <h1 className="text-xl font-bold text-[var(--text-primary)]">
              {sprintLabel} has ended
            </h1>
            {retro.iterationName && (
              <p className="text-sm text-[var(--text-secondary)] mt-1">
                {retro.iterationName}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="brand" className="text-[10px] font-mono">
              {source.label}
            </Badge>
            {retro.finalizedAt ? (
              <Badge variant="rag-green" className="text-[10px]">
                Finalized {formatDate(retro.finalizedAt)}
              </Badge>
            ) : (
              <Badge variant="rag-amber">Draft</Badge>
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--text-secondary)]">
          {retro.iterationStartDate && retro.iterationEndDate && (
            <span className="flex items-center gap-1">
              <Calendar className="h-3 w-3" />
              {formatDate(retro.iterationStartDate)} &mdash; {formatDate(retro.iterationEndDate)}
              {sprintDays && <span className="text-[var(--text-tertiary)]">({sprintDays} days)</span>}
            </span>
          )}
          <span className="px-2 py-0.5 rounded-md bg-[var(--bg-surface-raised)] border border-[var(--border-subtle)]">
            {source.detail}
          </span>
        </div>
      </div>

      {/* ── Sprint Metrics (4 tiles) ── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricTile
          icon={BarChart3}
          label="Completion Rate"
          value={evidence ? `${completionRate.toFixed(0)}%` : "N/A"}
          color={
            completionRate >= 85
              ? "var(--color-rag-green)"
              : completionRate >= 50
                ? "var(--color-rag-amber)"
                : "var(--color-rag-red)"
          }
          subtext={
            evidence
              ? `${evidence.doneSP?.toFixed(0)} of ${evidence.totalSP?.toFixed(0)} SP completed`
              : undefined
          }
        />
        <MetricTile
          icon={Target}
          label="Spillover"
          value={evidence ? `${spilloverSP.toFixed(0)} SP` : "N/A"}
          color={spilloverSP > 0 ? "var(--color-rag-amber)" : "var(--color-rag-green)"}
          subtext={spilloverSP > 0 ? "Carried to next sprint" : "No spillover"}
        />
        <MetricTile
          icon={Users}
          label="Overloaded Devs"
          value={overloadedDevs.length > 0 ? `${overloadedDevs.length}` : "0"}
          color={overloadedDevs.length > 0 ? "var(--color-rag-red)" : "var(--color-rag-green)"}
          subtext={overloadedDevs.length > 0 ? "Above capacity" : "All within capacity"}
        />
        <MetricTile
          icon={Clock}
          label="Sprint Duration"
          value={sprintDays ? `${sprintDays}d` : "N/A"}
          color="var(--color-brand-secondary)"
          subtext={retro.iterationState ? `State: ${retro.iterationState}` : undefined}
        />
      </div>

      {/* ── What Went Well / Didn't Go Well — side by side ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* What Went Well */}
        <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]/80 p-5">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-rag-green)] mb-3 flex items-center gap-1.5">
            <CheckCircle2 className="h-3.5 w-3.5" />
            What Went Well
          </h3>
          {retro.whatWentWell.length > 0 ? (
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
          ) : (
            <p className="text-xs text-[var(--text-tertiary)]">No items recorded</p>
          )}
        </div>

        {/* What Didn't Go Well */}
        <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]/80 p-5">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-rag-red)] mb-3 flex items-center gap-1.5">
            <XCircle className="h-3.5 w-3.5" />
            What Didn&apos;t Go Well
          </h3>
          {retro.whatDidntGoWell.length > 0 ? (
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
          ) : (
            <p className="text-xs text-[var(--text-tertiary)]">No items recorded</p>
          )}
        </div>
      </div>

      {/* ── Root Cause Analysis (full-width) ── */}
      {retro.rootCauseAnalysis.length > 0 && (
        <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]/80 p-5">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] mb-3">
            Root Cause Analysis
          </h3>
          <div className="space-y-2">
            {retro.rootCauseAnalysis.map((rca, idx) => (
              <div
                key={idx}
                className="flex items-center gap-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/40 px-3 py-2.5"
              >
                <span className="text-sm font-medium text-[var(--text-primary)] flex-1 min-w-0">
                  {rca.issue}
                </span>
                <ArrowRight className="h-4 w-4 shrink-0 text-[var(--text-secondary)]" />
                <span className="text-sm text-[var(--text-secondary)] flex-1 min-w-0">
                  {rca.cause}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Action Items (full-width) ── */}
      {retro.actionItems.length > 0 && (
        <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]/80 p-5">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] mb-3">
            Action Items ({retro.actionItems.length})
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
                  <span className="text-sm text-[var(--text-primary)] flex-1 min-w-0 truncate">
                    {action.title}
                  </span>
                  <Badge variant={cfg.variant} className="text-[10px] shrink-0">
                    {cfg.label}
                  </Badge>
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

      {/* ── Sprint Intelligence Summary (full-width) ── */}
      <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]/80 p-5">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] mb-3 flex items-center gap-1.5">
          <Brain className="h-3.5 w-3.5" />
          Sprint Intelligence Summary
        </h3>
        <div className="space-y-3 text-sm text-[var(--text-primary)] leading-relaxed">
          {isFailed ? (
            <>
              <p>
                {sprintLabel} completed with a{" "}
                <span className="font-medium text-[var(--color-rag-amber)]">
                  {completionRate.toFixed(0)}% completion rate
                </span>
                , classified as{" "}
                <span className="font-medium">
                  {classificationLabels[retro.failureClassification!] ?? retro.failureClassification}
                </span>
                . {spilloverSP > 0 && `${spilloverSP.toFixed(0)} story points spilled over to the next sprint.`}
              </p>
              {overloadedDevs.length > 0 && (
                <p>
                  {overloadedDevs.length} developer{overloadedDevs.length > 1 ? "s were" : " was"}{" "}
                  identified as overloaded, with the highest utilization at{" "}
                  {Math.max(...overloadedDevs.map((d) => d.utilization)).toFixed(0)}%.
                  This has been flagged as a planning constraint for the next sprint.
                </p>
              )}
              {retro.patternDetected && (
                <p className="text-[var(--color-rag-amber)]">
                  A recurring pattern of {classificationLabels[retro.failureClassification!] ?? retro.failureClassification}{" "}
                  has been detected across {retro.consecutiveFailureCount} consecutive sprints.
                  The AI planner will automatically apply capacity adjustments.
                </p>
              )}
            </>
          ) : evidence ? (
            <p>
              {sprintLabel} completed successfully with a{" "}
              <span className="font-medium text-[var(--color-rag-green)]">
                {completionRate.toFixed(0)}% completion rate
              </span>
              . The team delivered {evidence.doneSP?.toFixed(0)} of {evidence.totalSP?.toFixed(0)} story points.
              {spilloverSP > 0
                ? ` ${spilloverSP.toFixed(0)} story points were carried over.`
                : " All planned work was completed."}
            </p>
          ) : (
            <p className="text-[var(--text-secondary)]">
              Sprint metrics are not available for detailed analysis.
              Complete a sprint with tracked story points to see the intelligence summary.
            </p>
          )}
        </div>
      </div>

      {/* ── AI Diagnostics (combined card — only renders if failure data exists) ── */}
      {(retro.failureClassification || overloadedDevs.length > 0) && (
        <div className="rounded-xl border border-[var(--color-rag-amber)]/30 bg-[var(--bg-surface)]/80 p-5 space-y-5">
          {/* Sprint Failure Analysis */}
          {retro.failureClassification && (
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-rag-amber)] mb-4 flex items-center gap-1.5">
                <TrendingDown className="h-3.5 w-3.5" />
                Sprint Failure Analysis
              </h3>
              <div className="space-y-4">
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

                {retro.patternDetected && (
                  <div className="rounded-lg border border-[var(--color-rag-amber)]/30 bg-[var(--color-rag-amber)]/5 p-3">
                    <div className="flex items-start gap-2">
                      <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5 text-[var(--color-rag-amber)]" />
                      <div className="space-y-1">
                        <p className="text-xs font-medium text-[var(--text-primary)]">
                          Pattern Detected: This is the{" "}
                          {ordinalSuffix(retro.consecutiveFailureCount ?? 2)} consecutive
                          sprint with{" "}
                          {classificationLabels[retro.failureClassification] ?? retro.failureClassification}{" "}
                          classification.
                        </p>
                        <p className="text-xs text-[var(--text-secondary)]">
                          This pattern has been sent to the next sprint generation as a planning constraint.
                        </p>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Overloaded Developers */}
          {overloadedDevs.length > 0 && (
            <div className={retro.failureClassification ? "pt-4 border-t border-[var(--border-subtle)]" : ""}>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-rag-red)] mb-3 flex items-center gap-1.5">
                <Users className="h-3.5 w-3.5" />
                Overloaded Developers
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {overloadedDevs.map((dev, idx) => (
                  <div
                    key={idx}
                    className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/40 p-3"
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm font-medium text-[var(--text-primary)]">
                        {dev.name}
                      </span>
                      <Badge
                        variant={dev.utilization > 120 ? "rag-red" : "rag-amber"}
                        className="text-[10px]"
                      >
                        {dev.utilization.toFixed(0)}% utilized
                      </Badge>
                    </div>
                    <div className="h-2 rounded-full bg-[var(--bg-surface)] overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{
                          width: `${Math.min(dev.utilization, 150)}%`,
                          maxWidth: "100%",
                          backgroundColor:
                            dev.utilization > 120
                              ? "var(--color-rag-red)"
                              : "var(--color-rag-amber)",
                        }}
                      />
                    </div>
                    {dev.assignedSP != null && dev.capacitySP != null && (
                      <p className="text-xs text-[var(--text-tertiary)] mt-1.5">
                        {dev.assignedSP} SP assigned / {dev.capacitySP} SP capacity
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* AI Planning Constraints / Feed-forward */}
          {retro.feedForwardSignals?.signals && retro.feedForwardSignals.signals.length > 0 && (
            <div className="pt-4 border-t border-[var(--border-subtle)]">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-brand-secondary)] mb-3 flex items-center gap-1.5">
                <Brain className="h-3.5 w-3.5" />
                AI Planning Constraints
              </h3>
              <p className="text-xs text-[var(--text-secondary)] mb-3">
                These signals will be automatically applied to the next sprint plan generation.
              </p>
              <ul className="space-y-2">
                {retro.feedForwardSignals.signals.map((signal, idx) => (
                  <li
                    key={idx}
                    className="flex items-start gap-2 rounded-lg border border-[var(--color-brand-secondary)]/15 bg-[var(--color-brand-secondary)]/5 px-3 py-2.5"
                  >
                    <Zap className="h-3.5 w-3.5 shrink-0 mt-0.5 text-[var(--color-brand-secondary)]" />
                    <span className="text-sm text-[var(--text-primary)] leading-snug">{signal}</span>
                  </li>
                ))}
              </ul>

              {retro.feedForwardSignals.details && retro.feedForwardSignals.details.length > 0 && (
                <div className="mt-4 pt-3 border-t border-[var(--border-subtle)]">
                  <p className="text-xs font-medium text-[var(--text-secondary)] mb-2">
                    Specific Adjustments:
                  </p>
                  <div className="space-y-1.5">
                    {retro.feedForwardSignals.details.map((detail, idx) => (
                      <div
                        key={idx}
                        className="flex items-center gap-2 text-xs text-[var(--text-primary)]"
                      >
                        <span className="px-1.5 py-0.5 rounded bg-[var(--bg-surface-raised)] border border-[var(--border-subtle)] font-mono text-[10px] text-[var(--text-secondary)]">
                          {detail.type}
                        </span>
                        <span className="flex-1">{detail.reason}</span>
                        {detail.target && (
                          <span className="text-[var(--text-tertiary)]">
                            Target: {detail.target}
                          </span>
                        )}
                        {detail.adjustment != null && (
                          <Badge
                            variant={detail.adjustment < 0 ? "rag-red" : "rag-green"}
                            className="text-[10px]"
                          >
                            {detail.adjustment > 0 ? "+" : ""}
                            {detail.adjustment}%
                          </Badge>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
