/**
 * Mock data for integration API responses.
 * Used in demo mode to simulate Jira, ADO, and GitHub data.
 */

import type {
  JiraProject,
  JiraSprint,
  AdoProject,
  AdoIteration,
  GitHubRepo,
} from "@/lib/integrations/types";
import type { PullRequest, Commit } from "@/lib/types/models";

// ============================================================================
// JIRA MOCK DATA
// ============================================================================

export const mockJiraProjects: JiraProject[] = [
  { id: "jp-1", key: "PROJ", name: "Main Product", projectType: "scrum", avatarUrl: undefined },
  { id: "jp-2", key: "INFRA", name: "Infrastructure", projectType: "kanban", avatarUrl: undefined },
  { id: "jp-3", key: "MOBILE", name: "Mobile App", projectType: "scrum", avatarUrl: undefined },
  { id: "jp-4", key: "DESIGN", name: "Design System", projectType: "scrum", avatarUrl: undefined },
];

export const mockJiraSprints: JiraSprint[] = [
  { id: "js-1", name: "Sprint 24", state: "active", startDate: "2026-02-09T00:00:00Z", endDate: "2026-02-23T00:00:00Z", boardId: "board-1" },
  { id: "js-2", name: "Sprint 25", state: "future", startDate: "2026-02-23T00:00:00Z", endDate: "2026-03-09T00:00:00Z", boardId: "board-1" },
  { id: "js-3", name: "Sprint 23", state: "closed", startDate: "2026-01-26T00:00:00Z", endDate: "2026-02-09T00:00:00Z", boardId: "board-1" },
];

// ============================================================================
// ADO MOCK DATA
// ============================================================================

export const mockAdoProjects: AdoProject[] = [
  { id: "ap-1", name: "Acme Platform", description: "Main platform project", state: "wellFormed", url: "https://dev.azure.com/acme/AcmePlatform" },
  { id: "ap-2", name: "Acme Mobile", description: "Mobile app project", state: "wellFormed", url: "https://dev.azure.com/acme/AcmeMobile" },
  { id: "ap-3", name: "Acme Internal", description: "Internal tools", state: "wellFormed", url: "https://dev.azure.com/acme/AcmeInternal" },
];

export const mockAdoIterations: AdoIteration[] = [
  { id: "ai-1", name: "Sprint 24", path: "Acme Platform\\Sprint 24", startDate: "2026-02-09T00:00:00Z", finishDate: "2026-02-23T00:00:00Z" },
  { id: "ai-2", name: "Sprint 25", path: "Acme Platform\\Sprint 25", startDate: "2026-02-23T00:00:00Z", finishDate: "2026-03-09T00:00:00Z" },
  { id: "ai-3", name: "Sprint 23", path: "Acme Platform\\Sprint 23", startDate: "2026-01-26T00:00:00Z", finishDate: "2026-02-09T00:00:00Z" },
];

// ============================================================================
// GITHUB MOCK DATA
// ============================================================================

export const mockGitHubRepos: GitHubRepo[] = [
  { id: "gr-1", name: "acme-web", fullName: "acme-org/acme-web", defaultBranch: "main", url: "https://github.com/acme-org/acme-web", isPrivate: true, language: "TypeScript", openIssuesCount: 12, stargazersCount: 45 },
  { id: "gr-2", name: "acme-api", fullName: "acme-org/acme-api", defaultBranch: "main", url: "https://github.com/acme-org/acme-api", isPrivate: true, language: "Python", openIssuesCount: 8, stargazersCount: 32 },
  { id: "gr-3", name: "acme-mobile", fullName: "acme-org/acme-mobile", defaultBranch: "develop", url: "https://github.com/acme-org/acme-mobile", isPrivate: true, language: "TypeScript", openIssuesCount: 5, stargazersCount: 18 },
  { id: "gr-4", name: "acme-infra", fullName: "acme-org/acme-infra", defaultBranch: "main", url: "https://github.com/acme-org/acme-infra", isPrivate: true, language: "HCL", openIssuesCount: 3, stargazersCount: 8 },
  { id: "gr-5", name: "design-system", fullName: "acme-org/design-system", defaultBranch: "main", url: "https://github.com/acme-org/design-system", isPrivate: false, language: "TypeScript", openIssuesCount: 2, stargazersCount: 120 },
];

