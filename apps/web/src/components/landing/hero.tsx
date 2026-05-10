"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { ArrowRight, ChevronDown, CheckCircle2, GitPullRequest } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button, Badge } from "@/components/ui";

/* ──────────────────────────────────────────────
   Animation variants
   ────────────────────────────────────────────── */
const stagger = {
  hidden: {},
  visible: {
    transition: { staggerChildren: 0.12, delayChildren: 0.2 },
  },
};

const fadeSlideUp = {
  hidden: { opacity: 0, y: 30 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.6, ease: [0.22, 1, 0.36, 1] as const },
  },
};

const fadeSlideRight = {
  hidden: { opacity: 0, x: 60 },
  visible: {
    opacity: 1,
    x: 0,
    transition: { duration: 0.8, ease: [0.22, 1, 0.36, 1] as const, delay: 0.4 },
  },
};

/* ──────────────────────────────────────────────
   Ticket status config
   ────────────────────────────────────────────── */
const tickets = [
  { id: "AUTH-42", title: "OAuth token refresh", dev: "Sarah L.", points: 5, status: "done" as const },
  { id: "AUTH-43", title: "Login rate limiter", dev: "Mike R.", points: 3, status: "progress" as const },
  { id: "AUTH-44", title: "SSO callback handler", dev: "Alex K.", points: 8, status: "review" as const },
  { id: "AUTH-45", title: "Session timeout fix", dev: "Priya M.", points: 2, status: "todo" as const },
];

const statusColors: Record<string, string> = {
  done: "bg-[var(--color-rag-green)]",
  progress: "bg-[var(--color-brand-secondary)]",
  review: "bg-[var(--color-rag-amber)]",
  todo: "bg-[var(--text-secondary)]",
};

/* ──────────────────────────────────────────────
   Mini SVG sparkline
   ────────────────────────────────────────────── */
function VelocitySparkline() {
  const points = [12, 18, 15, 24, 22, 30, 28, 35];
  const w = 120;
  const h = 40;
  const max = Math.max(...points);
  const coords = points
    .map((p, i) => `${(i / (points.length - 1)) * w},${h - (p / max) * h}`)
    .join(" ");

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-full" fill="none">
      <defs>
        <linearGradient id="sparkGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--color-brand-secondary)" stopOpacity="0.3" />
          <stop offset="100%" stopColor="var(--color-brand-secondary)" stopOpacity="0" />
        </linearGradient>
      </defs>
      <polyline
        points={coords}
        stroke="var(--color-brand-secondary)"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <polygon
        points={`0,${h} ${coords} ${w},${h}`}
        fill="url(#sparkGrad)"
      />
    </svg>
  );
}

/* ──────────────────────────────────────────────
   Hero Component
   ────────────────────────────────────────────── */
