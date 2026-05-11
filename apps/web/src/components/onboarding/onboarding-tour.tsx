"use client";

/**
 * OnboardingTour — root renderer for the product tour.
 *
 * Decides which primitive to mount based on the current OnboardingProgress:
 *   shouldShowWelcome (not_started OR current_step="welcome" post-replay)
 *     → WelcomeModal
 *   in_progress + step.variant=spotlight → SpotlightCard + ChecklistWidget
 *   in_progress + step.variant=completion → CompletionModal
 *   (always)                              → PageHintCard (gated internally)
 *
 * Mounted in (app)/layout once via OnboardingProvider. Sits at z-index
 * 90+ so it always wins over normal page content.
 */

import { useOnboarding } from "@/lib/onboarding/context";
import { WelcomeModal } from "./welcome-modal";
import { CompletionModal } from "./completion-modal";
import { SpotlightCard } from "./spotlight-card";
import { ChecklistWidget } from "./checklist-widget";
import { PageHintCard } from "./page-hint-card";

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

      {/* Active tour — spotlight + checklist */}
      {isActive && currentStep?.variant === "spotlight" && (
        <>
          <SpotlightCard />
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
