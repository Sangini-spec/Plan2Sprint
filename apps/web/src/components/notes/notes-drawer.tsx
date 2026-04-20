"use client";

/* -------------------------------------------------------------------------- */
/*  SMART NOTES DRAWER                                                         */
/*                                                                             */
/*  Slide-out notebook from the right edge of the screen. Sticky-note cards   */
/*  with a pastel palette. One-click share to Slack/Teams + AI Expand.        */
/* -------------------------------------------------------------------------- */

import { useState, useEffect, useCallback, useRef, type KeyboardEvent } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Search,
  Pin,
  PinOff,
  Trash2,
  Send,
  Sparkles,
  X,
  Plus,
  StickyNote,
  Loader2,
  Check,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useSelectedProject } from "@/lib/project/context";

/* -------------------------------------------------------------------------- */

export interface Note {
  id: string;
  content: string;
  category: string;
  color: string;
  pinned: boolean;
  tags: string[];
  projectId: string | null;
  authorEmail: string;
  authorName: string | null;
  createdAt: string | null;
  updatedAt: string | null;
}

/* Pastel color map — matches the gradient palette (blue ↔ green) */
const NOTE_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  blue: { bg: "#dbeafe", border: "#93c5fd", text: "#1e3a8a" },
  teal: { bg: "#ccfbf1", border: "#5eead4", text: "#115e59" },
  mint: { bg: "#d1fae5", border: "#6ee7b7", text: "#065f46" },
  sage: { bg: "#ecfccb", border: "#bef264", text: "#365314" },
  sky:  { bg: "#e0f2fe", border: "#7dd3fc", text: "#075985" },
  amber:{ bg: "#fef3c7", border: "#fcd34d", text: "#78350f" },
};

const CATEGORY_OPTIONS = ["idea", "bug", "feature", "decision", "question", "note"];

/* -------------------------------------------------------------------------- */

interface NotesDrawerProps {
  open: boolean;
  onClose: () => void;
}

