"use client";

import { useRef } from "react";
import {
  motion,
  useInView,
  type Variants,
} from "framer-motion";
import {
  Plug,
  MessageSquare,
  Bot,
  Clock,
  Coffee,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  GlassCard,
  SectionLabel,
  SectionHeading,
} from "@/components/ui";

/* ==========================================================================
   Animation Variants
   ========================================================================== */

const fadeUp: Variants = {
  hidden: { opacity: 0, y: 40 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.6, ease: "easeOut" },
  },
};

const staggerContainer: Variants = {
  hidden: {},
  visible: {
    transition: { staggerChildren: 0.2 },
  },
};

const stepVariant: Variants = {
  hidden: { opacity: 0, y: 30, scale: 0.95 },
  visible: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { duration: 0.5, ease: "easeOut" },
  },
};

/* ==========================================================================
   Step Data
   ========================================================================== */

const steps = [
  {
    icon: Plug,
    number: 1,
    title: "Connect Your Tools",
    description:
      "OAuth-connect Jira or Azure DevOps, then GitHub. Backlog syncs in minutes.",
  },
  {
    icon: MessageSquare,
    number: 2,
    title: "Set Up Slack or Teams",
    description:
      "Install the Plan2Sprint app in your workspace. Map users. Configure channels.",
  },
  {
    icon: Bot,
    number: 3,
    title: "Generate Your First AI Plan",
    description:
      "Click Generate. Review AI assignments and rationale. Edit if needed. Approve.",
  },
  {
    icon: Clock,
    number: 4,
    title: "Set Your Standup Time",
    description:
      "Pick a weekday delivery time and timezone. Plan2Sprint takes it from there.",
  },
  {
    icon: Coffee,
    number: 5,
    title: "Cancel the Standup Meeting",
    description:
      "Every weekday morning, your team gets their standup report. The meeting is gone.",
  },
];

/* ==========================================================================
   Animated Connecting Line (SVG)
   ========================================================================== */

function ConnectingLineSVG({ isInView }: { isInView: boolean }) {
  return (
    <svg
      className="absolute top-6 left-0 w-full h-0.5 hidden lg:block"
      style={{ zIndex: 0 }}
      preserveAspectRatio="none"
    >
      <line
        x1="10%"
        y1="50%"
        x2="90%"
        y2="50%"
        stroke="var(--color-brand-secondary)"
        strokeWidth="2"
        strokeDasharray="8 6"
        strokeOpacity={0.3}
        className={cn(
          "transition-all duration-[2000ms] ease-out",
          isInView ? "opacity-100" : "opacity-0"
        )}
        style={{
          strokeDashoffset: isInView ? 0 : 1000,
          transition:
            "stroke-dashoffset 2s ease-out, opacity 0.5s ease-out",
        }}
      />
    </svg>
  );
}

/* ==========================================================================
   Vertical Connecting Line for Mobile
   ========================================================================== */

function VerticalLine({ isInView }: { isInView: boolean }) {
  return (
    <div className="lg:hidden absolute left-6 top-14 bottom-14 w-px overflow-hidden">
      <motion.div
        className="w-full bg-gradient-to-b from-[var(--color-brand-secondary)]/40 via-[var(--color-brand-secondary)]/20 to-[var(--color-brand-secondary)]/40"
        style={{
          backgroundSize: "1px 12px",
          backgroundImage:
            "repeating-linear-gradient(to bottom, var(--color-brand-secondary) 0px, var(--color-brand-secondary) 6px, transparent 6px, transparent 12px)",
        }}
        initial={{ height: "0%" }}
        animate={isInView ? { height: "100%" } : { height: "0%" }}
        transition={{ duration: 2, ease: "easeOut" }}
      />
    </div>
  );
}

/* ==========================================================================
   Step Card
   ========================================================================== */

function StepCard({
  step,
  index,
}: {
  step: (typeof steps)[number];
  index: number;
}) {
  const Icon = step.icon;

  return (
    <motion.div variants={stepVariant} className="relative flex flex-col items-center text-center">
      {/* Numbered circle */}
      <div className="relative z-10 mb-4">
        <div
          className={cn(
            "w-12 h-12 rounded-full flex items-center justify-center",
            "bg-gradient-to-br from-[var(--color-brand-secondary)] to-[var(--color-brand-primary)]",
            "shadow-lg shadow-[var(--color-brand-secondary)]/25",
            "text-white font-bold text-sm"
          )}
        >
          {step.number}
        </div>
        {/* Icon below number */}
        <div
          className={cn(
            "absolute -bottom-1 -right-1 w-6 h-6 rounded-full flex items-center justify-center",
            "bg-[var(--bg-surface)] border border-[var(--border-subtle)]",
            "shadow-sm"
          )}
        >
          <Icon className="w-3 h-3 text-[var(--color-brand-secondary)]" />
        </div>
      </div>

      {/* Text */}
      <h4 className="text-base font-bold text-[var(--text-primary)] mb-2">
        {step.title}
      </h4>
      <p className="text-sm text-[var(--text-secondary)] leading-relaxed max-w-[200px]">
        {step.description}
      </p>
    </motion.div>
  );
}

