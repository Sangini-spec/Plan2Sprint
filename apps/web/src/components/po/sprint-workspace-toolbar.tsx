"use client";

import { useState, useEffect } from "react";
import { Loader2, RefreshCw, Zap, CheckCircle2, XCircle, MessageSquareText, ChevronUp, Send } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge, Button } from "@/components/ui";
import type { SprintPlanStatus } from "@/lib/types/models";

// Hotfix 33c — countdown timer next to the "Generating new plan…"
// indicator. Counts DOWN from an ETA budget so the user sees how much
// time is expected to remain (per user feedback). Once it hits 0 it
// keeps showing "0:00" — by that point the polling loop should have
// detected completion and cleared ``startedAtMs`` anyway, so the
// component unmounts. ETA budget defaults to 3 minutes (180s) which
// matches the observed typical max for sprint plan generation
// (Grok-fast on a ~50-item backlog).
const GENERATION_ETA_SECONDS = 180;
function GenerationTimer({ startedAtMs }: { startedAtMs: number | null }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!startedAtMs) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [startedAtMs]);
  if (!startedAtMs) return null;
  const elapsedSec = Math.max(0, Math.floor((now - startedAtMs) / 1000));
  const remainingSec = Math.max(0, GENERATION_ETA_SECONDS - elapsedSec);
  const mm = Math.floor(remainingSec / 60).toString().padStart(2, "0");
  const ss = (remainingSec % 60).toString().padStart(2, "0");
  return <span className="tabular-nums">{mm}:{ss}</span>;
}

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

interface SprintWorkspaceToolbarProps {
  status: SprintPlanStatus | null;
  /** Hotfix 32 — Step E: separate in-flight signal so the badge can show
   *  GENERATING/FAILED while the underlying ``status`` still reflects
   *  the previous READY plan (whose data fills the rest of the page). */
  inflightStatus?: "GENERATING" | "FAILED" | null;
  inflightRiskSummary?: string | null;
  /** Hotfix 33b — when generation started (ms epoch). Used to drive the
   *  live "MM:SS" timer in the inline indicator. */
  inflightStartedAtMs?: number | null;
  generating: boolean;
  projectName: string | null;
  onGenerate: () => void;
  onRegenerate: (feedback?: string) => void;
  onApprove: () => void;
  onReject: () => void;
}

