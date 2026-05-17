"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import {
  Scale,
  Shield,
  Clock,
  Calendar,
  ChevronDown,
  ChevronUp,
  CheckCircle2,
  AlertTriangle,
  ArrowRight,
  Loader2,
  RefreshCw,
  Target,
  TrendingUp,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button, Badge, Input } from "@/components/ui";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { useSelectedProject } from "@/lib/project/context";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface RebalanceStory {
  id: string;
  title: string;
  sp: number;
  action: string;
  reason?: string;
  status?: string;
  priority?: number;
  assignee?: string;
}

interface RebalanceSprint {
  number: number;
  totalSP: number;
  startDate?: string;
  endDate?: string;
  stories: RebalanceStory[];
}

interface ChangeSummary {
  id: string;
  title: string;
  action: string;
  fromSprint: number;
  toSprint: number | null;
  spFreed: number;
  reason: string;
}

interface DownstreamImpact {
  [sprint: string]: {
    spChange: string;
    newTotal: number;
    capacityPct: number;
    warning: string | null;
  };
}

interface RebalanceProposal {
  proposalId: string;
  status: string;
  mode: string;
  summary: string;
  rationale: string;
  originalSuccessProbability: number;
  projectedSuccessProbability: number;
  originalEndDate: string | null;
  projectedEndDate: string | null;
  sprints: RebalanceSprint[];
  changesSummary: ChangeSummary[];
  downstreamImpact: DownstreamImpact;
}

type RebalanceMode = "PROTECT_TIMELINE" | "PROTECT_SCOPE" | "CUSTOM_DATE";

// ---------------------------------------------------------------------------
// Action Badge
// ---------------------------------------------------------------------------

