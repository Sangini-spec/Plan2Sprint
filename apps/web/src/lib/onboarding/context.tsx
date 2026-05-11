"use client";

/**
 * OnboardingProvider — central state for the product tour.
 *
 * Owns:
 *  - the current ``OnboardingProgress`` fetched from /api/onboarding/progress
 *  - the active ``OnboardingStep`` (resolved from progress.current_step against
 *    the role-specific step list)
 *  - the queue of unseen page hints
 *  - all transition helpers (next, back, skip, completeTour, dismiss, replay)
 *
 * Does NOT render any UI — ``OnboardingTour`` (mounted by (app)/layout)
 * subscribes via ``useOnboarding`` and renders the appropriate primitive.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth/context";
import {
  fetchProgress,
  patchProgress,
  replayTour as apiReplay,
  markPageHintSeen as apiMarkHint,
  resetPageHints as apiResetHints,
  dismissTour as apiDismiss,
} from "./api";
import type {
  OnboardingProgress,
  OnboardingRole,
  OnboardingStep,
  PageHint,
} from "./types";
import { PO_STEPS } from "@/components/onboarding/steps/po-steps";
import { DEV_STEPS } from "@/components/onboarding/steps/dev-steps";
import { STAKEHOLDER_STEPS } from "@/components/onboarding/steps/stakeholder-steps";
import { PAGE_HINTS } from "@/components/onboarding/steps/page-hints";

function stepsFor(role: OnboardingRole): OnboardingStep[] {
  if (role === "product_owner") return PO_STEPS;
  if (role === "stakeholder") return STAKEHOLDER_STEPS;
  return DEV_STEPS;
}

interface OnboardingContextValue {
  progress: OnboardingProgress | null;
  loading: boolean;

  /** The currently active step, derived from progress.current_step. */
  currentStep: OnboardingStep | null;
  /** The full step list for the user's role. */
  allSteps: OnboardingStep[];
  /** 0-based index of the current step within ``allSteps``. */
  currentStepIndex: number;

  /** True while the user is between welcome and completion (UI should render). */
  isActive: boolean;

  /** True if the tour is fresh (status=not_started) — shows welcome modal. */
  shouldShowWelcome: boolean;

  /** True if we should show the re-engagement banner. */
  shouldShowBanner: boolean;

  /** Advance to the next step in the role list. */
  next: () => Promise<void>;
  /** Go back one step (does not mutate completed_steps). */
  back: () => Promise<void>;
  /** Skip the current step (records it under skipped_steps). */
  skipCurrent: () => Promise<void>;
  /** Skip everything — marks status=dismissed. */
  skipTour: () => Promise<void>;
  /** Mark tour completed — shows confetti modal. */
  completeTour: () => Promise<void>;
  /** Start the tour from the welcome step (replay or first-time-take). */
  startTour: () => Promise<void>;
  /** Reset to step 1 and increment replay_count. */
  replay: () => Promise<void>;
  /** Mark the re-engagement banner dismissed. */
  dismissBanner: () => Promise<void>;
  /** Jump to an arbitrary step by id (used by Settings → Jump to step). */
  jumpToStep: (stepId: string) => Promise<void>;

  /** First-visit page hint queue — null when no hint is pending. */
  activePageHint: PageHint | null;
  /** Dismiss the current page hint (records pathname to seen list). */
  dismissPageHint: () => Promise<void>;
  /** Wipe all page hints — Settings → Reset all page hints. */
  resetPageHints: () => Promise<void>;
}

const OnboardingContext = createContext<OnboardingContextValue | null>(null);

export function useOnboarding() {
  const ctx = useContext(OnboardingContext);
  if (!ctx) {
    throw new Error("useOnboarding must be used within OnboardingProvider");
  }
  return ctx;
}

const PAGE_HINT_DELAY_MS = 600;

