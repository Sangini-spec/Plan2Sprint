"use client";

import { useState } from "react";
import { Users } from "lucide-react";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Button, Input, Select, FormField, Avatar, Badge } from "@/components/ui";

type Role = "Admin" | "Product Owner" | "Scrum Master" | "Developer" | "Viewer";

interface Member {
  id: string;
  name: string;
  email: string;
  role: Role;
}

const ROLES: Role[] = ["Admin", "Product Owner", "Scrum Master", "Developer", "Viewer"];

const INITIAL_MEMBERS: Member[] = [
  { id: "tm-1", name: "Alex Chen", email: "alex.chen@acme.com", role: "Developer" },
  { id: "tm-2", name: "Sarah Kim", email: "sarah.kim@acme.com", role: "Developer" },
  { id: "tm-3", name: "Marcus Johnson", email: "marcus.johnson@acme.com", role: "Developer" },
  { id: "tm-4", name: "Priya Patel", email: "priya.patel@acme.com", role: "Scrum Master" },
  { id: "tm-5", name: "James Wilson", email: "james.wilson@acme.com", role: "Developer" },
  { id: "tm-6", name: "Emma Davis", email: "emma.davis@acme.com", role: "Developer" },
];

const roleBadgeVariant: Record<Role, "brand" | "rag-green" | "rag-amber" | "rag-red"> = {
  Admin: "rag-red",
  "Product Owner": "rag-amber",
  "Scrum Master": "brand",
  Developer: "rag-green",
  Viewer: "brand",
};

export default function TeamSettingsPage() {
  const [members, setMembers] = useState<Member[]>(INITIAL_MEMBERS);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<Role>("Developer");

  function handleRoleChange(memberId: string, newRole: Role) {
    setMembers((prev) =>
      prev.map((m) => (m.id === memberId ? { ...m, role: newRole } : m))
    );
  }

  function handleRemove(memberId: string) {
    setMembers((prev) => prev.filter((m) => m.id !== memberId));
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-[var(--text-primary)]">
          Team Management
        </h1>
        <p className="mt-1 text-sm text-[var(--text-secondary)]">
          Manage team members, roles, and send invitations.
        </p>
      </div>

      {/* Team Members List */}
      <DashboardPanel title="Team Members" icon={Users}>
        <div className="space-y-1">
          {/* Header row */}
          <div className="hidden sm:grid grid-cols-[1fr_1fr_160px_80px] gap-4 px-4 py-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
            <span>Member</span>
            <span>Email</span>
            <span>Role</span>
            <span />
          </div>

          {/* Member rows */}
          {members.map((member) => (
            <div
              key={member.id}
              className={cn(
                "grid grid-cols-1 sm:grid-cols-[1fr_1fr_160px_80px] gap-3 sm:gap-4 items-center",
                "rounded-xl px-4 py-3",
                "border border-[var(--border-subtle)] sm:border-transparent",
                "hover:bg-[var(--bg-surface-raised)]/50 transition-colors duration-200"
              )}
            >
              {/* Avatar + Name */}
              <div className="flex items-center gap-3">
                <Avatar
                  fallback={member.name}
                  size="md"
                />
                <span className="text-sm font-medium text-[var(--text-primary)]">
                  {member.name}
                </span>
              </div>

              {/* Email */}
              <span className="text-sm text-[var(--text-secondary)] truncate">
                {member.email}
              </span>

              {/* Role select */}
              <Select
                value={member.role}
                onChange={(e) =>
                  handleRoleChange(member.id, e.target.value as Role)
                }
              >
                {ROLES.map((role) => (
                  <option key={role} value={role}>
                    {role}
                  </option>
                ))}
              </Select>

              {/* Remove */}
              <div className="flex justify-end">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleRemove(member.id)}
                  className="text-[var(--color-rag-red)] hover:text-[var(--color-rag-red)] hover:bg-[var(--color-rag-red)]/5"
                >
                  Remove
                </Button>
              </div>
            </div>
          ))}

          {members.length === 0 && (
            <p className="py-8 text-center text-sm text-[var(--text-secondary)]">
              No team members yet. Invite someone below.
            </p>
          )}
        </div>
      </DashboardPanel>

      {/* Invite Member */}
      <DashboardPanel title="Invite Member" icon={Users}>
        <div className="flex flex-col sm:flex-row gap-4 items-end">
          <FormField label="Email Address" className="flex-1">
            <Input
              type="email"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              placeholder="colleague@acme.com"
            />
          </FormField>

          <FormField label="Role" className="sm:w-48">
            <Select
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value as Role)}
            >
              {ROLES.map((role) => (
                <option key={role} value={role}>
                  {role}
                </option>
              ))}
            </Select>
          </FormField>

          <Button variant="primary" size="md">
            Send Invite
          </Button>
        </div>
      </DashboardPanel>
    </div>
  );
}
