"use client";

import { useRef } from "react";
import { motion, useInView } from "framer-motion";
import {
  Cloud,
  GitBranch,
  MessageSquare,
  Users,
  FileText,
  LayoutList,
  Shield,
  Server,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { GlassCard, SectionLabel, SectionHeading, Badge } from "@/components/ui";

/* -------------------------------------------------------------------------- */
/*  Data                                                                       */
/* -------------------------------------------------------------------------- */

interface Integration {
  name: string;
  capability: string;
  icon: React.ReactNode;
  phase?: string;
}

const integrations: Integration[] = [
  {
    name: "Jira Cloud",
    capability: "Full sync + write-back",
    icon: <Cloud className="h-8 w-8" />,
  },
  {
    name: "Azure DevOps",
    capability: "Full sync + write-back",
    icon: <Server className="h-8 w-8" />,
  },
  {
    name: "GitHub",
    capability: "PR & commit monitoring",
    icon: <GitBranch className="h-8 w-8" />,
  },
  {
    name: "Slack",
    capability: "Standup delivery + alerts",
    icon: <MessageSquare className="h-8 w-8" />,
  },
  {
    name: "Microsoft Teams",
    capability: "Standup delivery + alerts",
    icon: <Users className="h-8 w-8" />,
  },
  {
    name: "Notion",
    capability: "Requirements reading",
    icon: <FileText className="h-8 w-8" />,
    phase: "Coming Soon",
  },
  {
    name: "Linear",
    capability: "Issue sync",
    icon: <LayoutList className="h-8 w-8" />,
    phase: "Coming Soon",
  },
];

/* -------------------------------------------------------------------------- */
/*  Animation variants                                                         */
/* -------------------------------------------------------------------------- */

const containerVariants = {
  hidden: {},
  visible: {
    transition: {
      staggerChildren: 0.08,
    },
  },
};

const tileVariants = {
  hidden: { opacity: 0, y: 32 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.5, ease: [0.25, 0.46, 0.45, 0.94] as const },
  },
};

const calloutVariants = {
  hidden: { opacity: 0, y: 24 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.6, ease: "easeOut" as const, delay: 0.3 },
  },
};

/* -------------------------------------------------------------------------- */
/*  Integration Tile                                                           */
/* -------------------------------------------------------------------------- */

function IntegrationTile({ integration }: { integration: Integration }) {
  return (
    <motion.div variants={tileVariants}>
      <GlassCard
        className={cn(
          "group relative flex flex-col items-center gap-4 text-center",
          "opacity-90 hover:opacity-100",
          "transition-all duration-300"
        )}
      >
        {/* Phase badge */}
        {integration.phase && (
          <Badge
            variant="brand"
            className="absolute top-3 right-3 text-[10px]"
          >
            {integration.phase}
          </Badge>
        )}

        {/* Icon */}
        <div
          className={cn(
            "flex h-14 w-14 items-center justify-center rounded-xl",
            "bg-[var(--color-brand-secondary)]/10",
            "text-[var(--color-brand-secondary)]",
            "transition-colors duration-300",
            "group-hover:bg-[var(--color-brand-secondary)]/20"
          )}
        >
          {integration.icon}
        </div>

        {/* Name */}
        <h3 className="text-lg font-semibold text-[var(--text-primary)]">
          {integration.name}
        </h3>

        {/* Capability tag */}
        <span
          className={cn(
            "inline-block rounded-full px-3 py-1 text-xs font-medium",
            "bg-[var(--bg-surface-raised)] text-[var(--text-secondary)]",
            "border border-[var(--border-subtle)]"
          )}
        >
          {integration.capability}
        </span>
      </GlassCard>
    </motion.div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Section                                                                    */
/* -------------------------------------------------------------------------- */

export default function IntegrationsSection() {
  const sectionRef = useRef<HTMLElement>(null);
  const isInView = useInView(sectionRef, { once: true, margin: "-100px" });

  return (
    <section
      id="integrations"
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
          <SectionLabel>INTEGRATIONS</SectionLabel>
          <SectionHeading className="mt-2">
            Works where your team already works.
          </SectionHeading>
          <p className="mt-6 text-lg leading-relaxed text-[var(--text-secondary)]">
            Plan2Sprint overlays on top of your existing tools. It never
            replaces them.
          </p>
        </motion.div>

        {/* Integration grid */}
        <motion.div
          variants={containerVariants}
          initial="hidden"
          animate={isInView ? "visible" : "hidden"}
          className={cn(
            "mt-16 grid gap-6",
            "grid-cols-2 md:grid-cols-3"
          )}
        >
          {integrations.map((integration) => (
            <IntegrationTile key={integration.name} integration={integration} />
          ))}
        </motion.div>

        {/* Write-back reassurance callout */}
        <motion.div
          variants={calloutVariants}
          initial="hidden"
          animate={isInView ? "visible" : "hidden"}
          className="mt-16"
        >
          <div
            className={cn(
              "glass rounded-2xl p-6 sm:p-8",
              "border-l-4 border-l-[var(--color-brand-accent)]",
              "flex items-start gap-5"
            )}
          >
            {/* Shield icon */}
            <div
              className={cn(
                "flex h-12 w-12 shrink-0 items-center justify-center rounded-xl",
                "bg-[var(--color-brand-accent)]/10 text-[var(--color-brand-accent)]"
              )}
            >
              <Shield className="h-6 w-6" />
            </div>

            {/* Text */}
            <div>
              <p className="text-base font-semibold text-[var(--text-primary)] leading-relaxed">
                Plan2Sprint never modifies your ticket fields. Sprint plans,
                rebalances, and recommendations are posted as{" "}
                <span className="text-[var(--color-brand-secondary)]">
                  comments
                </span>{" "}
                on the ticket itself.
              </p>
              <p className="mt-2 text-sm text-[var(--text-secondary)]">
                Your structured data stays yours. You decide what (if anything)
                to action.
              </p>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}
