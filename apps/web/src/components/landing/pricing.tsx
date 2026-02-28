"use client";

import { useRef, useState } from "react";
import { motion, useInView, AnimatePresence } from "framer-motion";
import { Check, ChevronDown, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { GlassCard, Button, Badge, SectionLabel, SectionHeading } from "@/components/ui";

/* -------------------------------------------------------------------------- */
/*  Types & Data                                                               */
/* -------------------------------------------------------------------------- */

interface PricingTier {
  name: string;
  monthlyPrice: string | number;
  annualPrice: string | number;
  priceLabel: string;
  annualPriceLabel: string;
  description: string;
  capacity: string;
  features: string[];
  cta: string;
  variant: "secondary" | "primary";
  recommended?: boolean;
}

const tiers: PricingTier[] = [
  {
    name: "Starter",
    monthlyPrice: 0,
    annualPrice: 0,
    priceLabel: "Free forever",
    annualPriceLabel: "Free forever",
    description: "For small teams getting started",
    capacity: "Up to 5 developers, 1 project",
    features: [
      "AI sprint plans (3/mo)",
      "Async standups (weekdays)",
      "Slack or Teams",
      "Developer Dashboard",
      "30-day history",
    ],
    cta: "Start Free",
    variant: "secondary",
  },
  {
    name: "Team",
    monthlyPrice: 18,
    annualPrice: 15,
    priceLabel: "/dev/month",
    annualPriceLabel: "/dev/month billed annually",
    description: "For growing engineering teams",
    capacity: "Up to 30 devs, unlimited projects",
    features: [
      "Everything in Starter, plus:",
      "Unlimited plans",
      "GitHub integration",
      "Full PO Dashboard",
      "Team health & burnout",
      "AI retrospectives",
      "Slack + Teams",
      "Approval gateway + undo",
      "Priority support",
    ],
    cta: "Start 14-Day Free Trial",
    variant: "primary",
    recommended: true,
  },
  {
    name: "Enterprise",
    monthlyPrice: "Custom",
    annualPrice: "Custom",
    priceLabel: "",
    annualPriceLabel: "",
    description: "For large organizations and regulated industries",
    capacity: "Unlimited devs, multi-org",
    features: [
      "Everything in Team, plus:",
      "Jira DC + ADO Server",
      "SAML 2.0 / OIDC SSO",
      "SOC 2 Type II",
      "GDPR DPA + residency",
      "Custom LLM config",
      "Dedicated CSM + SLA",
      "Audit log export",
      "Custom integrations",
    ],
    cta: "Talk to Sales",
    variant: "secondary",
  },
];

interface FaqItem {
  question: string;
  answer: string;
}

const faqs: FaqItem[] = [
  {
    question: "Does Plan2Sprint replace Jira or ADO?",
    answer:
      "No. Plan2Sprint is designed to overlay on top of Jira, Azure DevOps, and your other existing tools. It reads from them, generates AI-powered plans, and writes back only three specific fields. Your team keeps using the tools they already know.",
  },
  {
    question: "What does 'write-back' mean exactly?",
    answer:
      "Write-back means Plan2Sprint can update exactly three fields in your project management tool: Assignee, Sprint Membership, and Story Points. Every write-back is logged, visible in the PO dashboard, and can be undone within 60 minutes.",
  },
  {
    question: "Does it really block weekend standups?",
    answer:
      "Yes. Weekend standup delivery is hard-blocked at the engine level. This isn't a setting that can be toggled off\u2014it's an architectural decision. We believe developer well-being is non-negotiable.",
  },
  {
    question: "Can developers see each other's data?",
    answer:
      "No. This is architecturally impossible in Plan2Sprint. Each developer's dashboard shows only their own work, velocity, and focus data. Team-level views are only available to Product Owners and Engineering Managers.",
  },
  {
    question: "What happens if the AI is unavailable?",
    answer:
      "Plan2Sprint is designed with graceful degradation. If the AI layer is temporarily unavailable, the system falls back to template-based reports and cached data. Your standups and dashboards continue to function without interruption.",
  },
  {
    question: "Is my code or commit data stored?",
    answer:
      "No. Plan2Sprint only stores commit timestamps and status metadata (e.g., 'merged', 'in review'). We never read, store, or process your actual source code, diffs, or commit messages. Your intellectual property stays in your repositories.",
  },
];

/* -------------------------------------------------------------------------- */
/*  Animation variants                                                         */
/* -------------------------------------------------------------------------- */

const cardVariants = {
  hidden: { opacity: 0, y: 40 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.6,
      ease: [0.25, 0.46, 0.45, 0.94] as const,
      delay: i * 0.12,
    },
  }),
};

