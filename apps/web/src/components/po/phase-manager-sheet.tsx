"use client";

import { useState, useCallback, useEffect } from "react";
import {
  Plus,
  Trash2,
  GripVertical,
  ChevronDown,
  ChevronRight,
  RefreshCw,
  Import,
  Sparkles,
  X,
} from "lucide-react";
import { Sheet, Badge } from "@/components/ui";
import { cn } from "@/lib/utils";
import { useSelectedProject } from "@/lib/project/context";
import type { ProjectPhase, PhaseAssignmentRule } from "@/lib/types/models";

// ── API helpers ──

async function apiFetch<T>(url: string, opts?: RequestInit): Promise<T | null> {
  try {
    const res = await fetch(url, {
      credentials: "include",
      headers: { "Content-Type": "application/json", ...(opts?.headers ?? {}) },
      ...opts,
    });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

// ── Color presets ──

const COLOR_PRESETS = [
  "#8b5cf6", "#3b82f6", "#06b6d4", "#f59e0b", "#f97316",
  "#22c55e", "#ef4444", "#ec4899", "#6366f1", "#14b8a6",
];

// ── Rule type labels ──

const RULE_TYPE_LABELS: Record<string, string> = {
  keyword: "Keyword (title match)",
  board_column: "Board Column (source_status)",
  iteration_path: "Iteration Path",
};

// ── Phase Card ──

interface PhaseCardProps {
  phase: ProjectPhase & { rules?: PhaseAssignmentRule[] };
  onDelete: (phaseId: string) => void;
  onUpdate: (phaseId: string, name: string, color: string) => void;
  onAddRule: (phaseId: string, ruleType: string, pattern: string) => void;
  onDeleteRule: (ruleId: string) => void;
  projectId: string;
}

function PhaseCard({ phase, onDelete, onUpdate, onAddRule, onDeleteRule, projectId }: PhaseCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(phase.name);
  const [color, setColor] = useState(phase.color);
  const [newRuleType, setNewRuleType] = useState("keyword");
  const [newPattern, setNewPattern] = useState("");

  const handleSaveName = () => {
    if (name.trim() && (name !== phase.name || color !== phase.color)) {
      onUpdate(phase.id, name.trim(), color);
    }
    setEditing(false);
  };

  return (
    <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2.5">
        <GripVertical className="h-4 w-4 text-[var(--text-secondary)]/40 shrink-0 cursor-grab" />
        <span
          className="h-3 w-3 rounded-full shrink-0"
          style={{ backgroundColor: phase.color }}
        />

        {editing ? (
          <input
            className="flex-1 text-sm font-medium bg-transparent border-b border-[var(--color-brand-secondary)] text-[var(--text-primary)] outline-none px-1"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={handleSaveName}
            onKeyDown={(e) => e.key === "Enter" && handleSaveName()}
            autoFocus
          />
        ) : (
          <span
            className="flex-1 text-sm font-medium text-[var(--text-primary)] cursor-pointer"
            onClick={() => setEditing(true)}
          >
            {phase.name}
          </span>
        )}

        {phase.featureCount !== undefined && (
          <span className="text-xs text-[var(--text-secondary)] tabular-nums">
            {phase.featureCount} features
          </span>
        )}

        <button
          onClick={() => setExpanded(!expanded)}
          className="p-1 rounded hover:bg-[var(--bg-surface)] transition-colors"
        >
          {expanded ? (
            <ChevronDown className="h-3.5 w-3.5 text-[var(--text-secondary)]" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-[var(--text-secondary)]" />
          )}
        </button>

        <button
          onClick={() => onDelete(phase.id)}
          className="p-1 rounded hover:bg-[var(--color-rag-red)]/10 transition-colors"
          title="Delete phase"
        >
          <Trash2 className="h-3.5 w-3.5 text-[var(--text-secondary)] hover:text-[var(--color-rag-red)]" />
        </button>
      </div>

      {/* Expanded: color picker + rules */}
      {expanded && (
        <div className="border-t border-[var(--border-subtle)] px-3 py-3 space-y-3">
          {/* Color picker */}
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-[var(--text-secondary)] mb-1 block">
              Color
            </label>
            <div className="flex flex-wrap gap-1.5">
              {COLOR_PRESETS.map((c) => (
                <button
                  key={c}
                  onClick={() => {
                    setColor(c);
                    onUpdate(phase.id, name, c);
                  }}
                  className={cn(
                    "h-6 w-6 rounded-full border-2 transition-all",
                    color === c
                      ? "border-[var(--text-primary)] scale-110"
                      : "border-transparent hover:scale-105"
                  )}
                  style={{ backgroundColor: c }}
                />
              ))}
            </div>
          </div>

          {/* Rules */}
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-[var(--text-secondary)] mb-1.5 block">
              Assignment Rules
            </label>
            {phase.rules && phase.rules.length > 0 ? (
              <div className="space-y-1.5">
                {phase.rules.map((rule) => (
                  <div
                    key={rule.id}
                    className="flex items-center gap-2 text-xs bg-[var(--bg-surface)] rounded px-2 py-1.5"
                  >
                    <Badge variant="brand">
                      {rule.ruleType}
                    </Badge>
                    <span className="flex-1 text-[var(--text-secondary)] truncate font-mono text-[11px]">
                      {rule.pattern}
                    </span>
                    <button
                      onClick={() => onDeleteRule(rule.id)}
                      className="p-0.5 rounded hover:bg-[var(--color-rag-red)]/10"
                    >
                      <X className="h-3 w-3 text-[var(--text-secondary)]" />
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-[var(--text-secondary)] italic">
                No rules — features won't auto-assign to this phase
              </p>
            )}

            {/* Add rule */}
            <div className="flex items-center gap-2 mt-2">
              <select
                className="text-xs bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded px-2 py-1.5 text-[var(--text-primary)]"
                value={newRuleType}
                onChange={(e) => setNewRuleType(e.target.value)}
              >
                <option value="keyword">Keyword</option>
                <option value="board_column">Board Column</option>
                <option value="iteration_path">Iteration Path</option>
              </select>
              <input
                className="flex-1 text-xs bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded px-2 py-1.5 text-[var(--text-primary)] placeholder:text-[var(--text-secondary)]/50"
                placeholder="e.g. design,ux,research"
                value={newPattern}
                onChange={(e) => setNewPattern(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && newPattern.trim()) {
                    onAddRule(phase.id, newRuleType, newPattern.trim());
                    setNewPattern("");
                  }
                }}
              />
              <button
                onClick={() => {
                  if (newPattern.trim()) {
                    onAddRule(phase.id, newRuleType, newPattern.trim());
                    setNewPattern("");
                  }
                }}
                className="p-1.5 rounded bg-[var(--color-brand-secondary)]/10 hover:bg-[var(--color-brand-secondary)]/20 transition-colors"
              >
                <Plus className="h-3.5 w-3.5 text-[var(--color-brand-secondary)]" />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Delete All Confirmation ──

interface DeleteAllDialogProps {
  open: boolean;
  onClose: () => void;
  onCreateOwn: () => void;
  onImportFromBoard: () => void;
}

function DeleteAllDialog({ open, onClose, onCreateOwn, onImportFromBoard }: DeleteAllDialogProps) {
  if (!open) return null;

  return (
    <div className="rounded-lg border-2 border-[var(--color-rag-amber)]/40 bg-[var(--color-rag-amber)]/5 p-4 space-y-3">
      <p className="text-sm font-semibold text-[var(--text-primary)]">
        Delete all phases and start fresh?
      </p>
      <p className="text-xs text-[var(--text-secondary)]">
        All phases and their rules will be deleted. Features will become unassigned.
      </p>
      <div className="flex flex-col gap-2">
        <button
          onClick={onCreateOwn}
          className="flex items-center gap-2 w-full px-3 py-2.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] hover:bg-[var(--bg-surface-raised)] transition-colors text-left"
        >
          <Sparkles className="h-4 w-4 text-[var(--color-brand-secondary)]" />
          <div>
            <div className="text-sm font-medium text-[var(--text-primary)]">Create Your Own</div>
            <div className="text-[10px] text-[var(--text-secondary)]">Blank slate — add custom phases manually</div>
          </div>
        </button>
        <button
          onClick={onImportFromBoard}
          className="flex items-center gap-2 w-full px-3 py-2.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] hover:bg-[var(--bg-surface-raised)] transition-colors text-left"
        >
          <Import className="h-4 w-4 text-[var(--color-brand-secondary)]" />
          <div>
            <div className="text-sm font-medium text-[var(--text-primary)]">Import from Board</div>
            <div className="text-[10px] text-[var(--text-secondary)]">Match your ADO/Jira board columns automatically</div>
          </div>
        </button>
      </div>
      <button
        onClick={onClose}
        className="text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
      >
        Cancel
      </button>
    </div>
  );
}

// ── Main Component ──

interface PhaseManagerSheetProps {
  open: boolean;
  onClose: () => void;
  onPhasesChanged?: () => void;
}

export function PhaseManagerSheet({ open, onClose, onPhasesChanged }: PhaseManagerSheetProps) {
  const { selectedProject } = useSelectedProject();
  const projectId = selectedProject?.internalId;

  const [phases, setPhases] = useState<(ProjectPhase & { rules?: PhaseAssignmentRule[] })[]>([]);
  const [loading, setLoading] = useState(false);
  const [showDeleteAll, setShowDeleteAll] = useState(false);
  const [newPhaseName, setNewPhaseName] = useState("");
  const [reassigning, setReassigning] = useState(false);
  const [importing, setImporting] = useState(false);
  // Two-step import flow (Sprint C): preview the board columns first,
  // then commit. ``previewing`` = fetching the columns; ``preview`` =
  // the result waiting for the PO to confirm or cancel.
  const [previewing, setPreviewing] = useState(false);
  const [preview, setPreview] = useState<{
    source: string;
    columns: string[];
    existingPhaseCount: number;
  } | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const apiBase = `/api/projects/${projectId}/phases`;

  const fetchPhases = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    // API returns a flat array of phases (each with inline rules)
    const data = await apiFetch<(ProjectPhase & { rules?: PhaseAssignmentRule[] })[]>(apiBase);
    if (Array.isArray(data)) {
      setPhases(data);
    }
    setLoading(false);
  }, [projectId, apiBase]);

  useEffect(() => {
    if (open) fetchPhases();
  }, [open, fetchPhases]);

  const handleAddPhase = async () => {
    if (!projectId || !newPhaseName.trim()) return;
    const color = COLOR_PRESETS[phases.length % COLOR_PRESETS.length];
    await apiFetch(apiBase, {
      method: "POST",
      body: JSON.stringify({ name: newPhaseName.trim(), color }),
    });
    setNewPhaseName("");
    await fetchPhases();
    onPhasesChanged?.();
  };

  const handleUpdatePhase = async (phaseId: string, name: string, color: string) => {
    await apiFetch(`${apiBase}/${phaseId}`, {
      method: "PATCH",
      body: JSON.stringify({ name, color }),
    });
    await fetchPhases();
    onPhasesChanged?.();
  };

  const handleDeletePhase = async (phaseId: string) => {
    await apiFetch(`${apiBase}/${phaseId}`, {
      method: "DELETE",
      body: JSON.stringify({ targetPhaseId: null }),
    });
    await fetchPhases();
    onPhasesChanged?.();
  };

  const handleAddRule = async (phaseId: string, ruleType: string, pattern: string) => {
    await apiFetch(`${apiBase}/${phaseId}/rules`, {
      method: "POST",
      body: JSON.stringify({ ruleType, pattern, priority: 10 }),
    });
    await fetchPhases();
  };

  const handleDeleteRule = async (ruleId: string) => {
    await apiFetch(`${apiBase}/rules/${ruleId}`, { method: "DELETE" });
    await fetchPhases();
  };

  const handleDeleteAll = async (mode: "own" | "import") => {
    // Delete all existing phases
    for (const p of phases) {
      await apiFetch(`${apiBase}/${p.id}`, {
        method: "DELETE",
        body: JSON.stringify({ targetPhaseId: null }),
      });
    }

    if (mode === "import") {
      // Import from board
      await apiFetch(`${apiBase}/import-from-board`, { method: "POST" });
    }

    setShowDeleteAll(false);
    await fetchPhases();
    onPhasesChanged?.();
  };

  const handleReassign = async () => {
    if (!projectId) return;
    setReassigning(true);
    await apiFetch(`${apiBase}/reassign`, { method: "POST" });
    setReassigning(false);
    onPhasesChanged?.();
  };

  // Sprint C — Import from Board is now two clicks:
  //   1) handleStartImport(): fetch the columns from ADO/Jira and show
  //      them in a confirmation panel inside this sheet (no DB writes).
  //   2) handleConfirmImport(): commit — wipe existing phases, create
  //      one phase per column verbatim. The board_column rule attached
  //      to each phase matches the source_status by exact name (case-
  //      insensitive), so no keyword guessing happens. Items that don't
  //      match any column drop into the existing "Unassigned" bucket.
  const handleStartImport = async () => {
    if (!projectId) return;
    setPreviewError(null);
    setPreview(null);
    setPreviewing(true);
    try {
      const res = await fetch(`${apiBase}/board-preview`, {
        credentials: "include",
        headers: { "Content-Type": "application/json" },
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        setPreviewError(
          (detail as { detail?: string })?.detail ||
            `Could not fetch board columns (HTTP ${res.status}).`
        );
        return;
      }
      const data = (await res.json()) as {
        source: string;
        columns: string[];
        existingPhaseCount: number;
      };
      if (!data.columns?.length) {
        setPreviewError("No columns returned from the board.");
        return;
      }
      setPreview(data);
    } catch (e) {
      setPreviewError(
        e instanceof Error ? e.message : "Network error fetching board columns."
      );
    } finally {
      setPreviewing(false);
    }
  };

  const handleConfirmImport = async () => {
    if (!projectId || !preview) return;
    setImporting(true);
    await apiFetch(`${apiBase}/import-from-board`, { method: "POST" });
    setImporting(false);
    setPreview(null);
    await fetchPhases();
    onPhasesChanged?.();
  };

  const handleCancelImport = () => {
    setPreview(null);
    setPreviewError(null);
  };

  return (
    <Sheet open={open} onClose={onClose} title="Customize Phases">
      <div className="p-4 space-y-4">
        {/* Actions bar */}
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={handleStartImport}
            disabled={previewing || importing}
            className="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-[var(--color-brand-secondary)] text-white hover:bg-[var(--color-brand-secondary)]/90 transition-colors disabled:opacity-50"
          >
            <Import className={cn("h-3.5 w-3.5", (previewing || importing) && "animate-spin")} />
            {previewing
              ? "Loading columns..."
              : importing
                ? "Importing..."
                : "Import from ADO/Jira Board"}
          </button>
          <button
            onClick={handleReassign}
            disabled={reassigning}
            className="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-[var(--color-brand-secondary)]/10 text-[var(--color-brand-secondary)] hover:bg-[var(--color-brand-secondary)]/20 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", reassigning && "animate-spin")} />
            Re-run Rules
          </button>
          <button
            onClick={() => setShowDeleteAll(true)}
            className="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-[var(--color-rag-red)]/10 text-[var(--color-rag-red)] hover:bg-[var(--color-rag-red)]/20 transition-colors"
          >
            <Trash2 className="h-3.5 w-3.5" />
            Delete All & Start Fresh
          </button>
        </div>

        {/* Preview error (shown when fetching columns failed) */}
        {previewError && (
          <div className="rounded-lg border border-[var(--color-rag-red)]/30 bg-[var(--color-rag-red)]/5 px-3 py-2 text-xs text-[var(--color-rag-red)]">
            {previewError}
          </div>
        )}

        {/* Preview & confirm panel — shown after the user clicks
            "Import from ADO/Jira Board" and the columns have been
            fetched successfully. NO DB writes have happened yet. */}
        {preview && (
          <div className="rounded-xl border border-[var(--color-brand-secondary)]/40 bg-[var(--color-brand-secondary)]/[0.04] p-4 space-y-3">
            <div className="flex items-start gap-2">
              <Sparkles className="h-4 w-4 text-[var(--color-brand-secondary)] mt-0.5 shrink-0" />
              <div className="text-xs text-[var(--text-primary)]">
                <p className="font-semibold">
                  Found {preview.columns.length} column{preview.columns.length === 1 ? "" : "s"} on your {preview.source.toUpperCase()} board.
                </p>
                <p className="mt-1 text-[var(--text-secondary)]">
                  Replace your current {preview.existingPhaseCount} phase{preview.existingPhaseCount === 1 ? "" : "s"} with these columns? Your work items will be re-bucketed by their <code className="px-1 py-0.5 rounded bg-[var(--bg-surface-raised)] text-[10px]">source_status</code>; anything that does not match a column lands in Unassigned.
                </p>
              </div>
            </div>

            <ul className="flex flex-wrap gap-2">
              {preview.columns.map((c, i) => (
                <li
                  key={`${c}-${i}`}
                  className="inline-flex items-center gap-1.5 rounded-full border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-3 py-1 text-[11px] font-medium text-[var(--text-primary)]"
                >
                  <span className="text-[var(--text-tertiary)] tabular-nums">{i + 1}.</span>
                  {c}
                </li>
              ))}
            </ul>

            <div className="flex items-center justify-end gap-2 pt-1">
              <button
                onClick={handleCancelImport}
                disabled={importing}
                className="inline-flex items-center gap-1 text-xs font-medium px-3 py-1.5 rounded-lg bg-[var(--bg-surface-raised)] text-[var(--text-secondary)] hover:bg-[var(--bg-surface-raised)]/80 transition-colors disabled:opacity-50"
              >
                <X className="h-3.5 w-3.5" />
                Cancel
              </button>
              <button
                onClick={handleConfirmImport}
                disabled={importing}
                className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg bg-[var(--color-brand-secondary)] text-white hover:bg-[var(--color-brand-secondary)]/90 transition-colors disabled:opacity-50"
              >
                <Import className={cn("h-3.5 w-3.5", importing && "animate-spin")} />
                {importing ? "Replacing..." : `Replace with ${preview.columns.length} board columns`}
              </button>
            </div>
          </div>
        )}

        {/* Delete all confirmation */}
        <DeleteAllDialog
          open={showDeleteAll}
          onClose={() => setShowDeleteAll(false)}
          onCreateOwn={() => handleDeleteAll("own")}
          onImportFromBoard={() => handleDeleteAll("import")}
        />

        {/* Phase list */}
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <RefreshCw className="h-5 w-5 animate-spin text-[var(--text-secondary)]" />
          </div>
        ) : phases.length === 0 ? (
          <div className="text-center py-8 text-sm text-[var(--text-secondary)]">
            No phases configured. Add one below or import from your board.
          </div>
        ) : (
          <div className="space-y-2">
            {phases.map((phase) => (
              <PhaseCard
                key={phase.id}
                phase={phase}
                onDelete={handleDeletePhase}
                onUpdate={handleUpdatePhase}
                onAddRule={handleAddRule}
                onDeleteRule={handleDeleteRule}
                projectId={projectId ?? ""}
              />
            ))}
          </div>
        )}

        {/* Add phase */}
        <div className="flex items-center gap-2 pt-2 border-t border-[var(--border-subtle)]">
          <input
            className="flex-1 text-sm bg-[var(--bg-surface-raised)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-[var(--text-primary)] placeholder:text-[var(--text-secondary)]/50"
            placeholder="New phase name..."
            value={newPhaseName}
            onChange={(e) => setNewPhaseName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleAddPhase()}
          />
          <button
            onClick={handleAddPhase}
            disabled={!newPhaseName.trim()}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-[var(--color-brand-secondary)] text-white text-sm font-medium hover:bg-[var(--color-brand-secondary)]/90 transition-colors disabled:opacity-50"
          >
            <Plus className="h-4 w-4" />
            Add
          </button>
        </div>
      </div>
    </Sheet>
  );
}
