"use client";

/**
 * ReplayBanner — dismissible top banner for existing users (those who
 * created their account before onboarding shipped).
 *
 * Hidden when:
 *  - User has already started the tour (status != not_started)
 *  - User has dismissed the banner
 *  - User would see the welcome modal instead (status = not_started AND
 *    !banner_dismissed AND the modal-trigger-route check passes — but
 *    the modal is preferred for brand-new users; the banner is for
 *    users who somehow ended up at status=dismissed without taking
 *    the tour)
 *
 * Per the design doc, this banner currently only appears for
 * status=dismissed users who haven't dismissed the banner.
 */

import { motion, AnimatePresence } from "framer-motion";
// Compass replaces the generic Sparkles glyph for the onboarding
// replay strip — see welcome-modal.tsx for rationale.
import { Compass, X } from "lucide-react";
import { useOnboarding } from "@/lib/onboarding/context";

export function ReplayBanner() {
  const { progress, replay, dismissBanner } = useOnboarding();

  const show =
    !!progress &&
    progress.status === "dismissed" &&
    !progress.banner_dismissed;

  return (
    <AnimatePresence>
      {show && (
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.2 }}
          className="border-b"
          style={{
            background: "var(--onboarding-gradient-soft)",
            borderColor: "var(--border-subtle)",
          }}
        >
          <div className="mx-auto max-w-[1600px] px-4 sm:px-5 lg:px-6 py-2.5 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 min-w-0">
              <Compass
                size={14}
                strokeWidth={1.9}
                style={{ color: "var(--onboarding-primary)" }}
              />
              <span
                className="text-sm font-medium truncate"
                style={{ color: "var(--onboarding-card-text)" }}
              >
                <span className="hidden sm:inline">New: a quick product tour.</span>
                <span className="sm:hidden">Product tour.</span>
                <span
                  className="ml-1"
                  style={{ color: "var(--onboarding-card-text-muted)" }}
                >
                  Want to take it?
                </span>
              </span>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={() => replay()}
                className="onb-cta text-xs"
                style={{ padding: "6px 14px" }}
              >
                Take the tour
              </button>
              <button
                onClick={() => dismissBanner()}
                className="text-[var(--onboarding-card-text-muted)] hover:text-[var(--onboarding-card-text)] transition-colors p-1"
                aria-label="Dismiss banner"
              >
                <X size={14} />
              </button>
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
