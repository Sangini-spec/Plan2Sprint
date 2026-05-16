/**
 * Developer main tour — redesigned per user feedback.
 *
 * Flow:
 *   1. Welcome
 *   2. Connect Tools + Project Picker (multi-anchor)  — show where
 *      projects come from
 *   3. Sprint board                                    — assigned
 *      work for the active sprint
 *   4. GitHub activity                                 — PRs +
 *      commits linked to work items (noOutline — page focus)
 *   5. Submit a standup                                — pre-filled
 *      from work item activity
 *   6. Channels (Slack / Teams)                        — workspace
 *      already connected at the org level, you'll see updates in
 *      the project channels (NOT a personal connection step)
 *   7. Flag a blocker                                  — flag from
 *      the standup, posts to your project channel
 *   8. Completion
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
    id: "find-projects",
    role: "developer",
    variant: "spotlight",
    title: "Find your assigned projects",
    body:
      "Projects are imported by your Product Owner via Connect Tools, then assigned to you. Use the project picker to switch between any projects you've been added to.",
    route: "/dev",
    // Multi-anchor — outline both Connect Tools button AND the
    // project picker. The dev needs to know about both: Connect
    // Tools is org-level (PO action), picker is per-dev navigation
    // between their assigned projects.
    anchor: "[data-onboarding=connect-tools-btn]",
    extraAnchors: ["[data-onboarding=project-picker]"],
    anchorPosition: "bottom",
  },
  {
    id: "sprint-board",
    role: "developer",
    variant: "spotlight",
    title: "Your sprint board",
    body:
      "Work items assigned to you for the active sprint — synced live from ADO or Jira. Toggle between the SOURCE view (raw ADO/Jira state) and the AI-OPTIMIZED view (the PO's rebalanced plan) at the top.",
    // Route the user to the dedicated Sprint section in the sidebar
    // (the page that hosts ``DevSprintView`` with the source vs.
    // AI-optimized toggle) — not the /dev dashboard, which previously
    // anchored an older sprint widget at this step.
    route: "/dev/sprint",
    anchor: "[data-onboarding=dev-sprint-board]",
    anchorPosition: "auto",
  },
  {
    id: "github-activity",
    role: "developer",
    variant: "spotlight",
    title: "Your GitHub activity",
    body:
      "Every PR you open and commit you push shows up here, automatically linked to the work item it touches. Plan2Sprint reads this from the GitHub connection your PO set up.",
    route: "/dev/github",
    noOutline: true,
  },
  {
    id: "submit-standup",
    role: "developer",
    variant: "spotlight",
    title: "Submit a standup",
    body:
      "Plan2Sprint pre-fills your standup from work item activity, PRs, and commits. Review what's there and submit — no more typing the same updates daily.",
    route: "/dev/standup",
    anchor: "[data-onboarding=submit-standup-btn]",
    anchorPosition: "auto",
  },
  {
    id: "channels",
    role: "developer",
    variant: "spotlight",
    title: "Slack & Teams channels",
    body:
      "Your organisation's Slack or Microsoft Teams workspace is already connected by your PO. You'll see daily standup digests, sprint plans, and blocker alerts in your project's channel automatically — nothing to set up on your end.",
    route: "/dev/notifications",
    // No outline — the entire channels page is the focus; outlining
    // the whole panel duplicated the context.
    noOutline: true,
  },
  {
    id: "flag-blocker",
    role: "developer",
    variant: "spotlight",
    title: "Flag a blocker",
    body:
      "Blockers flow through your Slack or Teams channel. When you flag one, Plan2Sprint posts an interactive card to the channel — your PO can acknowledge or escalate it from chat, and the resolution syncs back here. The whole loop happens in the channel; you don't have to chase anyone.",
    route: "/dev/notifications",
    // No outline — the channels page is the focus. Flagging
    // surfaces as a chat-side action (Adaptive Card buttons in
    // Slack/Teams), not as a button on this page.
    noOutline: true,
  },
  {
    id: "dev-completion",
    role: "developer",
    variant: "completion",
    title: "Done",
    body: "",
  },
];
