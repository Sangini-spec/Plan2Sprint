import type {
  Iteration,
  TeamMember,
  WorkItem,
  PullRequest,
  SprintPlan,
  PlanAssignment,
  StandupReport,
  TeamStandupDigest,
  HealthSignal,
  BurnoutAlert,
  VelocityProfile,
  Retrospective,
  BlockerFlag,
  DeveloperProgress,
  SprintOverview,
  BacklogHealthScore,
} from "@/lib/types/models";

// ============================================================================
// CURRENT SPRINT
// ============================================================================

export const currentIteration: Iteration = {
  id: "iter-1",
  organizationId: "org-1",
  externalId: "SPRINT-24",
  sourceTool: "JIRA",
  name: "Sprint 24",
  goal: "Complete checkout flow redesign and payment integration",
  startDate: "2026-02-09T00:00:00Z",
  endDate: "2026-02-23T00:00:00Z",
  state: "active",
};

// ============================================================================
// TEAM MEMBERS
// ============================================================================

export const teamMembers: TeamMember[] = [
  {
    id: "tm-1",
    organizationId: "org-1",
    externalId: "jira-101",
    email: "alex.chen@acme.com",
    displayName: "Alex Chen",
    avatarUrl: undefined,
    skillTags: ["React", "TypeScript", "Node.js"],
    defaultCapacity: 40,
  },
  {
    id: "tm-2",
    organizationId: "org-1",
    externalId: "jira-102",
    email: "sarah.kim@acme.com",
    displayName: "Sarah Kim",
    avatarUrl: undefined,
    skillTags: ["Python", "FastAPI", "PostgreSQL"],
    defaultCapacity: 40,
  },
  {
    id: "tm-3",
    organizationId: "org-1",
    externalId: "jira-103",
    email: "marcus.johnson@acme.com",
    displayName: "Marcus Johnson",
    avatarUrl: undefined,
    skillTags: ["React", "CSS", "Figma"],
    defaultCapacity: 32,
  },
  {
    id: "tm-4",
    organizationId: "org-1",
    externalId: "jira-104",
    email: "priya.patel@acme.com",
    displayName: "Priya Patel",
    avatarUrl: undefined,
    skillTags: ["Go", "Kubernetes", "AWS"],
    defaultCapacity: 40,
  },
  {
    id: "tm-5",
    organizationId: "org-1",
    externalId: "jira-105",
    email: "james.wilson@acme.com",
    displayName: "James Wilson",
    avatarUrl: undefined,
    skillTags: ["React Native", "TypeScript", "GraphQL"],
    defaultCapacity: 40,
  },
  {
    id: "tm-6",
    organizationId: "org-1",
    externalId: "jira-106",
    email: "emma.davis@acme.com",
    displayName: "Emma Davis",
    avatarUrl: undefined,
    skillTags: ["Python", "ML", "Data"],
    defaultCapacity: 40,
  },
];

// ============================================================================
// WORK ITEMS
// ============================================================================

