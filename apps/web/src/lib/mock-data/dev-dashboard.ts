import type {
  WorkItem,
  PullRequest,
  StandupReport,
  VelocityProfile,
} from "@/lib/types/models";

// Developer: Alex Chen (tm-1)
export const myTeamMember = {
  id: "tm-1",
  displayName: "Alex Chen",
  email: "alex.chen@acme.com",
  skillTags: ["React", "TypeScript", "Node.js"],
  defaultCapacity: 40,
};

export const mySprintStats = {
  sprintName: "Sprint 24",
  daysRemaining: 4,
  assignedSP: 16,
  completedSP: 11,
  remainingSP: 5,
  pacing: "GREEN" as const,
  capacityUsed: 0.73,
};

export const myWorkItems: WorkItem[] = [
  {
    id: "wi-1", organizationId: "org-1", externalId: "PROJ-201", sourceTool: "JIRA",
    title: "Implement checkout flow UI",
    description: "Build the multi-step checkout flow including cart review, shipping address, payment method selection, and order confirmation steps.",
    status: "IN_PROGRESS", storyPoints: 8, priority: 1, type: "story",
    labels: ["frontend", "checkout"], iterationId: "iter-1", assigneeId: "tm-1",
    acceptanceCriteria: "- Multi-step wizard with progress indicator\n- Cart review step with quantity editing\n- Shipping address form with validation\n- Payment method selection (credit card, PayPal)\n- Order confirmation with summary",
  },
  {
    id: "wi-5", organizationId: "org-1", externalId: "PROJ-205", sourceTool: "JIRA",
    title: "Fix mobile checkout layout",
    description: "The checkout flow breaks on screen widths below 375px. Fix responsive layout for all checkout steps.",
    status: "IN_REVIEW", storyPoints: 3, priority: 2, type: "bug",
    labels: ["frontend", "mobile"], iterationId: "iter-1", assigneeId: "tm-1",
  },
  {
    id: "wi-11", organizationId: "org-1", externalId: "PROJ-211", sourceTool: "JIRA",
    title: "Checkout flow E2E tests",
    description: "Write Playwright E2E tests for the complete checkout flow.",
    status: "TODO", storyPoints: 5, priority: 3, type: "story",
    labels: ["testing", "checkout"], iterationId: "iter-1", assigneeId: "tm-1",
  },
];

export const myPullRequests: PullRequest[] = [
  {
    id: "pr-1", repositoryId: "repo-1", externalId: "gh-301", number: 301,
    title: "feat: checkout flow step navigation",
    status: "AWAITING_REVIEW", authorId: "tm-1", reviewers: ["tm-3", "tm-5"],
    ciStatus: "PASSING", linkedWorkItemId: "wi-1", url: "#",
    createdExternalAt: "2026-02-17T14:30:00Z",
  },
  {
    id: "pr-3", repositoryId: "repo-1", externalId: "gh-305", number: 305,
    title: "fix: mobile checkout responsive layout",
    status: "APPROVED", authorId: "tm-1", reviewers: ["tm-3"],
    ciStatus: "PASSING", linkedWorkItemId: "wi-5", url: "#",
    createdExternalAt: "2026-02-18T09:15:00Z",
  },
];

export const myPRsToReview: PullRequest[] = [
  {
    id: "pr-5", repositoryId: "repo-1", externalId: "gh-303", number: 303,
    title: "feat: address autocomplete with Google Places",
    status: "AWAITING_REVIEW", authorId: "tm-5", reviewers: ["tm-1"],
    ciStatus: "PASSING", linkedWorkItemId: "wi-8", url: "#",
    createdExternalAt: "2026-02-17T16:45:00Z",
  },
];

export const myStandupReport: StandupReport = {
  id: "sr-1",
  organizationId: "org-1",
  teamMemberId: "tm-1",
  iterationId: "iter-1",
  reportDate: "2026-02-19T09:30:00Z",
  completedItems: {
    items: [
      { title: "Shipping address form with validation", ticketId: "PROJ-201", prId: "gh-301" },
    ],
  },
  inProgressItems: {
    items: [
      { title: "Payment method selection step", ticketId: "PROJ-201", prStatus: "AWAITING_REVIEW" },
      { title: "Mobile checkout responsive fixes", ticketId: "PROJ-205", prStatus: "APPROVED" },
    ],
  },
  blockers: { items: [] },
  narrativeText: "Alex completed the shipping address form with full validation and Google Places autocomplete. Currently working on the payment method selection step - PR #301 is awaiting review. The mobile checkout fix (PR #305) is approved and ready to merge.",
  acknowledged: true,
  acknowledgedAt: "2026-02-19T09:45:00Z",
  isInactive: false,
};

export const myVelocityHistory: VelocityProfile[] = Array.from({ length: 8 }, (_, i) => ({
  id: `vp-tm1-${i}`,
  teamMemberId: "tm-1",
  iterationId: `iter-${i + 17}`,
  plannedSP: [13, 11, 16, 13, 15, 14, 16, 16][i]!,
  completedSP: [13, 10, 14, 13, 13, 14, 15, 11][i]!,
  rollingAverage: 12.8,
  isColdStart: false,
  recordedAt: new Date(2025, 10, 4 + i * 14).toISOString(),
}));

export const myRecentCommits = [
  { sha: "a1b2c3d", message: "feat: add shipping address form with Places API", branch: "feat/PROJ-201-checkout-flow", committedAt: "2026-02-19T08:30:00Z", linkedTicketIds: ["PROJ-201"] },
  { sha: "e4f5g6h", message: "fix: responsive grid breakpoints for mobile checkout", branch: "fix/PROJ-205-mobile-checkout", committedAt: "2026-02-18T17:15:00Z", linkedTicketIds: ["PROJ-205"] },
  { sha: "i7j8k9l", message: "feat: step navigation with progress indicator", branch: "feat/PROJ-201-checkout-flow", committedAt: "2026-02-18T14:00:00Z", linkedTicketIds: ["PROJ-201"] },
  { sha: "m0n1o2p", message: "test: unit tests for cart calculation hooks", branch: "feat/PROJ-201-checkout-flow", committedAt: "2026-02-17T16:45:00Z", linkedTicketIds: ["PROJ-201"] },
];
