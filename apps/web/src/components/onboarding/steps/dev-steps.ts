/**
 * Developer main tour — 6 steps.
 *
 * Pages NOT in this tour (notification page, project picker etc) get
 * page hints from page-hints.ts.
 */

import type { OnboardingStep } from "@/lib/onboarding/types";

export const DEV_STEPS: OnboardingStep[] = [
  {
    id: "welcome",
    role: "developer",
    variant: "welcome",
    title: "Welcome",
    body: "",
  },
  {
    id: "sprint-board",
    role: "developer",
    variant: "spotlight",
    title: "Your sprint board",
    body:
      "The work items currently assigned to you for this sprint. Plan2Sprint pulls these directly from ADO or Jira, so the board always matches reality.",
    route: "/dev",
    anchor: "[data-onboarding=dev-sprint-board]",
    anchorPosition: "auto",
  },
  {
    id: "submit-standup",
    role: "developer",
    variant: "spotlight",
    title: "Submit a standup",
    body:
      "Plan2Sprint pre-fills your standup from work item activity, PRs, and commits. You just review what's already there — no more typing the same updates daily.",
    route: "/dev/standup",
    anchor: "[data-onboarding=submit-standup-btn]",
    anchorPosition: "auto",
  },
  {
    id: "flag-blocker",
    role: "developer",
    variant: "spotlight",
    title: "Flag a blocker",
    body:
      "Stuck on something? Flag it as a blocker and your PO gets notified instantly in Slack or Teams. They can acknowledge or escalate without leaving chat.",
    route: "/dev/standup",
    anchor: "[data-onboarding=blocker-flag-btn]",
    anchorPosition: "auto",
  },
  {
    id: "personal-channel-link",
    role: "developer",
    variant: "spotlight",
    title: "Link your personal Slack or Teams (optional)",
    body:
      "Connect your own Slack or Teams account so direct messages route to you specifically — separately from the org-level bot. Your PO can DM you a blocker question without it showing up in the channel.",
    route: "/dev/notifications",
    anchor: "[data-onboarding=link-personal-account]",
    anchorPosition: "auto",
  },
  {
    id: "dev-completion",
    role: "developer",
    variant: "completion",
    title: "Done",
    body: "",
  },
];
