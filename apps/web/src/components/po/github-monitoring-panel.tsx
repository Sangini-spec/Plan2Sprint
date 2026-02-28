"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Github,
  AlertTriangle,
  ExternalLink,
  GitPullRequest,
  Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Badge, Avatar } from "@/components/ui";
import type { PRStatus, CIStatus } from "@/lib/types/models";
import { useAutoRefresh } from "@/lib/ws/context";
import { cachedFetch } from "@/lib/fetch-cache";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PRData {
  id: string;
  number: number;
  title: string;
  status: PRStatus;
  author: string;
  authorAvatar?: string;
  repo: string;
  ciStatus: CIStatus;
  reviewers: string[];
  createdAt: string;
  url?: string;
  linkedWorkItemId?: string;
  linkedTicket?: string;
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

function hasReviewLag(createdAt: string, status: PRStatus): boolean {
  const created = new Date(createdAt).getTime();
  const now = Date.now();
  const twentyFourHours = 24 * 60 * 60 * 1000;
  return now - created > twentyFourHours && status !== "APPROVED" && status !== "MERGED";
}

function mapStatus(raw: string): PRStatus {
  const upper = raw.toUpperCase().replace(/\s+/g, "_");
  if (upper in prStatusConfig) return upper as PRStatus;
  if (upper === "MERGED") return "MERGED";
  if (upper === "CLOSED") return "CLOSED";
  return "OPEN";
}

function mapCIStatus(raw?: string): CIStatus {
  if (!raw) return "UNKNOWN";
  const upper = raw.toUpperCase();
  if (upper === "PASSING" || upper === "PASSED" || upper === "SUCCESS") return "PASSING";
  if (upper === "FAILING" || upper === "FAILED" || upper === "FAILURE") return "FAILING";
  if (upper === "PENDING" || upper === "RUNNING" || upper === "QUEUED") return "PENDING";
  return "UNKNOWN";
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function GithubMonitoringPanel() {
  const [pullRequests, setPullRequests] = useState<PRData[]>([]);
  const [loading, setLoading] = useState(true);
  const [hoveredRow, setHoveredRow] = useState<string | null>(null);
  const refreshKey = useAutoRefresh(["sync_complete", "github_sync"]);

  const fetchPRs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await cachedFetch("/api/github");
      if (res.ok) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const data = res.data as any;
        const prs: PRData[] = (data.pullRequests ?? []).map((pr: Record<string, unknown>) => ({
          id: pr.id as string,
          number: pr.number as number,
          title: pr.title as string,
          status: mapStatus(pr.status as string ?? "OPEN"),
          author: pr.author as string ?? "Unknown",
          authorAvatar: pr.authorAvatar as string | undefined,
          repo: pr.repo as string ?? "",
          ciStatus: mapCIStatus(pr.ciStatus as string | undefined),
          reviewers: (pr.reviewers as string[]) ?? [],
          createdAt: pr.createdAt as string ?? new Date().toISOString(),
          url: pr.url as string | undefined,
          linkedTicket: pr.linkedTicket as string | undefined,
        }));
        setPullRequests(prs);
      } else {
        setPullRequests([]);
      }
    } catch {
      setPullRequests([]);
    }
    setLoading(false);
  }, []);

  useEffect(() => { fetchPRs(); }, [fetchPRs, refreshKey]);

  if (loading) {
    return (
      <DashboardPanel title="GitHub Monitoring" icon={Github} noPadding>
        <div className="flex items-center justify-center py-8">
          <Loader2 size={20} className="animate-spin text-[var(--color-brand-secondary)]" />
        </div>
      </DashboardPanel>
    );
  }

  if (pullRequests.length === 0) {
    return (
      <DashboardPanel title="GitHub Monitoring" icon={Github}>
        <div className="flex flex-col items-center justify-center py-8 gap-2">
          <Github size={24} className="text-[var(--text-tertiary)]" />
          <p className="text-sm text-[var(--text-secondary)]">No pull requests found</p>
          <p className="text-xs text-[var(--text-tertiary)]">
            Connect GitHub and sync to see PR activity.
          </p>
        </div>
      </DashboardPanel>
    );
  }

  return (
    <DashboardPanel
      title="GitHub Monitoring"
      icon={Github}
      noPadding
      actions={
        <span className="text-xs font-medium text-[var(--text-secondary)]">
          {pullRequests.length} PRs
        </span>
      }
    >
      {/* Table header */}
      <div className="grid grid-cols-[1fr_140px_140px_130px_100px] gap-3 px-6 py-3 border-b border-[var(--border-subtle)] text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
        <span>Pull Request</span>
        <span>Author</span>
        <span>Linked Ticket</span>
        <span>Review</span>
        <span>CI</span>
      </div>

      {/* Table rows */}
      <div className="divide-y divide-[var(--border-subtle)]">
        {pullRequests.map((pr) => {
          const prCfg = prStatusConfig[pr.status];
          const ciCfg = ciStatusConfig[pr.ciStatus];
          const showWarning =
            pr.ciStatus === "FAILING" ||
            hasReviewLag(pr.createdAt, pr.status);

          return (
            <div
              key={pr.id}
              className={cn(
                "grid grid-cols-[1fr_140px_140px_130px_100px] gap-3 items-center px-6 py-3 transition-colors duration-150",
                hoveredRow === pr.id && "bg-[var(--bg-surface-raised)]/50"
              )}
              onMouseEnter={() => setHoveredRow(pr.id)}
              onMouseLeave={() => setHoveredRow(null)}
            >
              {/* PR title + number + warning */}
              <div className="flex items-center gap-2 min-w-0">
                <GitPullRequest className="h-4 w-4 shrink-0 text-[var(--color-brand-secondary)]" />
                <div className="min-w-0">
                  {pr.url ? (
                    <a
                      href={pr.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm font-medium text-[var(--text-primary)] hover:text-[var(--color-brand-secondary)] transition-colors truncate block"
                    >
                      {pr.title}
                    </a>
                  ) : (
                    <span className="text-sm font-medium text-[var(--text-primary)] truncate block">
                      {pr.title}
                    </span>
                  )}
                  <span className="text-xs text-[var(--text-secondary)]">
                    #{pr.number}
                  </span>
                </div>
                {showWarning && (
                  <AlertTriangle className="h-4 w-4 shrink-0 text-[var(--color-rag-amber)]" />
                )}
              </div>

              {/* Author */}
              <div className="flex items-center gap-2 min-w-0">
                {pr.authorAvatar ? (
                  <>
                    <Avatar src={pr.authorAvatar} fallback={pr.author} size="sm" />
                    <span className="text-sm text-[var(--text-primary)] truncate">
                      {pr.author.split(" ")[0]}
                    </span>
                  </>
                ) : (
                  <span className="text-sm text-[var(--text-secondary)]">
                    {pr.author}
                  </span>
                )}
              </div>

              {/* Linked ticket */}
              <div className="min-w-0">
                {pr.linkedTicket ? (
                  <span className="inline-flex items-center gap-1 text-xs font-medium text-[var(--color-brand-secondary)] bg-[var(--color-brand-secondary)]/10 rounded-md px-2 py-0.5 truncate">
                    {pr.linkedTicket}
                    <ExternalLink className="h-3 w-3 shrink-0" />
                  </span>
                ) : (
                  <span className="text-xs text-[var(--text-secondary)]">
                    &mdash;
                  </span>
                )}
              </div>

              {/* Review status */}
              <Badge variant={prCfg.variant} className="text-[11px] w-fit">
                {prCfg.label}
              </Badge>

              {/* CI status */}
              <Badge variant={ciCfg.variant} className="text-[11px] w-fit">
                {ciCfg.label}
              </Badge>
            </div>
          );
        })}
      </div>
    </DashboardPanel>
  );
}
