/**
 * Azure DevOps API adapter.
 * Uses PAT (Personal Access Token) + Organization URL for authentication.
 * When real credentials (PAT + orgUrl) are provided, ALWAYS uses real API.
 * Falls back to mock data ONLY when no credentials exist AND isDemoMode is true.
 */

import type { AdoProject, AdoIteration, AdoWorkItem, AdoTeamMember } from "../types";
import type { WorkItem } from "@/lib/types/models";
import { validateWritebackFields } from "../writeback";
import {
  mockAdoProjects,
  mockAdoIterations,
} from "@/lib/mock-data/integration-data";
import { workItems as mockWorkItems } from "@/lib/mock-data/po-dashboard";

const isDemoMode =
  !process.env.NEXT_PUBLIC_SUPABASE_URL ||
  process.env.NEXT_PUBLIC_SUPABASE_URL === "https://your-project.supabase.co";

export class AdoAdapter {
  private pat: string;
  private orgUrl: string;
  /** True when real credentials are provided - always use real API */
  private hasRealCredentials: boolean;

  constructor(pat: string, orgUrl: string) {
    this.pat = pat;
    this.orgUrl = orgUrl.replace(/\/+$/, "");
    this.hasRealCredentials = Boolean(pat && orgUrl && orgUrl.length > 5);
  }

  /** Return true if we should use mock data (no credentials + demo mode) */
  private get useMock(): boolean {
    return !this.hasRealCredentials && isDemoMode;
  }

  private get authHeader(): string {
    return `Basic ${Buffer.from(`:${this.pat}`).toString("base64")}`;
  }

  async getProjects(): Promise<AdoProject[]> {
    if (this.useMock) return mockAdoProjects;

    const res = await fetch(
      `${this.orgUrl}/_apis/projects?api-version=7.0`,
      {
        headers: {
          Authorization: this.authHeader,
          "Content-Type": "application/json",
        },
      }
    );
    if (!res.ok) throw new Error(`ADO API error: ${res.status}`);
    const data = await res.json();
    return data.value.map((p: Record<string, string>) => ({
      id: p.id,
      name: p.name,
      description: p.description,
      state: p.state,
      url: p.url,
    }));
  }

  async getIterations(projectName: string): Promise<AdoIteration[]> {
    if (this.useMock) return mockAdoIterations;

    const res = await fetch(
      `${this.orgUrl}/${encodeURIComponent(projectName)}/_apis/work/teamsettings/iterations?api-version=7.0`,
      {
        headers: {
          Authorization: this.authHeader,
          "Content-Type": "application/json",
        },
      }
    );
    if (!res.ok) throw new Error(`ADO API error: ${res.status}`);
    const data = await res.json();
    return data.value.map((i: Record<string, string | Record<string, string>>) => ({
      id: i.id as string,
      name: i.name as string,
      path: i.path as string,
      startDate: (i.attributes as Record<string, string>)?.startDate,
      finishDate: (i.attributes as Record<string, string>)?.finishDate,
    }));
  }

  /** Fetch ALL work items for a project (features, epics, stories, bugs, tasks) */
  async getWorkItemsByProject(projectName: string): Promise<AdoWorkItem[]> {
    if (this.useMock) {
      return mockWorkItems.map((wi) => ({
        id: parseInt(wi.externalId.replace(/\D/g, "") || "0"),
        title: wi.title,
        state: wi.status,
        workItemType: wi.type ?? "User Story",
        assignedTo: wi.assigneeId ?? undefined,
        storyPoints: wi.storyPoints,
        priority: wi.priority,
      }));
    }

    // WIQL query - fetch ALL work item types from the project
    const res = await fetch(
      `${this.orgUrl}/${encodeURIComponent(projectName)}/_apis/wit/wiql?api-version=7.0`,
      {
        method: "POST",
        headers: {
          Authorization: this.authHeader,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          query: `SELECT [System.Id], [System.Title], [System.State], [System.WorkItemType], [System.AssignedTo], [Microsoft.VSTS.Scheduling.StoryPoints], [System.AreaPath], [System.IterationPath], [System.Tags], [System.CreatedDate], [System.ChangedDate], [System.Description], [Microsoft.VSTS.Common.Priority], [Microsoft.VSTS.Scheduling.Effort] FROM WorkItems WHERE [System.TeamProject] = '${projectName}' ORDER BY [System.WorkItemType] ASC, [System.Id] ASC`,
        }),
      }
    );
    if (!res.ok) throw new Error(`ADO WIQL error: ${res.status}`);
    const wiqlData = await res.json();

