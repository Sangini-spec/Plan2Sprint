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

  /** Route the user must be on for this step. Engine navigates if mismatched. */
  route?: string;

  /** Optional "Go to X" button label inside the card. */
  actionLabel?: string;

  /** Custom callback when the step becomes active (e.g. switch a tab). */
  onEnter?: () => void;

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
