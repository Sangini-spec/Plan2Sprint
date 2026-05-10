"use client";

import { useState, useEffect, useCallback } from "react";
import {
  MessageSquareText,
  CheckCircle2,
  Circle,
  AlertTriangle,
  Send,
  Clock,
  StickyNote,
  Loader2,
  ArrowRight,
  RefreshCw,
  GitCommit,
  GitPullRequest,
  GitMerge,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Badge } from "@/components/ui";
import { useSelectedProject } from "@/lib/project/context";
import { useAutoRefresh } from "@/lib/ws/context";
import { useAuth } from "@/lib/auth/context";
import { cachedFetch, invalidateCache } from "@/lib/fetch-cache";
import Link from "next/link";

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
  id?: string;
  teamMemberId: string;
  email?: string;
  displayName: string;
  completed: StandupItem[];
  inProgress: StandupItem[];
  blockers: { description: string; status: string }[];
  recentActivity?: RecentActivityItem[];
  inFlight?: InFlightItem[];
  narrativeText: string;
  isInactive: boolean;
}

interface SubmittedNote {
  id: string;
  date: string;
  author: string;
  authorRole: string;
  note: string;
  submittedAt: string;
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true });
}

// ---------------------------------------------------------------------------
// Compact Standup Widget — for developer overview dashboard (no calendar)
// ---------------------------------------------------------------------------