export default function Hero() {
  const prefersReducedMotion = useReducedMotion();
  const containerRef = useRef<HTMLElement>(null);
  const [mouse, setMouse] = useState({ x: 0, y: 0 });

  /* Parallax mouse handler (desktop only) */
  const handleMouseMove = useCallback(
    (e: MouseEvent) => {
      if (prefersReducedMotion) return;
      const { innerWidth, innerHeight } = window;
      setMouse({
        x: (e.clientX / innerWidth - 0.5) * 2,
        y: (e.clientY / innerHeight - 0.5) * 2,
      });
    },
    [prefersReducedMotion]
  );

  useEffect(() => {
    const mql = window.matchMedia("(min-width: 1024px)");
    if (!mql.matches) return;

    window.addEventListener("mousemove", handleMouseMove);
    return () => window.removeEventListener("mousemove", handleMouseMove);
  }, [handleMouseMove]);

  /* Helper: parallax transform */
  const px = (strength: number) =>
    prefersReducedMotion
      ? {}
      : {
          transform: `translate(${mouse.x * strength}px, ${mouse.y * strength}px)`,
          transition: "transform 0.15s ease-out",
        };

  /* Progress bar width */
  const progressPercent = 62;

  return (
    <section
      ref={containerRef}
      className="relative min-h-screen flex items-center overflow-hidden pt-20"
    >
      {/* ── Background layers ── */}
      <div
        className="absolute inset-0 animate-gradient-mesh"
        style={{ background: "var(--gradient-hero)" }}
      />
      <div className="absolute inset-0 grid-pattern opacity-[0.04]" />

      {/* Soft glow orbs */}
      <div className="absolute top-1/4 left-1/4 w-[500px] h-[500px] rounded-full bg-[var(--color-brand-secondary)]/[0.06] blur-[120px] pointer-events-none" />
      <div className="absolute bottom-1/4 right-1/3 w-[400px] h-[400px] rounded-full bg-[var(--color-brand-accent)]/[0.04] blur-[100px] pointer-events-none" />

      {/* ── Main content ── */}
      <div className="relative z-10 w-full max-w-7xl mx-auto px-6 py-24 lg:pt-8 lg:pb-0">
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-12 lg:gap-8 items-center">
          {/* ════════════════════════════
             LEFT COLUMN — Text (3/5 = 60%)
             ════════════════════════════ */}
          <motion.div
            className="lg:col-span-3 flex flex-col gap-8"
            variants={stagger}
            initial="hidden"
            animate="visible"
          >
            {/* Badge chip */}
            <motion.div variants={fadeSlideUp}>
              <Badge variant="brand" className="text-sm gap-2">
                <span className="inline-block w-1.5 h-1.5 rounded-full bg-[var(--color-brand-secondary)] animate-pulse" />
                AI-Powered Sprint Planning
              </Badge>
            </motion.div>

            {/* H1 headline */}
            <motion.h1
              variants={fadeSlideUp}
              className="text-4xl sm:text-5xl lg:text-6xl xl:text-7xl font-extrabold tracking-tight leading-[1.08]"
            >
              Plan{" "}
              <span className="gradient-text">Smarter</span>.
              <br />
              Ship Without the Meetings.
            </motion.h1>

            {/* Sub-headline */}
            <motion.p
              variants={fadeSlideUp}
              className="text-lg lg:text-xl text-[var(--text-secondary)] max-w-lg leading-relaxed"
            >
              AI-powered sprint plans, standups, and retrospectives
              generated automatically from your Jira, GitHub, and real team data.
            </motion.p>

            {/* CTA row */}
            <motion.div
              variants={fadeSlideUp}
              className="flex flex-wrap items-center gap-4"
            >
              <Button size="lg" href="/signup">
                Start for Free <ArrowRight className="w-5 h-5" />
              </Button>
              <Button variant="ghost" size="lg" href="#how-it-works">
                See How It Works
              </Button>
            </motion.div>

            {/* Trust micro-copy */}
            <motion.div
              variants={fadeSlideUp}
              className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-[var(--text-secondary)]"
            >
              {[
                "No credit card required",
                "5-minute setup",
                "Works with Jira, ADO & GitHub",
              ].map((item) => (
                <span key={item} className="inline-flex items-center gap-1.5">
                  <CheckCircle2 className="w-4 h-4 text-[var(--color-rag-green)]" />
                  {item}
                </span>
              ))}
            </motion.div>
          </motion.div>

          {/* ════════════════════════════
             RIGHT COLUMN — Hero visual (2/5 = 40%)
             ════════════════════════════ */}
          <motion.div
            className="lg:col-span-2 relative w-full min-h-[420px] lg:min-h-[520px]"
            variants={fadeSlideRight}
            initial="hidden"
            animate="visible"
          >
            {/* ── 1. Central sprint-plan card ── */}
            <div
              className="absolute inset-x-0 top-16 mx-auto w-[320px] sm:w-[360px]"
              style={{
                ...px(8),
                perspective: "1000px",
              }}
            >
              <div
                className={cn(
                  "glass rounded-2xl p-5 shadow-2xl shadow-black/10",
                  "origin-center"
                )}
                style={{
                  transform: "rotateY(-15deg) rotateX(5deg)",
                }}
              >
                {/* Card header */}
                <div className="flex items-center justify-between mb-4">
                  <span className="text-xs font-bold tracking-wider uppercase text-[var(--color-brand-secondary)]">
                    Sprint 24 Plan
                  </span>
                  <span className="text-[10px] text-[var(--text-secondary)] font-mono">
                    Feb 17 – Mar 3
                  </span>
                </div>

                {/* Ticket rows */}
                <div className="space-y-2.5">
                  {tickets.map((t) => (
                    <div
                      key={t.id}
                      className="flex items-center gap-2.5 p-2 rounded-lg bg-[var(--bg-base)]/60"
                    >
                      <span
                        className={cn("w-2 h-2 rounded-full shrink-0", statusColors[t.status])}
                      />
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-semibold truncate">
                          {t.title}
                        </p>
                        <p className="text-[10px] text-[var(--text-secondary)]">
                          {t.dev}
                        </p>
                      </div>
                      <span className="shrink-0 text-[10px] font-bold text-[var(--color-brand-secondary)] bg-[var(--color-brand-secondary)]/10 px-1.5 py-0.5 rounded">
                        {t.points} SP
                      </span>
                    </div>
                  ))}
                </div>

                {/* Progress bar */}
                <div className="mt-4">
                  <div className="flex items-center justify-between text-[10px] text-[var(--text-secondary)] mb-1">
                    <span>Sprint Progress</span>
                    <span className="font-mono">{progressPercent}%</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-[var(--bg-surface-raised)] overflow-hidden">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-[var(--color-brand-secondary)] to-[var(--color-brand-primary)]"
                      style={{ width: `${progressPercent}%` }}
                    />
                  </div>
                </div>
              </div>
            </div>

            {/* ── 2. Standup card (upper right) ── */}
            <div
              className="absolute top-6 -right-2 sm:right-0 w-[200px] animate-float"
              style={{
                ...px(14),
                transform: `rotate(12deg) ${px(14).transform ?? ""}`,
              }}
            >
              <div className="glass rounded-xl p-3 shadow-lg shadow-black/5 text-[11px]">
                <span className="block text-[10px] font-bold text-[var(--color-brand-secondary)] mb-2 uppercase tracking-wider">
                  Today&rsquo;s Standup
                </span>
                <ul className="space-y-1.5 text-[var(--text-primary)]">
                  <li className="flex items-start gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-rag-green)] mt-1 shrink-0" />
                    <span>Merged OAuth PR</span>
                  </li>
                  <li className="flex items-start gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-brand-secondary)] mt-1 shrink-0" />
                    <span>In Progress: Auth Module</span>
                  </li>
                  <li className="flex items-start gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-rag-amber)] mt-1 shrink-0" />
                    <span>PR awaiting review</span>
                  </li>
                </ul>
              </div>
            </div>

            {/* ── 3. GitHub PR chip (lower left) ── */}
            <div
              className="absolute bottom-16 -left-4 sm:left-0 animate-float-delayed"
              style={px(18)}
            >
              <div className="glass rounded-xl px-3.5 py-2.5 flex items-center gap-2 shadow-lg shadow-black/5">
                <GitPullRequest className="w-3.5 h-3.5 text-[var(--color-brand-secondary)]" />
                <span className="text-xs font-semibold">PR #89</span>
                <span className="text-[10px] text-[var(--text-secondary)]">&middot;</span>
                <span className="flex items-center gap-1 text-[10px] text-[var(--color-rag-green)] font-medium">
                  <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-rag-green)]" />
                  CI Passing
                </span>
              </div>
            </div>

            {/* ── 4. Burnout alert chip (upper left, amber) ── */}
            <div
              className="absolute top-12 -left-6 sm:left-[-20px] animate-float-slow opacity-90 blur-[0.3px]"
              style={px(22)}
            >
              <div className="glass rounded-xl px-3 py-2 border-[var(--color-rag-amber)]/30 shadow-lg shadow-black/5">
                <span className="flex items-center gap-1.5 text-[11px] font-semibold text-[var(--color-rag-amber)]">
                  <span className="w-2 h-2 rounded-full bg-[var(--color-rag-amber)] animate-pulse" />
                  Alex: 3rd high-load sprint
                </span>
              </div>
            </div>

            {/* ── 5. Velocity sparkline (lower right) ── */}
            <div
              className="absolute bottom-4 right-2 sm:right-4 w-[160px] opacity-80 blur-[0.2px]"
              style={px(12)}
            >
              <div className="glass rounded-xl p-3 shadow-lg shadow-black/5">
                <span className="block text-[10px] font-bold text-[var(--text-secondary)] mb-1 uppercase tracking-wider">
                  Team Velocity
                </span>
                <div className="h-10">
                  <VelocitySparkline />
                </div>
                <span className="block text-right text-[10px] font-mono text-[var(--color-rag-green)] mt-1">
                  +18% this sprint
                </span>
              </div>
            </div>
          </motion.div>
        </div>
      </div>

      {/* ── Scroll indicator ── */}
      <motion.div
        className="absolute bottom-8 left-1/2 -translate-x-1/2 flex flex-col items-center gap-1"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 1.4, duration: 0.6 }}
      >
        <span className="text-xs text-[var(--text-secondary)]">Scroll</span>
        <ChevronDown className="w-5 h-5 text-[var(--text-secondary)] animate-bounce-subtle" />
      </motion.div>
    </section>
  );
}
