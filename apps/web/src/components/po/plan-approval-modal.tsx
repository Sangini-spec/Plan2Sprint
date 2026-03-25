"use client";

import { useState } from "react";
import { Loader2, CheckCircle2, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button, Textarea } from "@/components/ui";

// ---------------------------------------------------------------------------
// Slim confirmation dialog — the full plan view is the workspace now.
// ---------------------------------------------------------------------------

interface PlanApprovalModalProps {
  open: boolean;
  onClose: () => void;
  mode: "approve" | "reject";
  planId: string | null;
  totalSP: number | null;
  estimatedSprints: number | null;
  tool: string | null;
}

export function PlanApprovalModal({
  open,
  onClose,
  mode,
  planId,
  totalSP,
  estimatedSprints,
  tool,
}: PlanApprovalModalProps) {
  const [processing, setProcessing] = useState(false);
  const [done, setDone] = useState(false);
  const [feedback, setFeedback] = useState("");

  if (!open) return null;

  const handleAction = async () => {
    if (!planId) return;
    setProcessing(true);

    try {
      const body: Record<string, unknown> = { planId };

      if (mode === "approve") {
        body.status = "APPROVED";
      } else {
        body.status = "REJECTED";
        body.rejectionFeedback =
          feedback.trim() || "Rejected by PO — regenerate with adjustments";
      }

      const res = await fetch("/api/sprints", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (res.ok) {
        setDone(true);
        setTimeout(() => {
          setDone(false);
          setFeedback("");
          onClose();
        }, 1200);
      }
    } catch (e) {
      console.error(`${mode} failed:`, e);
    } finally {
      setProcessing(false);
    }
  };

  const toolLabel = (tool || "project tool").toUpperCase();

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-50 bg-black/50"
        onClick={onClose}
      />

      {/* Dialog */}
      <div
        className={cn(
          "fixed top-1/2 left-1/2 z-50 -translate-x-1/2 -translate-y-1/2",
          "w-full max-w-md rounded-lg border border-[var(--border-subtle)]",
          "bg-[var(--bg-surface)] shadow-xl p-6"
        )}
      >
        {done ? (
          <div className="flex flex-col items-center gap-3 py-6">
            <CheckCircle2
              className={cn(
                "h-10 w-10",
                mode === "approve"
                  ? "text-[var(--color-rag-green)]"
                  : "text-[var(--color-rag-amber)]"
              )}
            />
            <p className="text-sm font-semibold text-[var(--text-primary)]">
              {mode === "approve" ? "Plan Approved!" : "Plan Rejected"}
            </p>
          </div>
        ) : mode === "approve" ? (
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              <CheckCircle2 className="h-5 w-5 text-[var(--color-rag-green)]" />
              <h3 className="text-sm font-semibold text-[var(--text-primary)]">
                Approve &amp; Sync
              </h3>
            </div>
            <p className="text-sm text-[var(--text-secondary)]">
              Approve and post AI recommendations for{" "}
              <span className="font-semibold text-[var(--text-primary)]">
                {totalSP ?? 0} SP
              </span>{" "}
              across{" "}
              <span className="font-semibold text-[var(--text-primary)]">
                {estimatedSprints ?? 1} sprint{(estimatedSprints ?? 1) > 1 ? "s" : ""}
              </span>{" "}
              to {toolLabel}?
            </p>
            <p className="text-xs text-[var(--text-tertiary)]">
              AI recommendation comments will be posted to each work item. No fields will be modified.
            </p>
            <div className="flex items-center justify-end gap-2 pt-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={onClose}
                disabled={processing}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                size="sm"
                onClick={handleAction}
                disabled={processing}
              >
                {processing && (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                )}
                Approve &amp; Sync
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              <XCircle className="h-5 w-5 text-[var(--color-rag-red)]" />
              <h3 className="text-sm font-semibold text-[var(--text-primary)]">
                Reject Plan
              </h3>
            </div>
            <Textarea
              placeholder="Optional: feedback for the AI to improve the next plan..."
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              className="min-h-[80px]"
            />
            <div className="flex items-center justify-end gap-2 pt-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={onClose}
                disabled={processing}
              >
                Cancel
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={handleAction}
                disabled={processing}
              >
                {processing && (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                )}
                Reject
              </Button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