export const mockGitHubPRs: PullRequest[] = [
  { id: "gpr-1", repositoryId: "gr-1", externalId: "gh-412", number: 412, title: "feat: checkout flow step navigation", status: "AWAITING_REVIEW", authorId: "tm-1", reviewers: ["tm-3", "tm-5"], ciStatus: "PASSING", linkedWorkItemId: "wi-1", url: "https://github.com/acme-org/acme-web/pull/412", createdExternalAt: "2026-02-19T14:30:00Z" },
  { id: "gpr-2", repositoryId: "gr-2", externalId: "gh-189", number: 189, title: "feat: Stripe payment intent endpoint", status: "CHANGES_REQUESTED", authorId: "tm-2", reviewers: ["tm-4"], ciStatus: "PASSING", linkedWorkItemId: "wi-2", url: "https://github.com/acme-org/acme-api/pull/189", createdExternalAt: "2026-02-18T10:00:00Z" },
  { id: "gpr-3", repositoryId: "gr-1", externalId: "gh-415", number: 415, title: "fix: mobile checkout responsive layout", status: "APPROVED", authorId: "tm-1", reviewers: ["tm-3"], ciStatus: "PASSING", linkedWorkItemId: "wi-5", url: "https://github.com/acme-org/acme-web/pull/415", createdExternalAt: "2026-02-19T09:15:00Z" },
  { id: "gpr-4", repositoryId: "gr-2", externalId: "gh-191", number: 191, title: "feat: webhook signature verification", status: "OPEN", authorId: "tm-2", reviewers: ["tm-4", "tm-6"], ciStatus: "FAILING", linkedWorkItemId: "wi-6", url: "https://github.com/acme-org/acme-api/pull/191", createdExternalAt: "2026-02-18T16:00:00Z" },
  { id: "gpr-5", repositoryId: "gr-1", externalId: "gh-413", number: 413, title: "feat: address autocomplete with Google Places", status: "AWAITING_REVIEW", authorId: "tm-5", reviewers: ["tm-1"], ciStatus: "PASSING", linkedWorkItemId: "wi-8", url: "https://github.com/acme-org/acme-web/pull/413", createdExternalAt: "2026-02-19T16:45:00Z" },
  { id: "gpr-6", repositoryId: "gr-3", externalId: "gh-78", number: 78, title: "chore: upgrade React Native to 0.76", status: "MERGED", authorId: "tm-5", reviewers: ["tm-1"], ciStatus: "PASSING", url: "https://github.com/acme-org/acme-mobile/pull/78", createdExternalAt: "2026-02-17T11:00:00Z", mergedAt: "2026-02-18T14:00:00Z" },
];

export const mockGitHubCommits: Commit[] = [
  { id: "gc-1", repositoryId: "gr-1", sha: "a1b2c3d", message: "feat: add checkout step component", authorId: "tm-1", branch: "feat/checkout-flow", linkedTicketIds: ["PROJ-201"], filesChanged: 5, committedAt: "2026-02-19T14:15:00Z" },
  { id: "gc-2", repositoryId: "gr-2", sha: "e4f5g6h", message: "feat: implement Stripe payment intent creation", authorId: "tm-2", branch: "feat/payment-gateway", linkedTicketIds: ["PROJ-202"], filesChanged: 3, committedAt: "2026-02-19T11:30:00Z" },
  { id: "gc-3", repositoryId: "gr-1", sha: "i7j8k9l", message: "fix: responsive grid on mobile checkout", authorId: "tm-1", branch: "fix/mobile-checkout", linkedTicketIds: ["PROJ-205"], filesChanged: 2, committedAt: "2026-02-19T09:00:00Z" },
  { id: "gc-4", repositoryId: "gr-2", sha: "m0n1o2p", message: "feat: add Stripe webhook signature verification", authorId: "tm-2", branch: "feat/stripe-webhooks", linkedTicketIds: ["PROJ-206"], filesChanged: 4, committedAt: "2026-02-18T17:45:00Z" },
  { id: "gc-5", repositoryId: "gr-1", sha: "q3r4s5t", message: "feat: Google Places autocomplete integration", authorId: "tm-5", branch: "feat/address-autocomplete", linkedTicketIds: ["PROJ-208"], filesChanged: 6, committedAt: "2026-02-19T16:30:00Z" },
  { id: "gc-6", repositoryId: "gr-4", sha: "u6v7w8x", message: "chore: update Terraform modules to v5", authorId: "tm-4", branch: "chore/terraform-upgrade", linkedTicketIds: [], filesChanged: 12, committedAt: "2026-02-18T14:00:00Z" },
  { id: "gc-7", repositoryId: "gr-1", sha: "y9z0a1b", message: "test: add E2E tests for cart summary", authorId: "tm-3", branch: "test/cart-e2e", linkedTicketIds: ["PROJ-203"], filesChanged: 3, committedAt: "2026-02-18T11:20:00Z" },
];

// ============================================================================
// MOCK AUDIT LOG ENTRIES
// ============================================================================

export const mockAuditEntries = [
  { id: "ma-1", timestamp: "2026-02-19T10:00:00Z", tool: "jira" as const, action: "connected" as const, details: "Connected Jira Cloud (acme.atlassian.net)", success: true },
  { id: "ma-2", timestamp: "2026-02-19T10:01:00Z", tool: "jira" as const, action: "synced" as const, details: "Initial sync: 47 work items, 3 sprints, 8 team members", success: true },
  { id: "ma-3", timestamp: "2026-02-19T10:15:00Z", tool: "github" as const, action: "connected" as const, details: "Connected GitHub App (acme-org, 5 repos)", success: true },
  { id: "ma-4", timestamp: "2026-02-19T10:16:00Z", tool: "github" as const, action: "synced" as const, details: "Initial sync: 12 PRs, 45 commits", success: true },
  { id: "ma-5", timestamp: "2026-02-19T12:30:00Z", tool: "jira" as const, action: "webhook_received" as const, details: "jira:issue_updated PROJ-201", success: true },
  { id: "ma-6", timestamp: "2026-02-19T14:00:00Z", tool: "jira" as const, action: "writeback" as const, details: "Updated assignee on PROJ-204", success: true },
];