export function OnboardingProvider({ children }: { children: ReactNode }) {
  const { appUser, loading: authLoading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  const [progress, setProgress] = useState<OnboardingProgress | null>(null);
  const [loading, setLoading] = useState(true);
  const [activePageHint, setActivePageHint] = useState<PageHint | null>(null);

  /** Tracks whether we've done the one-shot "resume the tour on the
   *  right page" navigation. Without this guard the effect below would
   *  loop forever — pathname changes after we navigate, the effect
   *  re-fires, sees a mismatch again (since the step state is
   *  cached), and pushes again. */
  const resumedNavRef = useRef(false);

  /** Load initial progress when the user is ready. */
  useEffect(() => {
    if (authLoading || !appUser) return;
    let cancelled = false;
    (async () => {
      try {
        const p = await fetchProgress();
        if (!cancelled) setProgress(p);
      } catch {
        // Treat fetch error like not_started so the UI doesn't get stuck.
        if (!cancelled) setProgress(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [authLoading, appUser?.id]);

  /** One-shot resume nav — if the user closed the browser mid-tour and
   *  comes back to their dashboard home, send them to the page their
   *  current step points at. Only fires once per provider mount; if the
   *  user manually navigates away mid-tour, we don't yank them back. */
  useEffect(() => {
    if (loading || resumedNavRef.current) return;
    if (!progress || progress.status !== "in_progress") return;
    // Only resume from the role's home — if they're already deep in
    // the app on a non-home page, treat that as intentional navigation
    // and respect it.
    const home =
      progress.role === "product_owner"
        ? "/po"
        : progress.role === "stakeholder"
        ? "/stakeholder"
        : "/dev";
    if (pathname !== home) {
      resumedNavRef.current = true;
      return;
    }
    const step = stepsFor(progress.role).find(
      (s) => s.id === progress.current_step,
    );
    if (step?.route && step.route !== pathname && step.variant === "spotlight") {
      resumedNavRef.current = true;
      router.push(step.route);
    } else {
      resumedNavRef.current = true;
    }
  }, [loading, progress, pathname, router]);

  const allSteps = useMemo(() => {
    if (!progress) return [];
    return stepsFor(progress.role);
  }, [progress?.role]);

  const currentStepIndex = useMemo(() => {
    if (!progress || allSteps.length === 0) return -1;
    return allSteps.findIndex((s) => s.id === progress.current_step);
  }, [progress?.current_step, allSteps]);

  const currentStep: OnboardingStep | null = useMemo(() => {
    if (currentStepIndex < 0) return null;
    return allSteps[currentStepIndex] ?? null;
  }, [allSteps, currentStepIndex]);

  const isActive = progress?.status === "in_progress";

  // The welcome modal fires in two cases:
  //   1. Brand-new user — status=not_started + !banner_dismissed
  //   2. Replay — backend's ``/replay`` endpoint sets
  //      status=in_progress + current_step="welcome". Without this
  //      branch the modal would never re-fire on replay and the user
  //      would land on a blank dashboard (the spotlight variant check
  //      doesn't match the welcome step, so nothing renders).
  const shouldShowWelcome: boolean =
    !!progress &&
    progress.status !== "dismissed" &&
    !progress.banner_dismissed &&
    (progress.status === "not_started" || progress.current_step === "welcome");

  // Re-engagement banner fires when the user dismissed the tour but
  // hasn't dismissed the banner yet. Brand-new users see the welcome
  // modal instead; in-progress users see the spotlight tour.
  const shouldShowBanner: boolean =
    !!progress &&
    progress.status === "dismissed" &&
    !progress.banner_dismissed;

  // ---------------- Transition helpers ----------------

  const advanceTo = useCallback(
    async (stepId: string, opts?: { markCompleted?: string }) => {
      const updated = await patchProgress({
        current_step: stepId,
        status: "in_progress",
        ...(opts?.markCompleted
          ? { mark_completed: [opts.markCompleted] }
          : {}),
      });
      setProgress(updated);

      // If the new step targets a different route, navigate.
      const step = stepsFor(updated.role).find((s) => s.id === stepId);
      if (step?.route && step.route !== pathname) {
        router.push(step.route);
      }
      // Fire onEnter side-effects (e.g. switch a tab).
      step?.onEnter?.();
    },
    [pathname, router],
  );

  const next = useCallback(async () => {
    if (!progress || currentStepIndex < 0) return;
    const nextIdx = currentStepIndex + 1;
    if (nextIdx >= allSteps.length) {
      // Already at completion — close out.
      const updated = await patchProgress({ status: "completed" });
      setProgress(updated);
      return;
    }
    const completedId = allSteps[currentStepIndex]?.id;
    await advanceTo(allSteps[nextIdx].id, { markCompleted: completedId });
  }, [progress, currentStepIndex, allSteps, advanceTo]);

  const back = useCallback(async () => {
    if (!progress || currentStepIndex <= 0) return;
    const prevIdx = currentStepIndex - 1;
    await advanceTo(allSteps[prevIdx].id);
  }, [progress, currentStepIndex, allSteps, advanceTo]);

  const skipCurrent = useCallback(async () => {
    if (!progress || currentStepIndex < 0) return;
    const skippedId = allSteps[currentStepIndex].id;
    const nextIdx = currentStepIndex + 1;
    if (nextIdx >= allSteps.length) {
      const updated = await patchProgress({
        status: "completed",
        mark_skipped: [skippedId],
      });
      setProgress(updated);
      return;
    }
    const updated = await patchProgress({
      current_step: allSteps[nextIdx].id,
      mark_skipped: [skippedId],
      status: "in_progress",
    });
    setProgress(updated);
    const step = allSteps[nextIdx];
    if (step?.route && step.route !== pathname) router.push(step.route);
    step?.onEnter?.();
  }, [progress, currentStepIndex, allSteps, pathname, router]);

  const skipTour = useCallback(async () => {
    await apiDismiss();
    const p = await fetchProgress();
    setProgress(p);
  }, []);

  const completeTour = useCallback(async () => {
    const updated = await patchProgress({ status: "completed" });
    setProgress(updated);
  }, []);

  const startTour = useCallback(async () => {
    if (!progress) return;
    // Mark welcome step done, advance to step 2.
    if (allSteps.length < 2) return;
    await advanceTo(allSteps[1].id, { markCompleted: "welcome" });
  }, [progress, allSteps, advanceTo]);

  const replay = useCallback(async () => {
    const p = await apiReplay();
    setProgress(p);
    // After replay, navigate to the role's home so the welcome modal
    // fires in the right context.
    const home =
      p.role === "product_owner"
        ? "/po"
        : p.role === "stakeholder"
        ? "/stakeholder"
        : "/dev";
    router.push(home);
  }, [router]);

  const dismissBanner = useCallback(async () => {
    const updated = await patchProgress({ banner_dismissed: true });
    setProgress(updated);
  }, []);

  const jumpToStep = useCallback(
    async (stepId: string) => {
      if (!allSteps.find((s) => s.id === stepId)) return;
      await advanceTo(stepId);
    },
    [allSteps, advanceTo],
  );

  // ---------------- Page hints ----------------

  useEffect(() => {
    if (!progress || isActive) {
      // Don't show page hints while the tour itself is running.
      setActivePageHint(null);
      return;
    }
    if (progress.status === "not_started") {
      // Don't show page hints to brand-new users — they should see the welcome modal first.
      setActivePageHint(null);
      return;
    }
    const hint = PAGE_HINTS.find((h) => h.pathname === pathname);
    if (!hint) {
      setActivePageHint(null);
      return;
    }
    if (progress.page_hints_seen.includes(pathname)) {
      setActivePageHint(null);
      return;
    }
    // Delay so the page has a chance to render its initial content.
    const timer = setTimeout(() => {
      setActivePageHint(hint);
    }, PAGE_HINT_DELAY_MS);
    return () => clearTimeout(timer);
  }, [pathname, progress?.page_hints_seen, progress?.status, isActive]);

  const dismissPageHint = useCallback(async () => {
    if (!activePageHint || !progress) return;
    const path = activePageHint.pathname;
    setActivePageHint(null);
    await apiMarkHint(path);
    setProgress({
      ...progress,
      page_hints_seen: [...progress.page_hints_seen, path],
    });
  }, [activePageHint, progress]);

  const resetPageHints = useCallback(async () => {
    await apiResetHints();
    if (progress) {
      setProgress({ ...progress, page_hints_seen: [] });
    }
  }, [progress]);

  // ---------------- Context value ----------------

  const value: OnboardingContextValue = {
    progress,
    loading,
    currentStep,
    allSteps,
    currentStepIndex,
    isActive: !!isActive,
    shouldShowWelcome,
    shouldShowBanner,
    next,
    back,
    skipCurrent,
    skipTour,
    completeTour,
    startTour,
    replay,
    dismissBanner,
    jumpToStep,
    activePageHint,
    dismissPageHint,
    resetPageHints,
  };

  return (
    <OnboardingContext.Provider value={value}>
      {children}
    </OnboardingContext.Provider>
  );
}
