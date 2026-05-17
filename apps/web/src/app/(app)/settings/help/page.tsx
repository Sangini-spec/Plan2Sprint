"use client";

/**
 * Settings → Help & Onboarding.
 *
 * Three sections:
 *   1. Product tour    - Replay full tour + Jump to specific step + last-completed line
 *   2. Page hints      - Reset all page hints with seen-count
 *   3. Documentation   - placeholder external links
 *
 * Crucially this is where the user goes for their own testing workflow
 * (since they already have multiple accounts logged in without the tour).
 * "Replay the full tour" restarts the welcome modal flow + spotlight tour
 * without requiring a fresh signup.
 */

import { useState } from "react";
import {
  // Compass marks the "Product tour" section (replaces the generic
  // Sparkles glyph that read as the AI-vibe-coded badge every starter
  // landing page ships). Lightbulb stays for the "Tips" subsection
  // since that's a different concept (insight/hint), not the tour.
  Compass,
  RotateCcw,
  ChevronDown,
  Lightbulb,
  BookOpen,
  Keyboard,
  Mail,
  CheckCircle2,
  Loader2,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useOnboarding } from "@/lib/onboarding/context";

export default function HelpPage() {
  const {
    progress,
    loading,
    allSteps,
    replay,
    resetPageHints,
    jumpToStep,
  } = useOnboarding();
  const router = useRouter();

  const [stepDropdownOpen, setStepDropdownOpen] = useState(false);
  const [replaying, setReplaying] = useState(false);
  const [resettingHints, setResettingHints] = useState(false);
  const [resetConfirmed, setResetConfirmed] = useState(false);

  // Total page hints registered (mirrors PAGE_HINTS count - kept in
  // sync manually since this is just a display number).
  const TOTAL_PAGE_HINTS = 9;
  const hintsSeen = progress?.page_hints_seen.length ?? 0;

  async function handleReplay() {
    setReplaying(true);
    try {
      await replay();
    } finally {
      setReplaying(false);
    }
  }

  async function handleReset() {
    setResettingHints(true);
    try {
      await resetPageHints();
      setResetConfirmed(true);
      setTimeout(() => setResetConfirmed(false), 2500);
    } finally {
      setResettingHints(false);
    }
  }

  async function handleJump(stepId: string) {
    setStepDropdownOpen(false);
    await jumpToStep(stepId);
    const home =
      progress?.role === "product_owner"
        ? "/po"
        : progress?.role === "stakeholder"
        ? "/stakeholder"
        : "/dev";
    router.push(home);
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-5 w-5 animate-spin text-[var(--text-secondary)]" />
      </div>
    );
  }

  const completedDate = progress?.completed_at
    ? new Date(progress.completed_at).toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
      })
    : null;

  const stepCount = allSteps.length;
  const completedCount = progress?.completed_steps.length ?? 0;
  // Steps available in the dropdown - skip welcome (always step 1) since
  // "Replay full tour" already covers that case.
  const jumpableSteps = allSteps.filter((s) => s.variant === "spotlight");

  return (
    <div className="space-y-6 max-w-2xl">
      {/* ============ Product tour ============ */}
      <section className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-6">
        <div className="flex items-start gap-3 mb-4">
          <div
            className="flex h-9 w-9 items-center justify-center rounded-lg shrink-0"
            style={{ background: "var(--onboarding-gradient-soft)" }}
          >
            <Compass
              size={18}
              strokeWidth={1.85}
              style={{ color: "var(--onboarding-primary)" }}
            />
          </div>
          <div>
            <h2 className="text-base font-semibold text-[var(--text-primary)]">
              Product tour
            </h2>
            <p className="text-sm text-[var(--text-secondary)] mt-0.5">
              {completedDate ? (
                <>
                  Last completed:{" "}
                  <span className="text-[var(--text-primary)] font-medium">
                    {completedDate}
                  </span>{" "}
                  ·{" "}
                  <span className="text-[var(--text-primary)] font-medium">
                    {completedCount} of {stepCount} steps
                  </span>
                </>
              ) : progress?.status === "in_progress" ? (
                <>
                  In progress -{" "}
                  <span className="text-[var(--text-primary)] font-medium">
                    {completedCount} of {stepCount} steps
                  </span>{" "}
                  done
                </>
              ) : (
                <>You haven&apos;t started the tour yet.</>
              )}
              {(progress?.replay_count ?? 0) > 0 && (
                <span className="ml-2 text-[var(--text-tertiary)]">
                  · Replayed {progress?.replay_count}×
                </span>
              )}
            </p>
          </div>
        </div>

        <div className="flex flex-col sm:flex-row gap-2">
          <button
            onClick={handleReplay}
            disabled={replaying}
            className="onb-cta flex-1 flex items-center justify-center gap-2 disabled:opacity-60"
          >
            {replaying ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <RotateCcw size={16} />
            )}
            {replaying ? "Restarting…" : "Replay the full tour"}
          </button>

          <div className="relative flex-1">
            <button
              onClick={() => setStepDropdownOpen((o) => !o)}
              className="w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] hover:bg-[var(--bg-surface-sunken)] transition-colors px-4 py-2.5 text-sm font-medium text-[var(--text-primary)] flex items-center justify-between gap-2"
            >
              <span>Jump to a specific step</span>
              <ChevronDown
                size={14}
                className={`transition-transform ${stepDropdownOpen ? "rotate-180" : ""}`}
              />
            </button>
            {stepDropdownOpen && (
              <div className="absolute z-10 right-0 left-0 mt-1 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-xl max-h-72 overflow-y-auto">
                {jumpableSteps.map((step, idx) => (
                  <button
                    key={step.id}
                    onClick={() => handleJump(step.id)}
                    className="w-full text-left px-4 py-2.5 text-sm hover:bg-[var(--bg-surface-raised)] transition-colors text-[var(--text-primary)] border-b border-[var(--border-subtle)] last:border-b-0"
                  >
                    <span className="text-[var(--text-tertiary)] mr-2">
                      {idx + 1}.
                    </span>
                    {step.title}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </section>

      {/* ============ Page hints ============ */}
      <section className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-6">
        <div className="flex items-start gap-3 mb-4">
          <div
            className="flex h-9 w-9 items-center justify-center rounded-lg shrink-0"
            style={{ background: "var(--onboarding-gradient-soft)" }}
          >
            <Lightbulb
              size={18}
              style={{ color: "var(--onboarding-primary)" }}
            />
          </div>
          <div>
            <h2 className="text-base font-semibold text-[var(--text-primary)]">
              Page hints
            </h2>
            <p className="text-sm text-[var(--text-secondary)] mt-0.5">
              Pop-up cards that explain a page the first time you visit it.{" "}
              <span className="text-[var(--text-primary)] font-medium">
                Seen {hintsSeen} of {TOTAL_PAGE_HINTS}
              </span>
              .
            </p>
          </div>
        </div>

        <button
          onClick={handleReset}
          disabled={resettingHints || hintsSeen === 0}
          className="onb-cta-secondary border border-[var(--border-subtle)] hover:bg-[var(--bg-surface-raised)] rounded-lg flex items-center gap-2 disabled:opacity-50"
        >
          {resetConfirmed ? (
            <>
              <CheckCircle2 size={14} style={{ color: "var(--onboarding-accent)" }} />
              Reset - all hints will fire again
            </>
          ) : resettingHints ? (
            <>
              <Loader2 size={14} className="animate-spin" />
              Resetting…
            </>
          ) : (
            <>
              <RotateCcw size={14} />
              Reset all page hints
            </>
          )}
        </button>
      </section>

      {/* ============ Documentation ============ */}
      <section className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-6">
        <h2 className="text-base font-semibold text-[var(--text-primary)] mb-1">
          Documentation
        </h2>
        <p className="text-sm text-[var(--text-secondary)] mb-4">
          Helpful resources outside the app.
        </p>
        <div className="space-y-1">
          <DocLink
            icon={BookOpen}
            label="User guide"
            href="https://docs.plan2sprint.com"
          />
          <DocLink
            icon={Keyboard}
            label="Keyboard shortcuts"
            href="https://docs.plan2sprint.com/shortcuts"
          />
          <DocLink
            icon={Mail}
            label="Contact support"
            href="mailto:support@plan2sprint.app"
          />
        </div>
      </section>
    </div>
  );
}

function DocLink({
  icon: Icon,
  label,
  href,
}: {
  icon: React.ElementType;
  label: string;
  href: string;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-[var(--bg-surface-raised)] transition-colors text-sm text-[var(--text-primary)]"
    >
      <Icon size={16} className="text-[var(--text-secondary)]" />
      <span>{label}</span>
      <span className="ml-auto text-[var(--text-tertiary)]">↗</span>
    </a>
  );
}
