"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  MessageSquareText,
  ChevronDown,
  CheckCircle2,
  Clock,
  AlertCircle,
  Circle,
  StickyNote,
  RefreshCw,
  Eye,
  Loader2,
  GitCommit,
  GitPullRequest,
  GitMerge,
  ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Badge, Avatar } from "@/components/ui";
import { useAutoRefresh } from "@/lib/ws/context";
import { useSelectedProject } from "@/lib/project/context";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface StandupItem {
  title: string;
  ticketId?: string;
  prId?: string;
  prStatus?: string;
}

interface RecentActivityItem {
  type: "commits" | "pr";
  title: string;
  repo?: string;
  count?: number;
  prNumber?: number;
  prStatus?: string;
  url?: string;
  occurredAt?: string;
}

interface InFlightItem {
  id: string;
  title: string;
  ticketId?: string | null;
  status: string;
  type?: string;
  updatedAt?: string | null;
}

interface IndividualReport {
  id: string;
  teamMemberId: string;
  email: string;
  displayName: string;
  avatarUrl?: string | null;
  githubUsername?: string | null;
  acknowledged: boolean;
  isInactive: boolean;
  recentActivity: RecentActivityItem[];
  inFlight: InFlightItem[];
  /** AI-generated 3–4 sentence summary of the dev's recent commits.
   *  Backend extracts this from the standup's completed_items when
   *  there are 4+ surfaced commits. Same shape as the dev page's
   *  isCommitSummary block, surfaced here so the PO sees the same
   *  concise paragraph instead of a long row of commit titles. */
  commitSummary?: { text: string; commitCount: number } | null;
  completedCount: number;
  inProgressCount: number;
  blockerCount: number;
  completed: StandupItem[];
  inProgress: StandupItem[];
  hasMoreSprintContributions: boolean;
  blockers: { description: string; status: string }[];
  narrativeText: string;
  reportDate: string | null;
  teamMember: string;
}

interface SubmittedNote {
  id: string;
  date: string;
  author: string;
  authorRole: string;
  note: string;
  submittedAt: string;
}

interface DigestData {
  id: string;
  sprintPacing: number;
  acknowledgedPct: number;
  sprintHealth: string;
  blockerCount: number;
  summaryText: string;
  individualReports: IndividualReport[];
  submittedNotes: SubmittedNote[];
  effectiveDate?: string;
  isWeekendFallback?: boolean;
}

interface SprintContributions {
  reportId: string;
  displayName: string;
  completed: StandupItem[];
  inProgress: StandupItem[];
  completedCount: number;
  inProgressCount: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatNoteTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true });
}

