"use client";

import { motion, AnimatePresence } from "framer-motion";
import { MessageSquare, X, Check, Info } from "lucide-react";
import { cn } from "@/lib/utils";

interface WritebackGuardProps {
  open: boolean;
  onClose: () => void;
  onApprove: () => void;
  tool: "jira" | "ado";
  itemId: string;
  itemTitle: string;
  loading?: boolean;
}

export function WritebackGuard({
  open,
  onClose,
  onApprove,
  tool,
  itemId,
  itemTitle,
  loading,
}: WritebackGuardProps) {
  const toolLabel = tool === "jira" ? "Jira" : "Azure DevOps";

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
            onClick={onClose}
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            className={cn(
              "fixed left-1/2 top-1/2 z-50 -translate-x-1/2 -translate-y-1/2",
              "w-[90vw] max-w-md",
              "rounded-2xl border border-[var(--border-subtle)]",
              "bg-[var(--bg-surface)]/95 backdrop-blur-xl shadow-2xl"
            )}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border-subtle)]">
              <div className="flex items-center gap-2">
                <MessageSquare size={18} className="text-[var(--color-brand-secondary)]" />
                <h2 className="text-base font-semibold text-[var(--text-primary)]">
                  Post AI Comment
                </h2>
              </div>
              <button
                onClick={onClose}
                className="flex h-8 w-8 items-center justify-center rounded-lg text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-surface-raised)] transition-colors cursor-pointer"
              >
                <X size={18} />
              </button>
            </div>

            {/* Content */}
            <div className="px-6 py-5 space-y-4">
              <div className="flex items-center gap-2">
                <Info size={14} className="text-[var(--color-brand-secondary)]" />
                <p className="text-xs text-[var(--text-secondary)]">
                  An AI recommendation comment will be posted to{" "}
                  <span className="font-medium text-[var(--text-primary)]">{itemId}</span>{" "}
                  in {toolLabel}.
                </p>
              </div>

              <p className="text-sm font-medium text-[var(--text-primary)]">{itemTitle}</p>

              {/* Info box */}
              <div className="rounded-lg border border-[var(--color-brand-secondary)]/20 bg-[var(--color-brand-secondary)]/5 px-4 py-3">
                <p className="text-xs text-[var(--text-secondary)]">
                  The comment will include sprint placement, story points, confidence score,
                  risk flags, and AI rationale. No fields on the work item will be modified.
                </p>
              </div>

              <p className="text-[11px] text-[var(--text-tertiary)]">
                This action will be logged in the audit trail.
              </p>
            </div>

            {/* Footer */}
            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-[var(--border-subtle)]">
              <button
                onClick={onClose}
                className="rounded-lg px-4 py-2 text-sm font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-surface-raised)] transition-colors cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={onApprove}
                disabled={loading}
                className={cn(
                  "flex items-center gap-2 rounded-lg px-4 py-2",
                  "text-sm font-medium text-white",
                  "bg-[var(--color-brand-secondary)] hover:bg-[var(--color-brand-secondary)]/90",
                  "transition-all cursor-pointer",
                  "disabled:opacity-50 disabled:cursor-not-allowed"
                )}
              >
                <Check size={14} />
                {loading ? "Posting..." : "Post Comment"}
              </button>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
