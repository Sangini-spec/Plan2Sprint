/**
 * Product Owner main tour — 12 steps.
 *
 * Order matches the actual workflow: connect tool → pick project →
 * import projects → invite team → assign projects → sprint planning
 * (3 sub-views) → GitHub → standups → channels → done.
 *
 * Pages NOT in this tour (Retro, Team Health, Smart Notes) are covered
 * by ``page-hints.ts`` — first-visit one-shot cards.
 */

import type { OnboardingStep } from "@/lib/onboarding/types";

export const PO_STEPS: OnboardingStep[] = [
  {
    id: "welcome",
    role: "product_owner",
    variant: "welcome",
    title: "Welcome",
    body: "",
  },
  {
    id: "connect-tool",
    role: "product_owner",
    variant: "spotlight",
    title: "Connect ADO or Jira",
    body:
      "Plan2Sprint reads work items from your project tool. Click 'Connect Tools' to set up Azure DevOps, Jira, or GitHub — pick whichever your team already uses.",
    route: "/po",
    anchor: "[data-onboarding=connect-tools-btn]",
    anchorPosition: "bottom",
  },
  {
    id: "project-selector",
    role: "product_owner",
    variant: "spotlight",
    title: "Pick your project",
    body:
      "Everything in Plan2Sprint is scoped to the project you've selected. Use this picker in the topbar to switch between projects.",
    route: "/po",
    anchor: "[data-onboarding=project-picker]",
    anchorPosition: "bottom",
  },
  {
    id: "add-projects",
    role: "product_owner",
    variant: "spotlight",
    title: "Add projects to your workspace",
    body:
      "Choose which projects from your connected tool to import into Plan2Sprint. You can add more later from this same page.",
    route: "/po/projects",
    anchor: "[data-onboarding=projects-page]",
    anchorPosition: "auto",
  },
  {
    id: "invite-team",
    role: "product_owner",
    variant: "spotlight",
    title: "Invite your team",
    body:
      "Add your developers and stakeholders. Plan2Sprint also auto-discovers team members from your ADO/Jira sync, but invites get them into the platform with the right role from day one.",
    route: "/settings/team",
    anchor: "[data-onboarding=invite-button]",
    anchorPosition: "auto",
  },
  {
    id: "assign-projects",
    role: "product_owner",
    variant: "spotlight",
    title: "Assign projects to team members",
    body:
      "Each developer and stakeholder gets access only to the projects you assign them. This drives the access guard — they can't see projects they're not on.",
    route: "/settings/team",
    anchor: "[data-onboarding=assign-projects-section]",
    anchorPosition: "auto",
  },
  {
    id: "sprint-planning",
    role: "product_owner",
    variant: "spotlight",
    title: "Sprint Planning",
    body:
      "Generate a sprint plan in one click. The AI assigns work items to team members based on skills + capacity, with a confidence score for the whole plan.",
    route: "/po/planning?tab=planning",
    anchor: "[data-onboarding=planning-generate]",
    anchorPosition: "auto",
  },
  {
    id: "sprint-forecast",
    role: "product_owner",
    variant: "spotlight",
    title: "Forecast",
    body:
      "See success probability, spillover risk, and the predictability score for the proposed plan before approving. Use this to validate plans before they reach the team.",
    route: "/po/planning?tab=forecast",
    anchor: "[data-onboarding=planning-forecast]",
    anchorPosition: "auto",
  },
  {
    id: "sprint-rebalance",
    role: "product_owner",
    variant: "spotlight",
    title: "Rebalance",
    body:
      "When the plan ends past your target launch, Plan2Sprint suggests realistic shifts — move scope, extend the sprint, or both. Review and approve the rebalanced plan here.",
    route: "/po/planning?tab=rebalance",
    anchor: "[data-onboarding=planning-rebalance]",
    anchorPosition: "auto",
  },
  {
    id: "github-monitoring",
    role: "product_owner",
    variant: "spotlight",
    title: "GitHub Monitoring",
    body:
      "Pull requests, commits, and CI status — all linked to work items so you can see what's actually shipping vs what's still in flight.",
    route: "/po/github",
    anchor: "[data-onboarding=github-panel]",
    anchorPosition: "auto",
  },
  {
    id: "standup-digest",
    role: "product_owner",
    variant: "spotlight",
    title: "Standup Digest",
    body:
      "Auto-generated standups from work item activity, PRs, and commits. Blockers surface here and route to Slack/Teams. No more chasing your team for updates.",
    route: "/po/standups",
    anchor: "[data-onboarding=standup-digest-panel]",
    anchorPosition: "auto",
  },
  {
    id: "channels",
    role: "product_owner",
    variant: "spotlight",
    title: "Channels — Slack & Teams",
    body:
      "Connect Slack or Microsoft Teams to auto-post sprint plans, blockers, and daily digests. Each project gets its own channel. Use the tab switcher to pick whichever platform your team prefers.",
    route: "/po/notifications",
    anchor: "[data-onboarding=channels-tabs]",
    anchorPosition: "auto",
  },
  {
    id: "po-completion",
    role: "product_owner",
    variant: "completion",
    title: "Done",
    body: "",
  },
];