function ActionBadge({ action }: { action: string }) {
  const styles: Record<string, { bg: string; text: string; label: string }> = {
    KEEP: { bg: "bg-[var(--bg-surface-raised)]", text: "text-[var(--text-tertiary)]", label: "KEEP" },
    DEFER: { bg: "bg-amber-500/10", text: "text-amber-400", label: "DEFERRED" },
    DEFERRED: { bg: "bg-amber-500/10", text: "text-amber-400", label: "DEFERRED" },
    SPLIT: { bg: "bg-purple-500/10", text: "text-purple-400", label: "SPLIT" },
    ADJUST_SP: { bg: "bg-blue-500/10", text: "text-blue-400", label: "ADJUSTED" },
    REPRIORITIZE: { bg: "bg-cyan-500/10", text: "text-cyan-400", label: "MOVED" },
    DESCOPE: { bg: "bg-red-500/10", text: "text-red-400", label: "DESCOPED" },
  };
  const s = styles[action] || styles.KEEP;
  return (
    <span className={cn("inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider", s.bg, s.text)}>
      {s.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Success Gauge
// ---------------------------------------------------------------------------

function SuccessGauge({ value, label }: { value: number; label: string }) {
  const color = value >= 75 ? "var(--color-rag-green)" : value >= 50 ? "var(--color-rag-amber)" : "var(--color-rag-red)";
  const circumference = 2 * Math.PI * 40;
  const offset = circumference - (value / 100) * circumference;

  return (
    <div className="flex flex-col items-center">
      <div className="relative w-24 h-24">
        <svg className="w-full h-full -rotate-90" viewBox="0 0 100 100">
          <circle cx="50" cy="50" r="40" fill="none" stroke="var(--border-subtle)" strokeWidth="6" />
          <circle cx="50" cy="50" r="40" fill="none" stroke={color} strokeWidth="6"
            strokeDasharray={circumference} strokeDashoffset={offset} strokeLinecap="round"
            className="transition-all duration-700" />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-xl font-bold tabular-nums" style={{ color }}>{value}%</span>
        </div>
      </div>
      <span className="text-[10px] text-[var(--text-tertiary)] mt-1 uppercase tracking-wider">{label}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

interface SprintRebalanceTabProps {
  planId: string | null;
  rebalancingRecommended: boolean;
  successProbability: number;
  isRebalanced?: boolean;
}

export function SprintRebalanceTab({ planId, rebalancingRecommended, successProbability, isRebalanced }: SprintRebalanceTabProps) {
  const { selectedProject } = useSelectedProject();
  const [mode, setMode] = useState<RebalanceMode>("PROTECT_TIMELINE");
  const [targetDate, setTargetDate] = useState("");
  const [poGuidance, setPoGuidance] = useState("");
  const [generating, setGenerating] = useState(false);
  const [approving, setApproving] = useState(false);
  const [proposal, setProposal] = useState<RebalanceProposal | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expandedSprints, setExpandedSprints] = useState<Set<number>>(new Set([1, 2]));
  const [showChanges, setShowChanges] = useState(true);
  const [countdown, setCountdown] = useState(0);
  const countdownRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [lastApproved, setLastApproved] = useState<RebalanceProposal | null>(null);
  const [viewingApproved, setViewingApproved] = useState(false);

  const ESTIMATED_SECONDS = 90; // AI typically takes 60-90s

  // Load last approved proposal on mount
  useEffect(() => {
    if (!planId || !isRebalanced) return;
    (async () => {
      try {
        const res = await fetch(`/api/sprints/rebalance/latest?planId=${planId}`);
        if (res.ok) {
          const data = await res.json();
          if (data.found && data.status === "APPROVED") {
            setLastApproved(data as RebalanceProposal);
          }
        }
      } catch { /* swallow */ }
    })();
  }, [planId, isRebalanced]);

  // Countdown timer effect
  useEffect(() => {
    if (generating && countdown > 0) {
      countdownRef.current = setInterval(() => {
        setCountdown(prev => {
          if (prev <= 1) {
            if (countdownRef.current) clearInterval(countdownRef.current);
            return 0;
          }
          return prev - 1;
        });
      }, 1000);
    }
    return () => {
      if (countdownRef.current) clearInterval(countdownRef.current);
    };
  }, [generating, countdown > 0]);

  // Stop countdown when generation completes
  useEffect(() => {
    if (!generating && countdownRef.current) {
      clearInterval(countdownRef.current);
      setCountdown(0);
    }
  }, [generating]);

  const toggleSprint = (n: number) => {
    setExpandedSprints(prev => {
      const next = new Set(prev);
      if (next.has(n)) next.delete(n); else next.add(n);
      return next;
    });
  };

  // Generate rebalancing proposal
  const handleGenerate = useCallback(async () => {
    if (!planId) return;
    setGenerating(true);
    setError(null);
    setCountdown(ESTIMATED_SECONDS);
    try {
      // Use AbortController with long timeout for AI-powered generation
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 180000); // 3 min
      const res = await fetch("/api/sprints/rebalance", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          planId,
          mode,
          targetDate: mode === "CUSTOM_DATE" ? targetDate : undefined,
          poGuidance: poGuidance || undefined,
        }),
        signal: controller.signal,
      });
      clearTimeout(timeout);
      if (res.ok) {
        const data = await res.json();
        setProposal(data as RebalanceProposal);
      } else {
        const err = await res.json().catch(() => ({ detail: "Generation failed" }));
        setError(err.detail || "Failed to generate rebalancing plan");
      }
    } catch {
      setError("Network error - please try again");
    }
    setGenerating(false);
  }, [planId, mode, targetDate, poGuidance]);

  // Approve rebalancing → new plan
  const handleApprove = useCallback(async () => {
    if (!proposal) return;
    setApproving(true);
    try {
      const res = await fetch("/api/sprints/rebalance/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ proposalId: proposal.proposalId }),
      });
      if (res.ok) {
        const data = await res.json();
        setProposal(prev => prev ? { ...prev, status: "APPROVED" } : null);
        // Reload page to reflect new plan across all tabs
        setTimeout(() => window.location.reload(), 1500);
      } else {
        setError("Approval failed - please try again");
      }
    } catch {
      setError("Network error");
    }
    setApproving(false);
  }, [proposal]);

  // ── Mode selection: show when no proposal, or when approved but NOT viewing ──
  if (!proposal || (proposal.status === "APPROVED" && !viewingApproved)) {
    return (
      <div className="space-y-6">
        {/* Status banner - rebalanced or at-risk */}
        {isRebalanced ? (
          <div className="flex items-center gap-3 p-4 rounded-lg bg-orange-500/5 border border-orange-500/20">
            <CheckCircle2 className="h-5 w-5 text-orange-400 shrink-0" />
            <div className="flex-1">
              <p className="text-sm font-medium text-[var(--text-primary)]">
                Rebalancing plan approved and active
              </p>
              <p className="text-xs text-[var(--text-secondary)] mt-0.5">
                Projected success probability: {successProbability}%. You can generate a new rebalancing plan anytime.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Badge variant="brand" className="bg-orange-500/10 text-orange-400 border-orange-500/20">
                Active
              </Badge>
              {lastApproved && (
                <button
                  onClick={() => {
                    setProposal(lastApproved);
                    setViewingApproved(true);
                  }}
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-medium bg-[var(--color-brand-secondary)]/10 text-[var(--color-brand-secondary)] border border-[var(--color-brand-secondary)]/20 hover:bg-[var(--color-brand-secondary)]/20 transition-colors"
                >
                  <Target size={11} />
                  View Plan
                </button>
              )}
            </div>
          </div>
        ) : rebalancingRecommended ? (
          <div className="flex items-center gap-3 p-4 rounded-lg bg-[var(--color-rag-red)]/5 border border-[var(--color-rag-red)]/20">
            <AlertTriangle className="h-5 w-5 text-[var(--color-rag-red)] shrink-0" />
            <div>
              <p className="text-sm font-medium text-[var(--text-primary)]">
                Sprint at risk - {successProbability}% success probability
              </p>
              <p className="text-xs text-[var(--text-secondary)] mt-0.5">
                AI analysis indicates the sprint will likely fail without rebalancing.
              </p>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-3 p-4 rounded-lg bg-[var(--color-rag-green)]/5 border border-[var(--color-rag-green)]/20">
            <CheckCircle2 className="h-5 w-5 text-[var(--color-rag-green)] shrink-0" />
            <div>
              <p className="text-sm font-medium text-[var(--text-primary)]">
                Sprint health: {successProbability}% success probability
              </p>
              <p className="text-xs text-[var(--text-secondary)] mt-0.5">
                Sprint looks healthy. You can still generate a rebalancing plan to optimize further.
              </p>
            </div>
          </div>
        )}

        {/* Mode selection */}
        <DashboardPanel title="How should we rebalance?" icon={Scale}>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Mode 1: Protect Timeline */}
            <button
              onClick={() => setMode("PROTECT_TIMELINE")}
              className={cn(
                "p-5 rounded-xl border-2 text-left transition-all hover:shadow-md",
                mode === "PROTECT_TIMELINE"
                  ? "border-[var(--color-brand-secondary)] bg-[var(--color-brand-secondary)]/5"
                  : "border-[var(--border-subtle)] bg-[var(--bg-surface)]"
              )}
            >
              <div className="flex items-center gap-2 mb-2">
                <Shield className="h-5 w-5 text-[var(--color-brand-secondary)]" />
                <span className="font-semibold text-[var(--text-primary)]">Protect Timeline</span>
              </div>
              <p className="text-xs text-[var(--text-secondary)]">
                Keep the end date fixed. AI will defer or descope lower-priority items to meet the deadline.
              </p>
            </button>

            {/* Mode 2: Protect Scope */}
            <button
              onClick={() => setMode("PROTECT_SCOPE")}
              className={cn(
                "p-5 rounded-xl border-2 text-left transition-all hover:shadow-md",
                mode === "PROTECT_SCOPE"
                  ? "border-[var(--color-brand-secondary)] bg-[var(--color-brand-secondary)]/5"
                  : "border-[var(--border-subtle)] bg-[var(--bg-surface)]"
              )}
            >
              <div className="flex items-center gap-2 mb-2">
                <Target className="h-5 w-5 text-[var(--color-brand-secondary)]" />
                <span className="font-semibold text-[var(--text-primary)]">Protect Scope</span>
              </div>
              <p className="text-xs text-[var(--text-secondary)]">
                Keep all stories. AI will extend the timeline and rebalance sprints for even load.
              </p>
            </button>
          </div>

          {/* Custom Date (sub-option of Protect Scope) */}
          <div className="mt-4">
            <button
              onClick={() => setMode("CUSTOM_DATE")}
              className={cn(
                "w-full p-4 rounded-xl border-2 text-left transition-all hover:shadow-md",
                mode === "CUSTOM_DATE"
                  ? "border-[var(--color-brand-secondary)] bg-[var(--color-brand-secondary)]/5"
                  : "border-[var(--border-subtle)] bg-[var(--bg-surface)]"
              )}
            >
              <div className="flex items-center gap-2 mb-2">
                <Calendar className="h-5 w-5 text-[var(--color-brand-secondary)]" />
                <span className="font-semibold text-[var(--text-primary)]">Custom Target Date</span>
              </div>
              <p className="text-xs text-[var(--text-secondary)]">
                Everything done by a specific date. AI optimizes for your deadline.
              </p>
            </button>
            {mode === "CUSTOM_DATE" && (
              <div className="mt-3 pl-4">
                <label className="text-xs text-[var(--text-secondary)] mb-1 block">Target completion date:</label>
                <Input
                  type="date"
                  value={targetDate}
                  onChange={(e) => setTargetDate(e.target.value)}
                  className="max-w-xs"
                />
              </div>
            )}
          </div>

          {/* PO Guidance */}
          <div className="mt-4">
            <label className="text-xs text-[var(--text-secondary)] mb-1 block">
              PO Guidance (optional):
            </label>
            <Input
              value={poGuidance}
              onChange={(e) => setPoGuidance(e.target.value)}
              placeholder="e.g., Keep auth feature in Sprint 1 no matter what"
              className="text-sm"
            />
          </div>

          {/* Generate button */}
          <div className="mt-6 flex flex-col items-center gap-3">
            <Button
              onClick={handleGenerate}
              disabled={generating || !planId || (mode === "CUSTOM_DATE" && !targetDate)}
              className="px-8"
            >
              {generating ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  Generating Rebalancing Plan...
                </>
              ) : (
                <>
                  <Scale className="h-4 w-4 mr-2" />
                  Generate Rebalancing Plan
                </>
              )}
            </Button>
            {generating && countdown > 0 && (
              <p className="text-xs text-[var(--text-tertiary)] animate-pulse">
                AI is analyzing your sprint plan
              </p>
            )}
          </div>

          {/* Countdown toast - fixed top-right */}
          {generating && (
            <div className="fixed top-20 right-6 z-50 flex items-center gap-3 px-5 py-3 rounded-xl bg-[var(--bg-surface)] border border-[var(--color-brand-secondary)]/30 shadow-lg shadow-[var(--color-brand-secondary)]/10 animate-in slide-in-from-right">
              <div className="flex items-center justify-center h-10 w-10 rounded-full bg-[var(--color-brand-secondary)]/10">
                <span className="text-lg font-bold tabular-nums text-[var(--color-brand-secondary)]">
                  {countdown > 0 ? countdown : <Loader2 className="h-5 w-5 animate-spin" />}
                </span>
              </div>
              <div>
                <p className="text-sm font-medium text-[var(--text-primary)]">
                  {countdown > 0
                    ? `Generating plan in ${countdown} seconds`
                    : "Finalizing your plan..."
                  }
                </p>
                <div className="mt-1 h-1 w-full rounded-full bg-[var(--border-subtle)] overflow-hidden">
                  <div
                    className="h-full rounded-full bg-[var(--color-brand-secondary)] transition-all duration-1000 ease-linear"
                    style={{ width: `${Math.max(0, ((ESTIMATED_SECONDS - countdown) / ESTIMATED_SECONDS) * 100)}%` }}
                  />
                </div>
              </div>
            </div>
          )}

          {error && (
            <p className="mt-3 text-xs text-[var(--color-rag-red)] text-center">{error}</p>
          )}
        </DashboardPanel>
      </div>
    );
  }

  // ── Proposal view (after generation) ──
  const changes = proposal.changesSummary || [];
  const totalChanges = changes.length;

  return (
    <div className="space-y-4">
      {/* Header: Before → After gauges */}
      <DashboardPanel title="Sprint Rebalance" icon={Scale}>
        <div className="flex flex-col sm:flex-row items-center gap-8 justify-center py-4">
          <SuccessGauge value={proposal.originalSuccessProbability} label="Current" />
          <ArrowRight className="h-6 w-6 text-[var(--text-tertiary)] hidden sm:block" />
          <SuccessGauge value={proposal.projectedSuccessProbability} label="Projected" />
          <div className="text-center sm:text-left">
            <div className="text-2xl font-bold text-[var(--color-rag-green)]">
              +{proposal.projectedSuccessProbability - proposal.originalSuccessProbability}%
            </div>
            <div className="text-xs text-[var(--text-tertiary)]">improvement</div>
          </div>
        </div>

        {/* Mode + timeline info */}
        <div className="flex flex-wrap gap-3 justify-center mt-2">
          <Badge variant="brand" className="bg-[var(--color-brand-secondary)]/10 text-[var(--color-brand-secondary)] border-[var(--color-brand-secondary)]/20">
            {mode === "PROTECT_TIMELINE" ? "Protect Timeline" : mode === "PROTECT_SCOPE" ? "Protect Scope" : "Custom Date"}
          </Badge>
          {proposal.projectedEndDate && (
            <Badge variant="brand" className="bg-[var(--bg-surface-raised)] text-[var(--text-secondary)]">
              <Clock className="h-3 w-3 mr-1" />
              End: {new Date(proposal.projectedEndDate).toLocaleDateString()}
            </Badge>
          )}
          <Badge variant="brand" className="bg-orange-500/10 text-orange-400 border-orange-500/20">
            {totalChanges} change{totalChanges !== 1 ? "s" : ""}
          </Badge>
        </div>

        {/* AI Strategy */}
        <div className="mt-4 p-3 rounded-lg bg-[var(--bg-surface-raised)] border border-[var(--border-subtle)]">
          <p className="text-xs font-medium text-[var(--text-secondary)] mb-1">AI Rescue Strategy:</p>
          <p className="text-sm text-[var(--text-primary)] leading-relaxed">{proposal.summary}</p>
        </div>
      </DashboardPanel>

      {/* Sprint Allocation - full list */}
      {(proposal.sprints || []).map((sprint) => {
        const isExpanded = expandedSprints.has(sprint.number);
        const changedCount = sprint.stories.filter(s => s.action !== "KEEP").length;

        return (
          <DashboardPanel
            key={sprint.number}
            title={`Sprint ${sprint.number}`}
            icon={TrendingUp}
            collapsible
            defaultCollapsed={!isExpanded}
            actions={
              <div className="flex items-center gap-2">
                <span className="text-xs text-[var(--text-secondary)] tabular-nums">
                  {sprint.totalSP} SP
                </span>
                {changedCount > 0 && (
                  <Badge variant="brand" className="bg-orange-500/10 text-orange-400 border-orange-500/20 text-[10px]">
                    {changedCount} changed
                  </Badge>
                )}
              </div>
            }
          >
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[var(--border-subtle)]">
                    <th className="text-left py-2 px-3 text-xs text-[var(--text-tertiary)] font-medium">ID</th>
                    <th className="text-left py-2 px-3 text-xs text-[var(--text-tertiary)] font-medium">Story</th>
                    <th className="text-center py-2 px-3 text-xs text-[var(--text-tertiary)] font-medium">SP</th>
                    <th className="text-center py-2 px-3 text-xs text-[var(--text-tertiary)] font-medium">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {sprint.stories.map((story, idx) => (
                    <tr
                      key={`${story.id}-${idx}`}
                      className={cn(
                        "border-b border-[var(--border-subtle)]/50 transition-colors",
                        story.action !== "KEEP" && "bg-orange-500/[0.03]"
                      )}
                    >
                      <td className="py-2 px-3 text-xs text-[var(--text-tertiary)] tabular-nums">
                        {story.id.slice(-4)}
                      </td>
                      <td className="py-2 px-3">
                        <span className="text-sm text-[var(--text-primary)]">{story.title}</span>
                        {story.reason && story.action !== "KEEP" && (
                          <p className="text-[10px] text-[var(--text-tertiary)] mt-0.5">{story.reason}</p>
                        )}
                      </td>
                      <td className="py-2 px-3 text-center text-xs tabular-nums text-[var(--text-secondary)]">
                        {story.sp}
                      </td>
                      <td className="py-2 px-3 text-center">
                        <ActionBadge action={story.action} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </DashboardPanel>
        );
      })}

      {/* Downstream Impact */}
      {proposal.downstreamImpact && Object.keys(proposal.downstreamImpact).length > 0 && (
        <DashboardPanel title="Downstream Impact" icon={TrendingUp}>
          <p className="text-xs text-[var(--text-secondary)] mb-3">
            How the rebalancing affects each sprint&apos;s workload. Negative SP means load was reduced (stories moved out), positive means load increased (deferred stories landed here).
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {Object.entries(proposal.downstreamImpact).map(([sprint, impact]) => {
              const spNum = parseInt(impact.spChange) || 0;
              const cap = impact.capacityPct || 0;
              const isOverloaded = cap >= 90;
              const isReduced = spNum < 0;
              const isIncreased = spNum > 0;
              const isUnchanged = spNum === 0;

              // Generate a human-readable description
              let description = "";
              if (isUnchanged) {
                description = "No change - this sprint is unaffected by the rebalancing.";
              } else if (isReduced && cap <= 70) {
                description = `Load reduced by ${Math.abs(spNum)} SP. Sprint now has comfortable capacity for unexpected work.`;
              } else if (isReduced && cap <= 85) {
                description = `Load reduced by ${Math.abs(spNum)} SP. Sprint is well-balanced with room for minor scope changes.`;
              } else if (isReduced) {
                description = `Load reduced by ${Math.abs(spNum)} SP, but sprint is still near capacity. Monitor closely.`;
              } else if (isIncreased && cap >= 100) {
                description = `Deferred items added ${spNum} SP. Sprint is at full capacity - risk of spillover if blockers arise.`;
              } else if (isIncreased && cap >= 85) {
                description = `Deferred items added ${spNum} SP. Sprint is running heavy - keep an eye on velocity.`;
              } else {
                description = `${spNum > 0 ? "+" : ""}${spNum} SP moved here. Sprint has healthy capacity remaining.`;
              }

              return (
                <div
                  key={sprint}
                  className={cn(
                    "p-3 rounded-lg border",
                    isOverloaded
                      ? "bg-[var(--color-rag-red)]/5 border-[var(--color-rag-red)]/20"
                      : isIncreased && cap >= 80
                        ? "bg-[var(--color-rag-amber)]/5 border-[var(--color-rag-amber)]/20"
                        : isReduced
                          ? "bg-[var(--color-rag-green)]/5 border-[var(--color-rag-green)]/20"
                          : "bg-[var(--bg-surface-raised)] border-[var(--border-subtle)]"
                  )}
                >
                  <div className="flex items-center justify-between mb-1">
                    <p className="text-xs font-semibold text-[var(--text-primary)] capitalize">Sprint {sprint}</p>
                    <span className={cn(
                      "text-xs font-bold tabular-nums",
                      isOverloaded ? "text-[var(--color-rag-red)]" :
                      isIncreased && cap >= 80 ? "text-[var(--color-rag-amber)]" :
                      isReduced ? "text-[var(--color-rag-green)]" :
                      "text-[var(--text-secondary)]"
                    )}>
                      {cap}%
                    </span>
                  </div>
                  <p className="text-sm tabular-nums text-[var(--text-secondary)]">
                    {impact.spChange} SP
                  </p>
                  <p className="text-[11px] text-[var(--text-tertiary)] mt-1.5 leading-relaxed">
                    {impact.warning || description}
                  </p>
                </div>
              );
            })}
          </div>
        </DashboardPanel>
      )}

      {/* Why Each Change */}
      {changes.length > 0 && (
        <DashboardPanel
          title={`Why Each Change (${changes.length})`}
          icon={AlertTriangle}
          collapsible
          defaultCollapsed={!showChanges}
        >
          <div className="space-y-2">
            {changes.map((change, idx) => (
              <div
                key={`${change.id}-${idx}`}
                className="flex items-start gap-3 p-3 rounded-lg bg-[var(--bg-surface-raised)]"
              >
                <ActionBadge action={change.action} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-[var(--text-primary)]">{change.title}</p>
                  <p className="text-xs text-[var(--text-tertiary)] mt-0.5">
                    Sprint {change.fromSprint} → {change.toSprint !== null ? `Sprint ${change.toSprint}` : "Post-launch"}
                    {change.spFreed > 0 && ` | Frees ${change.spFreed} SP`}
                  </p>
                  <p className="text-xs text-[var(--text-secondary)] mt-1">{change.reason}</p>
                </div>
              </div>
            ))}
          </div>
        </DashboardPanel>
      )}

      {/* Action buttons */}
      <div className="flex items-center justify-center gap-4 py-4">
        {viewingApproved ? (
          /* Read-only mode - viewing the previously approved plan */
          <Button
            variant="secondary"
            onClick={() => { setProposal(null); setViewingApproved(false); }}
          >
            <ArrowRight className="h-4 w-4 mr-2 rotate-180" />
            Back to Rebalance Options
          </Button>
        ) : (
          /* Normal mode - new proposal ready for approval */
          <>
            <Button
              onClick={handleApprove}
              disabled={approving}
              className="px-6 bg-[var(--color-rag-green)] hover:bg-[var(--color-rag-green)]/90 text-white"
            >
              {approving ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  Approving...
                </>
              ) : (
                <>
                  <CheckCircle2 className="h-4 w-4 mr-2" />
                  Approve & Sync
                </>
              )}
            </Button>
            <Button
              variant="secondary"
              onClick={() => { setProposal(null); setError(null); }}
            >
              <RefreshCw className="h-4 w-4 mr-2" />
              Regenerate
            </Button>
            <Button
              variant="ghost"
              onClick={() => setProposal(null)}
            >
              Dismiss
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
