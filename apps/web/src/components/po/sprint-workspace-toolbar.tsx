"use client";

import { useState } from "react";
import { Loader2, RefreshCw, Zap, CheckCircle2, XCircle, MessageSquareText, ChevronUp, Send } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge, Button } from "@/components/ui";
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

interface SprintWorkspaceToolbarProps {
  status: SprintPlanStatus | null;
  generating: boolean;
  projectName: string | null;
  onGenerate: () => void;
  onRegenerate: (feedback?: string) => void;
  onApprove: () => void;
  onReject: () => void;
}

export function SprintWorkspaceToolbar({
  status,
  generating,
  projectName,
  onGenerate,
  onRegenerate,
  onApprove,
  onReject,
}: SprintWorkspaceToolbarProps) {
  const [showPrompt, setShowPrompt] = useState(false);
  const [feedback, setFeedback] = useState("");

  const canApprove = status === "PENDING_REVIEW";
  const canReject = status === "PENDING_REVIEW";
  const canRegenerate = !!status && status !== "GENERATING" && status !== "REGENERATING";
  const isReadOnly = status === "APPROVED" || status === "SYNCED" || status === "SYNCED_PARTIAL";

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
        {/* Left: status + project */}
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
