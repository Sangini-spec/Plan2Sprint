"use client";

import { useState, useEffect, useCallback } from "react";
import { Users, UserPlus, Loader2, Clock, Mail, CircleCheck, CircleX, FolderKanban, X, Plus } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button, Select, Avatar, Badge } from "@/components/ui";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { useAuth } from "@/lib/auth/context";
import { isAdmin, ROLE_LABELS, type UserRole } from "@/lib/types/auth";
import { InviteMemberModal } from "@/components/settings/invite-member-modal";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { JoinRequestsSection } from "@/components/settings/join-requests-section";

interface MemberProject {
  id: string;
  name: string;
}

interface Member {
  id: string;
  teamMemberId: string | null;
  type: string;
  email: string;
  displayName: string;
  avatarUrl: string | null;
  role: string;
  isActive: boolean;
  projects: MemberProject[];
  createdAt: string | null;
}

interface Invitation {
  id: string;
  email: string;
  role: string;
  status: string;
  invitedBy: string;
  expiresAt: string | null;
  createdAt: string | null;
}

const EDITABLE_ROLES: { value: UserRole; label: string }[] = [
  { value: "product_owner", label: "Product Owner" },
  { value: "developer", label: "Developer" },
  { value: "stakeholder", label: "Stakeholder" },
];