export function SprintWorkspaceToolbar({
  status,
  inflightStatus = null,
  inflightRiskSummary = null,
  inflightStartedAtMs = null,
  generating,
  projectName,
  onGenerate,
  onRegenerate,
  onApprove,
  onReject,
}: SprintWorkspaceToolbarProps) {
  const [showPrompt, setShowPrompt] = useState(false);
  const [feedback, setFeedback] = useState("");

  // Hotfix 32 (revised) — keep the badge showing the READY plan's
  // status (PENDING_REVIEW / APPROVED / etc.) like it always did. The
  // user wanted the simple spinner-on-button UX from before, not a
  // "GENERATING" tag overriding the badge. We still surface the FAILED
  // case via an inline error message so the user knows what went wrong.
  const isInflightGenerating = inflightStatus === "GENERATING";
  const isInflightFailed = inflightStatus === "FAILED";

  // Approvals & rejections gate on the READY plan's status, but also
  // disable while a regen is in flight (don't let user approve while
  // a new plan is mid-flight).
  const canApprove = status === "PENDING_REVIEW" && !isInflightGenerating;
  const canReject = status === "PENDING_REVIEW" && !isInflightGenerating;
  // Don't allow Regenerate while a generation is in flight.
  const canRegenerate =
    !!status && status !== "GENERATING" && status !== "REGENERATING" && !isInflightGenerating;
  const isReadOnly =
    !isInflightGenerating &&
    (status === "APPROVED" || status === "SYNCED" || status === "SYNCED_PARTIAL");

  const handleRegenerate = () => {
    const trimmed = feedback.trim();
    onRegenerate(trimmed || undefined);
    setFeedback("");
    setShowPrompt(false);
  };

  return (
    <div className="border-b border-[var(--border-subtle)] bg-[var(--bg-surface)]">
      {/* Main toolbar row */}
      <div className="flex items-center justify-between px-5 py-2.5">
        {/* Left: status + project + (optional) inflight indicator */}
        <div className="flex items-center gap-3">
          {status && (
            <Badge variant={statusBadgeVariant[status]}>
              {status.replace(/_/g, " ")}
            </Badge>
          )}
          {projectName && (
            <span className="text-xs text-[var(--text-secondary)]">
              {projectName}
            </span>
          )}
          {/* Subtle inline indicator — does NOT replace the status badge.
              Hotfix 33c — countdown from estimated 3 min so the wait
              feels finite. */}
          {isInflightGenerating && (
            <span className="flex items-center gap-1.5 text-xs text-[var(--color-brand-secondary)]">
              <Loader2 className="h-3 w-3 animate-spin" />
              Generating new plan…
              {inflightStartedAtMs && (
                <>
                  <GenerationTimer startedAtMs={inflightStartedAtMs} />
                  <span className="text-[var(--text-tertiary)]">remaining</span>
                </>
              )}
            </span>
          )}
          {isInflightFailed && inflightRiskSummary && (
            <span className="flex items-center gap-1.5 text-xs text-[var(--color-rag-red)] truncate max-w-[480px]" title={inflightRiskSummary}>
              <XCircle className="h-3 w-3 shrink-0" />
              {inflightRiskSummary}
            </span>
          )}
        </div>

        {/* Right: action buttons */}
        <div className="flex items-center gap-2">
          {/* Generate (only when no plan) */}
          {!status && (
            <Button
              variant="primary"
              size="sm"
              onClick={onGenerate}
              disabled={generating}
            >
              {generating ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Zap className="h-3.5 w-3.5" />
              )}
              {generating ? "Generating..." : "Generate Plan"}
            </Button>
          )}

          {/* Regenerate with prompt toggle */}
          {canRegenerate && (
            <>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setShowPrompt(!showPrompt)}
                disabled={generating}
                data-onboarding="regenerate-btn"
                className={cn(
                  showPrompt && "ring-1 ring-[var(--color-brand)]"
                )}
              >
                {generating ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
                {generating ? "Generating..." : "Regenerate"}
                {!generating && (
                  <MessageSquareText className="h-3 w-3 ml-0.5 text-[var(--text-tertiary)]" />
                )}
              </Button>
            </>
          )}

          {/* Approve */}
          {canApprove && (
            <Button variant="primary" size="sm" onClick={onApprove}>
              <CheckCircle2 className="h-3.5 w-3.5" />
              Approve &amp; Sync
            </Button>
          )}

          {/* Reject */}
          {canReject && (
            <Button variant="ghost" size="sm" onClick={onReject}>
              <XCircle className="h-3.5 w-3.5" />
              Reject
            </Button>
          )}

          {/* Read-only indicator */}
          {isReadOnly && (
            <span className="text-xs text-[var(--color-rag-green)] flex items-center gap-1">
              <CheckCircle2 className="h-3 w-3" />
              {status === "APPROVED" ? "Approved" : "Synced"}
            </span>
          )}
        </div>
      </div>

      {/* Expandable prompt input */}
      {showPrompt && !generating && (
        <div className="px-5 pb-3 animate-in slide-in-from-top-1 duration-200">
          <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-sunken)] p-3">
            <div className="flex items-start gap-2 mb-2">
              <MessageSquareText className="h-4 w-4 text-[var(--color-brand)] mt-0.5 shrink-0" />
              <p className="text-[11px] text-[var(--text-secondary)]">
                Tell the AI how you want the next plan to be different. For example: prioritize authentication first, limit to 6 sprints, assign more work per sprint, etc.
              </p>
            </div>
            <textarea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder="E.g., Put login and registration in Sprint 1. Group related features together. Keep it under 8 sprints..."
              className="w-full rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-3 py-2 text-xs text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:ring-1 focus:ring-[var(--color-brand)] resize-none"
              rows={3}
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                  handleRegenerate();
                }
              }}
            />
            <div className="flex items-center justify-between mt-2">
              <span className="text-[10px] text-[var(--text-tertiary)]">
                Ctrl+Enter to submit • Leave empty to auto-optimize
              </span>
              <div className="flex items-center gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => { setShowPrompt(false); setFeedback(""); }}
                >
                  <ChevronUp className="h-3 w-3" />
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  size="sm"
                  onClick={handleRegenerate}
                >
                  <Send className="h-3 w-3" />
                  {feedback.trim() ? "Regenerate with Instructions" : "Auto-Optimize"}
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
