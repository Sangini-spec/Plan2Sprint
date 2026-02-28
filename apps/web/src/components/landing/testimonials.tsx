"use client";

import { useRef } from "react";
import { motion, useInView } from "framer-motion";
import { Star } from "lucide-react";
import { cn } from "@/lib/utils";
import { GlassCard, SectionLabel, SectionHeading } from "@/components/ui";

/* -------------------------------------------------------------------------- */
/*  Data                                                                       */
/* -------------------------------------------------------------------------- */

interface Testimonial {
  quote: string;
  name: string;
  role: string;
  company: string;
}

const testimonials: Testimonial[] = [
  {
    quote:
      "We cancelled our daily standup meeting in Week 1. The async reports from Plan2Sprint were more detailed, more honest, and nobody had to sit through 25 minutes of status updates at 9 AM. Our team hasn\u2019t looked back.",
    name: "Jordan K.",
    role: "Product Owner",
    company: "Series B SaaS",
  },
  {
    quote:
      "The burnout detection caught something I completely missed. One of my senior engineers was quietly overloaded across three workstreams. Plan2Sprint flagged it before it became a retention problem. That feature alone justifies the cost.",
    name: "Priya M.",
    role: "Engineering Manager",
    company: "FinTech",
  },
  {
    quote:
      "I was skeptical about AI touching our sprint planning. But the rationale it provides for every assignment\u2014skill match, capacity, past velocity\u2014made it feel less like a black box and more like a very thorough data analyst on the team.",
    name: "Marcus T.",
    role: "CTO",
    company: "60-person org",
  },
  {
    quote:
      "The Slack integration is perfect. My standups show up in the channel at 9:15 AM, formatted cleanly, with blockers highlighted. I write my update once in 30 seconds and move on with my day. It\u2019s exactly how async should work.",
    name: "Lena W.",
    role: "Senior Developer",
    company: "DevOps Platform",
  },
];

/* -------------------------------------------------------------------------- */
/*  Animation variants                                                         */
/* -------------------------------------------------------------------------- */

const containerVariants = {
  hidden: {},
  visible: {
    transition: {
      staggerChildren: 0.12,
    },
  },
};

const cardVariants = {
  hidden: { opacity: 0, y: 32, scale: 0.97 },
  visible: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: {
      duration: 0.6,
      ease: [0.25, 0.46, 0.45, 0.94] as const,
    },
  },
};

/* -------------------------------------------------------------------------- */
/*  Stars Component                                                            */
/* -------------------------------------------------------------------------- */

function StarRating() {
  return (
    <div className="flex gap-1">
      {Array.from({ length: 5 }).map((_, i) => (
        <Star
          key={i}
          className="h-4 w-4 fill-[var(--color-brand-secondary)] text-[var(--color-brand-secondary)]"
        />
      ))}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Testimonial Card                                                           */
/* -------------------------------------------------------------------------- */

function TestimonialCard({ testimonial }: { testimonial: Testimonial }) {
  return (
    <motion.div variants={cardVariants}>
      <GlassCard
        gradient
        className="relative h-full flex flex-col"
      >
        {/* Stars */}
        <StarRating />

        {/* Quote */}
        <blockquote className="mt-5 flex-1">
          <p className="text-sm italic leading-relaxed text-[var(--text-secondary)]">
            &ldquo;{testimonial.quote}&rdquo;
          </p>
        </blockquote>

        {/* Author */}
        <div className="mt-6 pt-4 border-t border-[var(--border-subtle)]">
          <p className="text-sm font-semibold text-[var(--text-primary)]">
            {testimonial.name}
          </p>
          <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
            {testimonial.role}, {testimonial.company}
          </p>
        </div>
      </GlassCard>
    </motion.div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Section                                                                    */
/* -------------------------------------------------------------------------- */

export default function TestimonialsSection() {
  const sectionRef = useRef<HTMLElement>(null);
  const isInView = useInView(sectionRef, { once: true, margin: "-100px" });

  return (
    <section
      id="testimonials"
      ref={sectionRef}
      className="relative py-24 sm:py-32 overflow-hidden"
    >
      {/* Background glow */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{ background: "var(--gradient-glow)" }}
        aria-hidden="true"
      />

      <div className="relative mx-auto max-w-7xl px-6 lg:px-8">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={isInView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6, ease: "easeOut" }}
          className="mx-auto max-w-2xl text-center"
        >
          <SectionLabel>TESTIMONIALS</SectionLabel>
          <SectionHeading className="mt-2">
            Loved by teams who ship.
          </SectionHeading>
        </motion.div>

        {/* Testimonial grid */}
        <motion.div
          variants={containerVariants}
          initial="hidden"
          animate={isInView ? "visible" : "hidden"}
          className={cn(
            "mt-16 grid gap-8",
            "grid-cols-1 md:grid-cols-2"
          )}
        >
          {testimonials.map((testimonial) => (
            <TestimonialCard
              key={testimonial.name}
              testimonial={testimonial}
            />
          ))}
        </motion.div>
      </div>
    </section>
  );
}
