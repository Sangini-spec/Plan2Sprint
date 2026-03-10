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
} from "lucide-react";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Badge, Avatar } from "@/components/ui";
import { useAutoRefresh } from "@/lib/ws/context";

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
  avatarUrl?: string | null;
  acknowledged: boolean;
  isInactive: boolean;
  completedCount: number;
  inProgressCount: number;
  blockerCount: number;
  completed: StandupItem[];
  inProgress: StandupItem[];
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
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatNoteTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true });
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function StandupDigestPanel() {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [digest, setDigest] = useState<DigestData | null>(null);
  const [loading, setLoading] = useState(true);
  const refreshKey = useAutoRefresh(["standup_generated", "standup_note_submitted", "sync_complete"]);

  const fetchDigest = useCallback(async () => {
    setLoading(true);
    try {
      const today = new Date().toISOString().split("T")[0];
      const res = await fetch(`/api/standups?date=${today}`);
      const data = await res.json();
      setDigest(data);
    } catch {
      setDigest(null);
    }
    setLoading(false);
  }, []);

  useEffect(() => { fetchDigest(); }, [fetchDigest, refreshKey]);

  // Build a map of author -> notes for quick lookup
  const notesByAuthor = useMemo(() => {
    const map = new Map<string, SubmittedNote[]>();
    for (const note of (digest?.submittedNotes ?? [])) {
      const key = note.author.toLowerCase();
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(note);
    }
    return map;
  }, [digest?.submittedNotes]);

  const reports = digest?.individualReports ?? [];

  // Find note authors who are NOT in the individual reports
  const reportNames = useMemo(() => new Set(reports.map(r => r.displayName.toLowerCase())), [reports]);
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
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function hasSubmittedNote(displayName: string): boolean {
    return notesByAuthor.has(displayName.toLowerCase());
  }

  function getNotesForMember(displayName: string): SubmittedNote[] {
    return notesByAuthor.get(displayName.toLowerCase()) ?? [];
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
        <button onClick={fetchDigest}
          className="flex items-center gap-1 text-[10px] text-[var(--text-tertiary)] hover:text-[var(--color-brand-secondary)] transition-colors cursor-pointer">
          <RefreshCw size={10} /> Refresh
        </button>
      }
    >
      <div className="space-y-5">
        {/* Summary text */}
        <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
          {digest?.summaryText || "No standup data yet. Sync project data to auto-generate standups."}
        </p>

        {/* Header stats row */}
        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/50 p-3 text-center">
            <p className="text-xs font-medium text-[var(--text-secondary)] mb-1">Sprint Pacing</p>
            <p className="text-xl font-bold text-[var(--text-primary)]">{digest?.sprintPacing ?? 0}%</p>
          </div>
          <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/50 p-3 text-center">
            <p className="text-xs font-medium text-[var(--text-secondary)] mb-1">Acknowledged</p>
            <p className="text-xl font-bold text-[var(--text-primary)]">{digest?.acknowledgedPct ?? 0}%</p>
          </div>
          <div className={cn("rounded-xl border p-3 text-center",
            (digest?.blockerCount ?? 0) > 0
              ? "border-[var(--color-rag-red)]/30 bg-[var(--color-rag-red)]/5"
              : "border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/50")}>
            <p className="text-xs font-medium text-[var(--text-secondary)] mb-1">Blockers</p>
            <p className={cn("text-xl font-bold",
              (digest?.blockerCount ?? 0) > 0 ? "text-[var(--color-rag-red)]" : "text-[var(--text-primary)]")}>
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

          {reports.map((report, idx) => {
            const rowId = `${report.teamMemberId}-${idx}`;
            const isExpanded = expandedIds.has(rowId);
            const memberNotes = getNotesForMember(report.displayName);
            const hasNote = hasSubmittedNote(report.displayName);

            return (
              <div key={rowId} className="rounded-xl border border-[var(--border-subtle)] overflow-hidden">
                {/* Header row */}
                <div className={cn(
                  "flex items-center justify-between w-full px-4 py-3",
                  "hover:bg-[var(--bg-surface-raised)]/50 transition-colors duration-150"
                )}>
                  <div className="flex items-center gap-3 flex-1">
                    <Avatar src={report.avatarUrl ?? undefined} fallback={report.displayName} size="sm" />
                    <span className="text-sm font-medium text-[var(--text-primary)]">{report.displayName}</span>
                    {report.acknowledged ? (
                      <CheckCircle2 className="h-4 w-4 text-[var(--color-rag-green)]" />
                    ) : (
                      <Clock className="h-4 w-4 text-[var(--color-rag-amber)]" />
                    )}
                    {report.isInactive && (
                      <Badge variant="brand" className="text-[10px]">Inactive</Badge>
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

                  <div className="flex items-center gap-2">
                    <button
                      onClick={(e) => { e.stopPropagation(); toggleExpand(rowId); }}
                      className={cn(
                        "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-all cursor-pointer",
                        "border border-[var(--color-brand-secondary)]/30 text-[var(--color-brand-secondary)] bg-[var(--color-brand-secondary)]/5 hover:bg-[var(--color-brand-secondary)]/10"
                      )}
                    >
                      <Eye size={12} />
                      {isExpanded ? "Close" : "Read Standup"}
                    </button>
                    <button onClick={() => toggleExpand(rowId)} className="cursor-pointer p-1">
                      <motion.div animate={{ rotate: isExpanded ? 0 : -90 }} transition={{ duration: 0.2 }}>
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
                      <div className="px-4 pb-4 space-y-3 border-t border-[var(--border-subtle)] pt-3">
                        {/* Narrative */}
                        {report.narrativeText && (
                          <p className="text-sm text-[var(--text-secondary)] leading-relaxed italic">
                            {report.narrativeText}
                          </p>
                        )}

                        {/* Completed items */}
                        {report.completed.length > 0 && (
                          <div>
                            <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-rag-green)] mb-1.5">
                              Completed ({report.completed.length})
                            </h4>
                            <ul className="space-y-1">
                              {report.completed.map((item, cidx) => (
                                <li key={item.ticketId || `completed-${cidx}`} className="flex items-center gap-2 text-sm text-[var(--text-primary)]">
                                  <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-[var(--color-rag-green)]" />
                                  <span>{item.title}</span>
                                  {item.ticketId && <span className="text-xs text-[var(--text-secondary)]">({item.ticketId})</span>}
                                  {item.prId && <Badge variant="rag-green" className="text-[9px] px-1.5 py-0">PR #{item.prId}</Badge>}
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}

                        {/* In-progress items */}
                        {report.inProgress.length > 0 && (
                          <div>
                            <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-brand-secondary)] mb-1.5">
                              In Progress ({report.inProgress.length})
                            </h4>
                            <ul className="space-y-1.5">
                              {report.inProgress.map((item, pidx) => (
                                <li key={item.ticketId || `inprogress-${pidx}`} className="flex items-center gap-2 text-sm text-[var(--text-primary)]">
                                  <Circle className="h-3.5 w-3.5 shrink-0 text-[var(--color-brand-secondary)]" />
                                  <span className="truncate">{item.title}</span>
                                  {item.ticketId && <span className="text-xs text-[var(--text-secondary)] shrink-0">({item.ticketId})</span>}
                                  {item.prStatus && (
                                    <Badge
                                      variant={item.prStatus === "APPROVED" || item.prStatus === "MERGED" ? "rag-green" : "rag-amber"}
                                      className="text-[10px] shrink-0"
                                    >
                                      {item.prStatus.replace(/_/g, " ")}
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
                            <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-rag-red)] mb-1.5">Blockers</h4>
                            <ul className="space-y-1">
                              {report.blockers.map((blocker, bidx) => (
                                <li key={`blocker-${bidx}-${blocker.description.slice(0, 20)}`} className="flex items-start gap-2 text-sm text-[var(--color-rag-red)]">
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
                                <p className="text-sm text-[var(--text-primary)] whitespace-pre-wrap leading-relaxed">{n.note}</p>
                                <div className="flex items-center gap-2 mt-1.5 text-[10px] text-[var(--text-tertiary)]">
                                  <Clock size={10} />
                                  <span>Submitted at {formatNoteTime(n.submittedAt)}</span>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Inactive / no data */}
                        {report.isInactive && report.completed.length === 0 && report.inProgress.length === 0 && (
                          <div className="flex items-center gap-2 text-xs text-[var(--text-tertiary)] py-1">
                            <Clock size={12} />
                            <span>No recent activity for this member.</span>
                          </div>
                        )}
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
              <div key={rowId} className="rounded-xl border border-[var(--border-subtle)] overflow-hidden">
                <div className={cn(
                  "flex items-center justify-between w-full px-4 py-3",
                  "hover:bg-[var(--bg-surface-raised)]/50 transition-colors duration-150"
                )}>
                  <div className="flex items-center gap-3 flex-1">
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--color-brand-secondary)]/20 text-sm font-semibold text-[var(--color-brand-secondary)]">
                      {authorName.charAt(0).toUpperCase()}
                    </div>
                    <span className="text-sm font-medium text-[var(--text-primary)]">{authorName}</span>
                    <Badge variant="brand" className="text-[10px] px-1.5 py-0">{authorRole}</Badge>
                    <Badge variant="rag-green" className="text-[10px] px-2 py-0.5">
                      <StickyNote size={10} className="mr-1 inline" />
                      Note sent
                    </Badge>
                  </div>
                  <div className="flex items-center gap-2">
                    <button onClick={() => toggleExpand(rowId)}
                      className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium border border-[var(--color-brand-secondary)]/30 text-[var(--color-brand-secondary)] bg-[var(--color-brand-secondary)]/5 hover:bg-[var(--color-brand-secondary)]/10 cursor-pointer transition-all">
                      <Eye size={12} />
                      {isExpanded ? "Close" : "Read Standup"}
                    </button>
                    <button onClick={() => toggleExpand(rowId)} className="cursor-pointer p-1">
                      <motion.div animate={{ rotate: isExpanded ? 0 : -90 }} transition={{ duration: 0.2 }}>
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
                          <div key={n.id} className="rounded-lg border border-[var(--color-brand-secondary)]/20 bg-[var(--color-brand-secondary)]/5 p-3">
                            <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-brand-secondary)] flex items-center gap-1.5 mb-2">
                              <StickyNote size={12} /> Developer Note
                            </h4>
                            <p className="text-sm text-[var(--text-primary)] whitespace-pre-wrap leading-relaxed">{n.note}</p>
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
          <button onClick={fetchDigest} disabled={loading}
            className="flex items-center gap-1.5 text-xs text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] cursor-pointer disabled:opacity-50">
            <RefreshCw size={12} className={loading ? "animate-spin" : ""} /> Refresh
          </button>
        </div>
      </div>
    </DashboardPanel>
  );
}
