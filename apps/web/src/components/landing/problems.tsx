"use client";

import { useRef } from "react";
import { motion, useInView } from "framer-motion";
import {
  Clock,
  Drama,
  Flame,
  Ghost,
  Puzzle,
  TrendingDown,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { GlassCard, SectionLabel, SectionHeading } from "@/components/ui";

/* ──────────────────────────────────────────────
   Problem card data
   ────────────────────────────────────────────── */
const problems = [
  {
    icon: Clock,
    title: "Sprint Planning Takes Hours",
    body: "POs spend 3\u20135 hours per sprint manually reviewing backlogs and assigning tickets based on gut feel \u2014 not data.",
  },
  {
    icon: Drama,
    title: "Standups Are Just Theatre",
    body: "Every morning, developers report what\u2019s already in Jira and GitHub. The meeting exists because no tool synthesises it automatically.",
  },
  {
    icon: Flame,
    title: "Burnout Hides Until It\u2019s Too Late",
    body: "Overloading goes undetected until a developer disengages or leaves. No system flags the warning signs early.",
  },
  {
    icon: Ghost,
    title: "Progress is Invisible",
    body: "PRs stalled in review, CI failures, developers who haven\u2019t committed in days \u2014 none of this surfaces until the sprint is already at risk.",
  },
  {
    icon: Puzzle,
    title: "Signals Scattered Everywhere",
    body: "Critical info lives in Jira, GitHub, Slack, and email simultaneously. The right person never gets the right signal at the right time.",
  },
  {
    icon: TrendingDown,
    title: "Retrospectives Repeat Mistakes",
    body: "Post-sprint retros rely on memory. Teams repeat the same failures because there\u2019s no systematic analysis.",
  },
];

/* ──────────────────────────────────────────────
   Animation variants
   ────────────────────────────────────────────── */
const sectionVariants = {
  hidden: {},
  visible: {
    transition: { staggerChildren: 0.15, delayChildren: 0.15 },
  },
};

const cardVariant = {
  hidden: { opacity: 0, y: 40 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.55, ease: [0.22, 1, 0.36, 1] as const },
  },
};

const headingVariants = {
  hidden: { opacity: 0, y: 24 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.5, ease: [0.22, 1, 0.36, 1] as const },
  },
};

/* ──────────────────────────────────────────────
   Component
   ────────────────────────────────────────────── */
export default function Problems() {
  const sectionRef = useRef<HTMLElement>(null);
  const isInView = useInView(sectionRef, { once: true, margin: "-100px" });

  return (
    <section
      ref={sectionRef}
      className="relative py-24 lg:py-32 bg-[var(--bg-base)] overflow-hidden"
    >
      {/* Subtle top-glow accent */}
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[600px] h-[300px] rounded-full bg-[var(--color-brand-accent)]/[0.04] blur-[100px] pointer-events-none" />

      <div className="relative z-10 max-w-7xl mx-auto px-6">
        {/* ── Section header ── */}
        <motion.div
          className="flex flex-col items-center text-center gap-5 mb-16"
          variants={sectionVariants}
          initial="hidden"
          animate={isInView ? "visible" : "hidden"}
        >
          <motion.div variants={headingVariants}>
            <SectionLabel>The Problem</SectionLabel>
          </motion.div>

          <motion.div variants={headingVariants}>
            <SectionHeading className="max-w-3xl">
              Your team&rsquo;s best work is buried under meetings and manual&nbsp;updates.
            </SectionHeading>
          </motion.div>
        </motion.div>

        {/* ── Cards grid (desktop) / horizontal scroll (mobile) ── */}
        <motion.div
          variants={sectionVariants}
          initial="hidden"
          animate={isInView ? "visible" : "hidden"}
          className={cn(
            /* Mobile: horizontal scroll */
            "flex gap-5 overflow-x-auto pb-4 snap-x snap-mandatory scrollbar-none",
            "-mx-6 px-6",
            /* Desktop: 3-column grid */
            "lg:grid lg:grid-cols-3 lg:overflow-visible lg:mx-0 lg:px-0 lg:pb-0"
          )}
        >
          {problems.map((problem) => {
            const Icon = problem.icon;
            return (
              <motion.div
                key={problem.title}
                variants={cardVariant}
                className="snap-start shrink-0 w-[300px] sm:w-[320px] lg:w-auto"
              >
                <GlassCard
                  className="h-full flex flex-col gap-4 group"
                >
                  {/* Icon */}
                  <div
                    className={cn(
                      "w-11 h-11 rounded-xl flex items-center justify-center",
                      "bg-[var(--color-brand-accent)]/10",
                      "transition-colors duration-300 group-hover:bg-[var(--color-brand-accent)]/20"
                    )}
                  >
                    <Icon className="w-5 h-5 text-[var(--color-brand-accent)]" />
                  </div>

                  {/* Title */}
                  <h3 className="text-lg font-bold text-[var(--text-primary)]">
                    {problem.title}
                  </h3>

                  {/* Body */}
                  <p className="text-sm leading-relaxed text-[var(--text-secondary)]">
                    {problem.body}
                  </p>
                </GlassCard>
              </motion.div>
            );
          })}
        </motion.div>

        {/* ── Transition statement ── */}
        <motion.div
          className="mt-16 lg:mt-20 flex flex-col items-center text-center gap-4"
          initial={{ opacity: 0, y: 20 }}
          animate={isInView ? { opacity: 1, y: 0 } : {}}
          transition={{ delay: 1.1, duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
        >
          <p className="text-lg lg:text-xl font-semibold text-[var(--color-brand-accent)]">
            Plan2Sprint was built to eliminate every one of these&nbsp;problems.
          </p>
          <div className="w-48 h-px bg-gradient-to-r from-transparent via-[var(--color-brand-accent)]/40 to-transparent" />
        </motion.div>
      </div>
    </section>
  );
}
