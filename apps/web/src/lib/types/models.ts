/**
 * Domain model interfaces matching the Supabase/PostgreSQL schema.
 * Used for mock data and component props.
 */

// ============================================================================
// ENUMS
// ============================================================================

export type SprintPlanStatus =
  | "GENERATING"
  | "PENDING_REVIEW"
  | "APPROVED"
  | "REJECTED"
  | "REGENERATING"
  | "SYNCING"
  | "SYNCED"
  | "SYNCED_PARTIAL"
  | "UNDONE"
  | "EXPIRED"
  // Hotfix 24 — async generation. ``FAILED`` is set by the
  // background task when generation crashes or times out, so the
  // frontend polling can stop and surface a clear error message.
  | "FAILED";

export type WorkItemStatus =
  | "BACKLOG"
  | "TODO"
  | "IN_PROGRESS"
  | "IN_REVIEW"
  | "DONE"
  | "CLOSED";

export type PRStatus =
  | "OPEN"
  | "AWAITING_REVIEW"
  | "CHANGES_REQUESTED"
  | "APPROVED"
  | "MERGED"
  | "CLOSED";

export type CIStatus = "PASSING" | "FAILING" | "PENDING" | "UNKNOWN";

export type HealthSignalType =
  | "BURNOUT_RISK"
  | "VELOCITY_VARIANCE"
  | "STALLED_TICKET"
  | "REVIEW_LAG"
  | "CI_FAILURE"
  | "AFTER_HOURS"
  | "INACTIVITY"
  | "CAPACITY_OVERLOAD";

export type HealthSeverity = "GREEN" | "AMBER" | "RED";

export type SourceTool = "JIRA" | "ADO" | "GITHUB" | "NOTION" | "LINEAR";

export type BlockerStatus = "OPEN" | "ACKNOWLEDGED" | "ESCALATED" | "RESOLVED";

// ============================================================================
// DOMAIN MODELS
// ============================================================================

export interface Organization {
  id: string;
  name: string;
  slug: string;
  timezone: string;
  workingHoursStart: string;
  workingHoursEnd: string;
  standupTime: string;
}

export interface TeamMember {
  id: string;
  organizationId: string;
  externalId: string;
  email: string;
  displayName: string;
  avatarUrl?: string;
  skillTags: string[];
  defaultCapacity: number;
  slackUserId?: string;
  teamsUserId?: string;
}

export interface WorkItem {
  id: string;
  organizationId: string;
  externalId: string;
  sourceTool: SourceTool;
  title: string;
  description?: string;
  status: WorkItemStatus;
  storyPoints?: number;
  priority: number;
  type: string;
  labels: string[];
  acceptanceCriteria?: string;
  epicId?: string;
  plannedStart?: string;
  plannedEnd?: string;
  iterationId?: string;
  assigneeId?: string;
}

export interface Iteration {
  id: string;
  organizationId: string;
  externalId: string;
  sourceTool: SourceTool;
  name: string;
  goal?: string;
  startDate: string;
  endDate: string;
  state: string;
}

export interface Repository {
  id: string;
  organizationId: string;
  externalId: string;
  name: string;
  fullName: string;
  defaultBranch: string;
  url: string;
}

export interface PullRequest {
  id: string;
  repositoryId: string;
  externalId: string;
  number: number;
  title: string;
  status: PRStatus;
  authorId?: string;
  reviewers: string[];
  ciStatus: CIStatus;
  linkedWorkItemId?: string;
  url: string;
  createdExternalAt: string;
  mergedAt?: string;
}

export interface Commit {
  id: string;
  repositoryId: string;
  sha: string;
  message: string;
  authorId?: string;
  branch: string;
  linkedTicketIds: string[];
  filesChanged: number;
  committedAt: string;
}

export interface ActivityEvent {
  id: string;
  organizationId: string;
  teamMemberId: string;
  eventType: string;
  sourceTool: SourceTool;
  externalId?: string;
  linkedTicketId?: string;
  metadata?: Record<string, unknown>;
  isAfterHours: boolean;
  isWeekend: boolean;
  occurredAt: string;
}