export default function TeamSettingsPage() {
  const { appUser, role } = useAuth();
  const canManage = isAdmin(role);

  const [members, setMembers] = useState<Member[]>([]);
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [loading, setLoading] = useState(true);
  const [inviteOpen, setInviteOpen] = useState(false);

  // Confirm dialog state
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmTarget, setConfirmTarget] = useState<{
    type: "remove_member" | "revoke_invite";
    id: string;
    name: string;
  } | null>(null);

  // Assign Projects modal state
  const [assignModalOpen, setAssignModalOpen] = useState(false);
  const [assignTarget, setAssignTarget] = useState<Member | null>(null);
  const [orgProjects, setOrgProjects] = useState<{ internalId: string; name: string; source: string }[]>([]);
  const [assignedProjectIds, setAssignedProjectIds] = useState<Set<string>>(new Set());
  const [assignLoading, setAssignLoading] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const [membersRes, invitationsRes] = await Promise.all([
        fetch("/api/organizations/current/members"),
        canManage
          ? fetch("/api/organizations/current/invitations")
          : Promise.resolve(null),
      ]);

      if (membersRes.ok) {
        const data = await membersRes.json();
        setMembers(data.members || []);
      }

      if (invitationsRes && invitationsRes.ok) {
        const data = await invitationsRes.json();
        setInvitations(
          (data.invitations || []).filter(
            (i: Invitation) => i.status === "pending"
          )
        );
      }
    } catch {
      // API unavailable
    }
    setLoading(false);
  }, [canManage]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Hotfix 62A — auto-refresh so accepted invitations move into the
  // Members list (and disappear from "Pending Invitations") without the
  // PO ever needing to hit refresh.
  //
  //   • visibilitychange → refetch the moment the tab regains focus.
  //     Catches the common case: PO sends an invite, switches tabs to do
  //     something else, comes back → list is already current.
  //   • 60s interval (only while visible) → catches the less common case
  //     where the PO leaves the tab open in the foreground while the
  //     invitee accepts.
  //
  // We deliberately do NOT toggle the loading spinner here — fetchData
  // only ever sets loading=false at the end, so background refetches
  // update silently and the page doesn't flash on every poll.
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") {
        fetchData();
      }
    };
    document.addEventListener("visibilitychange", onVisible);

    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        fetchData();
      }
    }, 60_000);

    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.clearInterval(interval);
    };
  }, [fetchData]);

  const handleRoleChange = async (memberId: string, newRole: string) => {
    const res = await fetch(
      `/api/organizations/current/members/${memberId}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role: newRole }),
      }
    );
    if (res.ok) {
      setMembers((prev) =>
        prev.map((m) =>
          m.id === memberId ? { ...m, role: newRole } : m
        )
      );
    }
  };

  const handleRemoveMember = async () => {
    if (!confirmTarget || confirmTarget.type !== "remove_member") return;
    await fetch(
      `/api/organizations/current/members/${confirmTarget.id}`,
      { method: "DELETE" }
    );
    setMembers((prev) => prev.filter((m) => m.id !== confirmTarget.id));
    setConfirmOpen(false);
    setConfirmTarget(null);
  };

  const handleRevokeInvite = async () => {
    if (!confirmTarget || confirmTarget.type !== "revoke_invite") return;
    await fetch(
      `/api/organizations/current/invitations/${confirmTarget.id}`,
      { method: "DELETE" }
    );
    setInvitations((prev) =>
      prev.filter((i) => i.id !== confirmTarget.id)
    );
    setConfirmOpen(false);
    setConfirmTarget(null);
  };

  const openAssignModal = async (member: Member) => {
    setAssignTarget(member);
    setAssignLoading(true);
    setAssignModalOpen(true);

    try {
      // Fetch all org projects + existing assignments for this user
      const [projRes, assignRes] = await Promise.all([
        fetch("/api/projects/"),
        fetch(`/api/projects/stakeholder-assignments?userId=${member.id}`),
      ]);

      if (projRes.ok) {
        const data = await projRes.json();
        setOrgProjects(data.projects ?? []);
      }

      if (assignRes.ok) {
        const data = await assignRes.json();
        const ids = new Set<string>(
          (data.assignments ?? []).map((a: { projectId: string }) => a.projectId)
        );
        setAssignedProjectIds(ids);
      }
    } catch {
      // silent
    }
    setAssignLoading(false);
  };

  const toggleProjectAssignment = async (projectId: string) => {
    if (!assignTarget) return;
    const isAssigned = assignedProjectIds.has(projectId);

    if (isAssigned) {
      // Find the assignment to remove
      const assignRes = await fetch(
        `/api/projects/stakeholder-assignments?userId=${assignTarget.id}`
      );
      if (assignRes.ok) {
        const data = await assignRes.json();
        const assignment = (data.assignments ?? []).find(
          (a: { projectId: string }) => a.projectId === projectId
        );
        if (assignment) {
          await fetch(`/api/projects/stakeholder-assignments/${assignment.id}`, {
            method: "DELETE",
          });
        }
      }
      setAssignedProjectIds((prev) => {
        const next = new Set(prev);
        next.delete(projectId);
        return next;
      });
    } else {
      // Add assignment
      await fetch("/api/projects/stakeholder-assignments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ userId: assignTarget.id, projectId }),
      });
      setAssignedProjectIds((prev) => new Set([...prev, projectId]));
    }
  };

  const handleResend = async (invId: string) => {
    await fetch(
      `/api/organizations/current/invitations/${invId}/resend`,
      { method: "POST" }
    );
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-5 w-5 animate-spin text-[var(--text-secondary)]" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-[var(--text-primary)]">
            Team Management
          </h1>
          <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
            {members.length} member{members.length !== 1 ? "s" : ""}
            {members.filter((m) => m.isActive).length < members.length && (
              <span className="ml-1 text-[var(--text-tertiary)]">
                ({members.filter((m) => m.isActive).length} active)
              </span>
            )}
          </p>
        </div>
        {canManage && (
          <Button
            variant="primary"
            size="sm"
            onClick={() => setInviteOpen(true)}
            data-onboarding="invite-button"
          >
            <UserPlus className="h-3.5 w-3.5" />
            Invite Member
          </Button>
        )}
      </div>

      {/* Members Table */}
      <DashboardPanel title="Members" icon={Users}>
        <div className="space-y-0.5" data-onboarding="assign-projects-section">
          {/* Header */}
          <div className="hidden sm:grid grid-cols-[1fr_1.2fr_120px_1fr_80px_80px] gap-2 px-4 py-2 text-[10px] font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
            <span>Member</span>
            <span>Email</span>
            <span>Role</span>
            <span>Projects</span>
            <span>Status</span>
            <span className="text-right">Actions</span>
          </div>

          {members.map((member) => {
            const isSelf =
              member.email === appUser?.email || member.id === appUser?.id;
            const roleLabel =
              ROLE_LABELS[member.role as UserRole] || member.role;

            return (
              <div
                key={member.id}
                className={cn(
                  "grid grid-cols-1 sm:grid-cols-[1fr_1.2fr_120px_1fr_80px_80px] gap-2 items-center",
                  "rounded-lg px-4 py-2.5",
                  "hover:bg-[var(--bg-surface-raised)]/50 transition-colors"
                )}
              >
                {/* Avatar + Name */}
                <div className="flex items-center gap-3">
                  <Avatar
                    src={member.avatarUrl ?? undefined}
                    fallback={member.displayName}
                    size="sm"
                  />
                  <div className="min-w-0">
                    <span className="text-sm font-medium text-[var(--text-primary)] truncate block">
                      {member.displayName}
                    </span>
                    {isSelf && (
                      <span className="text-[10px] text-[var(--text-secondary)]">
                        You
                      </span>
                    )}
                  </div>
                </div>

                {/* Email */}
                <span className="text-xs text-[var(--text-secondary)] truncate">
                  {member.email}
                </span>

                {/* Role */}
                <Badge variant="brand">{roleLabel}</Badge>

                {/* Projects */}
                <div className="flex flex-wrap items-center gap-1">
                  {member.projects.length > 0 ? (
                    member.projects.map((p) => (
                      <span
                        key={p.id}
                        className="inline-flex items-center rounded-md bg-[var(--bg-surface-raised)] px-2 py-0.5 text-[11px] font-medium text-[var(--text-secondary)] border border-[var(--border-subtle)]"
                      >
                        {p.name}
                      </span>
                    ))
                  ) : (
                    <span className="text-[11px] text-[var(--text-tertiary)]">
                      None
                    </span>
                  )}
                  {canManage && (
                    <button
                      onClick={() => openAssignModal(member)}
                      className="inline-flex items-center gap-0.5 text-[11px] text-[var(--color-brand-secondary)] hover:underline cursor-pointer ml-1"
                    >
                      <FolderKanban className="h-3 w-3" />
                      Assign
                    </button>
                  )}
                </div>

                {/* Status */}
                <div>
                  {member.isActive ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-rag-green)]/10 px-2 py-0.5 text-[11px] font-medium text-[var(--color-rag-green)]">
                      <CircleCheck size={12} />
                      Active
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 rounded-full bg-[var(--text-tertiary)]/10 px-2 py-0.5 text-[11px] font-medium text-[var(--text-tertiary)]">
                      <CircleX size={12} />
                      Inactive
                    </span>
                  )}
                </div>

                {/* Actions */}
                <div className="flex gap-1 justify-end">
                  {canManage && !isSelf && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setConfirmTarget({
                          type: "remove_member",
                          id: member.id,
                          name: member.displayName,
                        });
                        setConfirmOpen(true);
                      }}
                      className="text-[var(--color-rag-red)] hover:text-[var(--color-rag-red)] hover:bg-[var(--color-rag-red)]/5 text-xs"
                    >
                      Remove
                    </Button>
                  )}
                </div>
              </div>
            );
          })}

          {members.length === 0 && (
            <p className="py-8 text-center text-sm text-[var(--text-secondary)]">
              No team members found.
            </p>
          )}
        </div>
      </DashboardPanel>

      {/* Hotfix 86 — pending org-join requests (founder-only). Component
          renders nothing for non-founders or when there are no requests. */}
      {canManage && <JoinRequestsSection />}

      {/* Pending Invitations (admin only) */}
      {canManage && invitations.length > 0 && (
        <DashboardPanel title="Pending Invitations" icon={Mail}>
          <div className="space-y-0.5">
            <div className="hidden sm:grid grid-cols-[1fr_120px_120px_100px] gap-4 px-4 py-2 text-[10px] font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
              <span>Email</span>
              <span>Role</span>
              <span>Expires</span>
              <span />
            </div>

            {invitations.map((inv) => {
              const roleLabel =
                ROLE_LABELS[inv.role as UserRole] || inv.role;
              const expiresAt = inv.expiresAt
                ? new Date(inv.expiresAt)
                : null;
              const daysLeft = expiresAt
                ? Math.max(
                    0,
                    Math.ceil(
                      (expiresAt.getTime() - Date.now()) / 86400000
                    )
                  )
                : null;

              return (
                <div
                  key={inv.id}
                  className="grid grid-cols-1 sm:grid-cols-[1fr_120px_120px_100px] gap-3 sm:gap-4 items-center rounded-lg px-4 py-2.5 hover:bg-[var(--bg-surface-raised)]/50 transition-colors"
                >
                  <span className="text-sm text-[var(--text-primary)] truncate">
                    {inv.email}
                  </span>
                  <Badge variant="brand">{roleLabel}</Badge>
                  <span className="text-xs text-[var(--text-secondary)] flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    {daysLeft !== null ? `${daysLeft}d left` : "—"}
                  </span>
                  <div className="flex gap-1 justify-end">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleResend(inv.id)}
                      className="text-xs"
                    >
                      Resend
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setConfirmTarget({
                          type: "revoke_invite",
                          id: inv.id,
                          name: inv.email,
                        });
                        setConfirmOpen(true);
                      }}
                      className="text-[var(--color-rag-red)] hover:text-[var(--color-rag-red)] text-xs"
                    >
                      Revoke
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        </DashboardPanel>
      )}

      {/* Invite modal */}
      <InviteMemberModal
        open={inviteOpen}
        onClose={() => setInviteOpen(false)}
        onInvited={fetchData}
      />

      {/* Confirm dialog */}
      <ConfirmDialog
        open={confirmOpen}
        title={
          confirmTarget?.type === "remove_member"
            ? "Remove Member"
            : "Revoke Invitation"
        }
        description={
          confirmTarget?.type === "remove_member"
            ? `Are you sure you want to remove ${confirmTarget?.name} from the organization? They will lose access immediately.`
            : `Are you sure you want to revoke the invitation for ${confirmTarget?.name}?`
        }
        confirmLabel={
          confirmTarget?.type === "remove_member" ? "Remove" : "Revoke"
        }
        variant="danger"
        onConfirm={
          confirmTarget?.type === "remove_member"
            ? handleRemoveMember
            : handleRevokeInvite
        }
        onCancel={() => {
          setConfirmOpen(false);
          setConfirmTarget(null);
        }}
      />

      {/* Assign Projects Modal */}
      {assignModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-2xl">
            {/* Header */}
            <div className="flex items-center justify-between border-b border-[var(--border-subtle)] px-5 py-4">
              <div>
                <h2 className="text-base font-semibold text-[var(--text-primary)]">
                  Assign Projects
                </h2>
                <p className="text-xs text-[var(--text-secondary)] mt-0.5">
                  {assignTarget?.displayName} — Stakeholder
                </p>
              </div>
              <button
                onClick={() => {
                  setAssignModalOpen(false);
                  setAssignTarget(null);
                  fetchData();
                }}
                className="rounded-lg p-1.5 hover:bg-[var(--bg-surface-raised)] text-[var(--text-secondary)] cursor-pointer"
              >
                <X size={18} />
              </button>
            </div>

            {/* Body */}
            <div className="px-5 py-4 max-h-80 overflow-y-auto">
              {assignLoading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 size={20} className="animate-spin text-[var(--text-secondary)]" />
                </div>
              ) : orgProjects.length === 0 ? (
                <p className="text-sm text-[var(--text-secondary)] text-center py-6">
                  No projects found. Import projects from ADO/Jira first.
                </p>
              ) : (
                <div className="space-y-1">
                  <p className="text-xs text-[var(--text-secondary)] mb-3">
                    Toggle projects this stakeholder can access:
                  </p>
                  {orgProjects.map((project) => {
                    const isAssigned = assignedProjectIds.has(project.internalId);
                    return (
                      <button
                        key={project.internalId}
                        onClick={() => toggleProjectAssignment(project.internalId)}
                        className={cn(
                          "w-full flex items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors cursor-pointer",
                          isAssigned
                            ? "bg-[var(--color-brand-secondary)]/10 border border-[var(--color-brand-secondary)]/30"
                            : "hover:bg-[var(--bg-surface-raised)] border border-transparent"
                        )}
                      >
                        <div
                          className={cn(
                            "flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-[10px] font-bold",
                            project.source === "ado"
                              ? "bg-[#0078D4]/10 text-[#0078D4]"
                              : "bg-[#0052CC]/10 text-[#0052CC]"
                          )}
                        >
                          {project.source === "ado" ? "AD" : "JR"}
                        </div>
                        <span className="text-sm font-medium text-[var(--text-primary)] flex-1">
                          {project.name}
                        </span>
                        {isAssigned ? (
                          <span className="text-xs font-medium text-[var(--color-brand-secondary)]">
                            Assigned
                          </span>
                        ) : (
                          <Plus size={16} className="text-[var(--text-tertiary)]" />
                        )}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="border-t border-[var(--border-subtle)] px-5 py-3 flex justify-end">
              <Button
                variant="primary"
                size="sm"
                onClick={() => {
                  setAssignModalOpen(false);
                  setAssignTarget(null);
                  fetchData();
                }}
              >
                Done
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