export const workItems: WorkItem[] = [
  { id: "wi-1", organizationId: "org-1", externalId: "PROJ-201", sourceTool: "JIRA", title: "Implement checkout flow UI", status: "IN_PROGRESS", storyPoints: 8, priority: 1, type: "story", labels: ["frontend", "checkout"], iterationId: "iter-1", assigneeId: "tm-1" },
  { id: "wi-2", organizationId: "org-1", externalId: "PROJ-202", sourceTool: "JIRA", title: "Payment gateway integration", status: "IN_PROGRESS", storyPoints: 13, priority: 1, type: "story", labels: ["backend", "payments"], iterationId: "iter-1", assigneeId: "tm-2" },
  { id: "wi-3", organizationId: "org-1", externalId: "PROJ-203", sourceTool: "JIRA", title: "Cart summary component", status: "DONE", storyPoints: 5, priority: 2, type: "story", labels: ["frontend"], iterationId: "iter-1", assigneeId: "tm-3" },
  { id: "wi-4", organizationId: "org-1", externalId: "PROJ-204", sourceTool: "JIRA", title: "Order confirmation email template", status: "TODO", storyPoints: 3, priority: 3, type: "story", labels: ["backend", "email"], iterationId: "iter-1", assigneeId: "tm-4" },
  { id: "wi-5", organizationId: "org-1", externalId: "PROJ-205", sourceTool: "JIRA", title: "Fix mobile checkout layout", status: "IN_REVIEW", storyPoints: 3, priority: 2, type: "bug", labels: ["frontend", "mobile"], iterationId: "iter-1", assigneeId: "tm-1" },
  { id: "wi-6", organizationId: "org-1", externalId: "PROJ-206", sourceTool: "JIRA", title: "Stripe webhook handler", status: "IN_PROGRESS", storyPoints: 5, priority: 1, type: "story", labels: ["backend", "payments"], iterationId: "iter-1", assigneeId: "tm-2" },
  { id: "wi-7", organizationId: "org-1", externalId: "PROJ-207", sourceTool: "JIRA", title: "Shipping calculator API", status: "TODO", storyPoints: 8, priority: 2, type: "story", labels: ["backend"], iterationId: "iter-1", assigneeId: "tm-4" },
  { id: "wi-8", organizationId: "org-1", externalId: "PROJ-208", sourceTool: "JIRA", title: "Address autocomplete integration", status: "IN_PROGRESS", storyPoints: 5, priority: 3, type: "story", labels: ["frontend"], iterationId: "iter-1", assigneeId: "tm-5" },
  { id: "wi-9", organizationId: "org-1", externalId: "PROJ-209", sourceTool: "JIRA", title: "Checkout analytics events", status: "BACKLOG", storyPoints: 3, priority: 4, type: "story", labels: ["analytics"], iterationId: "iter-1", assigneeId: "tm-6" },
  { id: "wi-10", organizationId: "org-1", externalId: "PROJ-210", sourceTool: "JIRA", title: "Payment error handling UI", status: "TODO", storyPoints: 5, priority: 2, type: "story", labels: ["frontend", "payments"], iterationId: "iter-1", assigneeId: "tm-3" },
];

// ============================================================================
// PULL REQUESTS
// ============================================================================

export const pullRequests: PullRequest[] = [
  { id: "pr-1", repositoryId: "repo-1", externalId: "gh-301", number: 301, title: "feat: checkout flow step navigation", status: "AWAITING_REVIEW", authorId: "tm-1", reviewers: ["tm-3", "tm-5"], ciStatus: "PASSING", linkedWorkItemId: "wi-1", url: "#", createdExternalAt: "2026-02-17T14:30:00Z" },
  { id: "pr-2", repositoryId: "repo-1", externalId: "gh-298", number: 298, title: "feat: Stripe payment intent API", status: "CHANGES_REQUESTED", authorId: "tm-2", reviewers: ["tm-4"], ciStatus: "PASSING", linkedWorkItemId: "wi-2", url: "#", createdExternalAt: "2026-02-16T10:00:00Z" },
  { id: "pr-3", repositoryId: "repo-1", externalId: "gh-305", number: 305, title: "fix: mobile checkout responsive layout", status: "APPROVED", authorId: "tm-1", reviewers: ["tm-3"], ciStatus: "PASSING", linkedWorkItemId: "wi-5", url: "#", createdExternalAt: "2026-02-18T09:15:00Z" },
  { id: "pr-4", repositoryId: "repo-1", externalId: "gh-299", number: 299, title: "feat: Stripe webhook signature verification", status: "OPEN", authorId: "tm-2", reviewers: ["tm-4", "tm-6"], ciStatus: "FAILING", linkedWorkItemId: "wi-6", url: "#", createdExternalAt: "2026-02-16T16:00:00Z" },
  { id: "pr-5", repositoryId: "repo-1", externalId: "gh-303", number: 303, title: "feat: address autocomplete with Google Places", status: "AWAITING_REVIEW", authorId: "tm-5", reviewers: ["tm-1"], ciStatus: "PASSING", linkedWorkItemId: "wi-8", url: "#", createdExternalAt: "2026-02-17T16:45:00Z" },
];

// ============================================================================
// SPRINT PLAN
// ============================================================================

