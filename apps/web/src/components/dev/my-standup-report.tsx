"use client";

import { useState, useEffect, useCallback } from "react";
import {
  MessageSquareText,
  CheckCircle2,
  Circle,
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  CalendarDays,
  Send,
  Lock,
  Clock,
  StickyNote,
  Loader2,
  RefreshCw,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Badge, Button } from "@/components/ui";
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

interface IndividualReport {
  teamMemberId: string;
  displayName: string;
  completed: StandupItem[];
  inProgress: StandupItem[];
  blockers: { description: string; status: string; ticketId?: string }[];
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

// ---------------------------------------------------------------------------
// Calendar helpers
// ---------------------------------------------------------------------------

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function toDateKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function isWeekend(d: Date): boolean {
  const day = d.getDay();
  return day === 0 || day === 6;
}

function isToday(d: Date): boolean {
  return toDateKey(d) === toDateKey(new Date());
}

function isFuture(d: Date): boolean {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(d);
  target.setHours(0, 0, 0, 0);
  return target > today;
}

function getMonthDays(year: number, month: number): Date[] {
  const days: Date[] = [];
  const firstDay = new Date(year, month, 1);
  const lastDay = new Date(year, month + 1, 0);

  // Fill leading empty days from previous month
  const startDay = firstDay.getDay();
  for (let i = startDay - 1; i >= 0; i--) {
    days.push(new Date(year, month, -i));
  }

  // Current month days
  for (let d = 1; d <= lastDay.getDate(); d++) {
    days.push(new Date(year, month, d));
  }

  // Fill trailing days to complete grid (6 rows)
  while (days.length < 42) {
    days.push(new Date(year, month + 1, days.length - lastDay.getDate() - startDay + 1));
  }

  return days;
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true });
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function MyStandupReport() {
  const { selectedProject } = useSelectedProject();
  const [selectedDate, setSelectedDate] = useState(new Date());
  const [viewMonth, setViewMonth] = useState(new Date().getMonth());
  const [viewYear, setViewYear] = useState(new Date().getFullYear());

  // Note state
  const [noteText, setNoteText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [sendingTo, setSendingTo] = useState<"slack" | "teams" | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [channelResult, setChannelResult] = useState<string | null>(null);

  // Platform connections
  const [slackConnected, setSlackConnected] = useState(false);
  const [teamsConnected, setTeamsConnected] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch("/api/integrations/slack/status");
        if (res.ok) setSlackConnected((await res.json()).connected === true);
      } catch {}
      try {
        const res = await fetch("/api/integrations/teams/status");
        if (res.ok) setTeamsConnected((await res.json()).connected === true);
      } catch {}
    })();
  }, []);

  // API data
  const [report, setReport] = useState<IndividualReport | null>(null);
  const [narrative, setNarrative] = useState("");
  const [notes, setNotes] = useState<SubmittedNote[]>([]);
  const [loading, setLoading] = useState(true);

  const selectedKey = toDateKey(selectedDate);
  const todayKey = toDateKey(new Date());
  const selectedIsToday = selectedKey === todayKey;
  const selectedIsWeekend = isWeekend(selectedDate);
  const selectedIsFuture = isFuture(selectedDate);
  const selectedIsPast = !selectedIsToday && !selectedIsFuture;

  const days = getMonthDays(viewYear, viewMonth);

  // ---------- Fetch standup data from API ----------
  const projectId = selectedProject?.internalId || "";

  const fetchStandup = useCallback(async (dateKey: string) => {
    setLoading(true);
    try {
      const pidParam = projectId ? `&projectId=${projectId}` : "";
      const res = await fetch(`/api/standups?date=${dateKey}${pidParam}`);
      const data = await res.json();

      const reports: IndividualReport[] = data.individualReports ?? [];
      if (reports.length > 0) {
        const r = reports[0];
        setReport(r);
        // Build a project-aware summary from the filtered items
        const cCount = r.completed?.length ?? 0;
        const ipCount = r.inProgress?.length ?? 0;
        const bCount = r.blockers?.length ?? 0;
        if (cCount + ipCount + bCount > 0) {
          setNarrative(r.narrativeText || data.summaryText || "");
        } else {
          setNarrative("No tracked activity for this project on this date.");
        }
      } else {
        setReport(null);
        setNarrative("No standup data for this date.");
      }
      setNotes(data.submittedNotes ?? []);
    } catch {
      setReport(null);
      setNarrative("Unable to load standup data.");
      setNotes([]);
    }
    setLoading(false);
  }, [projectId]);

  useEffect(() => { fetchStandup(selectedKey); }, [selectedKey, fetchStandup]);

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
        fetchStandup(selectedKey);
      }
    } catch { setSubmitError("Failed to submit note"); }
    setSubmitting(false);
  };

  // ---------- Submit note + send overview to a channel (Slack or Teams) ----------
  const handleSubmitAndChannel = async (platform: "slack" | "teams") => {
    if (!noteText.trim()) return;
    if (!selectedProject?.internalId) {
      setSubmitError("Select a project first");
      return;
    }
    setSendingTo(platform);
    setSubmitError(null);
    setChannelResult(null);

    try {
      // First: submit the full note to PO digest
      const res = await fetch("/api/standups", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note: noteText }),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        setSubmitError(data.error ?? "Failed to submit");
        setSendingTo(null);
        return;
      }

      // Then: send brief overview to channel
      const completedTitles = (report?.completed ?? []).slice(0, 3).map(c => c.title).join(", ");
      const inProgressTitles = (report?.inProgress ?? []).slice(0, 3).map(c => c.title).join(", ");
      const blockerCount = report?.blockers?.length ?? 0;

      const base = platform === "slack" ? "/api/integrations/slack" : "/api/integrations/teams";
      const prefix = platform === "slack" ? "#" : "";
      const chRes = await fetch(`${base}/post-to-channel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          projectId: selectedProject.internalId,
          type: "standup_to_channel",
          data: {
            completed: completedTitles,
            workingOn: inProgressTitles,
            blockers: blockerCount > 0 ? `${blockerCount} blocker(s) — see Plan2Sprint for details` : "",
          },
        }),
      });
      const chData = await chRes.json();
      if (chData.ok) {
        setChannelResult(`Sent overview to ${prefix}${chData.channelName}`);
        setSubmitted(true);
        setNoteText("");
        fetchStandup(selectedKey);
      } else {
        setChannelResult(chData.message || `Failed to send to ${platform === "slack" ? "Slack" : "Teams"}`);
      }
    } catch { setSubmitError("Failed to submit"); }
    setSendingTo(null);
  };

  // ---------- Flag blocker ----------
  const handleFlagBlocker = async () => {
    const desc = prompt("Describe the blocker:");
    if (!desc?.trim()) return;
    try {
      const res = await fetch("/api/standups/blocker", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ description: desc.trim() }),
      });
      if (res.ok) {
        fetchStandup(selectedKey);
      }
    } catch { /* ignore */ }
  };

  // ---------- Month navigation ----------
  const prevMonth = () => { if (viewMonth === 0) { setViewMonth(11); setViewYear(viewYear - 1); } else { setViewMonth(viewMonth - 1); } };
  const nextMonth = () => { if (viewMonth === 11) { setViewMonth(0); setViewYear(viewYear + 1); } else { setViewMonth(viewMonth + 1); } };
  const goToToday = () => { const now = new Date(); setSelectedDate(now); setViewMonth(now.getMonth()); setViewYear(now.getFullYear()); setSubmitted(false); setNoteText(""); };

  const completedItems = report?.completed ?? [];
  const inProgressItems = report?.inProgress ?? [];
  const blockerItems = report?.blockers ?? [];

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-6">

        {/* ---- CALENDAR ---- */}
        <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]/50 p-4">
          <div className="flex items-center justify-between mb-4">
            <button onClick={prevMonth} className="flex h-8 w-8 items-center justify-center rounded-lg text-[var(--text-secondary)] hover:bg-[var(--bg-surface-raised)] transition-colors cursor-pointer">
              <ChevronLeft size={16} />
            </button>
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">{MONTH_NAMES[viewMonth]} {viewYear}</h3>
            <button onClick={nextMonth} className="flex h-8 w-8 items-center justify-center rounded-lg text-[var(--text-secondary)] hover:bg-[var(--bg-surface-raised)] transition-colors cursor-pointer">
              <ChevronRight size={16} />
            </button>
          </div>

          <div className="grid grid-cols-7 mb-1">
            {DAY_LABELS.map((d) => (
              <div key={d} className="text-center text-[10px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)] py-1">{d}</div>
            ))}
          </div>

          <div className="grid grid-cols-7 gap-0.5">
            {days.map((day, idx) => {
              const key = toDateKey(day);
              const inCurrentMonth = day.getMonth() === viewMonth;
              const weekend = isWeekend(day);
              const today = isToday(day);
              const selected = key === selectedKey;
              const future = isFuture(day);

              return (
                <button key={key}
                  onClick={() => { setSelectedDate(day); setSubmitted(false); setNoteText(""); setSubmitError(null); }}
                  disabled={future}
                  className={cn(
                    "relative flex h-9 w-full items-center justify-center rounded-lg text-xs font-medium transition-all cursor-pointer",
                    !inCurrentMonth && "opacity-30",
                    future && "opacity-20 cursor-not-allowed",
                    weekend && inCurrentMonth && !selected && "text-[var(--text-tertiary)] bg-[var(--bg-surface-raised)]/30",
                    !weekend && !selected && !today && inCurrentMonth && "text-[var(--text-primary)] hover:bg-[var(--bg-surface-raised)]",
                    today && !selected && "ring-2 ring-[var(--color-brand-secondary)]/40 text-[var(--color-brand-secondary)] font-bold",
                    selected && "bg-[var(--color-brand-secondary)] text-white shadow-md",
                  )}>
                  {day.getDate()}
                  {!weekend && inCurrentMonth && !future && !selected && (
                    <span className="absolute bottom-0.5 left-1/2 -translate-x-1/2 h-1 w-1 rounded-full bg-[var(--color-rag-green)]" />
                  )}
                </button>
              );
            })}
          </div>

          <button onClick={goToToday}
            className="w-full mt-3 flex items-center justify-center gap-2 rounded-lg border border-[var(--border-subtle)] px-3 py-2 text-xs font-medium text-[var(--text-secondary)] hover:bg-[var(--bg-surface-raised)] transition-colors cursor-pointer">
            <CalendarDays size={14} /> Go to Today
          </button>

          <div className="mt-3 pt-3 border-t border-[var(--border-subtle)] space-y-1.5">
            <div className="flex items-center gap-2 text-[10px] text-[var(--text-tertiary)]">
              <span className="h-2 w-2 rounded-full bg-[var(--color-brand-secondary)]" /> Selected date
            </div>
            <div className="flex items-center gap-2 text-[10px] text-[var(--text-tertiary)]">
              <span className="h-2 w-2 rounded-full bg-[var(--color-rag-green)]" /> Standup available
            </div>
            <div className="flex items-center gap-2 text-[10px] text-[var(--text-tertiary)]">
              <span className="h-2 w-2 rounded-full bg-[var(--bg-surface-raised)]" /> Weekend (no standup)
            </div>
          </div>
        </div>

        {/* ---- STANDUP CONTENT ---- */}
        <div className="space-y-4">
          <DashboardPanel
            title={selectedIsToday ? "Today's Standup" : `Standup — ${selectedDate.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" })}`}
            icon={MessageSquareText}
            actions={
              <button
                onClick={() => fetchStandup(selectedKey)}
                className="flex items-center gap-1 text-[10px] text-[var(--text-tertiary)] hover:text-[var(--color-brand-secondary)] transition-colors cursor-pointer"
              >
                <RefreshCw size={10} /> Refresh
              </button>
            }
          >
            <div className="space-y-5">
              {selectedIsWeekend ? (
                <div className="flex flex-col items-center py-10 text-center">
                  <CalendarDays size={32} className="text-[var(--text-tertiary)] mb-3" />
                  <h3 className="text-base font-semibold text-[var(--text-primary)] mb-1">No Standup on Weekends</h3>
                  <p className="text-sm text-[var(--text-secondary)] max-w-sm">Standup reports are generated for weekdays only. Select a weekday to view the report.</p>
                </div>
              ) : loading ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 size={24} className="animate-spin text-[var(--color-brand-secondary)]" />
                </div>
              ) : (
                <>
                  {/* Date badge */}
                  <div className="flex items-center gap-2 flex-wrap">
                    <Badge variant={selectedIsToday ? "rag-green" : "brand"} className="text-[10px]">
                      {selectedIsToday ? "Today" : "Past Report"}
                    </Badge>
                    {selectedIsPast && (
                      <div className="flex items-center gap-1.5 text-xs text-[var(--text-tertiary)]">
                        <Lock size={12} />
                        <span>Read-only — past standups cannot be edited</span>
                      </div>
                    )}
                  </div>

                  <p className="text-sm leading-relaxed text-[var(--text-secondary)]">{narrative}</p>

                  {/* Completed */}
                  <div className="space-y-2">
                    <div className="flex items-center gap-2">
                      <CheckCircle2 className="h-4 w-4 text-[var(--color-rag-green)]" />
                      <span className="text-xs font-semibold uppercase tracking-wider text-[var(--color-rag-green)]">
                        Completed ({completedItems.length})
                      </span>
                    </div>
                    <div className="border-t border-[var(--border-subtle)]" />
                    {completedItems.length === 0 ? (
                      <p className="text-sm text-[var(--text-tertiary)] italic">No completed items</p>
                    ) : (
                      completedItems.map((item, i) => (
                        <div key={item.ticketId || `completed-${i}`} className="flex flex-wrap items-center gap-2 py-1.5 text-sm text-[var(--text-primary)]">
                          <span>{item.title}</span>
                          {item.ticketId && <Badge variant="brand" className="text-[10px] px-2 py-0.5">{item.ticketId}</Badge>}
                          {item.prId && <Badge variant="rag-green" className="text-[10px] px-2 py-0.5">PR #{item.prId}</Badge>}
                        </div>
                      ))
                    )}
                  </div>

                  {/* In Progress */}
                  <div className="space-y-2">
                    <div className="flex items-center gap-2">
                      <Circle className="h-4 w-4 text-[var(--color-brand-secondary)]" />
                      <span className="text-xs font-semibold uppercase tracking-wider text-[var(--color-brand-secondary)]">
                        In Progress ({inProgressItems.length})
                      </span>
                    </div>
                    <div className="border-t border-[var(--border-subtle)]" />
                    {inProgressItems.length === 0 ? (
                      <p className="text-sm text-[var(--text-tertiary)] italic">No items in progress</p>
                    ) : (
                      inProgressItems.map((item, i) => (
                        <div key={item.ticketId || `inprogress-${i}`} className="flex flex-wrap items-center gap-2 py-1.5 text-sm text-[var(--text-primary)]">
                          <span>{item.title}</span>
                          {item.ticketId && <Badge variant="brand" className="text-[10px] px-2 py-0.5">{item.ticketId}</Badge>}
                          {item.prStatus && (
                            <Badge variant={item.prStatus === "APPROVED" || item.prStatus === "MERGED" ? "rag-green" : "rag-amber"} className="text-[10px] px-2 py-0.5">
                              {item.prStatus.replace(/_/g, " ")}
                            </Badge>
                          )}
                        </div>
                      ))
                    )}
                  </div>

                  {/* Blockers */}
                  <div className="space-y-2">
                    <div className="flex items-center gap-2">
                      <AlertTriangle className="h-4 w-4 text-[var(--color-rag-red)]" />
                      <span className="text-xs font-semibold uppercase tracking-wider text-[var(--color-rag-red)]">
                        Blockers ({blockerItems.length})
                      </span>
                    </div>
                    <div className="border-t border-[var(--border-subtle)]" />
                    {blockerItems.length === 0 ? (
                      <div className="flex items-center gap-2 rounded-lg bg-[var(--color-rag-green)]/10 px-3 py-2">
                        <CheckCircle2 className="h-4 w-4 text-[var(--color-rag-green)]" />
                        <span className="text-sm font-medium text-[var(--color-rag-green)]">No blockers</span>
                      </div>
                    ) : blockerItems.map((item, i) => (
                      <div key={item.ticketId || `blocker-${i}`} className="flex flex-wrap items-center gap-2 py-1.5 text-sm text-[var(--text-primary)]">
                        <span>{item.description}</span>
                        {item.ticketId && <Badge variant="rag-red" className="text-[10px] px-2 py-0.5">{item.ticketId}</Badge>}
                        <Badge
                          variant={item.status === "OPEN" ? "rag-red" : "rag-amber"}
                          className="text-[9px] px-1.5 py-0"
                        >
                          {item.status}
                        </Badge>
                      </div>
                    ))}
                  </div>

                  {/* Submitted Notes */}
                  {notes.length > 0 && (
                    <div className="space-y-2 pt-2 border-t border-[var(--border-subtle)]">
                      <div className="flex items-center gap-2">
                        <StickyNote className="h-4 w-4 text-[var(--color-brand-secondary)]" />
                        <span className="text-xs font-semibold uppercase tracking-wider text-[var(--color-brand-secondary)]">Notes</span>
                      </div>
                      {notes.map((n) => (
                        <div key={n.id} className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/20 p-3">
                          <p className="text-sm text-[var(--text-primary)] whitespace-pre-wrap">{n.note}</p>
                          <div className="flex items-center gap-2 mt-2 text-[10px] text-[var(--text-tertiary)]">
                            <Clock size={10} /> <span>{formatTime(n.submittedAt)}</span>
                            <span>·</span> <span>{n.author}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Add Note (today only) */}
                  {selectedIsToday && !selectedIsWeekend && (
                    <div className="pt-3 border-t border-[var(--border-subtle)] space-y-3">
                      <div className="flex items-center gap-2">
                        <StickyNote className="h-4 w-4 text-[var(--text-secondary)]" />
                        <span className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">Add Note</span>
                      </div>
                      {submitted && !noteText ? (
                        <div className="flex items-center gap-2 rounded-lg bg-[var(--color-rag-green)]/10 px-4 py-3">
                          <CheckCircle2 size={16} className="text-[var(--color-rag-green)]" />
                          <span className="text-sm font-medium text-[var(--color-rag-green)]">Note submitted successfully!</span>
                          <button onClick={() => setSubmitted(false)} className="ml-auto text-xs text-[var(--color-brand-secondary)] hover:underline cursor-pointer">Add another</button>
                        </div>
                      ) : (
                        <>
                          <textarea value={noteText} onChange={(e) => setNoteText(e.target.value)}
                            placeholder="Add any comments, personal backlog items, or notes for today's standup..."
                            rows={4}
                            className={cn(
                              "w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-4 py-3 text-sm",
                              "text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)]",
                              "focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)]/40 focus:border-[var(--color-brand-secondary)]/40",
                              "resize-none"
                            )} />
                          {submitError && <p className="text-xs text-[var(--color-rag-red)]">{submitError}</p>}
                          {channelResult && <p className="text-xs text-[var(--color-rag-green)]">✓ {channelResult}</p>}
                          <div className="flex items-center justify-between gap-2 flex-wrap">
                            <p className="text-[10px] text-[var(--text-tertiary)]">This note will be visible to your Product Owner in the standup digest.</p>
                            <div className="flex items-center gap-2 flex-wrap">
                              <ChannelSendSplitButton
                                slackConnected={slackConnected}
                                teamsConnected={teamsConnected}
                                disabled={submitting || sendingTo !== null || !noteText.trim()}
                                sendingTo={sendingTo}
                                onSend={(p) => handleSubmitAndChannel(p)}
                              />
                              <button onClick={handleSubmit} disabled={submitting || sendingTo !== null || !noteText.trim()}
                                className={cn(
                                  "flex items-center gap-2 rounded-lg px-5 py-2.5 text-sm font-medium text-white transition-all cursor-pointer",
                                  "bg-[var(--color-brand-secondary)] hover:bg-[var(--color-brand-secondary)]/90",
                                  "disabled:opacity-40 disabled:cursor-not-allowed"
                                )}>
                                {submitting ? <Loader2 size={16} className="animate-spin" /> : <Send size={14} />}
                                {submitting ? "Submitting..." : "Submit"}
                              </button>
                            </div>
                          </div>
                        </>
                      )}
                    </div>
                  )}

                  {/* Past date notice */}
                  {selectedIsPast && (
                    <div className="flex items-center gap-2 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/20 px-4 py-3 text-xs text-[var(--text-tertiary)]">
                      <Lock size={14} />
                      <span>This is a past standup report. Notes can only be added for the current day.</span>
                    </div>
                  )}

                  {/* Action buttons (today only) */}
                  {selectedIsToday && (
                    <div className="flex flex-wrap gap-2 pt-2 border-t border-[var(--border-subtle)]">
                      <Button variant="secondary" size="sm" className="border-[var(--color-rag-green)]/40 text-[var(--color-rag-green)] hover:bg-[var(--color-rag-green)]/10">All Good</Button>
                      <Button variant="secondary" size="sm" onClick={handleFlagBlocker} className="border-[var(--color-rag-red)]/40 text-[var(--color-rag-red)] hover:bg-[var(--color-rag-red)]/10">Flag Blocker</Button>
                    </div>
                  )}
                </>
              )}
            </div>
          </DashboardPanel>
        </div>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  SPLIT BUTTON — "Send to Slack ▾" with dropdown showing Teams (or vice     */
/*  versa). Default = Slack if connected, else Teams. Remembers last choice.  */
/* -------------------------------------------------------------------------- */

function ChannelSendSplitButton({
  slackConnected,
  teamsConnected,
  disabled,
  sendingTo,
  onSend,
}: {
  slackConnected: boolean;
  teamsConnected: boolean;
  disabled: boolean;
  sendingTo: "slack" | "teams" | null;
  onSend: (platform: "slack" | "teams") => void;
}) {
  const [open, setOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  // Always show both platforms
  const platforms: { id: "slack" | "teams"; label: string; color: string; connected: boolean }[] = [
    { id: "slack", label: "Slack", color: "var(--color-brand-secondary)", connected: slackConnected },
    { id: "teams", label: "Teams", color: "#5059C9", connected: teamsConnected },
  ];

  // Default primary = Slack (familiar), or Teams if only Teams connected
  const [primary, setPrimary] = useState<"slack" | "teams">(
    slackConnected ? "slack" : "teams"
  );

  useEffect(() => {
    if (!slackConnected && teamsConnected) setPrimary("teams");
    if (slackConnected && !teamsConnected) setPrimary("slack");
  }, [slackConnected, teamsConnected]);

  const current = platforms.find((p) => p.id === primary) || platforms[0];
  const others = platforms.filter((p) => p.id !== current.id);
  const isSending = sendingTo !== null;
  const isSendingThis = sendingTo === current.id;

  const handleClick = (platformId: "slack" | "teams") => {
    const p = platforms.find((x) => x.id === platformId)!;
    if (!p.connected) {
      const label = platformId === "slack" ? "Slack" : "Microsoft Teams";
      setToast(`${label} is not connected yet. Ask your Product Owner to connect it.`);
      setTimeout(() => setToast(null), 4000);
      setOpen(false);
      return;
    }
    setOpen(false);
    onSend(platformId);
  };

  return (
    <div className="relative">
      <div className="flex items-stretch rounded-lg border overflow-hidden" style={{ borderColor: current.color }}>
        {/* Main action */}
        <button
          onClick={() => handleClick(current.id)}
          disabled={disabled}
          className={cn(
            "flex items-center gap-2 px-4 py-2.5 text-sm font-medium transition-all cursor-pointer",
            "disabled:opacity-40 disabled:cursor-not-allowed"
          )}
          style={{ color: current.color }}
        >
          {isSendingThis ? <Loader2 size={14} className="animate-spin" /> : <MessageSquareText size={14} />}
          {isSendingThis ? "Sending..." : `Send to ${current.label}`}
        </button>

        {/* Divider + dropdown arrow */}
        <button
          onClick={() => setOpen(!open)}
          disabled={isSending}
          className={cn(
            "flex items-center px-2 border-l transition-all cursor-pointer",
            "hover:bg-[var(--bg-surface-raised)]",
            "disabled:opacity-40 disabled:cursor-not-allowed"
          )}
          style={{ borderColor: current.color, color: current.color }}
        >
          <ChevronDown size={14} className={cn("transition-transform", open && "rotate-180")} />
        </button>
      </div>

      {/* Dropdown — always shows the other platform */}
      {open && (
        <div className="absolute z-50 top-full mt-1 right-0 min-w-[200px] rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-xl overflow-hidden">
          {others.map((p) => (
            <button
              key={p.id}
              onClick={() => {
                setPrimary(p.id);
                handleClick(p.id);
              }}
              disabled={disabled}
              className="w-full flex items-center gap-2 px-4 py-2.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-surface-raised)] transition-colors cursor-pointer disabled:opacity-40"
            >
              <MessageSquareText size={14} style={{ color: p.color }} />
              <span>Send to {p.label}</span>
              {!p.connected && (
                <span className="ml-auto text-[10px] text-[var(--text-tertiary)]">Not connected</span>
              )}
            </button>
          ))}
        </div>
      )}

      {/* Toast for not-connected platforms */}
      {toast && (
        <div className="absolute z-50 top-full mt-1 right-0 min-w-[240px] rounded-lg bg-[var(--color-rag-amber)]/10 border border-[var(--color-rag-amber)]/20 px-3 py-2">
          <p className="text-xs text-[var(--color-rag-amber)]">{toast}</p>
        </div>
      )}
    </div>
  );
}