    const ids = (wiqlData.workItems ?? []).map((wi: { id: number }) => wi.id).slice(0, 200);
    if (ids.length === 0) return [];

    // Fetch full work item details in batches of 200
    const detailsRes = await fetch(
      `${this.orgUrl}/_apis/wit/workitems?ids=${ids.join(",")}&$expand=all&api-version=7.0`,
      {
        headers: {
          Authorization: this.authHeader,
          "Content-Type": "application/json",
        },
      }
    );
    if (!detailsRes.ok) throw new Error(`ADO work items error: ${detailsRes.status}`);
    const detailsData = await detailsRes.json();

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return (detailsData.value ?? []).map((wi: any) => ({
      id: wi.id,
      title: wi.fields?.["System.Title"] ?? "",
      state: wi.fields?.["System.State"] ?? "",
      workItemType: wi.fields?.["System.WorkItemType"] ?? "",
      assignedTo: wi.fields?.["System.AssignedTo"]?.displayName ?? undefined,
      areaPath: wi.fields?.["System.AreaPath"] ?? undefined,
      iterationPath: wi.fields?.["System.IterationPath"] ?? undefined,
      storyPoints: wi.fields?.["Microsoft.VSTS.Scheduling.StoryPoints"] ?? wi.fields?.["Microsoft.VSTS.Scheduling.Effort"] ?? undefined,
      priority: wi.fields?.["Microsoft.VSTS.Common.Priority"] ?? undefined,
      tags: wi.fields?.["System.Tags"] ?? undefined,
      createdDate: wi.fields?.["System.CreatedDate"] ?? undefined,
      changedDate: wi.fields?.["System.ChangedDate"] ?? undefined,
      description: wi.fields?.["System.Description"] ?? undefined,
    }));
  }

  /** Fetch work items scoped to a specific iteration path */
  async getWorkItemsByIteration(projectName: string, iterationPath: string): Promise<AdoWorkItem[]> {
    if (this.useMock) {
      return mockWorkItems.map((wi) => ({
        id: parseInt(wi.externalId.replace(/\D/g, "") || "0"),
        title: wi.title,
        state: wi.status,
        workItemType: wi.type ?? "User Story",
        assignedTo: wi.assigneeId ?? undefined,
        storyPoints: wi.storyPoints,
        priority: wi.priority,
      }));
    }

    const res = await fetch(
      `${this.orgUrl}/${encodeURIComponent(projectName)}/_apis/wit/wiql?api-version=7.0`,
      {
        method: "POST",
        headers: {
          Authorization: this.authHeader,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          query: `SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = '${projectName}' AND [System.IterationPath] = '${iterationPath}' ORDER BY [Microsoft.VSTS.Common.BacklogPriority] ASC`,
        }),
      }
    );
    if (!res.ok) throw new Error(`ADO WIQL error: ${res.status}`);
    const wiqlData = await res.json();

    const ids = (wiqlData.workItems ?? []).map((wi: { id: number }) => wi.id).slice(0, 200);
    if (ids.length === 0) return [];

    const detailsRes = await fetch(
      `${this.orgUrl}/_apis/wit/workitems?ids=${ids.join(",")}&$expand=all&api-version=7.0`,
      {
        headers: {
          Authorization: this.authHeader,
          "Content-Type": "application/json",
        },
      }
    );
    if (!detailsRes.ok) throw new Error(`ADO work items error: ${detailsRes.status}`);
    const detailsData = await detailsRes.json();

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return (detailsData.value ?? []).map((wi: any) => ({
      id: wi.id,
      title: wi.fields?.["System.Title"] ?? "",
      state: wi.fields?.["System.State"] ?? "",
      workItemType: wi.fields?.["System.WorkItemType"] ?? "",
      assignedTo: wi.fields?.["System.AssignedTo"]?.displayName ?? undefined,
      areaPath: wi.fields?.["System.AreaPath"] ?? undefined,
      iterationPath: wi.fields?.["System.IterationPath"] ?? undefined,
      storyPoints: wi.fields?.["Microsoft.VSTS.Scheduling.StoryPoints"] ?? wi.fields?.["Microsoft.VSTS.Scheduling.Effort"] ?? undefined,
      priority: wi.fields?.["Microsoft.VSTS.Common.Priority"] ?? undefined,
      tags: wi.fields?.["System.Tags"] ?? undefined,
      createdDate: wi.fields?.["System.CreatedDate"] ?? undefined,
      changedDate: wi.fields?.["System.ChangedDate"] ?? undefined,
    }));
  }

  /** Fetch team members for a project */
  async getTeamMembers(projectName: string): Promise<AdoTeamMember[]> {
    if (this.useMock) {
      return [
        { id: "1", displayName: "Alex Kim", uniqueName: "alex.kim@demo.com" },
        { id: "2", displayName: "Sarah Chen", uniqueName: "sarah.chen@demo.com" },
        { id: "3", displayName: "Priya Patel", uniqueName: "priya.patel@demo.com" },
      ];
    }

    // Get teams for project
    const teamsRes = await fetch(
      `${this.orgUrl}/_apis/projects/${encodeURIComponent(projectName)}/teams?api-version=7.0`,
      {
        headers: {
          Authorization: this.authHeader,
          "Content-Type": "application/json",
        },
      }
    );
    if (!teamsRes.ok) return [];
    const teamsData = await teamsRes.json();
    const teams = teamsData.value ?? [];
    if (teams.length === 0) return [];

    // Fetch members of all teams
    const allMembers: AdoTeamMember[] = [];
    const seenIds = new Set<string>();

    for (const team of teams.slice(0, 5)) {
      const membersRes = await fetch(
        `${this.orgUrl}/_apis/projects/${encodeURIComponent(projectName)}/teams/${team.id}/members?api-version=7.0`,
        {
          headers: {
            Authorization: this.authHeader,
            "Content-Type": "application/json",
          },
        }
      );
      if (!membersRes.ok) continue;
      const membersData = await membersRes.json();

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      for (const m of membersData.value ?? []) {
        const member = m.identity ?? m;
        if (!seenIds.has(member.id)) {
          seenIds.add(member.id);
          allMembers.push({
            id: member.id,
            displayName: member.displayName ?? "",
            uniqueName: member.uniqueName ?? "",
            imageUrl: member.imageUrl ?? undefined,
          });
        }
      }
    }

    return allMembers;
  }

  async getWorkItems(iterationPath: string): Promise<WorkItem[]> {
    if (this.useMock) {
      return mockWorkItems.map((wi) => ({ ...wi, sourceTool: "ADO" as const }));
    }

    const res = await fetch(
      `${this.orgUrl}/_apis/wit/wiql?api-version=7.0`,
      {
        method: "POST",
        headers: {
          Authorization: this.authHeader,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          query: `SELECT [System.Id] FROM WorkItems WHERE [System.IterationPath] = '${iterationPath}'`,
        }),
      }
    );
    if (!res.ok) throw new Error(`ADO API error: ${res.status}`);
    const data = await res.json();

    return data.workItems?.map((wi: Record<string, unknown>) => ({
      id: `ado-${wi.id}`,
      organizationId: "org-1",
      externalId: String(wi.id),
      sourceTool: "ADO" as const,
      title: "",
      status: "TODO" as const,
      priority: 2,
      type: "story",
      labels: [],
      iterationId: iterationPath,
    })) ?? [];
  }

  async writeBack(
    itemId: string,
    fields: Record<string, unknown>
  ): Promise<{ success: boolean; error?: string }> {
    const validation = validateWritebackFields("ado", fields);
    if (!validation.valid) {
      return {
        success: false,
        error: `Disallowed fields: ${validation.disallowedFields.join(", ")}`,
      };
    }

    if (this.useMock) {
      await new Promise((r) => setTimeout(r, 1000));
      return { success: true };
    }

    const patchDocument = Object.entries(fields).map(([field, value]) => ({
      op: "replace",
      path: `/fields/${field}`,
      value,
    }));

    const res = await fetch(
      `${this.orgUrl}/_apis/wit/workitems/${itemId}?api-version=7.0`,
      {
        method: "PATCH",
        headers: {
          Authorization: this.authHeader,
          "Content-Type": "application/json-patch+json",
        },
        body: JSON.stringify(patchDocument),
      }
    );

    if (!res.ok) {
      return { success: false, error: `ADO API error: ${res.status}` };
    }
    return { success: true };
  }
}
