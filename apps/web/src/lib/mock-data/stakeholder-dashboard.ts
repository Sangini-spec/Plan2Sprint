import type { HealthSeverity, DeliveryPredictabilityScore } from "@/lib/types/models";

// ============================================================================
// PORTFOLIO SPRINT HEALTH
// ============================================================================

export interface PortfolioSprint {
  id: string;
  teamName: string;
  sprintName: string;
  health: HealthSeverity;
  completionPct: number;
  pacingPct: number;
  atRiskCount: number;
  daysRemaining: number;
}

export const portfolioSprints: PortfolioSprint[] = [
  { id: "ps-1", teamName: "Checkout Squad", sprintName: "Sprint 24", health: "GREEN", completionPct: 62, pacingPct: 65, atRiskCount: 2, daysRemaining: 4 },
  { id: "ps-2", teamName: "Search & Discovery", sprintName: "Sprint 24", health: "AMBER", completionPct: 45, pacingPct: 65, atRiskCount: 4, daysRemaining: 4 },
  { id: "ps-3", teamName: "Platform Core", sprintName: "Sprint 24", health: "GREEN", completionPct: 70, pacingPct: 65, atRiskCount: 1, daysRemaining: 4 },
  { id: "ps-4", teamName: "Mobile Team", sprintName: "Sprint 12", health: "RED", completionPct: 30, pacingPct: 65, atRiskCount: 6, daysRemaining: 4 },
  { id: "ps-5", teamName: "Data Pipeline", sprintName: "Sprint 24", health: "GREEN", completionPct: 72, pacingPct: 65, atRiskCount: 0, daysRemaining: 4 },
  { id: "ps-6", teamName: "DevOps & Infra", sprintName: "Sprint 24", health: "GREEN", completionPct: 80, pacingPct: 65, atRiskCount: 0, daysRemaining: 4 },
];

// ============================================================================
// TEAM HEALTH SUMMARY
// ============================================================================

export interface TeamHealthEntry {
  id: string;
  teamName: string;
  health: HealthSeverity;
  tooltip: string;
}

export const teamHealthSummary: TeamHealthEntry[] = [
  { id: "th-1", teamName: "Checkout Squad", health: "GREEN", tooltip: "Team health is stable" },
  { id: "th-2", teamName: "Search & Discovery", health: "AMBER", tooltip: "Capacity pressure detected" },
  { id: "th-3", teamName: "Platform Core", health: "GREEN", tooltip: "Team health is stable" },
  { id: "th-4", teamName: "Mobile Team", health: "RED", tooltip: "Sustained capacity overload" },
  { id: "th-5", teamName: "Data Pipeline", health: "GREEN", tooltip: "Team health is stable" },
  { id: "th-6", teamName: "DevOps & Infra", health: "GREEN", tooltip: "Team health is stable" },
];

// ============================================================================
// DELIVERY PREDICTABILITY
// ============================================================================

export const deliveryPredictability: DeliveryPredictabilityScore = {
  overall: 76,
  forecastAccuracy: 82,
  sprintGoalAttainment: 74,
  carryForwardRate: 18,
  trend: [
    { sprint: "Sprint 19", score: 68 },
    { sprint: "Sprint 20", score: 71 },
    { sprint: "Sprint 21", score: 73 },
    { sprint: "Sprint 22", score: 72 },
    { sprint: "Sprint 23", score: 78 },
    { sprint: "Sprint 24", score: 76 },
  ],
};

// ============================================================================
// EPICS & MILESTONES
// ============================================================================

export interface EpicProgress {
  id: string;
  name: string;
  owningTeam: string;
  totalTickets: number;
  completedTickets: number;
  projectedCompletion: string;
  riskFlag: HealthSeverity;
}

export const epicProgress: EpicProgress[] = [
  { id: "e-1", name: "Checkout Redesign", owningTeam: "Checkout Squad", totalTickets: 24, completedTickets: 18, projectedCompletion: "2026-03-07", riskFlag: "GREEN" },
  { id: "e-2", name: "Search V2", owningTeam: "Search & Discovery", totalTickets: 32, completedTickets: 14, projectedCompletion: "2026-04-15", riskFlag: "AMBER" },
  { id: "e-3", name: "Mobile App V3", owningTeam: "Mobile Team", totalTickets: 40, completedTickets: 12, projectedCompletion: "2026-05-01", riskFlag: "RED" },
  { id: "e-4", name: "Real-time Analytics", owningTeam: "Data Pipeline", totalTickets: 18, completedTickets: 15, projectedCompletion: "2026-02-28", riskFlag: "GREEN" },
  { id: "e-5", name: "Platform Migration", owningTeam: "Platform Core", totalTickets: 28, completedTickets: 22, projectedCompletion: "2026-03-14", riskFlag: "GREEN" },
];

export interface Milestone {
  id: string;
  name: string;
  date: string;
  status: HealthSeverity;
}

export const milestones: Milestone[] = [
  { id: "m-1", name: "Checkout Beta Launch", date: "2026-03-01", status: "GREEN" },
  { id: "m-2", name: "Search V2 Alpha", date: "2026-03-15", status: "AMBER" },
  { id: "m-3", name: "Mobile V3 TestFlight", date: "2026-04-01", status: "RED" },
  { id: "m-4", name: "Analytics Dashboard GA", date: "2026-02-28", status: "GREEN" },
];

// ============================================================================
// STANDUP REPLACEMENT STATUS
// ============================================================================

export interface StandupReplacementEntry {
  id: string;
  teamName: string;
  activated: boolean;
  activatedDate?: string;
  reportsThisSprint: number;
}

export const standupReplacement: StandupReplacementEntry[] = [
  { id: "srs-1", teamName: "Checkout Squad", activated: true, activatedDate: "2026-01-06", reportsThisSprint: 42 },
  { id: "srs-2", teamName: "Search & Discovery", activated: true, activatedDate: "2026-01-13", reportsThisSprint: 56 },
  { id: "srs-3", teamName: "Platform Core", activated: true, activatedDate: "2026-01-06", reportsThisSprint: 35 },
  { id: "srs-4", teamName: "Mobile Team", activated: true, activatedDate: "2026-01-20", reportsThisSprint: 28 },
  { id: "srs-5", teamName: "Data Pipeline", activated: true, activatedDate: "2026-02-03", reportsThisSprint: 21 },
  { id: "srs-6", teamName: "DevOps & Infra", activated: false, reportsThisSprint: 0 },
];

// ============================================================================
// PORTFOLIO SUMMARY STATS
// ============================================================================

export const portfolioStats = {
  totalTeams: 6,
  sprintsOnTrack: 4,
  sprintsAmber: 1,
  sprintsRed: 1,
  overallPredictability: 76,
  standupMeetingsReplaced: 5,
  totalReportsGenerated: 182,
};
