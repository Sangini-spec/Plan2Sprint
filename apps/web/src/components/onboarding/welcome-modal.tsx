"use client";

/**
 * WelcomeModal — first card a user sees.
 *
 * Big centered modal with backdrop. Two CTAs:
 *   - "Take the tour" → starts the spotlight tour
 *   - "Skip — I'll explore on my own" → marks status=dismissed
 *
 * Per design: text-only (no video). Tour automatically begins on
 * the user's dashboard route after they click "Take the tour".
 */

import { motion } from "framer-motion";
// Compass over Sparkles for the onboarding hero — the sparkle look
// reads as the generic "AI vibe-coded" badge that every starter
// landing page ships with. A compass signals "guided tour /
// orientation", which is what the welcome modal actually is, and
// matches the iconography Stripe Docs / Vercel / Linear use for
// their walkthrough sections. (Sparkles is still used elsewhere
// in the app for *AI-generated content* actions like "Generate
// Sprint Plan", which is the appropriate use of that glyph.)
import { Compass } from "lucide-react";
import { useOnboarding } from "@/lib/onboarding/context";

const ROLE_COPY = {
  product_owner: {
    title: "Welcome to Plan2Sprint",
    body:
      "You're the captain. We'll walk you through how to connect your project tool, import projects, invite your team, run sprint planning, and orchestrate Slack or Microsoft Teams — about 4 minutes.",
  },
  developer: {
    title: "Welcome, Developer",
    body:
      "Plan2Sprint pulls your tickets, PRs, and commits into one workspace so you never have to type a standup again. Quick 90-second tour of the essentials.",
  },
  stakeholder: {
    title: "Welcome, Stakeholder",
    body:
      "You get a read-only view across the portfolio — no edits required. A 60-second tour will show you where the signals live.",
  },
} as const;

export function WelcomeModal() {
  const { progress, startTour, skipTour } = useOnboarding();
  if (!progress) return null;
  const copy = ROLE_COPY[progress.role];

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center onb-backdrop p-4">
      <motion.div
        initial={{ opacity: 0, y: 12, scale: 0.96 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.25, ease: "easeOut" }}
        className="onb-card w-full max-w-md"
        role="dialog"
        aria-modal="true"
        aria-labelledby="onb-welcome-title"
      >
        <div className="onb-card-header-stripe" />
        <div className="p-7 pt-8">
          <div className="flex justify-center mb-5">
            <div
              className="flex h-14 w-14 items-center justify-center rounded-full"
              style={{ background: "var(--onboarding-gradient-soft)" }}
            >
              <Compass
                size={26}
                strokeWidth={1.75}
                style={{ color: "var(--onboarding-primary)" }}
              />
            </div>
          </div>
          <h2
            id="onb-welcome-title"
            className="text-xl font-bold text-center mb-3"
            style={{ color: "var(--onboarding-card-text)" }}
          >
            {copy.title}
          </h2>
          <p
            className="text-sm text-center leading-relaxed mb-7"
            style={{ color: "var(--onboarding-card-text-muted)" }}
          >
            {copy.body}
          </p>
          <div className="flex flex-col gap-2">
            <button
              onClick={() => startTour()}
              className="onb-cta w-full"
              autoFocus
            >
              Take the tour →
            </button>
            <button
              onClick={() => skipTour()}
              className="onb-cta-secondary w-full"
            >
              Skip — I&apos;ll explore on my own
            </button>
          </div>
          <p
            className="text-[11px] text-center mt-5"
            style={{ color: "var(--onboarding-card-text-muted)" }}
          >
            You can replay this tour anytime from{" "}
            <span style={{ color: "var(--onboarding-primary)" }}>
              Settings → Help
            </span>
            .
          </p>
        </div>
      </motion.div>
    </div>
  );
}
