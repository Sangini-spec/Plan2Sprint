"use client";

import { useState, useEffect, useCallback } from "react";
import { X, ShieldCheck, AlertTriangle, Loader2, CheckCircle2, Calendar, Clock } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";
import { Avatar, Badge, Button, Progress } from "@/components/ui";
import { useSelectedProject } from "@/lib/project/context";

// ---------------------------------------------------------------------------
// Types for API response
// ---------------------------------------------------------------------------

interface ApiPlan {
  id: string;
  status: string;
  confidenceScore: number | null;
  riskSummary: string | null;
  totalStoryPoints: number | null;
  unplannedItems?: { items: { workItemId: string; reason: string }[] };
  estimatedSprints?: number | null;
  estimatedEndDate?: string | null;
}

interface ApiAssignment {
  id: string;
  workItemId: string;
  teamMemberId: string;
  storyPoints: number;
  confidenceScore: number;
  rationale: string;
  riskFlags: string[];
  skillMatch?: { matchedSkills: string[]; score: number } | null;
  isHumanEdited: boolean;
  sprintNumber?: number;
}

interface ApiWorkItem {
  id: string;
  externalId: string;
  title: string;
  status: string;
  storyPoints: number | null;
  priority: number;
  type: string;
  labels: string[];
}

interface ApiTeamMember {
  id: string;
  displayName: string;
  email: string;
  avatarUrl: string | null;
  skillTags: string[];
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface PlanApprovalModalProps {
  open: boolean;
  onClose: () => void;
  isRebalancing?: boolean;
}

export function PlanApprovalModal({ open, onClose, isRebalancing = false }: PlanApprovalModalProps) {
  const { selectedProject } = useSelectedProject();
  const [loading, setLoading] = useState(true);
  const [plan, setPlan] = useState<ApiPlan | null>(null);
  const [assignments, setAssignments] = useState<ApiAssignment[]>([]);
  const [workItems, setWorkItems] = useState<ApiWorkItem[]>([]);
  const [teamMembers, setTeamMembers] = useState<ApiTeamMember[]>([]);
  const [approving, setApproving] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [actionDone, setActionDone] = useState<"approved" | "rejected" | null>(null);

  // Fetch full plan details when modal opens
  const fetchPlanDetails = useCallback(async () => {
    setLoading(true);
    try {
      const pid = selectedProject?.internalId;
      const q = pid ? `?projectId=${pid}` : "";
      const res = await fetch(`/api/sprints/plan${q}`);
      if (res.ok) {
        const data = await res.json();
        if (data.plan && data.assignments?.length > 0) {
          setPlan(data.plan);
          setAssignments(data.assignments);
          setWorkItems(data.workItems || []);
          setTeamMembers(data.teamMembers || []);
          setLoading(false);
          return;
        }
      }
    } catch {
      // API unavailable — leave empty state
    }

    // No real plan data — show empty state
    setPlan(null);
    setAssignments([]);
    setWorkItems([]);
    setTeamMembers([]);
    setLoading(false);
  }, []);

  useEffect(() => {
    if (open) {
      setActionDone(null);
      fetchPlanDetails();
    }
  }, [open, fetchPlanDetails]);

  // Approve handler
  const handleApprove = async () => {
    if (!plan) return;
    setApproving(true);
    try {
      const res = await fetch("/api/sprints", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ planId: plan.id, status: "APPROVED" }),
      });
      if (res.ok) {
        setActionDone("approved");
        setTimeout(() => onClose(), 1500);
      }
    } catch (e) {
      console.error("Approve failed:", e);
    } finally {
      setApproving(false);
    }
  };

  // Reject handler
  const handleReject = async () => {
    if (!plan) return;
    setRejecting(true);
    try {
      const res = await fetch("/api/sprints", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          planId: plan.id,
          status: "REJECTED",
          rejectionFeedback: "Rejected by PO — regenerate with adjustments",
        }),
      });
      if (res.ok) {
        setActionDone("rejected");
        setTimeout(() => onClose(), 1500);
      }
    } catch (e) {
      console.error("Reject failed:", e);
    } finally {
      setRejecting(false);
    }
  };

  const confidencePct = plan?.confidenceScore
    ? Math.round(plan.confidenceScore * 100)
    : 0;

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm"
            onClick={onClose}
          />

          {/* Modal */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            transition={{ duration: 0.25, ease: "easeOut" }}
            className={cn(
              "fixed inset-4 z-50 flex flex-col",
              "rounded-2xl border border-[var(--border-subtle)]",
              "bg-[var(--bg-surface)] shadow-2xl",
              "md:inset-8 lg:inset-16"
            )}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border-subtle)] shrink-0">
              <div className="flex items-center gap-4">
                <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[var(--color-brand-secondary)]/10">
                  <ShieldCheck className="h-5 w-5 text-[var(--color-brand-secondary)]" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold text-[var(--text-primary)]">
                    {isRebalancing ? "Rebalancing Plan" : "Sprint Plan Review"}
                  </h2>
                  <p className="text-xs text-[var(--text-secondary)]">
                    Review AI-generated assignments before syncing
                    {plan?.totalStoryPoints ? ` — ${plan.totalStoryPoints} SP total` : ""}
                    {plan?.estimatedSprints && plan.estimatedSprints > 1
                      ? ` across ${plan.estimatedSprints} sprints`
                      : ""}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-2">
                  <span className="text-sm text-[var(--text-secondary)]">
                    Confidence
                  </span>
                  <span
                    className={cn(
                      "text-sm font-bold tabular-nums",
                      confidencePct >= 80
                        ? "text-[var(--color-rag-green)]"
                        : confidencePct >= 60
                          ? "text-[var(--color-rag-amber)]"
                          : "text-[var(--color-rag-red)]"
                    )}
                  >
                    {confidencePct}%
                  </span>
                </div>
                <button
                  onClick={onClose}
                  className="flex h-8 w-8 items-center justify-center rounded-lg text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-surface-raised)] transition-colors cursor-pointer"
                >
                  <X size={18} />
                </button>
              </div>
            </div>

            {/* Body - scrollable assignment list */}
            <div className="flex-1 overflow-y-auto p-6 space-y-4">
              {loading ? (
                <div className="flex items-center justify-center py-16">
                  <Loader2 className="h-6 w-6 animate-spin text-[var(--text-secondary)]" />
                </div>
              ) : actionDone ? (
                <div className="flex flex-col items-center justify-center py-16 gap-3">
                  <CheckCircle2
                    className={cn(
                      "h-12 w-12",
                      actionDone === "approved" ? "text-[var(--color-rag-green)]" : "text-[var(--color-rag-amber)]"
                    )}
                  />
                  <p className="text-lg font-semibold text-[var(--text-primary)]">
                    {actionDone === "approved" ? "Plan Approved!" : "Plan Rejected"}
                  </p>
                  <p className="text-sm text-[var(--text-secondary)]">
                    {actionDone === "approved"
                      ? "Assignments are ready for sync to your project tool."
                      : "The plan has been rejected. You can regenerate with adjustments."}
                  </p>
                </div>
              ) : !plan || assignments.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 gap-3">
                  <ShieldCheck className="h-10 w-10 text-[var(--text-tertiary)]" />
                  <p className="text-lg font-semibold text-[var(--text-primary)]">
                    No Sprint Plan Available
                  </p>
                  <p className="text-sm text-[var(--text-secondary)] text-center max-w-sm">
                    Generate a sprint plan first from the Sprint Plan Generation panel, then come back here to review assignments.
                  </p>
                </div>
              ) : (
                <>
                  {/* Timeline banner */}
                  {plan?.estimatedSprints && plan.estimatedSprints > 0 && (
                    <div className="rounded-xl border border-[var(--color-brand-secondary)]/30 bg-[var(--color-brand-secondary)]/5 p-4 mb-2">
                      <div className="flex items-center gap-6 flex-wrap">
                        <div className="flex items-center gap-2">
                          <Calendar className="h-4 w-4 text-[var(--color-brand-secondary)]" />
                          <span className="text-sm font-semibold text-[var(--text-primary)]">
                            {plan.estimatedSprints} Sprint{plan.estimatedSprints > 1 ? "s" : ""} Required
                          </span>
                        </div>
                        {plan.estimatedEndDate && (
                          <div className="flex items-center gap-2">
                            <Clock className="h-4 w-4 text-[var(--text-secondary)]" />
                            <span className="text-sm text-[var(--text-secondary)]">
                              Est. completion: {new Date(plan.estimatedEndDate).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
                            </span>
                          </div>
                        )}
                        <div className="flex items-center gap-2">
                          <span className="text-sm text-[var(--text-secondary)]">
                            {plan.totalStoryPoints} SP total &middot; {assignments.length} items
                          </span>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Risk summary */}
                  {plan?.riskSummary && (
                    <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] p-4 mb-2">
                      <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
                        {plan.riskSummary}
                      </p>
                    </div>
                  )}

                  {/* Group assignments by sprint number */}
                  {(() => {
                    const sprintGroups = new Map<number, ApiAssignment[]>();
                    for (const a of assignments) {
                      const sn = a.sprintNumber ?? 1;
                      if (!sprintGroups.has(sn)) sprintGroups.set(sn, []);
                      sprintGroups.get(sn)!.push(a);
                    }
                    const sortedSprints = Array.from(sprintGroups.entries()).sort(
                      ([a], [b]) => a - b
                    );

                    return sortedSprints.map(([sprintNum, sprintAssignments]) => {
                      const sprintSP = sprintAssignments.reduce(
                        (sum, a) => sum + a.storyPoints,
                        0
                      );

                      return (
                        <div key={sprintNum} className="space-y-3">
                          {/* Sprint header */}
                          <div className="flex items-center gap-3 pt-2">
                            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[var(--color-brand-secondary)] text-white text-xs font-bold">
                              {sprintNum}
                            </div>
                            <h3 className="text-sm font-semibold text-[var(--text-primary)]">
                              Sprint {sprintNum}
                            </h3>
                            <Badge variant="brand">{sprintSP} SP</Badge>
                            <span className="text-xs text-[var(--text-secondary)]">
                              {sprintAssignments.length} item{sprintAssignments.length > 1 ? "s" : ""}
                            </span>
                          </div>

                          {/* Assignments for this sprint */}
                          {sprintAssignments.map((assignment) => {
                            const member = teamMembers.find(
                              (tm) => tm.id === assignment.teamMemberId
                            );
                            const workItem = workItems.find(
                              (wi) => wi.id === assignment.workItemId
                            );
                            const assignConfidence = Math.round(
                              assignment.confidenceScore * 100
                            );

                            return (
                              <div
                                key={assignment.id}
                                className={cn(
                                  "rounded-xl border border-[var(--border-subtle)]",
                                  "bg-[var(--bg-surface-raised)] p-5",
                                  "transition-colors hover:border-[var(--color-brand-secondary)]/30"
                                )}
                              >
                                {/* Top row: work item title + story points */}
                                <div className="flex items-start justify-between gap-4 mb-3">
                                  <div className="flex-1 min-w-0">
                                    <h3 className="text-sm font-semibold text-[var(--text-primary)] truncate">
                                      {workItem?.title ?? "Unknown Work Item"}
                                    </h3>
                                    {workItem?.externalId && (
                                      <span className="text-xs text-[var(--text-secondary)]">
                                        {workItem.externalId}
                                      </span>
                                    )}
                                  </div>
                                  <Badge variant="brand">{assignment.storyPoints} SP</Badge>
                                </div>

                                {/* Assignee row */}
                                <div className="flex items-center gap-2 mb-3">
                                  <Avatar
                                    src={member?.avatarUrl ?? undefined}
                                    fallback={member?.displayName ?? "?"}
                                    size="sm"
                                  />
                                  <span className="text-sm text-[var(--text-primary)]">
                                    {member?.displayName ?? "Unassigned"}
                                  </span>
                                  {assignment.skillMatch && assignment.skillMatch.matchedSkills.length > 0 && (
                                    <Badge variant="rag-green" className="text-[10px]">
                                      {assignment.skillMatch.matchedSkills.slice(0, 2).join(", ")}
                                    </Badge>
                                  )}
                                </div>

                                {/* Confidence bar */}
                                <div className="space-y-1 mb-3">
                                  <div className="flex items-center justify-between">
                                    <span className="text-xs text-[var(--text-secondary)]">
                                      Assignment Confidence
                                    </span>
                                    <span className="text-xs font-semibold tabular-nums text-[var(--text-primary)]">
                                      {assignConfidence}%
                                    </span>
                                  </div>
                                  <Progress
                                    value={assignConfidence}
                                    severity={
                                      assignConfidence >= 85
                                        ? "GREEN"
                                        : assignConfidence >= 70
                                          ? "AMBER"
                                          : "RED"
                                    }
                                    size="sm"
                                  />
                                </div>

                                {/* Rationale */}
                                <p className="text-xs text-[var(--text-secondary)] leading-relaxed mb-2">
                                  {assignment.rationale}
                                </p>

                                {/* Risk flags */}
                                {assignment.riskFlags.length > 0 && (
                                  <div className="flex items-center gap-2 flex-wrap">
                                    <AlertTriangle className="h-3 w-3 text-[var(--color-rag-red)]" />
                                    {assignment.riskFlags.map((flag) => (
                                      <Badge key={flag} variant="rag-red">
                                        {flag.replace(/_/g, " ")}
                                      </Badge>
                                    ))}
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      );
                    });
                  })()}

                  {/* Unplanned items section (only blocked items now) */}
                  {plan?.unplannedItems?.items && plan.unplannedItems.items.length > 0 && (
                    <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-sunken)] p-4">
                      <h4 className="text-sm font-semibold text-[var(--text-secondary)] mb-2">
                        Blocked Items ({plan.unplannedItems.items.length})
                      </h4>
                      <ul className="space-y-1">
                        {plan.unplannedItems.items.map((item) => (
                          <li key={item.workItemId} className="text-xs text-[var(--text-secondary)]">
                            <span className="font-medium">{item.workItemId}</span> — {item.reason}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </>
              )}
            </div>

            {/* Footer */}
            {!actionDone && (
              <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-[var(--border-subtle)] shrink-0">
                <Button
                  variant="ghost"
                  size="md"
                  onClick={handleReject}
                  disabled={loading || rejecting || approving}
                >
                  {rejecting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                  Reject
                </Button>
                <Button
                  variant="primary"
                  size="md"
                  onClick={handleApprove}
                  disabled={loading || approving || rejecting}
                >
                  {approving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                  Approve &amp; Sync
                </Button>
              </div>
            )}
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
