"use client";

/**
 * OnboardingTour — root renderer for the product tour.
 *
 * Banner-based UX (replaced earlier spotlight + full-page dim
 * pattern, which made the dashboard feel locked and prevented
 * scrolling):
 *
 *   shouldShowWelcome (not_started OR current_step="welcome" post-replay)
 *     → WelcomeModal (centered overlay, one-time)
 *   in_progress + step.variant=spotlight → TourBanner + ChecklistWidget
 *     The banner sticks at the top of the page below the topbar; the
 *     rest of the page stays fully interactive (no dim, no overlay).
 *     A subtle outline highlights the anchored element for context.
 *   in_progress + step.variant=completion → CompletionModal (with
 *     small corner-burst confetti)
 *   (always) → PageHintCard (gated internally on first-visit pages)
 */

import { useOnboarding } from "@/lib/onboarding/context";
import { WelcomeModal } from "./welcome-modal";
import { CompletionModal } from "./completion-modal";
import { AnchorOutline } from "./tour-banner";
import { ChecklistWidget } from "./checklist-widget";
import { PageHintCard } from "./page-hint-card";
import { InlineTooltips } from "./inline-tooltip";

export function OnboardingTour() {
  const { progress, currentStep, isActive, shouldShowWelcome } = useOnboarding();

  if (!progress) {
    // Page hint can still render even when tour state hasn't loaded yet,
    // but we keep it gated through context (activePageHint stays null).
    return <PageHintCard />;
  }

  return (
    <>
      {/* Welcome modal — pristine users only */}
      {shouldShowWelcome && <WelcomeModal />}

      {/* Active tour — bottom-right checklist widget + fixed-position
          anchor outline + optional per-element inline tooltips. The
          TOP BANNER is rendered inline in (app)/layout so it pushes
          content down instead of overlapping. */}
      {isActive && currentStep?.variant === "spotlight" && (
        <>
          <AnchorOutline />
          <InlineTooltips />
          <ChecklistWidget />
        </>
      )}

      {/* Completion modal — last step */}
      {isActive && currentStep?.variant === "completion" && <CompletionModal />}

      {/* Page hint — gated by activePageHint inside the component */}
      <PageHintCard />
    </>
  );
}
