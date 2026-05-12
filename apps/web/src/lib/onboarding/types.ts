/**
 * Onboarding feature — TypeScript types.
 *
 * Mirrors the JSON shape stored in ``users.onboarding_progress`` and
 * exchanged with ``/api/onboarding/*``. Keep this in sync with
 * ``apps/api/app/routers/onboarding.py``.
 */

import type { LucideIcon } from "lucide-react";

export type OnboardingRole = "product_owner" | "developer" | "stakeholder";

export type OnboardingStatus =
  | "not_started"
  | "in_progress"
  | "completed"
  | "dismissed";

export interface OnboardingProgress {
  role: OnboardingRole;
  current_step: string;
  completed_steps: string[];
  skipped_steps: string[];
  page_hints_seen: string[];
  status: OnboardingStatus;
  started_at: string | null;
  completed_at: string | null;
  banner_dismissed: boolean;
  replay_count: number;
}

/** A single step in the role-specific main tour. */
export interface OnboardingStep {
  id: string;
  role: OnboardingRole;
  variant: "welcome" | "spotlight" | "completion";
  title: string;
  body: string;
  icon?: LucideIcon;

  /** CSS selector to anchor the spotlight to. Skipped for welcome/completion. */
  anchor?: string;
  anchorPosition?: "top" | "bottom" | "left" | "right" | "auto";

  /**
   * Additional selectors to outline alongside the primary anchor.
   * Used when a single step is about two related controls (e.g. the
   * developer "find your projects" step which highlights both the
   * Connect Tools button and the Project Picker — they sit next to
   * each other in the topbar and the dev needs to know about both).
   */
  extraAnchors?: string[];

  /**
   * Suppress the anchor outline (purple ring + halo) for steps where
   * navigating to a dedicated page already makes the focus obvious
   * (e.g. GitHub Monitoring, Standup Digest). The banner still shows
   * the step copy; we just skip the visual ring around the whole
   * dashboard panel which felt redundant.
   */
  noOutline?: boolean;

  /** Route the user must be on for this step. Engine navigates if mismatched. */
  route?: string;

  /** Optional "Go to X" button label inside the card. */
  actionLabel?: string;

  /** Custom callback when the step becomes active (e.g. switch a tab). */
  onEnter?: () => void;

  /**
   * Optional in-context tooltips that pop next to specific UI
   * elements alongside the main banner. Each tooltip has its own
   * dismissible "Got it" button and only renders while this step is
   * the active one. Used to draw attention to secondary controls
   * without making them whole steps of the tour (e.g. a "regenerate
   * if not satisfied" hint next to the Regenerate button on the
   * sprint-planning step).
   */
  tooltips?: Array<{
    selector: string;
    body: string;
    position?: "top" | "bottom" | "left" | "right";
  }>;

  /**
   * Optional predicate — if it returns true at engine evaluation time,
   * the step is automatically skipped and recorded under ``skipped_steps``.
   * Used for smart skipping (e.g. "Connect a tool" when a tool is already
   * connected).
   */
  shouldSkip?: (ctx: OnboardingContext) => boolean;
}

/** A one-shot card that pops up the first time a user visits a page. */
export interface PageHint {
  pathname: string;     // exact pathname match
  title: string;
  body: string;
  icon?: LucideIcon;
  /** Anchor element selector — if omitted, hint floats top-right of viewport */
  anchor?: string;
}

/** Context the engine passes to ``shouldSkip`` predicates. */
export interface OnboardingContext {
  hasToolConnection: boolean;
  hasSelectedProject: boolean;
  hasTeamMembers: boolean;
  hasSlackConnection: boolean;
  hasTeamsConnection: boolean;
  hasProjectChannel: boolean;
}
