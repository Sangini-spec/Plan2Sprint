"use client";

/**
 * ChecklistWidget — floating bottom-right widget showing tour progress.
 *
 * Visible whenever the tour is active. Click a row to jump to that step.
 * Collapsible — collapsed state shows just a chip with progress.
 */

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Check, ChevronDown, ChevronUp, Target } from "lucide-react";
import { useOnboarding } from "@/lib/onboarding/context";

export function ChecklistWidget() {
  const {
    progress,
    allSteps,
    currentStepIndex,
    isActive,
    jumpToStep,
  } = useOnboarding();
  const [open, setOpen] = useState(true);

  if (!isActive || !progress) return null;
  if (allSteps.length === 0) return null;

  // Hide on the welcome step (the welcome modal is the focus instead).
  if (currentStepIndex === 0) return null;

  // Only count user-visible spotlight steps. The welcome row is
  // already auto-marked-completed when the user clicks "Take the
  // tour", which would otherwise inflate the progress count.
  const spotlightStepIds = new Set(
    allSteps.filter((s) => s.variant === "spotlight").map((s) => s.id),
  );
  const completed = progress.completed_steps.filter((id) =>
    spotlightStepIds.has(id),
  ).length;
  const skipped = progress.skipped_steps.filter((id) =>
    spotlightStepIds.has(id),
  ).length;
  const total = spotlightStepIds.size;
  const pct = Math.min(100, Math.round(((completed + skipped) / total) * 100));

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="fixed bottom-5 right-5 z-[94] onb-card"
      style={{ width: open ? 280 : 180 }}
    >
      <div className="onb-card-header-stripe" />
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full px-4 py-3 flex items-center justify-between gap-2"
      >
        <div className="flex items-center gap-2 min-w-0">
          <Target
            size={16}
            style={{ color: "var(--onboarding-primary)" }}
          />
          <span
            className="text-sm font-semibold truncate"
            style={{ color: "var(--onboarding-card-text)" }}
          >
            Getting started
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span
            className="text-xs font-medium"
            style={{ color: "var(--onboarding-card-text-muted)" }}
          >
            {completed + skipped}/{total}
          </span>
          {open ? (
            <ChevronDown size={14} style={{ color: "var(--onboarding-card-text-muted)" }} />
          ) : (
            <ChevronUp size={14} style={{ color: "var(--onboarding-card-text-muted)" }} />
          )}
        </div>
      </button>

      {/* Progress bar */}
      <div className="px-4 pb-2">
        <div
          className="h-1 rounded-full overflow-hidden"
          style={{ background: "var(--bg-surface-raised)" }}
        >
          <motion.div
            className="h-full rounded-full"
            style={{ background: "var(--onboarding-gradient)" }}
            animate={{ width: `${pct}%` }}
            transition={{ duration: 0.3 }}
          />
        </div>
      </div>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden border-t"
            style={{ borderColor: "var(--border-subtle)" }}
          >
            <ul className="max-h-72 overflow-y-auto py-1">
              {allSteps.map((step, idx) => {
                // Skip the welcome and completion bookends — they're
                // not actionable rows the user can navigate to.
                if (step.variant !== "spotlight") return null;
                const isCompleted = progress.completed_steps.includes(step.id);
                const isSkipped = progress.skipped_steps.includes(step.id);
                const isCurrent = idx === currentStepIndex;
                return (
                  <li key={step.id}>
                    <button
                      onClick={() => jumpToStep(step.id)}
                      className="w-full px-4 py-2 flex items-center gap-2.5 text-left hover:bg-[var(--bg-surface-raised)] transition-colors"
                    >
                      <span
                        className="flex h-5 w-5 items-center justify-center rounded-full shrink-0"
                        style={{
                          background: isCompleted
                            ? "var(--onboarding-accent)"
                            : isCurrent
                            ? "var(--onboarding-primary)"
                            : "transparent",
                          border: !isCompleted && !isCurrent
                            ? `1.5px solid var(--border-subtle)`
                            : "none",
                        }}
                      >
                        {isCompleted ? (
                          <Check size={12} color="white" strokeWidth={3} />
                        ) : isCurrent ? (
                          <span className="block h-1.5 w-1.5 rounded-full bg-white" />
                        ) : null}
                      </span>
                      <span
                        className="text-xs flex-1 truncate"
                        style={{
                          color: isCurrent
                            ? "var(--onboarding-card-text)"
                            : "var(--onboarding-card-text-muted)",
                          fontWeight: isCurrent ? 600 : 400,
                          textDecoration: isSkipped ? "line-through" : undefined,
                        }}
                      >
                        {step.title}
                      </span>
                      {isSkipped && (
                        <span className="text-[10px] uppercase tracking-wider text-[var(--text-secondary)]">
                          Skipped
                        </span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
