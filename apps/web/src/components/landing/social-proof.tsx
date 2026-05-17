"use client";

import { useRef } from "react";
import { motion, useInView } from "framer-motion";
import { cn } from "@/lib/utils";
import { AnimatedCounter } from "@/components/ui";

/* ──────────────────────────────────────────────
   Company logos (placeholder text badges)
   ────────────────────────────────────────────── */
const companies = [
  "TechCorp",
  "DataFlow",
  "CloudScale",
  "DevOps Inc",
  "AgileStack",
  "SprintForge",
];

/* ──────────────────────────────────────────────
   Stat data
   ────────────────────────────────────────────── */
const stats = [
  { value: 12400, suffix: "+", label: "Standup meetings eliminated" },
  { value: 3800, suffix: "+", label: "Sprint plans auto-generated" },
  { value: 24, suffix: "hrs", label: "Hours saved per team per month" },
];

/* ──────────────────────────────────────────────
   Animation variants
   ────────────────────────────────────────────── */
const containerVariants = {
  hidden: {},
  visible: {
    transition: { staggerChildren: 0.08, delayChildren: 0.1 },
  },
};

const itemFade = {
  hidden: { opacity: 0, y: 16 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.5, ease: [0.22, 1, 0.36, 1] as const },
  },
};

/* ──────────────────────────────────────────────
   Component
   ────────────────────────────────────────────── */
export default function SocialProof() {
  const sectionRef = useRef<HTMLElement>(null);
  const isInView = useInView(sectionRef, { once: true, margin: "-80px" });

  return (
    <section
      ref={sectionRef}
      className="relative py-32 lg:py-40 overflow-hidden"
    >
      {/* Top divider hairline */}
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-[var(--border-subtle)] to-transparent" />
      {/* Bottom divider hairline */}
      <div className="absolute inset-x-0 bottom-0 h-px bg-gradient-to-r from-transparent via-[var(--border-subtle)] to-transparent" />

      {/* Theme-matching glow band */}
      <div
        className="pointer-events-none absolute inset-x-0 top-1/2 -translate-y-1/2 h-[360px] bg-gradient-to-r from-transparent via-[var(--color-brand-secondary)]/[0.05] to-transparent"
        aria-hidden="true"
      />
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[900px] h-[260px] rounded-full bg-[var(--color-brand-accent)]/[0.05] blur-[110px] pointer-events-none" />

      <div className="relative max-w-7xl mx-auto px-6">
        <motion.div
          variants={containerVariants}
          initial="hidden"
          animate={isInView ? "visible" : "hidden"}
          className="flex flex-col items-center gap-16 lg:gap-20"
        >
          {/* ── Headline ── */}
          <motion.p
            variants={itemFade}
            className="text-sm font-semibold tracking-[0.25em] text-[var(--text-secondary)] uppercase"
          >
            Trusted by engineering teams at
          </motion.p>

          {/* ── Logo row - single line, no chips ── */}
          <motion.div
            variants={containerVariants}
            className={cn(
              "flex flex-nowrap items-center justify-between",
              "gap-x-6 sm:gap-x-10 lg:gap-x-14",
              "w-full overflow-x-auto scrollbar-none py-4"
            )}
          >
            {companies.map((name) => (
              <motion.span
                key={name}
                variants={itemFade}
                className={cn(
                  "shrink-0 whitespace-nowrap select-none",
                  "text-lg sm:text-xl lg:text-2xl font-bold tracking-tight",
                  "text-[var(--text-secondary)]/60",
                  "transition-colors duration-300",
                  "hover:text-[var(--text-primary)]"
                )}
              >
                {name}
              </motion.span>
            ))}
          </motion.div>

          {/* ── Divider ── */}
          <div className="w-full max-w-xl h-px bg-gradient-to-r from-transparent via-[var(--border-subtle)] to-transparent" />

          {/* ── Stats row ── */}
          <motion.div
            variants={containerVariants}
            className="grid grid-cols-1 sm:grid-cols-3 gap-12 sm:gap-16 w-full max-w-4xl text-center"
          >
            {stats.map((stat) => (
              <motion.div
                key={stat.label}
                variants={itemFade}
                className="flex flex-col items-center gap-3"
              >
                <AnimatedCounter
                  target={stat.value}
                  suffix={stat.suffix}
                  duration={2.2}
                  className="text-5xl lg:text-6xl font-extrabold text-[var(--color-brand-secondary)]"
                />
                <span className="text-sm text-[var(--text-secondary)] max-w-[220px]">
                  {stat.label}
                </span>
              </motion.div>
            ))}
          </motion.div>
        </motion.div>
      </div>
    </section>
  );
}
