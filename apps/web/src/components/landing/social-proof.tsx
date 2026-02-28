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
      className="relative py-20 bg-[var(--bg-surface-raised)]"
    >
      <div className="max-w-6xl mx-auto px-6">
        <motion.div
          variants={containerVariants}
          initial="hidden"
          animate={isInView ? "visible" : "hidden"}
          className="flex flex-col items-center gap-12"
        >
          {/* ── Headline ── */}
          <motion.p
            variants={itemFade}
            className="text-sm font-medium tracking-wide text-[var(--text-secondary)] uppercase"
          >
            Trusted by engineering teams at
          </motion.p>

          {/* ── Logo row ── */}
          <motion.div
            variants={containerVariants}
            className="flex flex-wrap items-center justify-center gap-x-10 gap-y-6"
          >
            {companies.map((name) => (
              <motion.div
                key={name}
                variants={itemFade}
                className={cn(
                  "px-5 py-2.5 rounded-lg",
                  "text-base font-bold tracking-tight",
                  "text-[var(--text-secondary)]/50 select-none",
                  "transition-all duration-300",
                  "hover:text-[var(--text-primary)] hover:opacity-100",
                  "opacity-50 grayscale hover:grayscale-0"
                )}
              >
                <span className="bg-[var(--bg-surface)] border border-[var(--border-subtle)] px-5 py-2.5 rounded-lg inline-block">
                  {name}
                </span>
              </motion.div>
            ))}
          </motion.div>

          {/* ── Divider ── */}
          <div className="w-full max-w-md h-px bg-gradient-to-r from-transparent via-[var(--border-subtle)] to-transparent" />

          {/* ── Stats row ── */}
          <motion.div
            variants={containerVariants}
            className="grid grid-cols-1 sm:grid-cols-3 gap-8 sm:gap-12 w-full max-w-3xl text-center"
          >
            {stats.map((stat) => (
              <motion.div
                key={stat.label}
                variants={itemFade}
                className="flex flex-col items-center gap-2"
              >
                <AnimatedCounter
                  target={stat.value}
                  suffix={stat.suffix}
                  duration={2.2}
                  className="text-4xl lg:text-5xl font-extrabold text-[var(--color-brand-secondary)]"
                />
                <span className="text-sm text-[var(--text-secondary)] max-w-[200px]">
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