export interface StandupReportItem {
  title: string;
  ticketId?: string;
  prId?: string;
  prStatus?: PRStatus;
}

export interface StandupReport {
  id: string;
  organizationId: string;
  teamMemberId: string;
  iterationId?: string;
  reportDate: string;
  completedItems: { items: StandupReportItem[] };
  inProgressItems: { items: StandupReportItem[] };
  blockers: { items: { description: string; ticketId?: string; status: BlockerStatus }[] };
  narrativeText: string;
  acknowledged: boolean;
  acknowledgedAt?: string;
  developerNote?: string;
  isInactive: boolean;
}

export interface TeamStandupDigest {
  id: string;
  organizationId: string;
  iterationId?: string;
  digestDate: string;
  sprintPacing: number;
  acknowledgedPct: number;
  sprintHealth: HealthSeverity;
  atRiskItems: { items: { workItemId: string; reason: string }[] };
  blockerCount: number;
  summaryText: string;
}

export interface BlockerFlag {
  id: string;
  standupReportId: string;
  description: string;
  ticketReference?: string;
  status: BlockerStatus;
  flaggedAt: string;
  resolvedAt?: string;
}

export interface SprintPlan {
  id: string;
  organizationId: string;
  iterationId: string;
  status: SprintPlanStatus;
  confidenceScore?: number;
  riskSummary?: string;
  totalStoryPoints?: number;
  unplannedItems?: { items: { workItemId: string; reason: string }[] };
  aiModelUsed?: string;
  rejectionFeedback?: string;
  approvedById?: string;
  approvedAt?: string;
  syncedAt?: string;
  undoAvailableUntil?: string;
  assignments?: PlanAssignment[];
}

export interface PlanAssignment {
  id: string;
  sprintPlanId: string;
  workItemId: string;
  teamMemberId: string;
  storyPoints: number;
  confidenceScore: number;
  rationale: string;
  riskFlags: string[];
  skillMatch?: { matchedSkills: string[]; score: number };
  isHumanEdited: boolean;
}

export interface VelocityProfile {
  id: string;
  teamMemberId: string;
  iterationId?: string;
  plannedSP: number;
  completedSP: number;
  rollingAverage?: number;
  byTicketType?: Record<string, number>;
  isColdStart: boolean;
  recordedAt: string;
}

export interface HealthSignal {
  id: string;
  organizationId: string;
  teamMemberId: string;
  signalType: HealthSignalType;
  severity: HealthSeverity;
  message: string;
  metadata?: Record<string, unknown>;
  resolvedAt?: string;
  createdAt: string;
}

export interface BurnoutAlert {
  id: string;
  organizationId: string;
  teamMemberId: string;
  severity: HealthSeverity;
  capacityUtilization: number;
  consecutiveSprints: number;
  afterHoursFrequency: number;
  acknowledgedAt?: string;
  createdAt: string;
}

export interface Retrospective {
  id: string;
  organizationId: string;
  iterationId?: string;
  whatWentWell: { items: string[] };
  whatDidntGoWell: { items: string[] };
  rootCauseAnalysis?: { items: { issue: string; cause: string }[] };
  isDraft: boolean;
  finalizedAt?: string;
  actionItems?: RetroActionItem[];
}

export interface RetroActionItem {
  id: string;
  retrospectiveId: string;
  title: string;
  assigneeId?: string;
  dueDate?: string;
  status: string;
  isCarryForward: boolean;
}

export interface AuditLogEntry {
  id: string;
  organizationId: string;
  actorId: string;
  actorRole: string;
  eventType: string;
  resourceType: string;
  resourceId: string;
  beforeState?: Record<string, unknown>;
  afterState?: Record<string, unknown>;
  sourceChannel?: string;
  success: boolean;
  metadata?: Record<string, unknown>;
  createdAt: string;
}

// ============================================================================
// COMPUTED / DASHBOARD TYPES
// ============================================================================

