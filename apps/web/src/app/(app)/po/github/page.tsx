"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Github,
  GitPullRequest,
  GitCommit,
  GitMerge,
  GitBranch,
  AlertTriangle,
  ExternalLink,
  ChevronDown,
  Activity,
  Loader2,
  RefreshCw,
  Database,
  Eye,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useIntegrations } from "@/lib/integrations/context";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { StatCard } from "@/components/dashboard/stat-card";
import { Badge, Avatar, Button } from "@/components/ui";
import { GitHubConnectCard } from "@/components/integrations/github-connect-card";
import { useSelectedProject } from "@/lib/project/context";
import { useAutoRefresh } from "@/lib/ws/context";
import { cachedFetch } from "@/lib/fetch-cache";
import type { PRStatus, CIStatus } from "@/lib/types/models";

// ---------------------------------------------------------------------------
// Types (API response shapes)
// ---------------------------------------------------------------------------

interface GitHubRepo {
  id: string;
  name: string;
  fullName: string;
  defaultBranch: string;
  url: string;
  isPrivate: boolean;
  language: string | null;
  openIssuesCount: number;
  stargazersCount: number;
  description?: string;
  updatedAt?: string;
  owner?: string;
}

interface GitHubPR {
  id: string;
  repositoryId?: string;
  externalId?: string;
  number: number;
  title: string;
  status: PRStatus;
  authorId?: string;
  author?: string;
  authorAvatar?: string;
  reviewers: string[];
  ciStatus: CIStatus;
  linkedWorkItemId?: string;
  url: string;
  createdExternalAt?: string;
  createdAt?: string;
  mergedAt?: string | null;
  repo?: string;
}

interface GitHubCommit {
  id?: string;
  repositoryId?: string;
  sha: string;
  message: string;
  authorId?: string;
  author?: string;
  authorLogin?: string;
  authorAvatar?: string;
  branch: string;
  linkedTicketIds: string[];
  filesChanged?: number;
  committedAt?: string;
  date?: string;
  repo?: string;
}

interface GitHubOverview {
  repos: number;
  openPrs: number;
  mergedPrs: number;
  commitsLast7d: number;
  sprintName: string | null;
  sprintStart: string;
  sprintEnd: string;
}

interface ActivityEventItem {
  id: string;
  eventType: string;
  developerId: string;
  developerName: string;
  developerAvatar: string | null;
  description: string;
  repo: string;
  metadata: Record<string, unknown> | null;
  occurredAt: string;
  isAfterHours: boolean;
  isWeekend: boolean;
}

interface ActivityTeamMember {
  id: string;
  name: string;
  avatarUrl: string | null;
}

