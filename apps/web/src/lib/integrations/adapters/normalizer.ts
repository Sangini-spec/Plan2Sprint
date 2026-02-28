/**
 * Normalize tool-specific data into unified domain model types.
 */

import type { WorkItem, PullRequest, Iteration } from "@/lib/types/models";
import type { JiraSprint, AdoIteration } from "../types";

/**
 * Normalize a Jira sprint to the unified Iteration type.
 */
export function normalizeJiraSprint(sprint: JiraSprint, orgId: string): Iteration {
  return {
    id: `jira-sprint-${sprint.id}`,
    organizationId: orgId,
    externalId: sprint.id,
    sourceTool: "JIRA",
    name: sprint.name,
    startDate: sprint.startDate ?? "",
    endDate: sprint.endDate ?? "",
    state: sprint.state,
  };
}

/**
 * Normalize an ADO iteration to the unified Iteration type.
 */
export function normalizeAdoIteration(iteration: AdoIteration, orgId: string): Iteration {
  return {
    id: `ado-iter-${iteration.id}`,
    organizationId: orgId,
    externalId: iteration.id,
    sourceTool: "ADO",
    name: iteration.name,
    startDate: iteration.startDate ?? "",
    endDate: iteration.finishDate ?? "",
    state: "active",
  };
}

/**
 * Normalize work items from any source to a consistent format.
 */
export function normalizeWorkItem(
  raw: Partial<WorkItem> & { id: string; title: string }
): WorkItem {
  return {
    id: raw.id,
    organizationId: raw.organizationId ?? "org-1",
    externalId: raw.externalId ?? raw.id,
    sourceTool: raw.sourceTool ?? "JIRA",
    title: raw.title,
    description: raw.description,
    status: raw.status ?? "TODO",
    storyPoints: raw.storyPoints,
    priority: raw.priority ?? 2,
    type: raw.type ?? "story",
    labels: raw.labels ?? [],
    iterationId: raw.iterationId,
    assigneeId: raw.assigneeId,
  };
}

/**
 * Normalize pull request from any source.
 */
export function normalizePullRequest(
  raw: Partial<PullRequest> & { id: string; title: string }
): PullRequest {
  return {
    id: raw.id,
    repositoryId: raw.repositoryId ?? "",
    externalId: raw.externalId ?? raw.id,
    number: raw.number ?? 0,
    title: raw.title,
    status: raw.status ?? "OPEN",
    authorId: raw.authorId,
    reviewers: raw.reviewers ?? [],
    ciStatus: raw.ciStatus ?? "UNKNOWN",
    linkedWorkItemId: raw.linkedWorkItemId,
    url: raw.url ?? "",
    createdExternalAt: raw.createdExternalAt ?? new Date().toISOString(),
    mergedAt: raw.mergedAt,
  };
}
