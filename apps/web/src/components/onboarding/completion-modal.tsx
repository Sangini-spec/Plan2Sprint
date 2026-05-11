"use client";

/**
 * CompletionModal — confetti card shown after the last tour step.
 *
 * Pure-CSS confetti (Framer Motion + multiple coloured div particles)
 * so we don't pull in canvas-confetti as a dependency. Auto-closes
 * via the "Go to my dashboard" CTA which sets status=completed.
 */

import { motion } from "framer-motion";
import { PartyPopper, HelpCircle } from "lucide-react";
import { useOnboarding } from "@/lib/onboarding/context";

const CONFETTI_PARTICLES = Array.from({ length: 24 }, (_, i) => i);

const ROLE_COPY = {
  product_owner: {
    title: "You're all set",
    body:
      "You now know how to connect tools, import projects, plan sprints, watch GitHub, run standups, and post to Slack or Teams. Pages we didn't cover (Retro, Team Health) will pop a quick hint the first time you visit them.",
  },
  developer: {
    title: "You're all set",
    body:
      "You know where your sprint lives, how to submit a standup, and how to flag a blocker. Pages we didn't cover will pop a quick hint when you visit them.",
  },
  stakeholder: {
    title: "You're all set",
    body:
      "You know where to find portfolio health, predictability, and the weekly PDF. Pages we didn't cover will pop a quick hint when you visit them.",
  },
} as const;

export function CompletionModal() {
  const { progress, completeTour } = useOnboarding();
  if (!progress) return null;
  const copy = ROLE_COPY[progress.role];

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center onb-backdrop p-4">
      {/* Confetti layer — fires once on mount */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        {CONFETTI_PARTICLES.map((i) => {
          // Deterministic pseudo-random so SSR matches CSR
          const x = ((i * 37) % 100);
          const delay = ((i * 53) % 1000) / 1000;
          const duration = 1.6 + ((i * 17) % 800) / 1000;
          const colorIdx = i % 4;
          const colors = ["#a78bfa", "#5eead4", "#f9a8d4", "#fcd34d"];
          return (
            <motion.span
              key={i}
              initial={{ y: -40, x: `${x}%`, opacity: 0, rotate: 0 }}
              animate={{
                y: "100vh",
                opacity: [0, 1, 1, 0],
                rotate: 360 * 2,
              }}
              transition={{ duration, delay, ease: "easeIn" }}
              className="absolute top-0 block h-2 w-2 rounded-sm"
              style={{ background: colors[colorIdx] }}
            />
          );
        })}
      </div>

      <motion.div
        initial={{ opacity: 0, y: 12, scale: 0.96 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.3, ease: "easeOut" }}
        className="onb-card w-full max-w-md relative"
        role="dialog"
        aria-modal="true"
        aria-labelledby="onb-complete-title"
      >
        <div className="onb-card-header-stripe" />
        <div className="p-7 pt-8">
          <div className="flex justify-center mb-5">
            <div
              className="flex h-14 w-14 items-center justify-center rounded-full"
              style={{ background: "var(--onboarding-gradient-soft)" }}
            >
              <PartyPopper
                size={26}
                style={{ color: "var(--onboarding-primary)" }}
              />
            </div>
          </div>
          <h2
            id="onb-complete-title"
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
          <button
            onClick={() => completeTour()}
            className="onb-cta w-full"
            autoFocus
          >
            Go to my dashboard
          </button>
          <div
            className="flex items-center justify-center gap-1.5 mt-5 text-[11px]"
            style={{ color: "var(--onboarding-card-text-muted)" }}
          >
            <HelpCircle size={12} />
            <span>
              Replay this tour anytime from{" "}
              <span style={{ color: "var(--onboarding-primary)" }}>
                Settings → Help
              </span>
            </span>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