interface ActivityFilters {
  developer: string; // "" = all
  type: string; // "" = all
  timeRange: string; // "7d" default
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const prStatusConfig: Record<
  PRStatus,
  { label: string; variant: "brand" | "rag-green" | "rag-amber" | "rag-red" }
> = {
  OPEN: { label: "Open", variant: "brand" },
  AWAITING_REVIEW: { label: "Awaiting Review", variant: "rag-amber" },
  CHANGES_REQUESTED: { label: "Changes Requested", variant: "rag-red" },
  APPROVED: { label: "Approved", variant: "rag-green" },
  MERGED: { label: "Merged", variant: "rag-green" },
  CLOSED: { label: "Closed", variant: "brand" },
};

const ciStatusConfig: Record<
  CIStatus,
  { label: string; variant: "rag-green" | "rag-amber" | "rag-red" | "brand" }
> = {
  PASSING: { label: "Passing", variant: "rag-green" },
  FAILING: { label: "Failing", variant: "rag-red" },
  PENDING: { label: "Pending", variant: "rag-amber" },
  UNKNOWN: { label: "Unknown", variant: "brand" },
};

function formatDate(iso: string | undefined | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(ms / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function getEventIcon(type: string) {
  switch (type.toLowerCase()) {
    case "push":
    case "commit_pushed":
      return <GitCommit size={14} className="text-[var(--color-rag-green)]" />;
    case "pull_request":
    case "pr_opened":
      return (
        <GitPullRequest
          size={14}
          className="text-[var(--color-brand-secondary)]"
        />
      );
    case "pr_merged":
      return <GitMerge size={14} className="text-[var(--color-rag-green)]" />;
    case "review":
    case "pr_reviewed":
      return <Eye size={14} className="text-[var(--color-rag-amber)]" />;
    case "comment":
      return <Activity size={14} className="text-[var(--text-secondary)]" />;
    case "create":
      return <GitBranch size={14} className="text-[#773B93]" />;
    case "delete":
      return <GitBranch size={14} className="text-[var(--color-rag-red)]" />;
    case "release":
      return <Activity size={14} className="text-[var(--color-rag-green)]" />;
    default:
      return <Activity size={14} className="text-[var(--text-tertiary)]" />;
  }
}

// ---------------------------------------------------------------------------
// Empty State
// ---------------------------------------------------------------------------

function GitHubEmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-6 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-[var(--bg-surface-raised)] mb-6">
        <Github size={32} className="text-[var(--text-secondary)]" />
      </div>

      <h2 className="text-lg font-semibold text-[var(--text-primary)] mb-2">
        Connect GitHub to Monitor Your Code
      </h2>
      <p className="text-sm text-[var(--text-secondary)] max-w-md mb-8">
        Link pull requests to sprint tickets, track CI/CD status, and spot
        review bottlenecks automatically. Plan2Sprint uses read-only access.
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8 max-w-lg w-full">
        {[
          {
            icon: GitPullRequest,
            label: "PR Monitoring",
            desc: "Link PRs to sprint tickets",
          },
          {
            icon: Activity,
            label: "CI/CD Status",
            desc: "Track build health in real-time",
          },
          {
            icon: GitCommit,
            label: "Commit Activity",
            desc: "Developer activity feed",
          },
        ].map(({ icon: Icon, label, desc }) => (
          <div
            key={label}
            className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]/50 p-4 text-center"
          >
            <Icon
              size={20}
              className="mx-auto mb-2 text-[var(--color-brand-secondary)]"
            />
            <p className="text-xs font-semibold text-[var(--text-primary)]">
              {label}
            </p>
            <p className="text-[11px] text-[var(--text-secondary)] mt-0.5">
              {desc}
            </p>
          </div>
        ))}
      </div>

      <div className="w-full max-w-sm">
        <GitHubConnectCard />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Connected View — fetches real data from API
// ---------------------------------------------------------------------------

function GitHubConnectedView() {
  const refreshKey = useAutoRefresh(["sync_complete", "github_event"]);
  const { selectedProject } = useSelectedProject();

  // -- Existing state --
  const [repos, setRepos] = useState<GitHubRepo[]>([]);
  const [prs, setPrs] = useState<GitHubPR[]>([]);
  const [commits, setCommits] = useState<GitHubCommit[]>([]);
  const [selectedRepo, setSelectedRepo] = useState("");
  const [hoveredRow, setHoveredRow] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  // -- Overview strip state --
  const [overview, setOverview] = useState<GitHubOverview | null>(null);

  // -- Activity feed state --
  const [activityEvents, setActivityEvents] = useState<ActivityEventItem[]>([]);
  const [activityFilters, setActivityFilters] = useState<ActivityFilters>({
    developer: "",
    type: "",
    timeRange: "7d",
  });
  const [activityLoading, setActivityLoading] = useState(false);
  const [developerNotLinked, setDeveloperNotLinked] = useState(false);

  // -- Project-scoped developers --
  interface ProjectDeveloper extends ActivityTeamMember {
    githubLinked: boolean;
    githubUsername: string | null;
  }
  const [projectDevs, setProjectDevs] = useState<ProjectDeveloper[]>([]);

  // -- Fetch project developers --
  const fetchProjectDevelopers = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (selectedProject?.internalId) {
        params.set("project_id", selectedProject.internalId);
      }
      const res = await fetch(`/api/github/project-developers?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        setProjectDevs(data.developers ?? []);
      }
    } catch {
      // swallow
    }
  }, [selectedProject]);

  // -- Fetch overview (with optional developer) --
  const fetchOverview = useCallback(async (developerId?: string) => {
    try {
      const params = new URLSearchParams();
      if (developerId) params.set("developer", developerId);
      const res = await cachedFetch(`/api/github/overview?${params.toString()}`);
      if (res.ok) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const data = res.data as any;
        setOverview(data);
      }
    } catch {
      // swallow
    }
  }, []);

  // -- Fetch activity feed --
  const fetchActivity = useCallback(async (filters: ActivityFilters) => {
    setActivityLoading(true);
    setDeveloperNotLinked(false);
    try {
      const params = new URLSearchParams();
      if (filters.developer) params.set("developer", filters.developer);
      if (filters.type) params.set("type", filters.type);
      params.set("timeRange", filters.timeRange);
      params.set("limit", "50");

      const res = await fetch(`/api/github/activity?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        setActivityEvents(data.events ?? []);
        if (data.developerNotLinked) {
          setDeveloperNotLinked(true);
        }
      }
    } catch {
      // swallow
    }
    setActivityLoading(false);
  }, []);

  // -- Fetch repos on mount --
  const fetchRepos = useCallback(async () => {
    try {
      const res = await cachedFetch("/api/integrations/github/repos");
      if (res.ok) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const data = res.data as any;
        const repoList: GitHubRepo[] = data.repos ?? [];
        setRepos(repoList);
        if (repoList.length > 0 && !selectedRepo) {
          setSelectedRepo(repoList[0].id);
        }
      }
    } catch {
      // swallow
    }
  }, [selectedRepo]);

  // -- Fetch PRs & commits for selected repo --
  const fetchRepoData = useCallback(async () => {
    if (!selectedRepo || repos.length === 0) return;
    const repo = repos.find((r) => r.id === selectedRepo);
    const repoParam = repo?.fullName
      ? `?repo=${encodeURIComponent(repo.fullName)}`
      : "";

    try {
      const [prRes, commitRes] = await Promise.all([
        fetch(`/api/integrations/github/pulls${repoParam}`),
        fetch(`/api/integrations/github/commits${repoParam}`),
      ]);
      if (prRes.ok) {
        const prData = await prRes.json();
        setPrs(prData.pulls ?? []);
      }
      if (commitRes.ok) {
        const commitData = await commitRes.json();
        setCommits(commitData.commits ?? []);
      }
    } catch {
      // swallow
    }
  }, [selectedRepo, repos]);

  // Mount: fetch repos + overview + activity + project developers
  useEffect(() => {
    setLoading(true);
    Promise.all([fetchRepos(), fetchOverview(), fetchProjectDevelopers()]).finally(() =>
      setLoading(false)
    );
  }, [fetchRepos, fetchOverview, fetchProjectDevelopers]);

  // Re-fetch project developers when project changes
  useEffect(() => {
    fetchProjectDevelopers();
    // Reset developer filter when project changes
    setActivityFilters((f) => ({ ...f, developer: "" }));
  }, [selectedProject, fetchProjectDevelopers]);

  // Repo data on repo change
  useEffect(() => {
    if (selectedRepo) {
      fetchRepoData();
    }
  }, [selectedRepo, fetchRepoData, refreshKey]);

  // Activity feed on filter change or refresh
  useEffect(() => {
    fetchActivity(activityFilters);
    // Also refresh overview when developer filter changes
    fetchOverview(activityFilters.developer || undefined);
  }, [activityFilters, fetchActivity, fetchOverview, refreshKey]);

  const handleRefresh = async () => {
    setRefreshing(true);
    await Promise.all([
      fetchRepos(),
      fetchRepoData(),
      fetchOverview(activityFilters.developer || undefined),
      fetchActivity(activityFilters),
      fetchProjectDevelopers(),
    ]);
    setRefreshing(false);
  };

  // -- Derived stats --
  const repo = repos.find((r) => r.id === selectedRepo);
  const openPRCount = prs.filter(
    (pr) => pr.status !== "MERGED" && pr.status !== "CLOSED"
  ).length;
  const failingCI = prs.filter((pr) => pr.ciStatus === "FAILING").length;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-5 w-5 animate-spin text-[var(--text-secondary)]" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* ================================================================= */}
      {/* SECTION 1: Overview Strip — 4 stat cards                          */}
      {/* ================================================================= */}
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-[var(--text-primary)]">
          GitHub Overview
          {overview?.sprintName && (
            <span className="ml-2 text-xs font-normal text-[var(--text-tertiary)]">
              — {overview.sprintName}
            </span>
          )}
        </h2>
        <Button
          variant="ghost"
          size="sm"
          onClick={handleRefresh}
          disabled={refreshing}
          className="h-8 w-8 p-0"
        >
          <RefreshCw
            className={cn("h-3.5 w-3.5", refreshing && "animate-spin")}
          />
        </Button>
      </div>

      {overview && (
        <div className="-mt-3">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard label="Repos" value={overview.repos} icon={Database} />
            <StatCard
              label="Open PRs"
              value={overview.openPrs}
              icon={GitPullRequest}
              severity={overview.openPrs > 10 ? "AMBER" : undefined}
            />
            <StatCard
              label="Merged PRs"
              value={overview.mergedPrs}
              icon={GitMerge}
              severity="GREEN"
            />
            <StatCard
              label="Commits (7d)"
              value={overview.commitsLast7d}
              icon={GitCommit}
            />
          </div>
        </div>
      )}

      {/* ================================================================= */}
      {/* SECTION 2: Tracked Activity Feed                                  */}
      {/* ================================================================= */}
      <DashboardPanel
        title="Tracked Activity Feed"
        icon={Activity}
        actions={
          <span className="text-xs font-medium text-[var(--text-secondary)]">
            {activityEvents.length} events
          </span>
        }
      >
        {/* Filter Bar */}
        <div className="flex flex-wrap items-center gap-3 mb-4">
          {/* Developer filter */}
          <div className="relative">
            <select
              value={activityFilters.developer}
              onChange={(e) =>
                setActivityFilters((f) => ({
                  ...f,
                  developer: e.target.value,
                }))
              }
              className={cn(
                "appearance-none rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-3 py-2 pr-8",
                "text-xs font-medium text-[var(--text-primary)]",
                "focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)]",
                "cursor-pointer"
              )}
            >
              <option value="">All Developers</option>
              {projectDevs.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}{!m.githubLinked ? " (not connected)" : ""}
                </option>
              ))}
            </select>
            <ChevronDown
              size={12}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[var(--text-secondary)] pointer-events-none"
            />
          </div>

          {/* Activity type filter */}
          <div className="relative">
            <select
              value={activityFilters.type}
              onChange={(e) =>
                setActivityFilters((f) => ({ ...f, type: e.target.value }))
              }
              className={cn(
                "appearance-none rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-3 py-2 pr-8",
                "text-xs font-medium text-[var(--text-primary)]",
                "focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)]",
                "cursor-pointer"
              )}
            >
              <option value="">All Types</option>
              <option value="push">Push</option>
              <option value="pull_request">Pull Request</option>
              <option value="review">Review</option>
              <option value="comment">Comment</option>
              <option value="create">Branch / Tag Created</option>
              <option value="delete">Branch / Tag Deleted</option>
              <option value="release">Release</option>
            </select>
            <ChevronDown
              size={12}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[var(--text-secondary)] pointer-events-none"
            />
          </div>

          {/* Time range segmented control */}
          <div className="flex items-center gap-1 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-0.5">
            {(
              [
                { value: "today", label: "Today" },
                { value: "7d", label: "7 days" },
                { value: "30d", label: "30 days" },
                { value: "sprint", label: "Sprint" },
              ] as const
            ).map(({ value, label }) => (
              <button
                key={value}
                onClick={() =>
                  setActivityFilters((f) => ({ ...f, timeRange: value }))
                }
                className={cn(
                  "px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer",
                  activityFilters.timeRange === value
                    ? "bg-[var(--color-brand-secondary)] text-white"
                    : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* Activity list */}
        {activityLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-[var(--text-secondary)]" />
          </div>
        ) : developerNotLinked ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-[var(--bg-surface-raised)] mb-4">
              <Github size={24} className="text-[var(--text-secondary)]" />
            </div>
            <p className="text-sm font-medium text-[var(--text-primary)] mb-1">
              {projectDevs.find((d) => d.id === activityFilters.developer)?.name ?? "This developer"} hasn&apos;t linked their GitHub yet
            </p>
            <p className="text-xs text-[var(--text-secondary)] max-w-sm">
              Ask them to connect their GitHub account from the Developer Dashboard to see their activity here.
            </p>
          </div>
        ) : activityEvents.length === 0 ? (
          <div className="text-center py-8 text-sm text-[var(--text-secondary)]">
            No activity found for the selected filters.
          </div>
        ) : (
          <div className="divide-y divide-[var(--border-subtle)]">
            {activityEvents.map((event) => (
              <div
                key={event.id}
                className="flex items-start gap-3 py-3 first:pt-0"
              >
                {/* Avatar */}
                {event.developerAvatar ? (
                  <Avatar
                    src={event.developerAvatar}
                    fallback={event.developerName}
                    size="sm"
                  />
                ) : (
                  <div className="flex h-7 w-7 items-center justify-center rounded-full bg-[var(--bg-surface-raised)] text-xs font-bold text-[var(--text-secondary)] shrink-0">
                    {event.developerName.charAt(0).toUpperCase()}
                  </div>
                )}

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-[var(--text-primary)]">
                      {event.developerName}
                    </span>
                    <span className="shrink-0">
                      {getEventIcon(event.eventType)}
                    </span>
                  </div>
                  <p className="text-sm text-[var(--text-secondary)] mt-0.5 line-clamp-1">
                    {event.description}
                  </p>
                  <div className="flex items-center gap-2 mt-1 flex-wrap">
                    {event.repo && (
                      <code className="text-[10px] font-mono text-[var(--color-brand-secondary)] bg-[var(--color-brand-secondary)]/10 px-1.5 py-0.5 rounded">
                        {event.repo}
                      </code>
                    )}
                    <span className="text-[10px] text-[var(--text-tertiary)]">
                      {timeAgo(event.occurredAt)}
                    </span>
                    {event.isAfterHours && (
                      <Badge variant="rag-amber" className="text-[9px]">
                        After hours
                      </Badge>
                    )}
                    {event.isWeekend && (
                      <Badge variant="rag-amber" className="text-[9px]">
                        Weekend
                      </Badge>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </DashboardPanel>

      {/* ================================================================= */}
      {/* EXISTING: Repo selector + PR table + Commits (only if repos)      */}
      {/* ================================================================= */}
      {repos.length > 0 && (
        <>
          <div className="flex flex-col sm:flex-row sm:items-center gap-4">
            {/* Repo selector */}
            <div className="relative">
              <select
                value={selectedRepo}
                onChange={(e) => setSelectedRepo(e.target.value)}
                className={cn(
                  "appearance-none rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-4 py-2.5 pr-10",
                  "text-sm font-medium text-[var(--text-primary)]",
                  "focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)]",
                  "cursor-pointer"
                )}
              >
                {repos.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.fullName}
                  </option>
                ))}
              </select>
              <ChevronDown
                size={14}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)] pointer-events-none"
              />
            </div>

            {/* Quick stats */}
            <div className="flex items-center gap-4">
              <span className="text-xs text-[var(--text-secondary)]">
                <span className="font-semibold text-[var(--text-primary)]">
                  {openPRCount}
                </span>{" "}
                open PRs
              </span>
              <span className="text-xs text-[var(--text-secondary)]">
                <span className="font-semibold text-[var(--text-primary)]">
                  {commits.length}
                </span>{" "}
                recent commits
              </span>
              {failingCI > 0 && (
                <span className="text-xs text-[var(--color-rag-red)] font-medium flex items-center gap-1">
                  <AlertTriangle size={12} />
                  {failingCI} failing CI
                </span>
              )}
              {repo && (
                <span className="text-xs text-[var(--text-tertiary)]">
                  {repo.language} &middot; {repo.defaultBranch}
                </span>
              )}
            </div>

            {/* Refresh button */}
            <Button
              variant="ghost"
              size="sm"
              onClick={handleRefresh}
              disabled={refreshing}
              className="ml-auto h-8 w-8 p-0"
            >
              <RefreshCw
                className={cn("h-3.5 w-3.5", refreshing && "animate-spin")}
              />
            </Button>
          </div>

          {/* Two-column layout: PRs table + Commits feed */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Panel 1 & 2: Pull Requests (spans 2 cols) */}
        <div className="lg:col-span-2">
          <DashboardPanel
            title="Pull Requests"
            icon={GitPullRequest}
            noPadding
            actions={
              <span className="text-xs font-medium text-[var(--text-secondary)]">
                {prs.length} total
              </span>
            }
          >
            {/* Table header */}
            <div className="grid grid-cols-[1fr_110px_110px_90px] gap-3 px-5 py-2.5 border-b border-[var(--border-subtle)] text-[11px] font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
              <span>Pull Request</span>
              <span>Author</span>
              <span>Review</span>
              <span>CI</span>
            </div>

            <div className="divide-y divide-[var(--border-subtle)]">
              {prs.map((pr) => {
                const authorName = pr.author ?? pr.authorId ?? "Unknown";
                const prCfg = prStatusConfig[pr.status] ?? prStatusConfig.OPEN;
                const ciCfg =
                  ciStatusConfig[pr.ciStatus] ?? ciStatusConfig.UNKNOWN;

                return (
                  <div
                    key={pr.id}
                    className={cn(
                      "grid grid-cols-[1fr_110px_110px_90px] gap-3 items-center px-5 py-2.5 transition-colors duration-150",
                      hoveredRow === pr.id && "bg-[var(--bg-surface-raised)]/50"
                    )}
                    onMouseEnter={() => setHoveredRow(pr.id)}
                    onMouseLeave={() => setHoveredRow(null)}
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <GitPullRequest className="h-3.5 w-3.5 shrink-0 text-[var(--color-brand-secondary)]" />
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-[var(--text-primary)] truncate">
                          {pr.title}
                        </p>
                        <span className="text-[11px] text-[var(--text-secondary)]">
                          #{pr.number}
                          {pr.linkedWorkItemId && (
                            <>
                              {" "}
                              &middot;{" "}
                              <span className="text-[var(--color-brand-secondary)]">
                                {pr.linkedWorkItemId}
                              </span>
                            </>
                          )}
                          {pr.repo && (
                            <>
                              {" "}
                              &middot;{" "}
                              <span className="text-[var(--text-tertiary)]">
                                {pr.repo}
                              </span>
                            </>
                          )}
                        </span>
                      </div>
                    </div>

                    <div className="flex items-center gap-1.5 min-w-0">
                      {pr.authorAvatar ? (
                        <Avatar
                          src={pr.authorAvatar}
                          fallback={authorName}
                          size="sm"
                        />
                      ) : null}
                      <span className="text-xs text-[var(--text-primary)] truncate">
                        {typeof authorName === "string"
                          ? authorName.split(" ")[0]
                          : "Unknown"}
                      </span>
                    </div>

                    <Badge variant={prCfg.variant} className="text-[10px] w-fit">
                      {prCfg.label}
                    </Badge>

                    <Badge variant={ciCfg.variant} className="text-[10px] w-fit">
                      {ciCfg.label}
                    </Badge>
                  </div>
                );
              })}
              {prs.length === 0 && (
                <div className="px-5 py-8 text-center text-sm text-[var(--text-secondary)]">
                  No pull requests found for this repository.
                </div>
              )}
            </div>
          </DashboardPanel>
        </div>

        {/* Panel 3: Recent Commits */}
        <div>
          <DashboardPanel title="Recent Commits" icon={GitCommit} noPadding>
            <div className="divide-y divide-[var(--border-subtle)]">
              {commits.slice(0, 8).map((commit) => {
                const authorName =
                  commit.author ??
                  commit.authorLogin ??
                  commit.authorId ??
                  "";
                const commitDate = commit.committedAt ?? commit.date;
                return (
                  <div
                    key={commit.sha ?? commit.id}
                    className="px-4 py-3 hover:bg-[var(--bg-surface-raised)]/30 transition-colors"
                  >
                    <p className="text-sm text-[var(--text-primary)] leading-snug line-clamp-2">
                      {commit.message}
                    </p>
                    <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                      <code className="text-[11px] font-mono text-[var(--color-brand-secondary)] bg-[var(--color-brand-secondary)]/10 px-1.5 py-0.5 rounded">
                        {commit.sha?.substring(0, 7) ?? ""}
                      </code>
                      {authorName && (
                        <span className="text-[11px] text-[var(--text-secondary)]">
                          {authorName.split(" ")[0]}
                        </span>
                      )}
                      <span className="text-[11px] text-[var(--text-tertiary)]">
                        {formatDate(commitDate)}
                      </span>
                      {commit.linkedTicketIds?.length > 0 && (
                        <span className="flex items-center gap-0.5 text-[11px] text-[var(--color-brand-secondary)]">
                          <ExternalLink size={10} />
                          {commit.linkedTicketIds[0]}
                        </span>
                      )}
                      {commit.branch && (
                        <code className="text-[10px] font-mono text-[var(--text-tertiary)] bg-[var(--bg-surface-raised)] px-1.5 py-0.5 rounded">
                          {commit.branch}
                        </code>
                      )}
                    </div>
                  </div>
                );
              })}
              {commits.length === 0 && (
                <div className="px-4 py-8 text-center text-sm text-[var(--text-secondary)]">
                  No commits found.
                </div>
              )}
            </div>
          </DashboardPanel>
        </div>
      </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

function GitHubNoRepoState({ projectName }: { projectName: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-6 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-[var(--bg-surface-raised)] mb-6">
        <Github size={32} className="text-[var(--text-secondary)]" />
      </div>
      <h2 className="text-lg font-semibold text-[var(--text-primary)] mb-2">
        No GitHub Repository Linked
      </h2>
      <p className="text-sm text-[var(--text-secondary)] max-w-md mb-4">
        <span className="font-medium text-[var(--text-primary)]">{projectName}</span> does not have a GitHub repository linked.
        GitHub monitoring shows data only for projects with connected repos.
      </p>
      <p className="text-xs text-[var(--text-tertiary)]">
        To see GitHub data, select a project that has a linked repository, or link a repo to this project.
      </p>
    </div>
  );
}

export default function GithubPage() {
  const { isConnected } = useIntegrations();
  const githubConnected = isConnected("github");

  return (
    <div className="space-y-6">
      {githubConnected ? <GitHubConnectedView /> : <GitHubEmptyState />}
    </div>
  );
}
