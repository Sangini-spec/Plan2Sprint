"use client";

import { useRef } from "react";
import {
  motion,
  useInView,
  type Variants,
} from "framer-motion";
import {
  Zap,
  GitBranch,
  Shield,
  Flame,
  RefreshCw,
  MessageSquare,
  BarChart3,
  Brain,
  Pencil,
  Search,
  Calendar,
  CheckCircle2,
  ArrowRight,
  GitPullRequest,
  CircleDot,
  AlertTriangle,
  Clock,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  GlassCard,
  Badge,
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

const slideInLeft: Variants = {
  hidden: { opacity: 0, x: -60 },
  visible: {
    opacity: 1,
    x: 0,
    transition: { duration: 0.7, ease: "easeOut" },
  },
};

const slideInRight: Variants = {
  hidden: { opacity: 0, x: 60 },
  visible: {
    opacity: 1,
    x: 0,
    transition: { duration: 0.7, ease: "easeOut" },
  },
};

const staggerContainer: Variants = {
  hidden: {},
  visible: {
    transition: { staggerChildren: 0.1 },
  },
};

/* ==========================================================================
   Animated Section Wrapper
   ========================================================================== */

function AnimatedSection({
  children,
  className,
  variants = fadeUp,
}: {
  children: React.ReactNode;
  className?: string;
  variants?: Variants;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-80px" });

  return (
    <motion.div
      ref={ref}
      initial="hidden"
      animate={isInView ? "visible" : "hidden"}
      variants={variants}
      className={className}
    >
      {children}
    </motion.div>
  );
}

/* ==========================================================================
   Bullet List Component
   ========================================================================== */

function BulletList({ items }: { items: string[] }) {
  return (
    <ul className="space-y-3 mt-6">
      {items.map((item) => (
        <li key={item} className="flex items-start gap-3">
          <CheckCircle2 className="w-5 h-5 text-[var(--color-brand-secondary)] shrink-0 mt-0.5" />
          <span className="text-[var(--text-secondary)] text-sm leading-relaxed">
            {item}
          </span>
        </li>
      ))}
    </ul>
  );
}

/* ==========================================================================
   Mock Visual: Sprint Plan Card
   ========================================================================== */

function SprintPlanMock() {
  const tickets = [
    {
      id: "P2S-142",
      title: "Auth token refresh flow",
      dev: "Sarah K.",
      sp: 5,
      color: "var(--color-brand-secondary)",
    },
    {
      id: "P2S-138",
      title: "Dashboard chart filters",
      dev: "Marcus T.",
      sp: 3,
      color: "var(--color-rag-green)",
    },
    {
      id: "P2S-151",
      title: "API rate limiter middleware",
      dev: "Priya D.",
      sp: 8,
      color: "var(--color-brand-accent)",
    },
    {
      id: "P2S-147",
      title: "Notification preferences UI",
      dev: "Jake L.",
      sp: 3,
      color: "var(--color-brand-secondary)",
    },
    {
      id: "P2S-155",
      title: "CI pipeline caching",
      dev: "Sarah K.",
      sp: 2,
      color: "var(--color-rag-green)",
    },
  ];

  return (
    <div className="relative">
      {/* Glow behind card */}
      <div className="absolute -inset-4 bg-[var(--color-brand-secondary)]/10 rounded-3xl blur-2xl" />
      <div
        className={cn(
          "relative glass rounded-2xl p-5 max-w-md",
          "transform rotate-1 hover:rotate-0 transition-transform duration-500"
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div>
            <p className="text-xs font-bold uppercase tracking-wider text-[var(--color-brand-secondary)]">
              Sprint 24
            </p>
            <p className="text-lg font-bold text-[var(--text-primary)] mt-0.5">
              AI-Generated Plan
            </p>
          </div>
          <Badge variant="rag-green">
            <Zap className="w-3 h-3" />
            Auto
          </Badge>
        </div>

        {/* Stats row */}
        <div className="flex gap-4 mb-4 text-xs text-[var(--text-secondary)]">
          <span>
            <strong className="text-[var(--text-primary)]">21</strong> SP
          </span>
          <span>
            <strong className="text-[var(--text-primary)]">5</strong> tickets
          </span>
          <span>
            <strong className="text-[var(--text-primary)]">3</strong> devs
          </span>
        </div>

        {/* Ticket list */}
        <div className="space-y-2">
          {tickets.map((ticket) => (
            <div
              key={ticket.id}
              className={cn(
                "flex items-center justify-between gap-3 p-2.5 rounded-lg",
                "bg-[var(--bg-surface-raised)]/60 border border-[var(--border-subtle)]"
              )}
            >
              <div className="flex items-center gap-2.5 min-w-0">
                <div
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{ backgroundColor: ticket.color }}
                />
                <div className="min-w-0">
                  <p className="text-xs font-semibold text-[var(--text-primary)] truncate">
                    {ticket.title}
                  </p>
                  <p className="text-[10px] text-[var(--text-secondary)]">
                    {ticket.id} &middot; {ticket.dev}
                  </p>
                </div>
              </div>
              <span
                className={cn(
                  "shrink-0 text-[10px] font-bold px-2 py-0.5 rounded-full",
                  "bg-[var(--color-brand-secondary)]/10 text-[var(--color-brand-secondary)]"
                )}
              >
                {ticket.sp} SP
              </span>
            </div>
          ))}
        </div>

        {/* AI rationale preview */}
        <div className="mt-4 p-3 rounded-lg bg-[var(--color-brand-secondary)]/5 border border-[var(--color-brand-secondary)]/15">
          <p className="text-[10px] font-semibold text-[var(--color-brand-secondary)] uppercase tracking-wider mb-1">
            AI Rationale
          </p>
          <p className="text-[11px] text-[var(--text-secondary)] leading-relaxed">
            Sarah has capacity for 7 SP and auth expertise. Marcus is best suited
            for front-end filter work.
          </p>
        </div>
      </div>
    </div>
  );
}

/* ==========================================================================
   Mock Visual: Slack Standup Card
   ========================================================================== */

function SlackStandupMock() {
  return (
    <div className="relative">
      <div className="absolute -inset-4 bg-[var(--color-brand-accent)]/10 rounded-3xl blur-2xl" />
      <div
        className={cn(
          "relative glass rounded-2xl p-5 max-w-md",
          "transform -rotate-1 hover:rotate-0 transition-transform duration-500"
        )}
      >
        {/* Slack header */}
        <div className="flex items-center gap-3 mb-4 pb-3 border-b border-[var(--border-subtle)]">
          <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-[var(--color-brand-secondary)] to-[var(--color-brand-primary)] flex items-center justify-center">
            <Zap className="w-4 h-4 text-white" />
          </div>
          <div>
            <p className="text-sm font-bold text-[var(--text-primary)]">
              Plan2Sprint
            </p>
            <p className="text-[10px] text-[var(--text-secondary)]">
              #eng-standups &middot; 9:00 AM
            </p>
          </div>
        </div>

        {/* Standup content */}
        <div className="space-y-4">
          {/* Completed */}
          <div>
            <div className="flex items-center gap-2 mb-2">
              <CheckCircle2 className="w-4 h-4 text-[var(--color-rag-green)]" />
              <p className="text-xs font-bold text-[var(--color-rag-green)] uppercase tracking-wider">
                Completed
              </p>
            </div>
            <div className="space-y-1.5 pl-6">
              <p className="text-xs text-[var(--text-secondary)]">
                <span className="font-medium text-[var(--text-primary)]">P2S-142</span>{" "}
                Auth token refresh flow &mdash; merged to main
              </p>
              <p className="text-xs text-[var(--text-secondary)]">
                <span className="font-medium text-[var(--text-primary)]">P2S-138</span>{" "}
                Dashboard chart filters &mdash; PR approved
              </p>
            </div>
          </div>

          {/* In Progress */}
          <div>
            <div className="flex items-center gap-2 mb-2">
              <Clock className="w-4 h-4 text-[var(--color-brand-secondary)]" />
              <p className="text-xs font-bold text-[var(--color-brand-secondary)] uppercase tracking-wider">
                In Progress
              </p>
            </div>
            <div className="space-y-1.5 pl-6">
              <p className="text-xs text-[var(--text-secondary)]">
                <span className="font-medium text-[var(--text-primary)]">P2S-151</span>{" "}
                API rate limiter &mdash; 3 commits, 2 files changed
              </p>
            </div>
          </div>

          {/* Blockers */}
          <div>
            <div className="flex items-center gap-2 mb-2">
              <AlertTriangle className="w-4 h-4 text-[var(--color-rag-red)]" />
              <p className="text-xs font-bold text-[var(--color-rag-red)] uppercase tracking-wider">
                Blockers
              </p>
            </div>
            <div className="pl-6">
              <p className="text-xs text-[var(--text-secondary)]">
                <span className="font-medium text-[var(--text-primary)]">P2S-147</span>{" "}
                Waiting on design review &mdash;{" "}
                <span className="text-[var(--color-rag-amber)]">2 days</span>
              </p>
            </div>
          </div>
        </div>

        {/* Flag blocker button */}
        <div className="mt-4 pt-3 border-t border-[var(--border-subtle)] flex items-center gap-2">
          <button className="text-[10px] font-semibold px-3 py-1.5 rounded-lg bg-[var(--color-rag-red)]/10 text-[var(--color-rag-red)] border border-[var(--color-rag-red)]/20 hover:bg-[var(--color-rag-red)]/20 transition-colors cursor-pointer">
            Flag Blocker
          </button>
          <button className="text-[10px] font-semibold px-3 py-1.5 rounded-lg bg-[var(--bg-surface-raised)] text-[var(--text-secondary)] border border-[var(--border-subtle)] hover:bg-[var(--bg-surface-raised)]/80 transition-colors cursor-pointer">
            View Full Report
          </button>
        </div>
      </div>
    </div>
  );
}

/* ==========================================================================
   Mock Visual: GitHub Monitoring Panel
   ========================================================================== */

function GitHubMonitorMock() {
  const prs = [
    {
      title: "feat: token refresh logic",
      number: 287,
      status: "merged",
      author: "sarah-k",
      checks: "passed",
      reviewLag: null,
    },
    {
      title: "fix: chart filter reset",
      number: 291,
      status: "open",
      author: "marcus-t",
      checks: "passed",
      reviewLag: "4h",
    },
    {
      title: "feat: rate limiter middleware",
      number: 294,
      status: "draft",
      author: "priya-d",
      checks: "running",
      reviewLag: null,
    },
    {
      title: "chore: bump deps",
      number: 296,
      status: "open",
      author: "jake-l",
      checks: "failed",
      reviewLag: "2d",
    },
  ];

  const statusConfig: Record<string, { label: string; className: string }> = {
    merged: {
      label: "Merged",
      className:
        "bg-purple-500/10 text-purple-400 border-purple-500/20",
    },
    open: {
      label: "Open",
      className:
        "bg-[var(--color-rag-green)]/10 text-[var(--color-rag-green)] border-[var(--color-rag-green)]/20",
    },
    draft: {
      label: "Draft",
      className:
        "bg-[var(--text-secondary)]/10 text-[var(--text-secondary)] border-[var(--text-secondary)]/20",
    },
  };

  const checkConfig: Record<string, { label: string; className: string }> = {
    passed: {
      label: "CI Passed",
      className: "text-[var(--color-rag-green)]",
    },
    running: {
      label: "CI Running",
      className: "text-[var(--color-rag-amber)]",
    },
    failed: {
      label: "CI Failed",
      className: "text-[var(--color-rag-red)]",
    },
  };

  return (
    <div className="relative">
      <div className="absolute -inset-4 bg-[var(--color-brand-primary)]/10 rounded-3xl blur-2xl" />
      <div
        className={cn(
          "relative glass rounded-2xl p-5 max-w-md",
          "transform rotate-1 hover:rotate-0 transition-transform duration-500"
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <GitBranch className="w-4 h-4 text-[var(--text-primary)]" />
            <p className="text-sm font-bold text-[var(--text-primary)]">
              GitHub Activity
            </p>
          </div>
          <span className="text-[10px] text-[var(--text-secondary)]">
            plan2sprint/api
          </span>
        </div>

        {/* PR list */}
        <div className="space-y-2">
          {prs.map((pr) => (
            <div
              key={pr.number}
              className={cn(
                "p-2.5 rounded-lg",
                "bg-[var(--bg-surface-raised)]/60 border border-[var(--border-subtle)]"
              )}
            >
              <div className="flex items-start justify-between gap-2 mb-1.5">
                <div className="flex items-center gap-2 min-w-0">
                  <GitPullRequest className="w-3.5 h-3.5 text-[var(--text-secondary)] shrink-0" />
                  <p className="text-xs font-semibold text-[var(--text-primary)] truncate">
                    {pr.title}
                  </p>
                </div>
                <span
                  className={cn(
                    "shrink-0 text-[10px] font-bold px-2 py-0.5 rounded-full border",
                    statusConfig[pr.status].className
                  )}
                >
                  {statusConfig[pr.status].label}
                </span>
              </div>
              <div className="flex items-center gap-3 pl-5.5 text-[10px] text-[var(--text-secondary)]">
                <span>#{pr.number}</span>
                <span>{pr.author}</span>
                <span className={checkConfig[pr.checks].className}>
                  <CircleDot className="w-3 h-3 inline mr-0.5" />
                  {checkConfig[pr.checks].label}
                </span>
                {pr.reviewLag && (
                  <span className="text-[var(--color-rag-amber)]">
                    Review lag: {pr.reviewLag}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Summary stats */}
        <div className="mt-4 flex gap-4 text-[10px] text-[var(--text-secondary)]">
          <span>
            <strong className="text-[var(--text-primary)]">12</strong> commits
            today
          </span>
          <span>
            <strong className="text-[var(--text-primary)]">4</strong> open PRs
          </span>
          <span>
            <strong className="text-[var(--color-rag-amber)]">1</strong> stalled
          </span>
        </div>
      </div>
    </div>
  );
}

/* ==========================================================================
   Feature Spotlight Row
   ========================================================================== */

interface SpotlightRowProps {
  eyebrow: string;
  headline: string;
  body: string;
  bullets: string[];
  ctaText: string;
  ctaHref: string;
  visual: React.ReactNode;
  reversed?: boolean;
}

function SpotlightRow({
  eyebrow,
  headline,
  body,
  bullets,
  ctaText,
  ctaHref,
  visual,
  reversed = false,
}: SpotlightRowProps) {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-80px" });

  return (
    <div
      ref={ref}
      className={cn(
        "grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-20 items-center",
        "py-16 lg:py-24"
      )}
    >
      {/* Text side */}
      <motion.div
        initial="hidden"
        animate={isInView ? "visible" : "hidden"}
        variants={reversed ? slideInRight : slideInLeft}
        className={cn(reversed && "lg:order-2")}
      >
        <Badge variant="brand" className="mb-4">
          <Zap className="w-3 h-3" />
          {eyebrow}
        </Badge>
        <h3 className="text-2xl sm:text-3xl lg:text-4xl font-bold text-[var(--text-primary)] leading-tight mt-3">
          {headline}
        </h3>
        <p className="text-[var(--text-secondary)] leading-relaxed mt-4 max-w-lg">
          {body}
        </p>
        <BulletList items={bullets} />
        <a
          href={ctaHref}
          className="inline-flex items-center gap-2 mt-6 text-sm font-semibold text-[var(--color-brand-secondary)] hover:text-[var(--color-brand-secondary)]/80 transition-colors group"
        >
          {ctaText}
          <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
        </a>
      </motion.div>

      {/* Visual side */}
      <motion.div
        initial="hidden"
        animate={isInView ? "visible" : "hidden"}
        variants={reversed ? slideInLeft : slideInRight}
        className={cn(
          "flex justify-center",
          reversed && "lg:order-1"
        )}
      >
        {visual}
      </motion.div>
    </div>
  );
}

/* ==========================================================================
   Feature Grid Card Data
   ========================================================================== */

const featureCards = [
  {
    icon: Shield,
    title: "Human-in-the-Loop Always",
    description:
      "Every AI plan requires explicit approval. Edit assignments, adjust story points, or override rationale before a single ticket moves.",
  },
  {
    icon: Flame,
    title: "Burnout Detection",
    description:
      "Track overtime patterns, consecutive high-load sprints, and weekend commits. Get early warnings before burnout hits your team.",
  },
  {
    icon: RefreshCw,
    title: "AI Retrospectives",
    description:
      "Auto-generated sprint retrospectives powered by real delivery data. See what actually happened, not what people remember.",
  },
  {
    icon: MessageSquare,
    title: "Slack & Teams Native",
    description:
      "Standups, blockers, and sprint digests delivered where your team already works. No new app to install or check.",
  },
  {
    icon: BarChart3,
    title: "Role-Based Dashboards",
    description:
      "Product owners see sprint health. Developers see their assignments. Managers see team load. Everyone gets the right view.",
  },
  {
    icon: Brain,
    title: "Learns Every Sprint",
    description:
      "Plan2Sprint refines its model each sprint based on actuals vs. estimates, improving accuracy with every iteration.",
  },
  {
    icon: Pencil,
    title: "Scoped Write-Back",
    description:
      "Write-back is limited to ticket status and sprint assignment. No repo access, no code changes, no destructive operations.",
  },
  {
    icon: Search,
    title: "Backlog Health Scoring",
    description:
      "AI scores your backlog on completeness, priority clarity, and estimation quality. Surface grooming debt before it stalls planning.",
  },
  {
    icon: Calendar,
    title: "Capacity-Aware Planning",
    description:
      "Factor in PTO, holidays, part-time allocations, and focus-time blocks. Plans that reflect reality, not just velocity averages.",
  },
];

/* ==========================================================================
   Feature Grid
   ========================================================================== */

function FeatureGrid() {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-80px" });

  return (
    <motion.div
      ref={ref}
      initial="hidden"
      animate={isInView ? "visible" : "hidden"}
      variants={staggerContainer}
      className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5"
    >
      {featureCards.map((card) => {
        const Icon = card.icon;
        return (
          <motion.div key={card.title} variants={fadeUp}>
            <GlassCard className="h-full">
              <div className="flex flex-col h-full">
                <div className="w-10 h-10 rounded-xl bg-[var(--color-brand-secondary)]/10 flex items-center justify-center mb-4">
                  <Icon className="w-5 h-5 text-[var(--color-brand-secondary)]" />
                </div>
                <h4 className="text-base font-bold text-[var(--text-primary)] mb-2">
                  {card.title}
                </h4>
                <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
                  {card.description}
                </p>
              </div>
            </GlassCard>
          </motion.div>
        );
      })}
    </motion.div>
  );
}

/* ==========================================================================
   Features Section (Export)
   ========================================================================== */

export default function Features() {
  return (
    <section
      id="features"
      className="relative py-24 lg:py-32 overflow-hidden"
    >
      {/* Background glow */}
      <div className="absolute top-0 left-1/4 w-[600px] h-[600px] bg-[var(--color-brand-secondary)]/5 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute bottom-0 right-1/4 w-[400px] h-[400px] bg-[var(--color-brand-accent)]/5 rounded-full blur-3xl pointer-events-none" />

      <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* Section Header */}
        <AnimatedSection className="text-center mb-16 lg:mb-20">
          <SectionLabel>FEATURES</SectionLabel>
          <SectionHeading className="mt-4">
            Everything your team needs.
            <br />
            <span className="gradient-text">Nothing it doesn&apos;t.</span>
          </SectionHeading>
        </AnimatedSection>

        {/* Spotlight Row 1: AI Sprint Generation */}
        <SpotlightRow
          eyebrow="AI Sprint Planning"
          headline="A complete sprint plan in under 90 seconds."
          body="Plan2Sprint reads your entire backlog, analyzes team velocity and individual skill profiles, then generates a capacity-aware sprint plan complete with assignments and rationale. No spreadsheets. No guesswork. Just a plan your team can review, edit, and approve."
          bullets={[
            "Velocity-based assignment",
            "Skill-affinity matching",
            "Dependency ordering",
            "Sprint goal alignment",
            "Per-assignment AI rationale",
          ]}
          ctaText="See it in action"
          ctaHref="#demo"
          visual={<SprintPlanMock />}
        />

        {/* Divider */}
        <div className="w-full h-px bg-gradient-to-r from-transparent via-[var(--border-subtle)] to-transparent" />

        {/* Spotlight Row 2: Async Standup Engine (reversed) */}
        <SpotlightRow
          reversed
          eyebrow="Async Standup Engine"
          headline="No more daily standup meetings. Ever."
          body="The Activity Engine monitors GitHub commits, PR activity, and Jira ticket transitions 24/7. Every weekday morning, it compiles a per-developer standup report generated entirely from real work data and delivers it straight to Slack or Teams."
          bullets={[
            "Generated from real data",
            "Delivered in Slack/Teams",
            "Flag blockers with one tap",
            "Zero weekend reports",
            "Team digest for PO",
          ]}
          ctaText="See it in action"
          ctaHref="#demo"
          visual={<SlackStandupMock />}
        />

        {/* Divider */}
        <div className="w-full h-px bg-gradient-to-r from-transparent via-[var(--border-subtle)] to-transparent" />

        {/* Spotlight Row 3: GitHub Monitoring */}
        <SpotlightRow
          eyebrow="GitHub Development Monitoring"
          headline="See actual progress — not just ticket status."
          body="Pull request status, CI/CD results, commit velocity, and review lag are surfaced inline on the PO Dashboard. Know exactly where development stands without asking a single developer or opening GitHub."
          bullets={[
            "Auto-link PRs to tickets",
            "Review lag detection",
            "CI/CD status per PR",
            "Stalled ticket detection",
            "Read-only — zero write access",
          ]}
          ctaText="See it in action"
          ctaHref="#demo"
          visual={<GitHubMonitorMock />}
        />

        {/* Divider before grid */}
        <div className="w-full h-px bg-gradient-to-r from-transparent via-[var(--border-subtle)] to-transparent my-16 lg:my-20" />

        {/* Feature Grid Header */}
        <AnimatedSection className="text-center mb-12">
          <SectionHeading as="h3" className="text-2xl sm:text-3xl">
            And so much more built in.
          </SectionHeading>
          <p className="text-[var(--text-secondary)] mt-4 max-w-2xl mx-auto">
            Every feature is designed to reduce ceremony and surface the signal
            your team needs to ship confidently.
          </p>
        </AnimatedSection>

        {/* Feature Grid */}
        <FeatureGrid />
      </div>
    </section>
  );
}