/* -------------------------------------------------------------------------- */
/*  Toggle Component                                                           */
/* -------------------------------------------------------------------------- */

function BillingToggle({
  isAnnual,
  onChange,
}: {
  isAnnual: boolean;
  onChange: (annual: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-center gap-4 mt-8">
      <span
        className={cn(
          "text-sm font-medium transition-colors duration-200",
          !isAnnual
            ? "text-[var(--text-primary)]"
            : "text-[var(--text-secondary)]"
        )}
      >
        Monthly
      </span>

      <button
        type="button"
        role="switch"
        aria-checked={isAnnual}
        onClick={() => onChange(!isAnnual)}
        className={cn(
          "relative inline-flex h-7 w-12 shrink-0 cursor-pointer rounded-full",
          "border border-[var(--border-subtle)]",
          "transition-colors duration-300 ease-in-out",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-brand-secondary)] focus-visible:ring-offset-2",
          isAnnual
            ? "bg-[var(--color-brand-secondary)]"
            : "bg-[var(--bg-surface-raised)]"
        )}
      >
        <span
          className={cn(
            "pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow-md",
            "transform transition-transform duration-300 ease-in-out",
            "mt-0.5",
            isAnnual ? "translate-x-[22px]" : "translate-x-[3px]"
          )}
        />
      </button>

      <span
        className={cn(
          "text-sm font-medium transition-colors duration-200",
          isAnnual
            ? "text-[var(--text-primary)]"
            : "text-[var(--text-secondary)]"
        )}
      >
        Annual
      </span>

      {isAnnual && (
        <Badge variant="rag-green" className="ml-1">
          Save ~20%
        </Badge>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Pricing Card                                                               */
/* -------------------------------------------------------------------------- */

function PricingCard({
  tier,
  isAnnual,
  index,
}: {
  tier: PricingTier;
  isAnnual: boolean;
  index: number;
}) {
  const price = isAnnual ? tier.annualPrice : tier.monthlyPrice;
  const label = isAnnual ? tier.annualPriceLabel : tier.priceLabel;

  return (
    <motion.div
      custom={index}
      variants={cardVariants}
      className={cn(
        "relative flex flex-col",
        tier.recommended && "scale-[1.04] z-10"
      )}
    >
      {/* Gradient border glow for recommended */}
      {tier.recommended && (
        <div
          className={cn(
            "absolute -inset-px rounded-2xl",
            "bg-gradient-to-br from-[var(--color-brand-secondary)] via-[var(--color-brand-accent)] to-[var(--color-brand-primary)]",
            "opacity-60 blur-[2px]"
          )}
          aria-hidden="true"
        />
      )}

      <GlassCard
        whileHover={{ y: 0 }}
        className={cn(
          "relative flex flex-col h-full",
          tier.recommended &&
            "border-[var(--color-brand-secondary)]/40 shadow-xl shadow-[var(--color-brand-secondary)]/10"
        )}
      >
        {/* Most Popular badge */}
        {tier.recommended && (
          <Badge
            variant="brand"
            className="absolute -top-3 left-1/2 -translate-x-1/2 flex items-center gap-1.5"
          >
            <Sparkles className="h-3 w-3" />
            Most Popular
          </Badge>
        )}

        {/* Header */}
        <div className="mb-6">
          <h3 className="text-xl font-bold text-[var(--text-primary)]">
            {tier.name}
          </h3>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            {tier.description}
          </p>
        </div>

        {/* Price */}
        <div className="mb-6">
          <div className="flex items-baseline gap-1">
            {typeof price === "number" ? (
              <>
                <span className="text-4xl font-extrabold text-[var(--text-primary)]">
                  ${price}
                </span>
                {price > 0 && (
                  <span className="text-sm text-[var(--text-secondary)]">
                    {label}
                  </span>
                )}
              </>
            ) : (
              <span className="text-4xl font-extrabold text-[var(--text-primary)]">
                {price}
              </span>
            )}
          </div>
          {typeof price === "number" && price === 0 && (
            <p className="mt-1 text-sm font-medium text-[var(--color-brand-secondary)]">
              {label}
            </p>
          )}
        </div>

        {/* Capacity */}
        <p className="mb-6 text-sm font-medium text-[var(--text-secondary)] border-b border-[var(--border-subtle)] pb-4">
          {tier.capacity}
        </p>

        {/* Features */}
        <ul className="mb-8 flex-1 space-y-3">
          {tier.features.map((feature) => {
            const isHeader = feature.endsWith(":");
            return (
              <li key={feature} className="flex items-start gap-3">
                {!isHeader && (
                  <Check className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-brand-secondary)]" />
                )}
                <span
                  className={cn(
                    "text-sm",
                    isHeader
                      ? "font-semibold text-[var(--text-primary)]"
                      : "text-[var(--text-secondary)]"
                  )}
                >
                  {feature}
                </span>
              </li>
            );
          })}
        </ul>

        {/* CTA */}
        <Button
          variant={tier.variant === "primary" ? "primary" : "secondary"}
          size="lg"
          className={cn(
            "w-full",
            tier.recommended &&
              "shadow-lg shadow-[var(--color-brand-secondary)]/25"
          )}
        >
          {tier.cta}
        </Button>
      </GlassCard>
    </motion.div>
  );
}

/* -------------------------------------------------------------------------- */
/*  FAQ Accordion                                                              */
/* -------------------------------------------------------------------------- */

function FaqAccordion({ items }: { items: FaqItem[] }) {
  const [openIndex, setOpenIndex] = useState<number | null>(null);

  return (
    <div className="mx-auto mt-20 max-w-3xl">
      <h3 className="mb-8 text-center text-2xl font-bold text-[var(--text-primary)]">
        Frequently Asked Questions
      </h3>

      <div className="space-y-3">
        {items.map((item, i) => {
          const isOpen = openIndex === i;
          return (
            <div
              key={i}
              className={cn(
                "glass rounded-xl overflow-hidden",
                "transition-colors duration-200",
                isOpen && "border-[var(--color-brand-secondary)]/20"
              )}
            >
              <button
                type="button"
                onClick={() => setOpenIndex(isOpen ? null : i)}
                className={cn(
                  "flex w-full items-center justify-between gap-4 px-6 py-4",
                  "text-left text-sm font-semibold text-[var(--text-primary)]",
                  "cursor-pointer",
                  "hover:bg-[var(--bg-surface-raised)]/50 transition-colors duration-200"
                )}
                aria-expanded={isOpen}
              >
                <span>{item.question}</span>
                <motion.span
                  animate={{ rotate: isOpen ? 180 : 0 }}
                  transition={{ duration: 0.25, ease: "easeInOut" }}
                  className="shrink-0"
                >
                  <ChevronDown className="h-4 w-4 text-[var(--text-secondary)]" />
                </motion.span>
              </button>

              <AnimatePresence initial={false}>
                {isOpen && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.3, ease: [0.25, 0.46, 0.45, 0.94] }}
                    className="overflow-hidden"
                  >
                    <p className="px-6 pb-5 text-sm leading-relaxed text-[var(--text-secondary)]">
                      {item.answer}
                    </p>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Section                                                                    */
/* -------------------------------------------------------------------------- */

export default function PricingSection() {
  const [isAnnual, setIsAnnual] = useState(false);
  const sectionRef = useRef<HTMLElement>(null);
  const isInView = useInView(sectionRef, { once: true, margin: "-100px" });

  return (
    <section
      id="pricing"
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
          <SectionLabel>PRICING</SectionLabel>
          <SectionHeading className="mt-2">
            Simple pricing. No surprises.
          </SectionHeading>

          <BillingToggle isAnnual={isAnnual} onChange={setIsAnnual} />
        </motion.div>

        {/* Pricing cards */}
        <motion.div
          initial="hidden"
          animate={isInView ? "visible" : "hidden"}
          className={cn(
            "mt-16 grid gap-8 items-stretch",
            "grid-cols-1 md:grid-cols-3"
          )}
        >
          {tiers.map((tier, i) => (
            <PricingCard
              key={tier.name}
              tier={tier}
              isAnnual={isAnnual}
              index={i}
            />
          ))}
        </motion.div>

        {/* FAQ */}
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={isInView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6, ease: "easeOut", delay: 0.5 }}
        >
          <FaqAccordion items={faqs} />
        </motion.div>
      </div>
    </section>
  );
}