function timeAgo(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  const diffMs = Date.now() - d.getTime();
  const diffMin = Math.round(diffMs / 60000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffH = Math.round(diffMin / 60);
  if (diffH < 24) return `${diffH}h ago`;
  const diffD = Math.round(diffH / 24);
  if (diffD === 1) return "yesterday";
  if (diffD < 7) return `${diffD}d ago`;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function buildSummaryBadges(report: IndividualReport): string {
  const parts: string[] = [];
  const commitCount = report.recentActivity
    .filter((a) => a.type === "commits")
    .reduce((sum, a) => sum + (a.count ?? 0), 0);
  const mergedPRs = report.recentActivity.filter(
    (a) => a.type === "pr" && a.prStatus === "MERGED"
  ).length;
  const openedPRs = report.recentActivity.filter(
    (a) => a.type === "pr" && a.prStatus !== "MERGED"
  ).length;
  if (commitCount > 0) parts.push(`${commitCount} commit${commitCount > 1 ? "s" : ""}`);
  if (mergedPRs > 0) parts.push(`${mergedPRs} PR${mergedPRs > 1 ? "s" : ""} merged`);
  if (openedPRs > 0) parts.push(`${openedPRs} PR${openedPRs > 1 ? "s" : ""} opened`);
  if (report.inFlight.length > 0) parts.push(`${report.inFlight.length} in flight`);
  return parts.join(" · ");
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function StandupDigestPanel() {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [digest, setDigest] = useState<DigestData | null>(null);
  const [loading, setLoading] = useState(true);
  const [sprintContribs, setSprintContribs] = useState<Record<string, SprintContributions | "loading">>({});
  const refreshKey = useAutoRefresh(["standup_generated", "standup_note_submitted", "sync_complete"]);
  const { selectedProject } = useSelectedProject();

  // Auto-expand developer row from ?developer=X URL param (e.g., from Slack link)
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const devId = params.get("developer");
    if (devId) {
      setExpandedIds((prev) => new Set([...prev, devId]));
    }
  }, []);

  // `force=true` makes the backend (a) trigger an ADO/Jira sync first
  // so DB statuses are fresh, and (b) regenerate the StandupReport rows
  // from the now-fresh data. Without it, a Refresh click just re-pulls
  // whatever the local DB happens to think is current — which can mean
  // showing items as IN_PROGRESS that the dev already closed in ADO
  // hours ago.
  const fetchDigest = useCallback(async (force = false) => {
    setLoading(true);
    try {
      const today = new Date().toISOString().split("T")[0];
      const params = new URLSearchParams({ date: today });
      // Hotfix 43b: backend expects the internal DB UUID; using the
      // external project ID (`selectedProject.id`) returns no rows.
      if (selectedProject?.internalId) params.set("projectId", selectedProject.internalId);
      if (force) params.set("forceRefresh", "true");
      const res = await fetch(`/api/standups?${params.toString()}`);
      const data = await res.json();
      setDigest(data);
      // Reset sprint-contributions cache on fresh fetch
      setSprintContribs({});
    } catch {
      setDigest(null);
    }
    setLoading(false);
  }, [selectedProject?.internalId]);

  useEffect(() => {
    fetchDigest();
  }, [fetchDigest, refreshKey]);

  // Build a map of author -> notes for quick lookup
  const notesByAuthor = useMemo(() => {
    const map = new Map<string, SubmittedNote[]>();
    for (const note of digest?.submittedNotes ?? []) {
      const key = note.author.toLowerCase();
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(note);
    }
    return map;
  }, [digest?.submittedNotes]);

  const reports = digest?.individualReports ?? [];

  // Find note authors who are NOT in the individual reports
  const reportNames = useMemo(
    () => new Set(reports.map((r) => r.displayName.toLowerCase())),
    [reports]
  );
  const extraNoteAuthors = useMemo(() => {
    const extras: string[] = [];
    for (const author of notesByAuthor.keys()) {
      if (!reportNames.has(author)) extras.push(author);
    }
    return extras;
  }, [notesByAuthor, reportNames]);

  function toggleExpand(id: string) {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function hasSubmittedNote(displayName: string): boolean {
    return notesByAuthor.has(displayName.toLowerCase());
  }

  function getNotesForMember(displayName: string): SubmittedNote[] {
    return notesByAuthor.get(displayName.toLowerCase()) ?? [];
  }

  async function loadSprintContributions(reportId: string) {
    if (sprintContribs[reportId]) return;
    setSprintContribs((prev) => ({ ...prev, [reportId]: "loading" }));
    try {
      const params = new URLSearchParams();
      if (selectedProject?.internalId) params.set("projectId", selectedProject.internalId);
      const url = `/api/standups/${reportId}/sprint-contributions${
        params.toString() ? `?${params.toString()}` : ""
      }`;
      const res = await fetch(url);
      const data = await res.json();
      setSprintContribs((prev) => ({ ...prev, [reportId]: data }));
    } catch {
      setSprintContribs((prev) => ({ ...prev, [reportId]: { reportId, displayName: "", completed: [], inProgress: [], completedCount: 0, inProgressCount: 0 } }));
    }
  }

  if (loading) {
    return (
      <DashboardPanel title="Standup Digest" icon={MessageSquareText}>
        <div className="flex items-center justify-center py-12">
          <Loader2 size={24} className="animate-spin text-[var(--color-brand-secondary)]" />
        </div>
      </DashboardPanel>
    );
  }

  return (
    <DashboardPanel
      title="Standup Digest"
      icon={MessageSquareText}
      actions={
        <button
          onClick={() => fetchDigest(true)}
          className="flex items-center gap-1 text-[10px] text-[var(--text-tertiary)] hover:text-[var(--color-brand-secondary)] transition-colors cursor-pointer"
        >
          <RefreshCw size={10} /> Refresh
        </button>
      }
    >
      <div className="space-y-5">
        {/* Weekend fallback notice */}
        {digest?.isWeekendFallback && digest.effectiveDate && (
          <div className="rounded-lg border border-[var(--color-brand-secondary)]/30 bg-[var(--color-brand-secondary)]/5 px-3 py-2 text-xs text-[var(--text-secondary)]">
            It&apos;s the weekend — no new standups are generated. Showing the most recent weekday&apos;s data ({new Date(digest.effectiveDate).toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric" })}).
          </div>
        )}

        {/* Summary text */}
        <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
          {digest?.summaryText || "No standup data yet. Sync project data to auto-generate standups."}
        </p>

        {/* Header stats row */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/50 p-3 text-center">
            <p className="text-xs font-medium text-[var(--text-secondary)] mb-1">Sprint Pacing</p>
            <p className="text-xl font-bold text-[var(--text-primary)]">{digest?.sprintPacing ?? 0}%</p>
          </div>
          <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/50 p-3 text-center">
            <p className="text-xs font-medium text-[var(--text-secondary)] mb-1">Acknowledged</p>
            <p className="text-xl font-bold text-[var(--text-primary)]">{digest?.acknowledgedPct ?? 0}%</p>
          </div>
          <div
            className={cn(
              "rounded-xl border p-3 text-center",
              (digest?.blockerCount ?? 0) > 0
                ? "border-[var(--color-rag-red)]/30 bg-[var(--color-rag-red)]/5"
                : "border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/50"
            )}
          >
            <p className="text-xs font-medium text-[var(--text-secondary)] mb-1">Blockers</p>
            <p
              className={cn(
                "text-xl font-bold",
                (digest?.blockerCount ?? 0) > 0
                  ? "text-[var(--color-rag-red)]"
                  : "text-[var(--text-primary)]"
              )}
            >
              {digest?.blockerCount ?? 0}
            </p>
          </div>
        </div>

        {/* Per-developer standup rows */}
        <div className="space-y-2">
          {reports.length === 0 && (
            <div className="py-6 text-center text-sm text-[var(--text-tertiary)]">
              No standup reports generated yet. Sync project data to populate.
            </div>
          )}

          {reports.map((report) => {
            // Hotfix 41: row key uses email so duplicate TM rows for the same
            // person can never produce duplicate cards even if the dedupe on
            // the backend slipped.
            const rowId = report.email || report.id || report.teamMemberId;
            const isExpanded = expandedIds.has(rowId);
            const memberNotes = getNotesForMember(report.displayName);
            const hasNote = hasSubmittedNote(report.displayName);
            const summaryLine = buildSummaryBadges(report);
            const contribState = sprintContribs[report.id];

            return (
              <div
                key={rowId}
                className="rounded-xl border border-[var(--border-subtle)] overflow-hidden"
              >
                {/* Header row */}
                <div className="flex items-center justify-between w-full px-4 py-3 hover:bg-[var(--bg-surface-raised)]/50 transition-colors duration-150 gap-3">
                  <div className="flex items-center gap-3 flex-1 min-w-0">
                    <Avatar
                      src={report.avatarUrl ?? undefined}
                      fallback={report.displayName}
                      size="sm"
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-medium text-[var(--text-primary)] truncate">
                          {report.displayName}
                        </span>
                        {report.acknowledged ? (
                          <CheckCircle2 className="h-4 w-4 text-[var(--color-rag-green)]" />
                        ) : (
                          <Clock className="h-4 w-4 text-[var(--color-rag-amber)]" />
                        )}
                        {report.isInactive && (
                          <Badge variant="brand" className="text-[10px]">
                            Inactive
                          </Badge>
                        )}
                        {report.blockerCount > 0 && (
                          <Badge variant="rag-red" className="text-[11px]">
                            {report.blockerCount} blocker{report.blockerCount > 1 ? "s" : ""}
                          </Badge>
                        )}
                        {hasNote && (
                          <Badge variant="rag-green" className="text-[10px] px-2 py-0.5">
                            <StickyNote size={10} className="mr-1 inline" />
                            Note sent
                          </Badge>
                        )}
                      </div>
                      {summaryLine && (
                        <p className="text-[11px] text-[var(--text-tertiary)] mt-0.5 truncate">
                          {summaryLine}
                        </p>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleExpand(rowId);
                      }}
                      className={cn(
                        "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-all cursor-pointer",
                        "border border-[var(--color-brand-secondary)]/30 text-[var(--color-brand-secondary)] bg-[var(--color-brand-secondary)]/5 hover:bg-[var(--color-brand-secondary)]/10"
                      )}
                    >
                      <Eye size={12} />
                      {isExpanded ? "Close" : "Read Standup"}
                    </button>
                    <button
                      onClick={() => toggleExpand(rowId)}
                      className="cursor-pointer p-1"
                    >
                      <motion.div
                        animate={{ rotate: isExpanded ? 0 : -90 }}
                        transition={{ duration: 0.2 }}
                      >
                        <ChevronDown className="h-4 w-4 text-[var(--text-secondary)]" />
                      </motion.div>
                    </button>
                  </div>
                </div>

                {/* Expanded content */}
                <AnimatePresence initial={false}>
                  {isExpanded && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.2, ease: "easeInOut" }}
                      className="overflow-hidden"
                    >
                      <div className="px-4 pb-4 space-y-4 border-t border-[var(--border-subtle)] pt-3">
                        {/* Narrative */}
                        {report.narrativeText && (
                          <p className="text-sm text-[var(--text-secondary)] leading-relaxed italic">
                            {report.narrativeText}
                          </p>
                        )}

                        {/* AI-generated commit summary — same data the dev's
                            own /dev/standup view renders. Shown as a
                            bordered paragraph block instead of a long row
                            of commit titles. Only renders when the
                            standup engine collapsed 4+ commits into a
                            summary. */}
                        {report.commitSummary && report.commitSummary.text && (
                          <div
                            className="rounded-lg border p-3 space-y-1.5"
                            style={{
                              borderColor: "color-mix(in srgb, var(--color-brand-secondary) 30%, transparent)",
                              background: "color-mix(in srgb, var(--color-brand-secondary) 6%, transparent)",
                            }}
                          >
                            <div className="flex items-center gap-2 mb-1">
                              <GitCommit className="h-3.5 w-3.5 text-[var(--color-brand-secondary)]" />
                              <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-brand-secondary)]">
                                Recent code activity
                              </span>
                              {report.commitSummary.commitCount > 0 && (
                                <span className="text-[10px] text-[var(--text-tertiary)]">
                                  {report.commitSummary.commitCount} commit
                                  {report.commitSummary.commitCount === 1 ? "" : "s"}
                                </span>
                              )}
                            </div>
                            <p className="text-sm leading-relaxed text-[var(--text-primary)]">
                              {report.commitSummary.text}
                            </p>
                          </div>
                        )}

                        {/* Recent Activity (last 48-72h GitHub) */}
                        {report.recentActivity.length > 0 && (
                          <div>
                            <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-rag-green)] mb-1.5">
                              Recent Activity
                            </h4>
                            <ul className="space-y-1.5">
                              {report.recentActivity.map((item, i) => {
                                const isPR = item.type === "pr";
                                const isMerged = item.prStatus === "MERGED";
                                const Icon = isPR ? (isMerged ? GitMerge : GitPullRequest) : GitCommit;
                                const iconColor = isMerged
                                  ? "text-[var(--color-rag-green)]"
                                  : isPR
                                    ? "text-[var(--color-brand-secondary)]"
                                    : "text-[var(--text-secondary)]";
                                return (
                                  <li
                                    key={`activity-${i}`}
                                    className="flex items-start gap-2 text-sm text-[var(--text-primary)]"
                                  >
                                    <Icon className={cn("h-3.5 w-3.5 shrink-0 mt-0.5", iconColor)} />
                                    <span className="flex-1 min-w-0">
                                      {item.url ? (
                                        <a
                                          href={item.url}
                                          target="_blank"
                                          rel="noreferrer"
                                          className="hover:text-[var(--color-brand-secondary)] truncate block"
                                        >
                                          {item.title}
                                        </a>
                                      ) : (
                                        <span className="truncate block">{item.title}</span>
                                      )}
                                    </span>
                                    {item.occurredAt && (
                                      <span className="text-[10px] text-[var(--text-tertiary)] shrink-0">
                                        {timeAgo(item.occurredAt)}
                                      </span>
                                    )}
                                  </li>
                                );
                              })}
                            </ul>
                          </div>
                        )}

                        {/* In Flight */}
                        {report.inFlight.length > 0 && (
                          <div>
                            <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-brand-secondary)] mb-1.5">
                              In Flight
                            </h4>
                            <ul className="space-y-1.5">
                              {report.inFlight.map((item) => (
                                <li
                                  key={item.id}
                                  className="flex items-center gap-2 text-sm text-[var(--text-primary)]"
                                >
                                  <Circle className="h-3.5 w-3.5 shrink-0 text-[var(--color-brand-secondary)]" />
                                  <span className="truncate flex-1 min-w-0">{item.title}</span>
                                  {item.ticketId && (
                                    <span className="text-xs text-[var(--text-secondary)] shrink-0">
                                      ({item.ticketId})
                                    </span>
                                  )}
                                  {item.status && (
                                    <Badge
                                      variant={
                                        item.status === "IN_REVIEW" ? "rag-amber" : "brand"
                                      }
                                      className="text-[10px] shrink-0"
                                    >
                                      {item.status.replace(/_/g, " ").toLowerCase()}
                                    </Badge>
                                  )}
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}

                        {/* Blockers */}
                        {report.blockers.length > 0 && (
                          <div className="rounded-lg border border-[var(--color-rag-red)]/30 bg-[var(--color-rag-red)]/5 p-3">
                            <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-rag-red)] mb-1.5">
                              Blockers
                            </h4>
                            <ul className="space-y-1">
                              {report.blockers.map((blocker, bidx) => (
                                <li
                                  key={`blocker-${bidx}-${blocker.description.slice(0, 20)}`}
                                  className="flex items-start gap-2 text-sm text-[var(--color-rag-red)]"
                                >
                                  <AlertCircle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                                  <span>{blocker.description}</span>
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}

                        {/* Member notes */}
                        {memberNotes.length > 0 && (
                          <div className="rounded-lg border border-[var(--color-brand-secondary)]/20 bg-[var(--color-brand-secondary)]/5 p-3 space-y-2">
                            <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-brand-secondary)] flex items-center gap-1.5">
                              <StickyNote size={12} /> Developer Note
                            </h4>
                            {memberNotes.map((n) => (
                              <div key={n.id}>
                                <p className="text-sm text-[var(--text-primary)] whitespace-pre-wrap leading-relaxed">
                                  {n.note}
                                </p>
                                <div className="flex items-center gap-2 mt-1.5 text-[10px] text-[var(--text-tertiary)]">
                                  <Clock size={10} />
                                  <span>Submitted at {formatNoteTime(n.submittedAt)}</span>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Empty state — fully inactive */}
                        {report.recentActivity.length === 0 &&
                          report.inFlight.length === 0 &&
                          report.blockers.length === 0 &&
                          memberNotes.length === 0 && (
                            <div className="flex items-center gap-2 text-xs text-[var(--text-tertiary)] py-1">
                              <Clock size={12} />
                              <span>
                                No GitHub activity, in-flight tickets, or blockers in the last
                                couple of days.
                              </span>
                            </div>
                          )}

                        {/* Sprint contributions expander — Hotfix 42: always
                            rendered so the PO can pull up the sprint-wide
                            picture for any developer, even when the recent
                            window is empty. Loaded lazily on first open. */}
                        <details
                          className="group rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)]/40"
                          onToggle={(e) => {
                            if ((e.target as HTMLDetailsElement).open) {
                              loadSprintContributions(report.id);
                            }
                          }}
                        >
                          <summary className="cursor-pointer select-none px-3 py-2 flex items-center gap-2 text-xs font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
                            <ChevronRight
                              size={12}
                              className="transition-transform group-open:rotate-90"
                            />
                            View full sprint contributions
                            <span className="text-[10px] text-[var(--text-tertiary)]">
                              ({report.completedCount} done · {report.inProgressCount} in progress)
                            </span>
                          </summary>
                          <div className="px-3 pb-3 pt-1 space-y-3 border-t border-[var(--border-subtle)]">
                            {contribState === "loading" && (
                              <div className="flex items-center gap-2 text-xs text-[var(--text-tertiary)] py-2">
                                <Loader2 size={12} className="animate-spin" />
                                Loading…
                              </div>
                            )}
                            {contribState && contribState !== "loading" && (
                              <>
                                {contribState.completed.length === 0 &&
                                  contribState.inProgress.length === 0 && (
                                    <p className="text-xs text-[var(--text-tertiary)] py-2">
                                      No sprint contributions tracked for this developer in the
                                      selected project yet.
                                    </p>
                                  )}
                                {contribState.completed.length > 0 && (
                                  <div>
                                    <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-rag-green)] mb-1">
                                      Completed ({contribState.completedCount})
                                    </p>
                                    <ul className="space-y-1">
                                      {contribState.completed.map((it, i) => (
                                        <li
                                          key={`fc-${i}`}
                                          className="flex items-center gap-2 text-xs text-[var(--text-primary)]"
                                        >
                                          <CheckCircle2 className="h-3 w-3 shrink-0 text-[var(--color-rag-green)]" />
                                          <span className="truncate">{it.title}</span>
                                          {it.ticketId && (
                                            <span className="text-[10px] text-[var(--text-tertiary)] shrink-0">
                                              ({it.ticketId})
                                            </span>
                                          )}
                                        </li>
                                      ))}
                                    </ul>
                                  </div>
                                )}
                                {contribState.inProgress.length > 0 && (
                                  <div>
                                    <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-brand-secondary)] mb-1">
                                      In Progress ({contribState.inProgressCount})
                                    </p>
                                    <ul className="space-y-1">
                                      {contribState.inProgress.map((it, i) => (
                                        <li
                                          key={`fp-${i}`}
                                          className="flex items-center gap-2 text-xs text-[var(--text-primary)]"
                                        >
                                          <Circle className="h-3 w-3 shrink-0 text-[var(--color-brand-secondary)]" />
                                          <span className="truncate">{it.title}</span>
                                          {it.ticketId && (
                                            <span className="text-[10px] text-[var(--text-tertiary)] shrink-0">
                                              ({it.ticketId})
                                            </span>
                                          )}
                                        </li>
                                      ))}
                                    </ul>
                                  </div>
                                )}
                              </>
                            )}
                          </div>
                        </details>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            );
          })}

          {/* Extra note authors (submitted notes but not in team reports) */}
          {extraNoteAuthors.map((authorKey) => {
            const authorNotes = notesByAuthor.get(authorKey) ?? [];
            if (authorNotes.length === 0) return null;
            const authorName = authorNotes[0].author;
            const authorRole = authorNotes[0].authorRole;
            const rowId = `extra-${authorKey}`;
            const isExpanded = expandedIds.has(rowId);

            return (
              <div
                key={rowId}
                className="rounded-xl border border-[var(--border-subtle)] overflow-hidden"
              >
                <div className="flex items-center justify-between w-full px-4 py-3 hover:bg-[var(--bg-surface-raised)]/50 transition-colors duration-150">
                  <div className="flex items-center gap-3 flex-1">
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--color-brand-secondary)]/20 text-sm font-semibold text-[var(--color-brand-secondary)]">
                      {authorName.charAt(0).toUpperCase()}
                    </div>
                    <span className="text-sm font-medium text-[var(--text-primary)]">
                      {authorName}
                    </span>
                    <Badge variant="brand" className="text-[10px] px-1.5 py-0">
                      {authorRole}
                    </Badge>
                    <Badge variant="rag-green" className="text-[10px] px-2 py-0.5">
                      <StickyNote size={10} className="mr-1 inline" />
                      Note sent
                    </Badge>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => toggleExpand(rowId)}
                      className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium border border-[var(--color-brand-secondary)]/30 text-[var(--color-brand-secondary)] bg-[var(--color-brand-secondary)]/5 hover:bg-[var(--color-brand-secondary)]/10 cursor-pointer transition-all"
                    >
                      <Eye size={12} />
                      {isExpanded ? "Close" : "Read Standup"}
                    </button>
                    <button onClick={() => toggleExpand(rowId)} className="cursor-pointer p-1">
                      <motion.div
                        animate={{ rotate: isExpanded ? 0 : -90 }}
                        transition={{ duration: 0.2 }}
                      >
                        <ChevronDown className="h-4 w-4 text-[var(--text-secondary)]" />
                      </motion.div>
                    </button>
                  </div>
                </div>
                <AnimatePresence initial={false}>
                  {isExpanded && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.2, ease: "easeInOut" }}
                      className="overflow-hidden"
                    >
                      <div className="px-4 pb-4 space-y-3 border-t border-[var(--border-subtle)] pt-3">
                        {authorNotes.map((n) => (
                          <div
                            key={n.id}
                            className="rounded-lg border border-[var(--color-brand-secondary)]/20 bg-[var(--color-brand-secondary)]/5 p-3"
                          >
                            <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-brand-secondary)] flex items-center gap-1.5 mb-2">
                              <StickyNote size={12} /> Developer Note
                            </h4>
                            <p className="text-sm text-[var(--text-primary)] whitespace-pre-wrap leading-relaxed">
                              {n.note}
                            </p>
                            <div className="flex items-center gap-2 mt-2 text-[10px] text-[var(--text-tertiary)]">
                              <Clock size={10} />
                              <span>Submitted at {formatNoteTime(n.submittedAt)}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            );
          })}
        </div>

        {/* Refresh hint */}
        <div className="flex items-center justify-end">
          <button
            onClick={() => fetchDigest(true)}
            disabled={loading}
            className="flex items-center gap-1.5 text-xs text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] cursor-pointer disabled:opacity-50"
          >
            <RefreshCw size={12} className={loading ? "animate-spin" : ""} /> Refresh
          </button>
        </div>
      </div>
    </DashboardPanel>
  );
}
