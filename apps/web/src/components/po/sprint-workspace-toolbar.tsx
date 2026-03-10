"use client";

import { Loader2, RefreshCw, Zap, CheckCircle2, XCircle } from "lucide-react";
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
  onRegenerate: () => void;
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
  const canApprove = status === "PENDING_REVIEW";
  const canReject = status === "PENDING_REVIEW";
  const canRegenerate = !!status && status !== "GENERATING" && status !== "REGENERATING";
  const isReadOnly = status === "APPROVED" || status === "SYNCED" || status === "SYNCED_PARTIAL";

  return (
    <div className="flex items-center justify-between border-b border-[var(--border-subtle)] bg-[var(--bg-surface)] px-5 py-2.5">
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

        {/* Regenerate */}
        {canRegenerate && (
          <Button
            variant="secondary"
            size="sm"
            onClick={onRegenerate}
            disabled={generating}
          >
            {generating ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
            {generating ? "Generating..." : "Regenerate"}
          </Button>
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
  );
}
