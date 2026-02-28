/**
 * GitHub API adapter (READ-ONLY).
 * Uses GitHub REST API v3.
 * No write-back methods — GitHub is read-only per MRD.
 */

import type { GitHubRepo } from "../types";
import type { PullRequest, Commit } from "@/lib/types/models";
import {
  mockGitHubRepos,
  mockGitHubPRs,
  mockGitHubCommits,
} from "@/lib/mock-data/integration-data";

const isDemoMode =
  !process.env.NEXT_PUBLIC_SUPABASE_URL ||
  process.env.NEXT_PUBLIC_SUPABASE_URL === "https://your-project.supabase.co";

export class GitHubAdapter {
  private accessToken: string;

  constructor(accessToken: string) {
    this.accessToken = accessToken;
  }

  async getRepos(): Promise<GitHubRepo[]> {
    if (isDemoMode) return mockGitHubRepos;

    const res = await fetch("https://api.github.com/installation/repositories", {
      headers: {
        Authorization: `Bearer ${this.accessToken}`,
        Accept: "application/vnd.github.v3+json",
      },
    });
    if (!res.ok) throw new Error(`GitHub API error: ${res.status}`);
    const data = await res.json();
    return data.repositories.map((r: Record<string, unknown>) => ({
      id: String(r.id),
      name: r.name as string,
      fullName: r.full_name as string,
      defaultBranch: (r.default_branch as string) ?? "main",
      url: r.html_url as string,
      isPrivate: r.private as boolean,
      language: r.language as string | undefined,
      openIssuesCount: (r.open_issues_count as number) ?? 0,
      stargazersCount: (r.stargazers_count as number) ?? 0,
    }));
  }

  async getPullRequests(repo: string): Promise<PullRequest[]> {
    if (isDemoMode) {
      return mockGitHubPRs.filter(
        (pr) => !repo || mockGitHubRepos.find((r) => r.id === pr.repositoryId)?.fullName === repo
      );
    }

    const res = await fetch(
      `https://api.github.com/repos/${repo}/pulls?state=all&per_page=30`,
      {
        headers: {
          Authorization: `Bearer ${this.accessToken}`,
          Accept: "application/vnd.github.v3+json",
        },
      }
    );
    if (!res.ok) throw new Error(`GitHub API error: ${res.status}`);
    const data = await res.json();
    return data.map((pr: Record<string, unknown>) => ({
      id: `gh-${pr.id}`,
      repositoryId: repo,
      externalId: String(pr.number),
      number: pr.number as number,
      title: pr.title as string,
      status: (pr.state === "open" ? "OPEN" : "MERGED") as PullRequest["status"],
      ciStatus: "UNKNOWN" as const,
      reviewers: [],
      url: pr.html_url as string,
      createdExternalAt: pr.created_at as string,
      mergedAt: pr.merged_at as string | undefined,
    }));
  }

  async getCommits(repo: string): Promise<Commit[]> {
    if (isDemoMode) {
      return mockGitHubCommits.filter(
        (c) => !repo || mockGitHubRepos.find((r) => r.id === c.repositoryId)?.fullName === repo
      );
    }

    const res = await fetch(
      `https://api.github.com/repos/${repo}/commits?per_page=30`,
      {
        headers: {
          Authorization: `Bearer ${this.accessToken}`,
          Accept: "application/vnd.github.v3+json",
        },
      }
    );
    if (!res.ok) throw new Error(`GitHub API error: ${res.status}`);
    const data = await res.json();
    return data.map((c: Record<string, Record<string, unknown>>) => ({
      id: `gh-${c.sha}`,
      repositoryId: repo,
      sha: (c.sha as unknown as string).slice(0, 7),
      message: (c.commit?.message as string) ?? "",
      branch: "",
      linkedTicketIds: [],
      filesChanged: 0,
      committedAt: (c.commit?.author as Record<string, string>)?.date ?? "",
    }));
  }

  async getCIStatus(repo: string, sha: string): Promise<string> {
    if (isDemoMode) return "PASSING";

    const res = await fetch(
      `https://api.github.com/repos/${repo}/commits/${sha}/check-runs`,
      {
        headers: {
          Authorization: `Bearer ${this.accessToken}`,
          Accept: "application/vnd.github.v3+json",
        },
      }
    );
    if (!res.ok) return "UNKNOWN";
    const data = await res.json();
    const allPassed = data.check_runs?.every(
      (cr: Record<string, string>) => cr.conclusion === "success"
    );
    return allPassed ? "PASSING" : "FAILING";
  }
}