export const currentPlan: SprintPlan = {
  id: "plan-1",
  organizationId: "org-1",
  iterationId: "iter-1",
  status: "SYNCED",
  confidenceScore: 0.84,
  riskSummary: "Low risk. Capacity utilization at 78% average. One dependency on Stripe API setup.",
  totalStoryPoints: 58,
  aiModelUsed: "claude-sonnet-4-5-20250514",
  approvedById: "user-po-1",
  approvedAt: "2026-02-08T16:30:00Z",
  syncedAt: "2026-02-08T16:32:00Z",
};

export const planAssignments: PlanAssignment[] = teamMembers.map((tm, i) => ({
  id: `pa-${i + 1}`,
  sprintPlanId: "plan-1",
  workItemId: workItems[i]?.id ?? `wi-${i + 1}`,
  teamMemberId: tm.id,
  storyPoints: workItems[i]?.storyPoints ?? 5,
  confidenceScore: 0.78 + Math.random() * 0.2,
  rationale: `Assigned based on ${tm.skillTags[0]} expertise and available capacity. Velocity match: 92%.`,
  riskFlags: i === 1 ? ["external_dependency"] : [],
  skillMatch: { matchedSkills: tm.skillTags.slice(0, 2), score: 0.85 + Math.random() * 0.1 },
  isHumanEdited: false,
}));

// ============================================================================
// STANDUP DATA
// ============================================================================

export const todayDigest: TeamStandupDigest = {
  id: "digest-1",
  organizationId: "org-1",
  iterationId: "iter-1",
  digestDate: "2026-02-19T09:30:00Z",
  sprintPacing: 62,
  acknowledgedPct: 83,
  sprintHealth: "GREEN",
  atRiskItems: {
    items: [
      { workItemId: "wi-7", reason: "No activity for 2 days" },
      { workItemId: "wi-2", reason: "PR awaiting review for 48h" },
    ],
  },
  blockerCount: 1,
  summaryText: "Sprint 24 is tracking well at 62% completion with 65% of time elapsed. 5 of 6 developers acknowledged. One blocker flagged on PROJ-206 (Stripe webhook handler) - waiting for API key provisioning.",
};

export const standupReports: StandupReport[] = teamMembers.map((tm, i) => ({
  id: `sr-${i + 1}`,
  organizationId: "org-1",
  teamMemberId: tm.id,
  iterationId: "iter-1",
  reportDate: "2026-02-19T09:30:00Z",
  completedItems: {
    items: i === 2
      ? [{ title: "Cart summary component styling", ticketId: "PROJ-203" }]
      : [],
  },
  inProgressItems: {
    items: [
      { title: workItems[i]?.title ?? "Working on assigned task", ticketId: workItems[i]?.externalId, prStatus: pullRequests[i]?.status as PullRequest["status"] | undefined },
    ],
  },
  blockers: {
    items: i === 1
      ? [{ description: "Waiting for Stripe API key provisioning from IT", ticketId: "PROJ-206", status: "OPEN" as const }]
      : [],
  },
  narrativeText: `${tm.displayName} continued work on sprint items. ${i === 2 ? "Completed cart summary component. " : ""}Progress is on track.`,
  acknowledged: i !== 3,
  acknowledgedAt: i !== 3 ? "2026-02-19T09:45:00Z" : undefined,
  isInactive: false,
}));

// ============================================================================
// BLOCKER FLAGS
// ============================================================================

export const blockerFlags: BlockerFlag[] = [
  {
    id: "bf-1",
    standupReportId: "sr-2",
    description: "Waiting for Stripe API key provisioning from IT - blocking webhook integration",
    ticketReference: "PROJ-206",
    status: "OPEN",
    flaggedAt: "2026-02-18T10:30:00Z",
  },
];

// ============================================================================
// HEALTH SIGNALS
// ============================================================================

export const healthSignals: HealthSignal[] = [
  { id: "hs-1", organizationId: "org-1", teamMemberId: "tm-2", signalType: "REVIEW_LAG", severity: "AMBER", message: "PR #298 awaiting review for 48+ hours", createdAt: "2026-02-18T10:00:00Z" },
  { id: "hs-2", organizationId: "org-1", teamMemberId: "tm-4", signalType: "STALLED_TICKET", severity: "AMBER", message: "PROJ-207 has had no activity for 2 days", createdAt: "2026-02-18T09:30:00Z" },
  { id: "hs-3", organizationId: "org-1", teamMemberId: "tm-2", signalType: "AFTER_HOURS", severity: "AMBER", message: "3 after-hours commits detected this week", createdAt: "2026-02-18T08:00:00Z" },
];

