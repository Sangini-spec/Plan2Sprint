"use client";

import { useState, useRef } from "react";
import {
  motion,
  AnimatePresence,
  useInView,
  type Variants,
} from "framer-motion";
import {
  Target,
  Code2,
  Building2,
  CheckCircle2,
  Zap,
  GitPullRequest,
  Clock,
  TrendingUp,
  Eye,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
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

const tabContentVariants: Variants = {
  initial: { opacity: 0, x: 20, scale: 0.98 },
  animate: {
    opacity: 1,
    x: 0,
    scale: 1,
    transition: { duration: 0.4, ease: "easeOut" },
  },
  exit: {
    opacity: 0,
    x: -20,
    scale: 0.98,
    transition: { duration: 0.25, ease: "easeIn" },
  },
};

/* ==========================================================================
   Tab Data
   ========================================================================== */

interface TabData {
  id: string;
  label: string;
  icon: React.ElementType;
  headline: string;
  body: string;
  capabilities: string[];
  dashboardLabel: string;
}

const tabs: TabData[] = [
  {
    id: "product-owners",
    label: "Product Owners",
    icon: Target,
    headline: "Stop planning sprints manually. Start approving them.",
    body: "Read backlog, analyse capacity, generate a sprint plan in under 90 seconds. Approve in 5 minutes.",
    capabilities: [
      "AI sprint plan in under 90 seconds",
      "Inline editing of assignments and story points",
      "Daily standup digest from real data",
      "AI retrospectives at sprint end",
    ],
    dashboardLabel: "PO Dashboard",
  },
  {
    id: "developers",
    label: "Developers",
    icon: Code2,
    headline: "Your standup is ready before you open Slack.",
    body: "Standups auto-compiled from your commits, PRs, and ticket activity. Flag blockers with one tap.",
    capabilities: [
      "Auto-standup from GitHub + Jira activity",
      "One-tap blocker flagging in Slack/Teams",
      "Clear assignments with AI rationale",
      "Zero manual status updates",
    ],
    dashboardLabel: "Developer View",
  },
  {
    id: "stakeholders",
    label: "Stakeholders",
    icon: Building2,
    headline: "Delivery health across teams. No meetings required.",
    body: "See sprint progress, team health, and delivery risk in one view. The signals that matter (velocity, blockers, burnout) without scheduling a sync.",
    capabilities: [
      "Cross-team delivery health dashboard",
      "Sprint completion and velocity tracking",
      "Blocker frequency and resolution metrics",
      "Zero meeting overhead. Everything async",
    ],
    dashboardLabel: "Stakeholder Dashboard",
  },
];

/* ==========================================================================
   Capability List
   ========================================================================== */

function CapabilityList({ items }: { items: string[] }) {
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
   Dashboard Visual Placeholder
   ========================================================================== */

function DashboardVisual({ label, tabId }: { label: string; tabId: string }) {
  // Different mock elements depending on the tab
  const mockContent: Record<string, React.ReactNode> = {
    "product-owners": (
      <div className="space-y-3">
        {/* Sprint overview row */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Zap className="w-4 h-4 text-[var(--color-brand-secondary)]" />
            <span className="text-xs font-semibold text-[var(--text-primary)]">
              Sprint 24
            </span>
          </div>
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-[var(--color-rag-green)]/10 text-[var(--color-rag-green)] font-semibold">
            On Track
          </span>
        </div>
        {/* Progress bar */}
        <div className="space-y-1.5">
          <div className="flex justify-between text-[10px] text-[var(--text-secondary)]">
            <span>Progress</span>
            <span>68%</span>
          </div>
          <div className="w-full h-2 rounded-full bg-[var(--bg-surface-raised)]">
            <div className="h-full w-[68%] rounded-full bg-gradient-to-r from-[var(--color-brand-secondary)] to-[var(--color-brand-primary)]" />
          </div>
        </div>
        {/* Mini ticket list */}
        <div className="space-y-1.5 mt-3">
          {[
            { title: "Auth flow", status: "Done", color: "var(--color-rag-green)" },
            { title: "Chart filters", status: "In Progress", color: "var(--color-brand-secondary)" },
            { title: "Rate limiter", status: "In Review", color: "var(--color-rag-amber)" },
          ].map((t) => (
            <div
              key={t.title}
              className="flex items-center justify-between p-2 rounded-lg bg-[var(--bg-surface-raised)]/50"
            >
              <span className="text-[11px] text-[var(--text-primary)]">{t.title}</span>
              <span
                className="text-[10px] font-semibold"
                style={{ color: t.color }}
              >
                {t.status}
              </span>
            </div>
          ))}
        </div>
      </div>
    ),

    developers: (
      <div className="space-y-3">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-7 h-7 rounded-full bg-gradient-to-br from-[var(--color-brand-secondary)] to-[var(--color-brand-primary)] flex items-center justify-center text-white text-[10px] font-bold">
            SK
          </div>
          <div>
            <p className="text-xs font-semibold text-[var(--text-primary)]">
              Sarah K.
            </p>
            <p className="text-[10px] text-[var(--text-secondary)]">
              Today&apos;s Standup
            </p>
          </div>
        </div>
        {/* Activity items */}
        {[
          { icon: GitPullRequest, text: "PR #287 merged: auth refresh", color: "var(--color-rag-green)" },
          { icon: Code2, text: "3 commits on rate-limiter branch", color: "var(--color-brand-secondary)" },
          { icon: Clock, text: "P2S-151 in progress: 6h", color: "var(--color-rag-amber)" },
        ].map((item, i) => (
          <div key={i} className="flex items-center gap-2.5 p-2 rounded-lg bg-[var(--bg-surface-raised)]/50">
            <item.icon className="w-3.5 h-3.5 shrink-0" style={{ color: item.color }} />
            <span className="text-[11px] text-[var(--text-secondary)]">{item.text}</span>
          </div>
        ))}
      </div>
    ),

    stakeholders: (
      <div className="space-y-3">
        <div className="flex items-center gap-2 mb-2">
          <TrendingUp className="w-4 h-4 text-[var(--color-brand-secondary)]" />
          <span className="text-xs font-semibold text-[var(--text-primary)]">
            Delivery Overview
          </span>
        </div>
        {/* Team rows */}
        {[
          { team: "Platform", velocity: "92%", risk: "Low", color: "var(--color-rag-green)" },
          { team: "Frontend", velocity: "87%", risk: "Medium", color: "var(--color-rag-amber)" },
          { team: "Data", velocity: "95%", risk: "Low", color: "var(--color-rag-green)" },
        ].map((row) => (
          <div
            key={row.team}
            className="flex items-center justify-between p-2 rounded-lg bg-[var(--bg-surface-raised)]/50"
          >
            <span className="text-[11px] font-medium text-[var(--text-primary)]">
              {row.team}
            </span>
            <div className="flex items-center gap-3">
              <span className="text-[10px] text-[var(--text-secondary)]">
                {row.velocity}
              </span>
              <span
                className="text-[10px] font-semibold"
                style={{ color: row.color }}
              >
                {row.risk}
              </span>
            </div>
          </div>
        ))}
        {/* Summary bar */}
        <div className="mt-2 p-2.5 rounded-lg bg-[var(--color-brand-secondary)]/5 border border-[var(--color-brand-secondary)]/10">
          <p className="text-[10px] text-[var(--text-secondary)]">
            <strong className="text-[var(--text-primary)]">3 teams</strong> tracked
            &middot; <strong className="text-[var(--color-rag-green)]">91%</strong>{" "}
            avg velocity &middot;{" "}
            <strong className="text-[var(--text-primary)]">0</strong> critical blockers
          </p>
        </div>
      </div>
    ),
  };

  return (
    <div className="relative">
      {/* Glow */}
      <div className="absolute -inset-4 bg-[var(--color-brand-secondary)]/8 rounded-3xl blur-2xl" />
      <div className="relative glass rounded-2xl p-5 max-w-sm w-full">
        {/* Dashboard label */}
        <div className="flex items-center justify-between mb-4 pb-3 border-b border-[var(--border-subtle)]">
          <div className="flex items-center gap-2">
            <Eye className="w-4 h-4 text-[var(--color-brand-secondary)]" />
            <span className="text-xs font-bold text-[var(--text-primary)]">
              {label}
            </span>
          </div>
          <span className="text-[10px] text-[var(--text-secondary)]">
            Live
          </span>
        </div>

        {mockContent[tabId]}
      </div>
    </div>
  );
}

/* ==========================================================================
   Tab Button
   ========================================================================== */

function TabButton({
  tab,
  isActive,
  onClick,
}: {
  tab: TabData;
  isActive: boolean;
  onClick: () => void;
}) {
  const Icon = tab.icon;

  return (
    <button
      onClick={onClick}
      className={cn(
        "relative flex items-center gap-2 px-4 py-3 text-sm font-medium transition-all duration-300 cursor-pointer whitespace-nowrap",
        "border-b-2",
        isActive
          ? "text-[var(--color-brand-secondary)] border-b-[var(--color-brand-secondary)]"
          : "text-[var(--text-secondary)] border-b-transparent hover:text-[var(--text-primary)] hover:border-b-[var(--border-subtle)]"
      )}
    >
      <Icon
        className={cn(
          "w-4 h-4 transition-colors duration-300",
          isActive
            ? "text-[var(--color-brand-secondary)]"
            : "text-[var(--text-secondary)]"
        )}
      />
      <span className="hidden sm:inline">{tab.label}</span>
    </button>
  );
}

/* ==========================================================================
   Tab Content Panel
   ========================================================================== */

function TabContent({ tab }: { tab: TabData }) {
  return (
    <motion.div
      key={tab.id}
      variants={tabContentVariants}
      initial="initial"
      animate="animate"
      exit="exit"
      className="grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-16 items-center pt-10"
    >
      {/* Text side */}
      <div>
        <h3 className="text-2xl sm:text-3xl font-bold text-[var(--text-primary)] leading-tight">
          {tab.headline}
        </h3>
        <p className="text-[var(--text-secondary)] leading-relaxed mt-4 max-w-lg">
          {tab.body}
        </p>
        <CapabilityList items={tab.capabilities} />
      </div>

      {/* Visual side */}
      <div className="flex justify-center lg:justify-end">
        <DashboardVisual label={tab.dashboardLabel} tabId={tab.id} />
      </div>
    </motion.div>
  );
}

/* ==========================================================================
   Solutions Section (Export)
   ========================================================================== */

export default function Solutions() {
  const [activeTab, setActiveTab] = useState(0);
  const sectionRef = useRef<HTMLDivElement>(null);
  const isInView = useInView(sectionRef, { once: true, margin: "-80px" });

  return (
    <section
      id="solutions"
      ref={sectionRef}
      className="relative py-24 lg:py-32 overflow-hidden"
    >
      {/* Background glow */}
      <div className="absolute top-1/3 right-0 w-[500px] h-[500px] bg-[var(--color-brand-secondary)]/5 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute bottom-1/4 left-0 w-[400px] h-[400px] bg-[var(--color-brand-accent)]/5 rounded-full blur-3xl pointer-events-none" />

      <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* Section Header */}
        <motion.div
          initial="hidden"
          animate={isInView ? "visible" : "hidden"}
          variants={fadeUp}
          className="text-center mb-12 lg:mb-16"
        >
          <SectionLabel>SOLUTIONS</SectionLabel>
          <SectionHeading className="mt-4">
            Built for every person
            <br />
            <span className="gradient-text">on the team.</span>
          </SectionHeading>
        </motion.div>

        {/* Tab Buttons */}
        <motion.div
          initial="hidden"
          animate={isInView ? "visible" : "hidden"}
          variants={fadeUp}
          className="flex justify-center"
        >
          <div
            className={cn(
              "flex gap-1 overflow-x-auto scrollbar-none",
              "border-b border-[var(--border-subtle)]",
              "max-w-full px-2"
            )}
          >
            {tabs.map((tab, index) => (
              <TabButton
                key={tab.id}
                tab={tab}
                isActive={activeTab === index}
                onClick={() => setActiveTab(index)}
              />
            ))}
          </div>
        </motion.div>

        {/* Tab Content */}
        <AnimatePresence mode="wait">
          <TabContent tab={tabs[activeTab]} />
        </AnimatePresence>
      </div>
    </section>
  );
}
