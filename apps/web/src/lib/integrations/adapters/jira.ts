/**
 * Jira API adapter.
 * Uses email + API token for Basic authentication.
 * In demo mode, returns mock data.
 */

import type { JiraProject, JiraSprint } from "../types";
import type { WorkItem } from "@/lib/types/models";
import { validateWritebackFields } from "../writeback";
import {
  mockJiraProjects,
  mockJiraSprints,
} from "@/lib/mock-data/integration-data";
import { workItems as mockWorkItems } from "@/lib/mock-data/po-dashboard";

const isDemoMode =
  !process.env.NEXT_PUBLIC_SUPABASE_URL ||
  process.env.NEXT_PUBLIC_SUPABASE_URL === "https://your-project.supabase.co";

export class JiraAdapter {
  private email: string;
  private apiToken: string;
  private siteUrl: string;

  constructor(emailOrToken: string, siteUrlOrEmpty: string, apiToken?: string) {
    if (apiToken) {
      // New signature: email, siteUrl, apiToken
      this.email = emailOrToken;
      this.siteUrl = siteUrlOrEmpty.replace(/\/+$/, "");
      this.apiToken = apiToken;
    } else {
      // Legacy signature: accessToken, siteUrl (for backward compat)
      this.email = "";
      this.apiToken = emailOrToken;
      this.siteUrl = siteUrlOrEmpty.replace(/\/+$/, "");
    }
  }

  private get authHeader(): string {
    if (this.email) {
      return `Basic ${Buffer.from(`${this.email}:${this.apiToken}`).toString("base64")}`;
    }
    return `Bearer ${this.apiToken}`;
  }

  async getProjects(): Promise<JiraProject[]> {
    if (isDemoMode) return mockJiraProjects;

    const res = await fetch(`${this.siteUrl}/rest/api/3/project/search`, {
      headers: {
        Authorization: this.authHeader,
        Accept: "application/json",
      },
    });
    if (!res.ok) throw new Error(`Jira API error: ${res.status}`);
    const data = await res.json();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return data.values.map((p: any) => ({
      id: String(p.id),
      key: String(p.key),
      name: String(p.name),
      projectType: String(p.projectTypeKey ?? ""),
      avatarUrl: p.avatarUrls?.["48x48"] as string | undefined,
    }));
  }

  async getSprints(boardId: string): Promise<JiraSprint[]> {
    if (isDemoMode) return mockJiraSprints;

    const res = await fetch(
      `${this.siteUrl}/rest/agile/1.0/board/${boardId}/sprint`,
      {
        headers: {
          Authorization: this.authHeader,
          Accept: "application/json",
        },
      }
    );
    if (!res.ok) throw new Error(`Jira API error: ${res.status}`);
    const data = await res.json();
    return data.values.map((s: Record<string, string>) => ({
      id: s.id,
      name: s.name,
      state: s.state,
      startDate: s.startDate,
      endDate: s.endDate,
      boardId,
    }));
  }

  /** Fetch issues for a specific project */
  async getIssuesByProject(
    projectKey: string
  ): Promise<
    {
      id: string;
      key: string;
      summary: string;
      status: string;
      issueType: string;
      assignee?: string;
      priority?: string;
      storyPoints?: number;
      sprint?: string;
      created?: string;
      updated?: string;
      labels?: string[];
    }[]
  > {
    if (isDemoMode) {
      return mockWorkItems
        .filter((wi) => wi.iterationId === "iter-1")
        .map((wi) => ({
          id: wi.id,
          key: wi.externalId,
          summary: wi.title,
          status: wi.status,
          issueType: wi.type ?? "Story",
          assignee: wi.assigneeId ?? undefined,
          storyPoints: wi.storyPoints,
        }));
    }

    const jql = encodeURIComponent(`project = "${projectKey}" ORDER BY updated DESC`);
    const res = await fetch(
      `${this.siteUrl}/rest/api/3/search?jql=${jql}&maxResults=200&fields=summary,status,issuetype,assignee,priority,customfield_10016,sprint,created,updated,labels`,
      {
        headers: {
          Authorization: this.authHeader,
          Accept: "application/json",
        },
      }
    );
    if (!res.ok) throw new Error(`Jira API error: ${res.status}`);
    const data = await res.json();

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return (data.issues ?? []).map((issue: any) => ({
      id: String(issue.id),
      key: String(issue.key),
      summary: issue.fields?.summary ?? "",
      status: issue.fields?.status?.name ?? "",
      issueType: issue.fields?.issuetype?.name ?? "",
      assignee: issue.fields?.assignee?.displayName ?? undefined,
      priority: issue.fields?.priority?.name ?? undefined,
      storyPoints: issue.fields?.customfield_10016 ?? undefined,
      sprint: issue.fields?.sprint?.name ?? undefined,
      created: issue.fields?.created ?? undefined,
      updated: issue.fields?.updated ?? undefined,
      labels: issue.fields?.labels ?? [],
    }));
  }

