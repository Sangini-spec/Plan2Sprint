"use client";

import { useRef } from "react";
import { motion, useInView } from "framer-motion";
import { cn } from "@/lib/utils";
import { Badge, SectionLabel, SectionHeading } from "@/components/ui";

/* -------------------------------------------------------------------------- */
/*  Data                                                                       */
/* -------------------------------------------------------------------------- */

const values = [
  "Human-first AI",
  "Minimal write access",
  "No weekend reports",
  "Full transparency",
  "Async by default",
  "Works with your tools",
];

/* -------------------------------------------------------------------------- */
/*  Animation variants                                                         */
/* -------------------------------------------------------------------------- */

const containerVariants = {
  hidden: {},
  visible: {
    transition: {
      staggerChildren: 0.06,
    },
  },
};

const chipVariants = {
  hidden: { opacity: 0, scale: 0.85 },
  visible: {
    opacity: 1,
    scale: 1,
    transition: { duration: 0.4, ease: [0.25, 0.46, 0.45, 0.94] as const },
  },
};

/* -------------------------------------------------------------------------- */
/*  Abstract Visual Placeholder                                                */
/* -------------------------------------------------------------------------- */

function AbstractVisual() {
  return (
    <div className="relative h-full min-h-[360px] w-full rounded-2xl overflow-hidden">
      {/* Base gradient */}
      <div
        className={cn(
          "absolute inset-0",
          "bg-gradient-to-br from-[var(--color-brand-primary)]/20 via-[var(--color-brand-secondary)]/10 to-[var(--color-brand-accent)]/15"
        )}
      />

      {/* Grid pattern */}
      <div className="absolute inset-0 grid-pattern opacity-60" />

      {/* Floating orbs */}
      <div
        className={cn(
          "absolute top-1/4 left-1/4 h-32 w-32 rounded-full",
          "bg-[var(--color-brand-secondary)]/15 blur-2xl",
          "animate-float"
        )}
      />
      <div
        className={cn(
          "absolute bottom-1/3 right-1/4 h-24 w-24 rounded-full",
          "bg-[var(--color-brand-accent)]/15 blur-2xl",
          "animate-float-delayed"
        )}
      />
      <div
        className={cn(
          "absolute top-1/2 right-1/3 h-20 w-20 rounded-full",
          "bg-[var(--color-brand-primary)]/20 blur-xl",
          "animate-float-slow"
        )}
      />

      {/* Glass overlay card */}
      <div
        className={cn(
          "absolute inset-0 flex items-center justify-center"
        )}
      >
        <div
          className={cn(
            "glass rounded-2xl p-8 text-center max-w-[240px]",
            "backdrop-blur-xl"
          )}
        >
          <div className="text-5xl font-extrabold gradient-text mb-2">P2S</div>
          <p className="text-xs font-medium text-[var(--text-secondary)] uppercase tracking-widest">
            Built by engineers,
            <br />
            for engineers
          </p>
        </div>
      </div>

      {/* Border */}
      <div
        className={cn(
          "absolute inset-0 rounded-2xl",
          "border border-[var(--border-subtle)]"
        )}
      />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Section                                                                    */
/* -------------------------------------------------------------------------- */

export default function AboutSection() {
  const sectionRef = useRef<HTMLElement>(null);
  const isInView = useInView(sectionRef, { once: true, margin: "-100px" });

  return (
    <section
      id="about"
      ref={sectionRef}
      className="relative py-24 sm:py-32 overflow-hidden"
    >
      <div className="relative mx-auto max-w-7xl px-6 lg:px-8">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={isInView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6, ease: "easeOut" }}
          className="mx-auto max-w-2xl text-center mb-16"
        >
          <SectionLabel>ABOUT</SectionLabel>
          <SectionHeading className="mt-2">
            We built the tool we always wished existed.
          </SectionHeading>
        </motion.div>

        {/* Two-column layout */}
        <div className="grid gap-12 lg:grid-cols-2 lg:gap-16 items-center">
          {/* Left: Story paragraphs */}
          <motion.div
            initial={{ opacity: 0, x: -30 }}
            animate={isInView ? { opacity: 1, x: 0 } : {}}
            transition={{ duration: 0.7, ease: "easeOut", delay: 0.15 }}
            className="space-y-6"
          >
            <p className="text-base leading-relaxed text-[var(--text-secondary)]">
              Plan2Sprint was born from a shared frustration: teams drowning in
              ceremony. Endless standups, planning marathons, retros built on
              memory.
            </p>

            <p className="text-base leading-relaxed text-[var(--text-secondary)]">
              We didn&rsquo;t want another surveillance dashboard or a black-box
              AI. We built an overlay that reads your existing tools, surfaces
              the signal, and writes back only what&rsquo;s necessary. Every
              decision is explainable. Every action is reversible. Weekends are
              sacred.
            </p>
          </motion.div>

          {/* Right: Abstract visual */}
          <motion.div
            initial={{ opacity: 0, x: 30 }}
            animate={isInView ? { opacity: 1, x: 0 } : {}}
            transition={{ duration: 0.7, ease: "easeOut", delay: 0.3 }}
          >
            <AbstractVisual />
          </motion.div>
        </div>

        {/* Values chips row */}
        <motion.div
          variants={containerVariants}
          initial="hidden"
          animate={isInView ? "visible" : "hidden"}
          className="mt-16 flex flex-wrap items-center justify-center gap-3"
        >
          {values.map((value) => (
            <motion.div key={value} variants={chipVariants}>
              <Badge
                variant="brand"
                className={cn(
                  "px-5 py-2 text-sm font-medium",
                  "hover:bg-[var(--color-brand-secondary)]/15 transition-colors duration-200"
                )}
              >
                {value}
              </Badge>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </section>
  );
}