export const burnoutAlerts: BurnoutAlert[] = [
  {
    id: "ba-1",
    organizationId: "org-1",
    teamMemberId: "tm-2",
    severity: "AMBER",
    capacityUtilization: 0.92,
    consecutiveSprints: 3,
    afterHoursFrequency: 0.25,
    createdAt: "2026-02-17T08:00:00Z",
  },
];

// ============================================================================
// VELOCITY PROFILES
// ============================================================================

export const velocityProfiles: VelocityProfile[] = teamMembers.flatMap((tm) =>
  Array.from({ length: 8 }, (_, i) => ({
    id: `vp-${tm.id}-${i}`,
    teamMemberId: tm.id,
    iterationId: `iter-${i - 7 + 24}`,
    plannedSP: 8 + Math.floor(Math.random() * 6),
    completedSP: 6 + Math.floor(Math.random() * 8),
    rollingAverage: 9.5 + Math.random() * 3,
    isColdStart: false,
    recordedAt: new Date(2026, 0, 6 + i * 14).toISOString(),
  }))
);

// ============================================================================
// RETROSPECTIVE
// ============================================================================

export const latestRetrospective: Retrospective = {
  id: "retro-1",
  organizationId: "org-1",
  iterationId: "iter-0",
  whatWentWell: {
    items: [
      "Sprint goal achieved at 95% - all checkout UI stories completed",
      "Code review turnaround improved to under 12 hours average",
      "Zero production incidents during the sprint",
    ],
  },
  whatDidntGoWell: {
    items: [
      "Payment integration took 2x longer than estimated due to Stripe docs gaps",
      "One developer had 95% capacity utilization for the third consecutive sprint",
    ],
  },
  rootCauseAnalysis: {
    items: [
      { issue: "Payment integration delays", cause: "Incomplete spike story; Stripe sandbox setup not included in estimation" },
      { issue: "Sustained overallocation", cause: "No buffer built into capacity model for tech debt and support rotation" },
    ],
  },
  isDraft: false,
  finalizedAt: "2026-02-08T14:00:00Z",
  actionItems: [
    { id: "rai-1", retrospectiveId: "retro-1", title: "Include sandbox setup time in all integration spikes", assigneeId: "tm-2", dueDate: "2026-02-23T00:00:00Z", status: "in_progress", isCarryForward: false },
    { id: "rai-2", retrospectiveId: "retro-1", title: "Add 10% tech debt buffer to capacity model", assigneeId: "tm-1", dueDate: "2026-02-23T00:00:00Z", status: "open", isCarryForward: false },
  ],
};

// ============================================================================
// COMPUTED DATA
// ============================================================================

export const sprintOverview: SprintOverview = {
  iteration: currentIteration,
  plan: currentPlan,
  health: "GREEN",
  completionPct: 62,
  pacingPct: 65,
  daysRemaining: 4,
  totalSP: 58,
  completedSP: 36,
};

export const developerProgress: DeveloperProgress[] = teamMembers.map((tm, i) => ({
  teamMember: tm,
  assignedSP: [16, 18, 10, 11, 5, 3][i] ?? 8,
  completedSP: [11, 8, 10, 3, 2, 0][i] ?? 4,
  pacingStatus: (["GREEN", "AMBER", "GREEN", "AMBER", "GREEN", "GREEN"] as const)[i] ?? "GREEN",
  lastCommitAt: new Date(2026, 1, 19, 8 + i, 30).toISOString(),
  openPRs: [2, 2, 0, 0, 1, 0][i] ?? 0,
  blockers: [0, 1, 0, 0, 0, 0][i] ?? 0,
}));

export const backlogHealth: BacklogHealthScore = {
  overall: 72,
  percentEstimated: 85,
  percentWithAcceptanceCriteria: 68,
  percentStale: 12,
  percentWithUnresolvedDeps: 8,
};
