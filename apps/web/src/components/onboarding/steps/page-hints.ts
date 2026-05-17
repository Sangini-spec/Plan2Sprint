/**
 * First-visit page hints.
 *
 * One-shot cards that pop 600ms after a user first lands on a given
 * page. Dismissed via the X button or the "Got it" CTA. Once dismissed,
 * recorded under ``onboarding_progress.page_hints_seen`` and never
 * auto-fired again. Replayable from Settings → Help → Reset all page
 * hints.
 *
 * Hints cover pages that aren't in the main tour but still benefit
 * from a quick orientation. Especially useful for PO-only surfaces
 * (Retro, Team Health) and the channels page.
 */

import type { PageHint } from "@/lib/onboarding/types";

export const PAGE_HINTS: PageHint[] = [
  // ---------- PO surfaces ----------
  {
    pathname: "/po/retro",
    title: "Retrospectives",
    body:
      "AI-driven failure analysis runs after each sprint - what went well, what didn't, and action items that carry forward. Projects past their target launch get a 'Project Cycle Concluded' card here.",
  },
  {
    pathname: "/po/health",
    title: "Team Health",
    body:
      "Plan2Sprint watches 8 signal types: burnout risk, velocity variance, stalled tickets, review lag, CI failure, after-hours activity, inactivity, and capacity overload. Red signals escalate to Slack/Teams automatically.",
  },
  {
    pathname: "/po/notifications",
    title: "Channels & Quick Actions",
    body:
      "Use the tab switcher above to pick Slack or Microsoft Teams. Create a project channel (the team gets auto-invited), then post sprint plans, announcements, or custom messages from here.",
  },

  // ---------- Dev surfaces ----------
  {
    pathname: "/dev/velocity",
    title: "Your Velocity",
    body:
      "Story points completed per sprint over time. Useful for understanding your own pace and spotting weeks you over- or under-committed. This data is private to you and your PO.",
  },
  {
    pathname: "/dev/notifications",
    title: "Channels",
    body:
      "Pick Slack or Teams, then post standups, blockers, or custom messages to your project's channel. You can also link your personal account so the PO can DM you directly.",
  },

  // ---------- Stakeholder surfaces ----------
  {
    pathname: "/stakeholder/delivery",
    title: "Delivery Predictability",
    body:
      "A composite score combining velocity stability, commitment-vs-delivery, and forecast confidence. Use this to spot teams that need help before deadlines slip.",
  },
  {
    pathname: "/stakeholder/epics",
    title: "Epics & Milestones",
    body:
      "Track the work items you actually care about - high-level epics and their milestones - without drowning in ticket-level detail.",
  },
  {
    pathname: "/stakeholder/health",
    title: "Team Health Summary",
    body:
      "Aggregate of the underlying team health signals, filtered to what stakeholders need to know. Red = the PO is already aware and acting.",
  },

  // ---------- Universal ----------
  {
    pathname: "/settings/help",
    title: "Help & Onboarding",
    body:
      "This is where you can replay the product tour from scratch, jump to a specific step, or reset every page hint so they all fire again on next visit.",
  },
];