export interface SprintOverview {
  iteration: Iteration;
  plan?: SprintPlan;
  health: HealthSeverity;
  completionPct: number;
  pacingPct: number;
  daysRemaining: number;
  totalSP: number;
  completedSP: number;
}

export interface DeveloperProgress {
  teamMember: TeamMember;
  assignedSP: number;
  completedSP: number;
  pacingStatus: HealthSeverity;
  lastCommitAt?: string;
  openPRs: number;
  blockers: number;
}

export interface BacklogHealthScore {
  overall: number; // 0-100
  percentEstimated: number;
  percentWithAcceptanceCriteria: number;
  percentStale: number;
  percentWithUnresolvedDeps: number;
}

export interface DeliveryPredictabilityScore {
  overall: number; // 0-100
  forecastAccuracy: number;
  sprintGoalAttainment: number;
  carryForwardRate: number;
  trend: { sprint: string; score: number }[];
}

// ============================================================================
// PHASES
// ============================================================================

export interface ProjectPhase {
  id: string;
  name: string;
  slug: string;
  color: string;
  sortOrder: number;
  isDefault: boolean;
  featureCount?: number;
}

export interface PhaseAssignmentRule {
  id: string;
  phaseId: string;
  ruleType: "keyword" | "board_column" | "iteration_path";
  pattern: string;
  priority: number;
}

// ============================================================================
// FEATURE PROGRESS / PROJECT PLAN TYPES
// ============================================================================

export interface FeatureBreakdown {
  done: number;
  inProgress: number;
  readyForTest: number;
  remaining: number;
}

export interface FeatureProgressCard {
  id: string;
  externalId: string;
  title: string;
  description: string;
  phaseId: string | null;
  phaseInfo?: ProjectPhase;
  completePct: number;
  totalStories: number;
  breakdown: FeatureBreakdown;
  plannedStart?: string;
  plannedEnd?: string;
  sourceStatus?: string;
  sourceTool?: string;
}

export interface FeatureProgressData {
  totalFeatures: number;
  totalStories: number;
  overallCompletePct: number;
  readyForTestCount: number;
  features: FeatureProgressCard[];
  /** Composite confidence score (0-100) — replaces SprintPlan.confidence_score
   * for the PO hero banner KPI. ``null`` when no approved plan exists yet. */
  confidence?: ConfidenceBlock | null;
}

export interface ConfidenceBlock {
  score: number | null;
  breakdown: {
    velocity: number | null;
    cicd: number | null;
    aiPlan: number | null;
    targetFeasibility: number | null;
    sprintReliability: number | null;
  };
  /** Rescaled weights the breakdown values were combined with. Keys
   * correspond to the breakdown field names in snake_case (e.g. "velocity",
   * "cicd", "ai_plan", "target_feasibility", "sprint_reliability"). */
  weights: Record<string, number>;
  factorsUsed: string[];
  reasonHidden: string | null;
}

export type GanttStatus = "not_started" | "in_progress" | "blocked" | "complete";

export interface ProjectPlanRow {
  id: string;
  externalId: string;
  title: string;
  phaseId: string | null;
  phaseInfo?: ProjectPhase;
  status: GanttStatus;
  completePct: number;
  totalStories: number;
  doneStories: number;
  plannedStart?: string;
  plannedEnd?: string;
  actualStart?: string;
  actualEnd?: string;
  assignees: string[];
  /* Sprint E — true when the PO has marked this feature as hidden from
   * the Gantt. The row is only included in the payload when the request
   * was made with ``includeHidden=1``. */
  hidden?: boolean;
  /* Diagnostic — raw external status string from ADO/Jira (e.g. "Resolved",
   * "In Review", "Deployed"). Surfaced on hover so the PO can see what
   * string the upstream tool actually returned, useful for diagnosing
   * features that the terminal-status alias list missed. */
  sourceStatus?: string | null;
}

