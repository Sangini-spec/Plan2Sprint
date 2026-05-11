"use client";

/**
 * PageHintCard — first-visit one-shot card.
 *
 * Pops up 600ms after a user lands on a page that has a registered hint
 * AND that the user hasn't dismissed before. Non-blocking — anchors to
 * the top-right of the viewport so the page remains interactive.
 */

import { motion, AnimatePresence } from "framer-motion";
import { Lightbulb, X } from "lucide-react";
import { useOnboarding } from "@/lib/onboarding/context";

export function PageHintCard() {
  const { activePageHint, dismissPageHint, startTour, progress } = useOnboarding();

  return (
    <AnimatePresence>
      {activePageHint && (
        <motion.div
          initial={{ opacity: 0, y: -8, scale: 0.96 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -8, scale: 0.96 }}
          transition={{ duration: 0.25, ease: "easeOut" }}
          className="onb-card fixed top-20 right-5 z-[93] w-80"
        >
          <div className="onb-card-header-stripe" />
          <div className="p-4 pt-4">
            <div className="flex items-start justify-between gap-3 mb-2">
              <div className="flex items-center gap-2">
                <Lightbulb
                  size={16}
                  style={{ color: "var(--onboarding-primary)" }}
                />
                <h4
                  className="text-sm font-semibold"
                  style={{ color: "var(--onboarding-card-text)" }}
                >
                  {activePageHint.title}
                </h4>
              </div>
              <button
                onClick={() => dismissPageHint()}
                className="shrink-0 text-[var(--onboarding-card-text-muted)] hover:text-[var(--onboarding-card-text)] transition-colors"
                aria-label="Dismiss hint"
              >
                <X size={14} />
              </button>
            </div>
            <p
              className="text-xs leading-relaxed mb-3 whitespace-pre-line"
              style={{ color: "var(--onboarding-card-text-muted)" }}
            >
              {activePageHint.body}
            </p>
            <div className="flex items-center justify-end gap-2">
              {progress?.status !== "completed" && (
                <button
                  onClick={async () => {
                    await dismissPageHint();
                    await startTour();
                  }}
                  className="onb-cta-secondary text-xs"
                  style={{ padding: "6px 12px" }}
                >
                  Take the full tour
                </button>
              )}
              <button
                onClick={() => dismissPageHint()}
                className="onb-cta text-xs"
                style={{ padding: "6px 14px" }}
              >
                Got it
              </button>
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