export function MyStandupCompact() {
  const { selectedProject } = useSelectedProject();
  const { appUser } = useAuth();
  const [noteText, setNoteText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [notes, setNotes] = useState<SubmittedNote[]>([]);
  const [report, setReport] = useState<IndividualReport | null>(null);
  const [narrative, setNarrative] = useState("");
  const [loading, setLoading] = useState(true);
  const refreshKey = useAutoRefresh(["standup_generated", "sync_complete"]);

  const projectId = selectedProject?.internalId;
  const userEmail = (appUser?.email ?? "").toLowerCase();
  const userName = appUser?.full_name ?? "";

  const today = new Date();
  const isWeekend = today.getDay() === 0 || today.getDay() === 6;
  const todayKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

  // ---------- Fetch standup data ----------
  // `force=true` is used by the Refresh button to (a) drop any cached
  // response so we hit the API again instead of returning the in-memory
  // 30-second snapshot, and (b) ask the backend to regenerate the
  // StandupReport rows even when ones already exist for today. Without
  // (a) the button was a no-op within the 30s TTL window. Without (b)
  // tickets the dev closed after the morning's auto-gen never showed
  // up here.
  const fetchStandup = useCallback(async (force = false) => {
    setLoading(true);
    try {
      const pidParam = projectId ? `&projectId=${projectId}` : "";
      const forceParam = force ? "&forceRefresh=true" : "";
      const url = `/api/standups?date=${todayKey}${pidParam}${forceParam}`;
      if (force) {
        // Drop the cached response so we actually hit the API again.
        invalidateCache(url);
        invalidateCache(`/api/standups?date=${todayKey}${pidParam}`);
      }
      const res = await cachedFetch(url);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const data = res.data as any;

      // Hotfix 42: pick the LOGGED-IN USER's report — not just reports[0],
      // which used to surface whichever developer's report_date was latest.
      // Hotfix 43: removed the displayName fallback; matching by name was
      // surfacing the wrong "Sangini Tripathi" (PO's row) when the dev row
      // didn't exist for the selected project. Strict email match only.
      // Hotfix (today): backend now resolves `mine` server-side using
      // email + displayName fallback, and bypasses drop_empty for the
      // requesting user's own row. Trust that field first; fall back to
      // the legacy email scan only when the backend didn't supply it
      // (older API revision still warming).
      const reports: IndividualReport[] = data.individualReports ?? [];
      let mine: IndividualReport | undefined =
        (data.mine as IndividualReport | undefined) ?? undefined;
      if (!mine && userEmail) {
        mine = reports.find((r) => (r.email ?? "").toLowerCase() === userEmail);
      }
      if (mine) {
        setReport(mine);
        setNarrative(mine.narrativeText || "");
      } else {
        setReport(null);
        setNarrative(
          "No standup generated for you yet on this project. Pick a different project or sync your data."
        );
      }
      setNotes(data.submittedNotes ?? []);
    } catch {
      setNarrative("Unable to load standup data.");
      setNotes([]);
    }
    setLoading(false);
  }, [todayKey, projectId, userEmail]);

  useEffect(() => { fetchStandup(); }, [fetchStandup, refreshKey]);

  // ---------- Submit note ----------
  const handleSubmit = async () => {
    if (!noteText.trim()) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const res = await fetch("/api/standups", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note: noteText }),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        setSubmitError(data.error ?? "Failed to submit");
      } else {
        setSubmitted(true);
        setNoteText("");
        fetchStandup();
      }
    } catch { setSubmitError("Failed to submit note"); }
    setSubmitting(false);
  };

  const completedItems = report?.completed ?? [];
  const inProgressItems = report?.inProgress ?? [];
  const blockerItems = report?.blockers ?? [];
  const recentActivity = report?.recentActivity ?? [];
  const inFlight = report?.inFlight ?? [];

  return (
    <DashboardPanel
      title="Today's Standup"
      icon={MessageSquareText}
      actions={
        !isWeekend ? (
          <button
            onClick={() => fetchStandup(true)}
            className="flex items-center gap-1 text-[10px] text-[var(--text-tertiary)] hover:text-[var(--color-brand-secondary)] transition-colors cursor-pointer"
          >
            <RefreshCw size={10} /> Refresh
          </button>
        ) : undefined
      }
    >
      <div className="space-y-4">
        {isWeekend ? (
          <div className="flex flex-col items-center py-6 text-center">
            <MessageSquareText size={24} className="text-[var(--text-tertiary)] mb-2" />
            <p className="text-sm font-medium text-[var(--text-primary)]">No Standup on Weekends</p>
            <p className="text-xs text-[var(--text-secondary)] mt-1">Standup reports resume on Monday.</p>
          </div>
        ) : loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 size={20} className="animate-spin text-[var(--color-brand-secondary)]" />
          </div>
        ) : (
          <>
            {/* Narrative */}
            <p className="text-sm leading-relaxed text-[var(--text-secondary)]">{narrative}</p>

            {/* Compact section rows */}
            <div className="space-y-3">
              {/* Recent Activity (last 48-72h GitHub) — Hotfix 42 */}
              {recentActivity.length > 0 && (
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <GitCommit className="h-3.5 w-3.5 text-[var(--color-rag-green)]" />
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-rag-green)]">
                      Recent Activity
                    </span>
                  </div>
                  {recentActivity.slice(0, 5).map((item, i) => {
                    const isPR = item.type === "pr";
                    const isMerged = item.prStatus === "MERGED";
                    const Icon = isPR ? (isMerged ? GitMerge : GitPullRequest) : GitCommit;
                    const iconColor = isMerged
                      ? "text-[var(--color-rag-green)]"
                      : isPR
                        ? "text-[var(--color-brand-secondary)]"
                        : "text-[var(--text-secondary)]";
                    return (
                      <div key={`ra-${i}`} className="flex items-center gap-2 pl-5 text-sm text-[var(--text-primary)]">
                        <Icon className={cn("h-3 w-3 shrink-0", iconColor)} />
                        {item.url ? (
                          <a href={item.url} target="_blank" rel="noreferrer" className="truncate hover:text-[var(--color-brand-secondary)]">
                            {item.title}
                          </a>
                        ) : (
                          <span className="truncate">{item.title}</span>
                        )}
                      </div>
                    );
                  })}
                  {recentActivity.length > 5 && (
                    <p className="pl-5 text-[10px] text-[var(--text-tertiary)]">+{recentActivity.length - 5} more</p>
                  )}
                </div>
              )}

              {/* In Flight (work items) — Hotfix 42 */}
              {inFlight.length > 0 && (
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <Circle className="h-3.5 w-3.5 text-[var(--color-brand-secondary)]" />
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-brand-secondary)]">
                      In Flight ({inFlight.length})
                    </span>
                  </div>
                  {inFlight.slice(0, 5).map((item) => (
                    <div key={item.id} className="flex items-center gap-2 pl-5 text-sm text-[var(--text-primary)]">
                      <span className="truncate">{item.title}</span>
                      {item.ticketId && <Badge variant="brand" className="text-[9px] px-1.5 py-0">{item.ticketId}</Badge>}
                    </div>
                  ))}
                </div>
              )}

              {/* Completed */}
              {completedItems.length > 0 && (
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="h-3.5 w-3.5 text-[var(--color-rag-green)]" />
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-rag-green)]">
                      Completed ({completedItems.length})
                    </span>
                  </div>
                  {completedItems.slice(0, 5).map((item, i) => (
                    <div key={i} className="flex flex-wrap items-center gap-2 pl-5 text-sm text-[var(--text-primary)]">
                      <span className="truncate">{item.title}</span>
                      {item.ticketId && <Badge variant="brand" className="text-[9px] px-1.5 py-0">{item.ticketId}</Badge>}
                      {item.prId && <Badge variant="rag-green" className="text-[9px] px-1.5 py-0">PR #{item.prId}</Badge>}
                    </div>
                  ))}
                  {completedItems.length > 5 && (
                    <p className="pl-5 text-[10px] text-[var(--text-tertiary)]">+{completedItems.length - 5} more</p>
                  )}
                </div>
              )}

              {/* In Progress */}
              {inProgressItems.length > 0 && (
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <Circle className="h-3.5 w-3.5 text-[var(--color-brand-secondary)]" />
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-brand-secondary)]">
                      In Progress ({inProgressItems.length})
                    </span>
                  </div>
                  {inProgressItems.slice(0, 5).map((item, i) => (
                    <div key={i} className="flex flex-wrap items-center gap-2 pl-5 text-sm text-[var(--text-primary)]">
                      <span className="truncate">{item.title}</span>
                      {item.ticketId && <Badge variant="brand" className="text-[9px] px-1.5 py-0">{item.ticketId}</Badge>}
                      {item.prStatus && (
                        <Badge
                          variant={item.prStatus === "APPROVED" ? "rag-green" : "rag-amber"}
                          className="text-[9px] px-1.5 py-0"
                        >
                          {item.prStatus.replace(/_/g, " ")}
                        </Badge>
                      )}
                    </div>
                  ))}
                  {inProgressItems.length > 5 && (
                    <p className="pl-5 text-[10px] text-[var(--text-tertiary)]">+{inProgressItems.length - 5} more</p>
                  )}
                </div>
              )}

              {/* Blockers */}
              {blockerItems.length > 0 ? (
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <AlertTriangle className="h-3.5 w-3.5 text-[var(--color-rag-red)]" />
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-rag-red)]">
                      Blockers ({blockerItems.length})
                    </span>
                  </div>
                  {blockerItems.map((item, i) => (
                    <div key={i} className="pl-5 text-sm text-[var(--color-rag-red)]">{item.description}</div>
                  ))}
                </div>
              ) : completedItems.length > 0 || inProgressItems.length > 0 ? (
                <div className="flex items-center gap-2 rounded-lg bg-[var(--color-rag-green)]/10 px-3 py-1.5">
                  <CheckCircle2 className="h-3.5 w-3.5 text-[var(--color-rag-green)]" />
                  <span className="text-xs font-medium text-[var(--color-rag-green)]">No blockers</span>
                </div>
              ) : null}

              {/* Empty state — Hotfix 42 also checks recentActivity / inFlight */}
              {completedItems.length === 0 &&
                inProgressItems.length === 0 &&
                blockerItems.length === 0 &&
                recentActivity.length === 0 &&
                inFlight.length === 0 && (
                  <div className="flex flex-col items-center py-4 text-center">
                    <p className="text-xs text-[var(--text-tertiary)]">
                      No activity data yet. Sync a project to auto-generate your standup.
                    </p>
                  </div>
                )}
            </div>

            {/* Submitted Notes */}
            {notes.length > 0 && (
              <div className="space-y-1.5 pt-2 border-t border-[var(--border-subtle)]">
                <div className="flex items-center gap-2">
                  <StickyNote className="h-3.5 w-3.5 text-[var(--color-brand-secondary)]" />
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-brand-secondary)]">
                    Notes ({notes.length})
                  </span>
                </div>
                {notes.map((n) => (
                  <div key={n.id} className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/20 px-3 py-2">
                    <p className="text-xs text-[var(--text-primary)] whitespace-pre-wrap line-clamp-2">{n.note}</p>
                    <div className="flex items-center gap-2 mt-1 text-[10px] text-[var(--text-tertiary)]">
                      <Clock size={9} /> <span>{formatTime(n.submittedAt)}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Quick Add Note */}
            <div className="pt-2 border-t border-[var(--border-subtle)] space-y-2">
              {submitted && !noteText ? (
                <div className="flex items-center gap-2 rounded-lg bg-[var(--color-rag-green)]/10 px-3 py-2">
                  <CheckCircle2 size={14} className="text-[var(--color-rag-green)]" />
                  <span className="text-xs font-medium text-[var(--color-rag-green)]">Note submitted!</span>
                  <button onClick={() => setSubmitted(false)} className="ml-auto text-[10px] text-[var(--color-brand-secondary)] hover:underline cursor-pointer">Add another</button>
                </div>
              ) : (
                <div className="flex gap-2">
                  <input
                    value={noteText}
                    onChange={(e) => setNoteText(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSubmit(); } }}
                    placeholder="Quick note for today's standup..."
                    className={cn(
                      "flex-1 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-3 py-2 text-xs",
                      "text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)]",
                      "focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)]/40"
                    )}
                  />
                  <button
                    onClick={handleSubmit}
                    disabled={submitting || !noteText.trim()}
                    className={cn(
                      "flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium text-white transition-all cursor-pointer",
                      "bg-[var(--color-brand-secondary)] hover:bg-[var(--color-brand-secondary)]/90",
                      "disabled:opacity-40 disabled:cursor-not-allowed"
                    )}
                  >
                    {submitting ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
                  </button>
                </div>
              )}
              {submitError && <p className="text-[10px] text-[var(--color-rag-red)]">{submitError}</p>}
            </div>

            {/* Link to full standup page */}
            <Link href="/dev/standup"
              className="flex items-center gap-2 text-xs font-medium text-[var(--color-brand-secondary)] hover:underline pt-1">
              View full standup with calendar <ArrowRight size={12} />
            </Link>
          </>
        )}
      </div>
    </DashboardPanel>
  );
}