/* ==========================================================================
   Mobile Step Card (Horizontal layout)
   ========================================================================== */

function MobileStepCard({
  step,
}: {
  step: (typeof steps)[number];
}) {
  const Icon = step.icon;

  return (
    <motion.div variants={stepVariant} className="relative flex items-start gap-4 pl-2">
      {/* Numbered circle */}
      <div className="relative z-10 shrink-0">
        <div
          className={cn(
            "w-12 h-12 rounded-full flex items-center justify-center",
            "bg-gradient-to-br from-[var(--color-brand-secondary)] to-[var(--color-brand-primary)]",
            "shadow-lg shadow-[var(--color-brand-secondary)]/25",
            "text-white font-bold text-sm"
          )}
        >
          {step.number}
        </div>
        <div
          className={cn(
            "absolute -bottom-1 -right-1 w-6 h-6 rounded-full flex items-center justify-center",
            "bg-[var(--bg-surface)] border border-[var(--border-subtle)]",
            "shadow-sm"
          )}
        >
          <Icon className="w-3 h-3 text-[var(--color-brand-secondary)]" />
        </div>
      </div>

      {/* Text */}
      <div className="pt-1">
        <h4 className="text-base font-bold text-[var(--text-primary)] mb-1">
          {step.title}
        </h4>
        <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
          {step.description}
        </p>
      </div>
    </motion.div>
  );
}

/* ==========================================================================
   Testimonial Quote
   ========================================================================== */

function TestimonialQuote() {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-60px" });

  return (
    <motion.div
      ref={ref}
      initial="hidden"
      animate={isInView ? "visible" : "hidden"}
      variants={fadeUp}
      className="mt-20 lg:mt-28 max-w-3xl mx-auto"
    >
      <div
        className={cn(
          "glass rounded-2xl p-8 lg:p-10",
          "border-l-4 border-l-[var(--color-brand-accent)]"
        )}
      >
        <blockquote>
          <p className="text-lg lg:text-xl font-medium text-[var(--text-primary)] leading-relaxed italic">
            &ldquo;We cancelled our daily standup in Week 1. The team got 30
            minutes back every single day.&rdquo;
          </p>
          <footer className="mt-6 flex items-center gap-4">
            {/* Avatar placeholder */}
            <div className="w-10 h-10 rounded-full bg-gradient-to-br from-[var(--color-brand-accent)] to-[var(--color-brand-primary)] flex items-center justify-center text-white font-bold text-sm">
              EM
            </div>
            <div>
              <p className="text-sm font-semibold text-[var(--text-primary)]">
                Engineering Manager
              </p>
              <p className="text-xs text-[var(--text-secondary)]">
                Series B SaaS Company
              </p>
            </div>
          </footer>
        </blockquote>
      </div>
    </motion.div>
  );
}

/* ==========================================================================
   How It Works Section (Export)
   ========================================================================== */

export default function HowItWorks() {
  const timelineRef = useRef<HTMLDivElement>(null);
  const isInView = useInView(timelineRef, { once: true, margin: "-80px" });

  return (
    <section
      id="how-it-works"
      className="relative py-24 lg:py-32 overflow-hidden"
    >
      {/* Background glow */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[400px] bg-[var(--color-brand-secondary)]/5 rounded-full blur-3xl pointer-events-none" />

      <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* Section Header */}
        <motion.div
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-80px" }}
          variants={fadeUp}
          className="text-center mb-16 lg:mb-20"
        >
          <SectionLabel>HOW IT WORKS</SectionLabel>
          <SectionHeading className="mt-4">
            From setup to standup-free
            <br />
            <span className="gradient-text">in under 20 minutes.</span>
          </SectionHeading>
        </motion.div>

        {/* Desktop Timeline (horizontal) */}
        <div
          ref={timelineRef}
          className="hidden lg:block relative"
        >
          {/* Connecting line */}
          <ConnectingLineSVG isInView={isInView} />

          <motion.div
            initial="hidden"
            animate={isInView ? "visible" : "hidden"}
            variants={staggerContainer}
            className="relative grid grid-cols-5 gap-6"
          >
            {steps.map((step, index) => (
              <StepCard key={step.number} step={step} index={index} />
            ))}
          </motion.div>
        </div>

        {/* Mobile Timeline (vertical) */}
        <div className="lg:hidden relative">
          <VerticalLine isInView={isInView} />

          <motion.div
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, margin: "-80px" }}
            variants={staggerContainer}
            className="relative space-y-10"
          >
            {steps.map((step) => (
              <MobileStepCard key={step.number} step={step} />
            ))}
          </motion.div>
        </div>

        {/* Testimonial */}
        <TestimonialQuote />
      </div>
    </section>
  );
}