export function NotesDrawer({ open, onClose }: NotesDrawerProps) {
  const { selectedProject } = useSelectedProject();
  const projectId = selectedProject?.internalId || "";

  const [notes, setNotes] = useState<Note[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [filterThisProject, setFilterThisProject] = useState(true);
  const [draft, setDraft] = useState("");
  const [draftCategory, setDraftCategory] = useState<string>("idea");
  const [creating, setCreating] = useState(false);

  const fetchNotes = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filterThisProject && projectId) params.set("projectId", projectId);
      if (search.trim()) params.set("q", search.trim());
      const res = await fetch(`/api/notes?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        setNotes(data.notes || []);
      }
    } catch { /* ignore */ }
    setLoading(false);
  }, [filterThisProject, projectId, search]);

  useEffect(() => {
    if (open) fetchNotes();
  }, [open, fetchNotes]);

  // ESC to close
  useEffect(() => {
    if (!open) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const handleCreate = async () => {
    const content = draft.trim();
    if (!content) return;
    setCreating(true);
    try {
      const res = await fetch("/api/notes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content,
          category: draftCategory,
          projectId: projectId || null,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setNotes((prev) => [data.note, ...prev]);
        setDraft("");
      }
    } catch { /* ignore */ }
    setCreating(false);
  };

  const handleUpdate = async (id: string, patch: Partial<Note>) => {
    try {
      const res = await fetch(`/api/notes/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      if (res.ok) {
        const data = await res.json();
        setNotes((prev) => prev.map((n) => (n.id === id ? data.note : n)));
      }
    } catch { /* ignore */ }
  };

  const handleDelete = async (id: string) => {
    try {
      const res = await fetch(`/api/notes/${id}`, { method: "DELETE" });
      if (res.ok) setNotes((prev) => prev.filter((n) => n.id !== id));
    } catch { /* ignore */ }
  };

  const handleExpand = async (id: string) => {
    try {
      const res = await fetch(`/api/notes/${id}/expand`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setNotes((prev) => prev.map((n) => (n.id === id ? data.note : n)));
      }
    } catch { /* ignore */ }
  };

  const handleShare = async (id: string, platform: "slack" | "teams") => {
    try {
      const res = await fetch(`/api/notes/${id}/share-to-channel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ platform }),
      });
      return res.ok;
    } catch {
      return false;
    }
  };

  const handleDraftKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      handleCreate();
    }
  };

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop — darker so the drawer reads as a clear foreground panel */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 z-40 bg-black/60"
          />

          {/* Drawer — explicit full viewport height + hardcoded opaque bg */}
          <motion.aside
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 28, stiffness: 300 }}
            style={{
              position: "fixed",
              top: 0,
              right: 0,
              height: "100vh",
              width: "min(640px, 100vw)",
              // Follows the theme: #FFFFFF in light mode, #13131A in dark mode
              backgroundColor: "var(--bg-surface)",
              zIndex: 50,
              display: "flex",
              flexDirection: "column",
            }}
            className={cn(
              "border-l border-[var(--border-subtle)]",
              // Left-only shadow so it doesn't bleed onto the top navbar or bottom.
              // Negative X offset + larger blur = soft left-edge lift without top/bottom haze.
              "shadow-[-12px_0_32px_rgba(0,0,0,0.25)]",
            )}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border-subtle)]">
              <div className="flex items-center gap-2.5">
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-[#60a5fa] to-[#34d399]">
                  <StickyNote size={16} className="text-white" />
                </span>
                <div>
                  <h2 className="text-sm font-semibold text-[var(--text-primary)]">My Notes</h2>
                  <p className="text-[11px] text-[var(--text-tertiary)]">
                    {notes.length} {notes.length === 1 ? "note" : "notes"}
                    {filterThisProject && selectedProject ? ` · ${selectedProject.name}` : ""}
                  </p>
                </div>
              </div>
              <button
                onClick={onClose}
                className="rounded-lg p-1.5 hover:bg-[var(--bg-surface-raised)] transition-colors cursor-pointer"
                aria-label="Close notes"
              >
                <X size={16} className="text-[var(--text-secondary)]" />
              </button>
            </div>

            {/* Search + Filter */}
            <div className="px-5 py-3 border-b border-[var(--border-subtle)] space-y-2">
              <div className="relative">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)]" />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search notes..."
                  className="w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] pl-9 pr-3 py-1.5 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)]/40"
                />
              </div>
              <div className="flex items-center gap-2 text-xs">
                <button
                  onClick={() => setFilterThisProject(false)}
                  className={cn(
                    "px-2.5 py-1 rounded-md transition-colors cursor-pointer",
                    !filterThisProject
                      ? "bg-[var(--color-brand-secondary)]/10 text-[var(--color-brand-secondary)] font-medium"
                      : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                  )}
                >
                  All projects
                </button>
                <button
                  onClick={() => setFilterThisProject(true)}
                  disabled={!projectId}
                  className={cn(
                    "px-2.5 py-1 rounded-md transition-colors cursor-pointer",
                    filterThisProject
                      ? "bg-[var(--color-brand-secondary)]/10 text-[var(--color-brand-secondary)] font-medium"
                      : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
                    !projectId && "opacity-40 cursor-not-allowed"
                  )}
                >
                  This project
                </button>
              </div>
            </div>

            {/* Notes list — min-h-0 lets it actually shrink inside the flex parent so overflow-y-auto kicks in */}
            <div className="flex-1 min-h-0 overflow-y-auto px-5 py-4 space-y-3">
              {loading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 size={18} className="animate-spin text-[var(--color-brand-secondary)]" />
                </div>
              ) : notes.length === 0 ? (
                <EmptyNotesState />
              ) : (
                notes.map((note) => (
                  <NoteCard
                    key={note.id}
                    note={note}
                    onUpdate={(patch) => handleUpdate(note.id, patch)}
                    onDelete={() => handleDelete(note.id)}
                    onExpand={() => handleExpand(note.id)}
                    onShare={(platform) => handleShare(note.id, platform)}
                  />
                ))
              )}
            </div>

            {/* Quick composer */}
            <div className="border-t border-[var(--border-subtle)] px-5 py-3 bg-[var(--bg-surface-raised)]/30">
              <div className="space-y-2">
                <textarea
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={handleDraftKey}
                  placeholder="Capture an idea… (⌘/Ctrl+Enter to save)"
                  rows={2}
                  className="w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] resize-none focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)]/40"
                />
                <div className="flex items-center justify-between gap-2">
                  <select
                    value={draftCategory}
                    onChange={(e) => setDraftCategory(e.target.value)}
                    className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-2 py-1 text-xs text-[var(--text-primary)] capitalize cursor-pointer"
                  >
                    {CATEGORY_OPTIONS.map((c) => (
                      <option key={c} value={c}>{c}</option>
                    ))}
                  </select>
                  <button
                    onClick={handleCreate}
                    disabled={!draft.trim() || creating}
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold text-white transition-all cursor-pointer",
                      "bg-gradient-to-r from-[#3b82f6] to-[#10b981] hover:brightness-110",
                      "disabled:opacity-40 disabled:cursor-not-allowed"
                    )}
                  >
                    {creating ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
                    Add note
                  </button>
                </div>
              </div>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

/* -------------------------------------------------------------------------- */
/*  NOTE CARD — sticky-note aesthetic                                         */
/* -------------------------------------------------------------------------- */

function NoteCard({
  note,
  onUpdate,
  onDelete,
  onExpand,
  onShare,
}: {
  note: Note;
  onUpdate: (patch: Partial<Note>) => Promise<void> | void;
  onDelete: () => Promise<void> | void;
  onExpand: () => Promise<void>;
  onShare: (platform: "slack" | "teams") => Promise<boolean>;
}) {
  const palette = NOTE_COLORS[note.color] || NOTE_COLORS.blue;
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState(note.content);
  const [expanding, setExpanding] = useState(false);
  const [sharing, setSharing] = useState<"slack" | "teams" | null>(null);
  const [shareResult, setShareResult] = useState<string | null>(null);

  const saveEdit = () => {
    const c = editContent.trim();
    if (c && c !== note.content) {
      onUpdate({ content: c });
    }
    setEditing(false);
  };

  const runExpand = async () => {
    setExpanding(true);
    await onExpand();
    setExpanding(false);
  };

  const runShare = async (platform: "slack" | "teams") => {
    setSharing(platform);
    const ok = await onShare(platform);
    setSharing(null);
    setShareResult(ok ? `Shared to ${platform}` : "Failed");
    setTimeout(() => setShareResult(null), 2500);
  };

  const timeAgo = note.updatedAt
    ? new Date(note.updatedAt).toLocaleDateString("en-US", { month: "short", day: "numeric" })
    : "";

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      style={{
        backgroundColor: palette.bg,
        borderColor: palette.border,
      }}
      className="relative rounded-xl border p-4 shadow-sm hover:shadow-md transition-shadow group"
    >
      {/* Pin indicator */}
      {note.pinned && (
        <span className="absolute -top-1.5 -right-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-[var(--color-rag-amber)] shadow">
          <Pin size={10} className="text-white" />
        </span>
      )}

      {/* Header row */}
      <div className="flex items-center gap-2 mb-2" style={{ color: palette.text }}>
        <span className="text-[10px] font-bold uppercase tracking-wider">
          {note.category}
        </span>
        <span className="text-[10px] opacity-60">·</span>
        <span className="text-[10px] opacity-70">{timeAgo}</span>
      </div>

      {/* Content */}
      {editing ? (
        <textarea
          value={editContent}
          onChange={(e) => setEditContent(e.target.value)}
          onBlur={saveEdit}
          autoFocus
          rows={Math.max(3, Math.min(10, editContent.split("\n").length + 1))}
          className="w-full bg-transparent text-sm leading-relaxed resize-none focus:outline-none"
          style={{ color: palette.text }}
        />
      ) : (
        <p
          onClick={() => setEditing(true)}
          className="text-sm leading-relaxed whitespace-pre-wrap cursor-text"
          style={{ color: palette.text }}
        >
          {note.content}
        </p>
      )}

      {/* Actions — appear on hover */}
      <div className="mt-3 pt-2 border-t flex items-center justify-between gap-2 opacity-60 group-hover:opacity-100 transition-opacity" style={{ borderColor: palette.border }}>
        <div className="flex items-center gap-1">
          <IconButton
            onClick={() => onUpdate({ pinned: !note.pinned })}
            title={note.pinned ? "Unpin" : "Pin to top"}
            color={palette.text}
          >
            {note.pinned ? <PinOff size={12} /> : <Pin size={12} />}
          </IconButton>
          <IconButton
            onClick={() => runShare("slack")}
            title="Share to Slack project channel"
            color={palette.text}
            disabled={sharing !== null || !note.projectId}
          >
            {sharing === "slack" ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
          </IconButton>
          <IconButton
            onClick={() => runShare("teams")}
            title="Share to Teams project channel"
            color={palette.text}
            disabled={sharing !== null || !note.projectId}
          >
            <span className="text-[10px] font-bold">T</span>
          </IconButton>
          <IconButton
            onClick={runExpand}
            title="Expand with AI"
            color={palette.text}
            disabled={expanding}
          >
            {expanding ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
          </IconButton>
        </div>
        <div className="flex items-center gap-2">
          {shareResult && (
            <span className="text-[10px] font-medium flex items-center gap-1" style={{ color: palette.text }}>
              <Check size={10} />
              {shareResult}
            </span>
          )}
          <IconButton
            onClick={onDelete}
            title="Delete note"
            color={palette.text}
          >
            <Trash2 size={12} />
          </IconButton>
        </div>
      </div>
    </motion.div>
  );
}

function IconButton({
  onClick,
  title,
  color,
  disabled,
  children,
}: {
  onClick: () => void;
  title: string;
  color: string;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      disabled={disabled}
      style={{ color }}
      className="p-1 rounded-md hover:bg-black/10 transition-colors cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed"
    >
      {children}
    </button>
  );
}

/* -------------------------------------------------------------------------- */

function EmptyNotesState() {
  return (
    <div className="flex flex-col items-center justify-center py-10 px-4 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-[#dbeafe] to-[#d1fae5] mb-3">
        <StickyNote size={22} className="text-[#3b82f6]" />
      </div>
      <p className="text-sm font-medium text-[var(--text-primary)] mb-1">
        Your notebook is empty
      </p>
      <p className="text-xs text-[var(--text-secondary)] leading-relaxed max-w-[260px]">
        Capture ideas, bugs, or decisions below. Each note is private to you and auto-tagged with your current project.
      </p>
    </div>
  );
}
