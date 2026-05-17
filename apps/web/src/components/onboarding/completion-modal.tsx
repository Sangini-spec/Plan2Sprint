"use client";

/**
 * CompletionModal - confetti card shown after the last tour step.
 *
 * Small corner-burst confetti - ~14 particles fan outward from the
 * top-right of the viewport in a quick "bang" rather than raining
 * down across the entire page. Fires once on mount and is done in
 * about 1.4 seconds.
 */

import { motion } from "framer-motion";
import { PartyPopper, HelpCircle } from "lucide-react";
import { useOnboarding } from "@/lib/onboarding/context";

const NUM_PARTICLES = 14;
const PARTICLE_COLORS = ["#a78bfa", "#5eead4", "#f9a8d4", "#fcd34d"];

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
      {/* Confetti - small burst fanning outward from the top-right
          viewport corner. Each particle gets a unique outward
          trajectory via polar coordinates so the cluster looks like
          a quick "bang" rather than a uniform rain. */}
      <div
        className="pointer-events-none absolute"
        style={{ top: 28, right: 28, width: 0, height: 0 }}
      >
        {Array.from({ length: NUM_PARTICLES }).map((_, i) => {
          // Deterministic pseudo-random so SSR matches CSR.
          // Angle spans 180° → 270° (i.e. down-left quadrant from
          // the top-right corner) so particles fan into the page,
          // not off-screen.
          const angle =
            Math.PI + (i / (NUM_PARTICLES - 1)) * (Math.PI / 2);
          const distance = 70 + ((i * 19) % 50); // 70–120 px
          const dx = Math.cos(angle) * distance;
          const dy = Math.sin(angle) * distance;
          const duration = 1.0 + ((i * 13) % 500) / 1000; // 1.0–1.5s
          const delay = ((i * 7) % 200) / 1000;            // 0–0.2s
          return (
            <motion.span
              key={i}
              initial={{ opacity: 0, x: 0, y: 0, scale: 0.6, rotate: 0 }}
              animate={{
                opacity: [0, 1, 1, 0],
                x: dx,
                y: dy,
                scale: 1,
                rotate: 360,
              }}
              transition={{ duration, delay, ease: "easeOut" }}
              className="absolute block"
              style={{
                width: 6,
                height: 6,
                borderRadius: 1.5,
                background: PARTICLE_COLORS[i % PARTICLE_COLORS.length],
              }}
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