export interface ProjectPlanData {
  features: ProjectPlanRow[];
  /** Hotfix 34 — split former ``unassigned`` into two semantic buckets.
   *  ``completed``: features with terminal status (delivered already).
   *  ``outOfPlan``: features with open stories not in current sprint plan.
   *  ``unassigned`` is kept for back-compat = completed + outOfPlan. */
  unassigned: ProjectPlanRow[];
  completed?: ProjectPlanRow[];
  outOfPlan?: ProjectPlanRow[];
  /** Optimized view: features added since the latest plan was created.
   *  Drives the "Regenerate to include them" banner above the
   *  Out of Plan section. */
  newSincePlan?: { count: number; titles: string[] };
  phases: ProjectPhase[];
  totalPhases: number;
  complete: number;
  inProgress: number;
  estDurationWeeks?: number;
  /* Present only in the /project-plan/optimized response */
  hasPlan?: boolean;
  planId?: string;
  planStatus?: SprintPlanStatus;
  planCreatedAt?: string;
  isRebalanced?: boolean;
  /* Timeline revamp (Sprint 6+): authoritative source of truth for the PO
   * hero banner. When present, the hero banner ignores its local date math
   * and renders directly from this block. */
  timeline?: TimelineBlock | null;
  /* Sprint E — visibility toggle. ``hiddenCount`` is the number of features
   * the PO has hidden from the Gantt; ``includeHidden`` mirrors the request
   * parameter so the UI knows whether the current payload includes the
   * hidden rows or not. Both are optional because legacy/cached payloads
   * may predate the flag. */
  hiddenCount?: number;
  includeHidden?: boolean;
}

export type TimelineMode = "RAW" | "AI_OPTIMIZED" | "REBALANCED";
export type TargetLaunchSource = "AUTO" | "MANUAL" | null;
export type CurrentPhaseSource = "ADO" | "GITHUB" | "BOTH" | null;

export interface TimelinePhaseRow {
  id: string;
  slug: string;
  name: string;
  sortOrder: number;
  color: string;
  /* ISO 8601 datetime or null when dates aren't known yet (TBD in UI). */
  plannedStart: string | null;
  plannedEnd: string | null;
}

export interface TimelineBlock {
  mode: TimelineMode;
  phases: TimelinePhaseRow[];
  targetLaunchDate: string | null;
  targetLaunchSource: TargetLaunchSource;
  targetViolated: boolean;
  targetViolatedDays: number;
  currentPhaseSlug: string | null;
  currentPhaseSource: CurrentPhaseSource;
  /* Hotfix 16 — phases the project's frontier has passed but which
   * still have in-flight items. Hero-banner timeline renders these in
   * a cyan glow so stakeholders see "Deployment is current, Testing
   * still has loose ends" without conflating the two states. Empty /
   * undefined when nothing is straggling. */
  alsoActivePhaseSlugs?: string[];
  /* Hotfix 83 — project lifecycle status relative to its target launch:
   *   "on_track"       — target unset, project archived, or still
   *                      within grace
   *   "overdue"        — past target_launch_date + 24h grace AND
   *                      completion < 100%. Triggers red Target Launch
   *                      tile, "PLAN OVERDUE" badge, and the cron-fired
   *                      one-shot email to the PO.
   *   "delivered_late" — past target but completion = 100%. Amber
   *                      "DELIVERED LATE" badge, no email.
   * ``daysPastTarget`` is the integer day count past the target;
   * always 0 when status === "on_track". */
  lifecycleStatus?: "on_track" | "overdue" | "delivered_late";
  daysPastTarget?: number;
}

export interface PlanSummaryData {
  hasPlan: boolean;
  planId?: string;
  status?: SprintPlanStatus;
  estimatedEndDate?: string;
  estimatedWeeksTotal?: number;
  estimatedSprints?: number;
  confidenceScore?: number;
  successProbability?: number;
  totalStoryPoints?: number;
  riskSummary?: string;
  projectCompletionSummary?: string;
  approvedAt?: string;
  createdAt?: string;
  isRebalanced?: boolean;
}
