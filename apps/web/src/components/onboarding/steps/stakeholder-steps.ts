/**
 * Stakeholder main tour — 5 steps.
 */

import type { OnboardingStep } from "@/lib/onboarding/types";

export const STAKEHOLDER_STEPS: OnboardingStep[] = [
  {
    id: "welcome",
    role: "stakeholder",
    variant: "welcome",
    title: "Welcome",
    body: "",
  },
  {
    id: "portfolio-health",
    role: "stakeholder",
    variant: "spotlight",
    title: "Portfolio health",
    body:
      "RAG indicators show severity at a glance: 🟢 healthy, 🟡 needs attention, 🔴 act now. Each signal is backed by data — no manual status reporting.",
    route: "/stakeholder",
    anchor: "[data-onboarding=portfolio-health]",
    anchorPosition: "auto",
  },
  {
    id: "predictability",
    role: "stakeholder",
    variant: "spotlight",
    title: "Predictability & Velocity",
    body:
      "How reliably is the team hitting commitments? Velocity Δ shows trend across sprints, capped at sane ranges so a tiny baseline never produces a misleading +33,200%.",
    route: "/stakeholder",
    anchor: "[data-onboarding=predictability-row]",
    anchorPosition: "auto",
  },
  {
    id: "switch-projects",
    role: "stakeholder",
    variant: "spotlight",
    title: "Switch between projects",
    body:
      "You can be assigned to multiple projects. Use the picker in the topbar to flip between them — your assigned projects are listed here.",
    route: "/stakeholder",
    anchor: "[data-onboarding=project-picker]",
    anchorPosition: "bottom",
  },
  {
    id: "weekly-export",
    role: "stakeholder",
    variant: "spotlight",
    title: "Weekly PDF report",
    body:
      "Every Friday at 5 PM IST you'll get a PDF summary delivered to your inbox. You can also generate one on demand from the Export page.",
    route: "/stakeholder/export",
    anchor: "[data-onboarding=export-button]",
    anchorPosition: "auto",
  },
  {
    id: "stakeholder-completion",
    role: "stakeholder",
    variant: "completion",
    title: "Done",
    body: "",
  },
];