  /** Fetch project members (users assignable in the project) */
  async getProjectMembers(
    projectKey: string
  ): Promise<{ accountId: string; displayName: string; emailAddress?: string; avatarUrl?: string }[]> {
    if (isDemoMode) {
      return [
        { accountId: "1", displayName: "Alex Kim", emailAddress: "alex@demo.com" },
        { accountId: "2", displayName: "Sarah Chen", emailAddress: "sarah@demo.com" },
        { accountId: "3", displayName: "Priya Patel", emailAddress: "priya@demo.com" },
      ];
    }

    const res = await fetch(
      `${this.siteUrl}/rest/api/3/user/assignable/search?project=${projectKey}&maxResults=200`,
      {
        headers: {
          Authorization: this.authHeader,
          Accept: "application/json",
        },
      }
    );
    if (!res.ok) return [];
    const data = await res.json();

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return (data ?? []).map((u: any) => ({
      accountId: u.accountId ?? "",
      displayName: u.displayName ?? "",
      emailAddress: u.emailAddress ?? undefined,
      avatarUrl: u.avatarUrls?.["48x48"] ?? undefined,
    }));
  }

  async getWorkItems(sprintId: string): Promise<WorkItem[]> {
    if (isDemoMode) return mockWorkItems.filter((wi) => wi.iterationId === "iter-1");

    const res = await fetch(
      `${this.siteUrl}/rest/agile/1.0/sprint/${sprintId}/issue`,
      {
        headers: {
          Authorization: this.authHeader,
          Accept: "application/json",
        },
      }
    );
    if (!res.ok) throw new Error(`Jira API error: ${res.status}`);
    const data = await res.json();
    // Normalize Jira issues to WorkItem format
    return data.issues.map((issue: Record<string, Record<string, unknown>>) => ({
      id: `jira-${issue.id}`,
      organizationId: "org-1",
      externalId: issue.key as unknown as string,
      sourceTool: "JIRA" as const,
      title: (issue.fields?.summary as string) ?? "",
      status: "TODO" as const,
      storyPoints: (issue.fields?.story_points as number) ?? undefined,
      priority: 2,
      type: "story",
      labels: [],
      iterationId: sprintId,
    }));
  }

  async writeBack(
    itemId: string,
    fields: Record<string, unknown>
  ): Promise<{ success: boolean; error?: string }> {
    const validation = validateWritebackFields("jira", fields);
    if (!validation.valid) {
      return {
        success: false,
        error: `Disallowed fields: ${validation.disallowedFields.join(", ")}`,
      };
    }

    if (isDemoMode) {
      // Simulate write-back delay
      await new Promise((r) => setTimeout(r, 1000));
      return { success: true };
    }

    const res = await fetch(
      `${this.siteUrl}/rest/api/3/issue/${itemId}`,
      {
        method: "PUT",
        headers: {
          Authorization: this.authHeader,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ fields }),
      }
    );

    if (!res.ok) {
      return { success: false, error: `Jira API error: ${res.status}` };
    }
    return { success: true };
  }
}
