"use client";

import { useState, useEffect } from "react";
import {
  User,
  Building2,
  Lock,
  Loader2,
  Check,
  Link as LinkIcon,
  Calendar,
} from "lucide-react";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Button, Input, FormField, Badge } from "@/components/ui";
import { useAuth } from "@/lib/auth/context";
import { useIntegrations } from "@/lib/integrations/context";
import { ROLE_LABELS, isAdmin, type UserRole } from "@/lib/types/auth";

/* ─────────────────────────── types ─────────────────────────── */

interface ProfileData {
  id: string;
  email: string;
  fullName: string;
  avatarUrl: string | null;
  role: string;
  organizationId: string;
  organizationName: string;
  onboardingCompleted: boolean;
  createdAt: string | null;
}

/* ─────────────────────────── connected tools chips ─────────── */

const TOOL_ICONS: Record<string, string> = {
  jira: "🔷",
  ado: "🔶",
  github: "🐙",
  slack: "💬",
  teams: "👥",
};

function LinkedToolsSummary() {
  const { connections } = useIntegrations();
  const connectedTools = connections.filter((c) => c.status === "connected");

  if (connectedTools.length === 0) {
    return (
      <div className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
        <LinkIcon size={14} />
        <span>No tools connected.</span>
        <a
          href="/settings/connections"
          className="text-[var(--color-brand-secondary)] hover:underline"
        >
          Connect tools →
        </a>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-[var(--text-secondary)] font-medium uppercase tracking-wide">
        Connected Tools
      </p>
      <div className="flex flex-wrap gap-2">
        {connectedTools.map((tool) => (
          <span
            key={tool.tool}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] px-3 py-1.5 text-xs font-medium text-[var(--text-primary)]"
          >
            <span>{TOOL_ICONS[tool.tool] || "🔧"}</span>
            {tool.tool === "ado"
              ? "Azure DevOps"
              : tool.tool === "github"
              ? "GitHub"
              : tool.tool.charAt(0).toUpperCase() + tool.tool.slice(1)}
          </span>
        ))}
      </div>
    </div>
  );
}

/* ─────────────────────────── main page ─────────────────────── */

export default function ProfileSettingsPage() {
  const { appUser, role, updateAppUser } = useAuth();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  // Editable fields
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");

  // Read-only fields
  const [profileRole, setProfileRole] = useState("");
  const [orgName, setOrgName] = useState("");
  const [createdAt, setCreatedAt] = useState<string | null>(null);
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!appUser) return;

    // Always use real auth context for identity fields
    setName(appUser.full_name || "");
    setEmail(appUser.email || "");
    setProfileRole(role || "");
    setOrgName(appUser.organization_name || "");
    setCreatedAt(appUser.created_at || null);
    setAvatarUrl(appUser.avatar_url || null);

    // Fetch supplementary org / created-at data from API
    (async () => {
      try {
        const res = await fetch("/api/me");
        if (res.ok) {
          const data: ProfileData = await res.json();
          // Use API org name if available and real (not demo)
          if (data.organizationName && data.organizationName !== "Demo Organization") {
            setOrgName(data.organizationName);
          }
          // Use API createdAt if available
          if (data.createdAt) {
            setCreatedAt(data.createdAt);
          }
        }
      } catch {
        // API unavailable — auth context data is already set above
      }
      setLoading(false);
    })();
  }, [appUser, role]);

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        fullName: name,
        email,
      };

      const res = await fetch("/api/me", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      // Always update the local auth context so topbar reflects changes immediately
      // (even if backend returns 404 for team_member-only users)
      updateAppUser({ full_name: name, email });
      if (res.ok) {
        setSaved(true);
        setTimeout(() => setSaved(false), 2000);
      }
    } catch {
      // Handle error silently
    }
    setSaving(false);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-5 w-5 animate-spin text-[var(--text-secondary)]" />
      </div>
    );
  }

  const effectiveRole = profileRole || role || "";
  const roleLabel =
    ROLE_LABELS[effectiveRole as UserRole] || effectiveRole || "Member";
  const isPO = isAdmin(effectiveRole);

  const memberSince = createdAt
    ? new Date(createdAt).toLocaleDateString("en-US", {
        year: "numeric",
        month: "long",
        day: "numeric",
      })
    : "—";

  const initial = name?.charAt(0)?.toUpperCase() ?? "U";

  return (
    <div className="space-y-6">
      {/* ── Profile Information ────────────────────────────── */}
      <DashboardPanel title="Profile Information" icon={User}>
        <div className="space-y-5">
          {/* Avatar + basic info row */}
          <div className="flex items-start gap-5">
            {/* Avatar */}
            <div className="flex-shrink-0">
              {avatarUrl ? (
                <img
                  src={avatarUrl}
                  alt={name}
                  className="h-16 w-16 rounded-full object-cover border-2 border-[var(--border-subtle)]"
                />
              ) : (
                <div className="flex h-16 w-16 items-center justify-center rounded-full bg-[var(--color-brand-secondary)]/20 text-xl font-bold text-[var(--color-brand-secondary)] border-2 border-[var(--color-brand-secondary)]/30">
                  {initial}
                </div>
              )}
            </div>

            {/* Name + role summary */}
            <div className="flex-1 min-w-0 pt-1">
              <h3 className="text-lg font-semibold text-[var(--text-primary)]">
                {name || "User"}
              </h3>
              <div className="flex items-center gap-2 mt-1">
                <Badge variant="brand">{roleLabel}</Badge>
                <span className="text-xs text-[var(--text-secondary)] flex items-center gap-1">
                  <Calendar size={12} />
                  Member since {memberSince}
                </span>
              </div>
            </div>
          </div>

          {/* Editable fields */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <FormField label="Display Name">
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Your full name"
              />
            </FormField>

            <FormField label="Email Address">
              <Input
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="your@email.com"
              />
              <p className="text-xs text-[var(--text-secondary)] mt-1">
                Changing email here updates your Plan2Sprint profile only.
              </p>
            </FormField>
          </div>

          {/* Role — read-only */}
          <FormField label="Role">
            <div className="flex items-center gap-3 h-10">
              <Badge variant="brand">{roleLabel}</Badge>
              <span className="text-xs text-[var(--text-secondary)]">
                {isPO
                  ? "You have management access to this organization."
                  : "Contact a Product Owner to change your role."}
              </span>
            </div>
          </FormField>
        </div>
      </DashboardPanel>

      {/* ── Organization ──────────────────────────────────── */}
      <DashboardPanel title="Organization" icon={Building2}>
        <div className="space-y-4">
          <FormField label="Organization Name">
            <Input value={orgName} disabled />
            {isPO && (
              <p className="text-xs text-[var(--text-secondary)] mt-1">
                Edit organization settings in the{" "}
                <a
                  href="/settings"
                  className="text-[var(--color-brand-secondary)] hover:underline"
                >
                  General tab
                </a>
                .
              </p>
            )}
          </FormField>

          {/* Linked tools — PO only */}
          {isPO && <LinkedToolsSummary />}
        </div>
      </DashboardPanel>

      {/* ── Developer API (Coming Soon) ───────────────────── */}
      <DashboardPanel title="Developer API" icon={Lock}>
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <Badge variant="rag-amber">Coming Soon</Badge>
          </div>
          <p className="text-sm text-[var(--text-secondary)]">
            Programmatic access to Plan2Sprint data — pull sprint metrics, push
            standup updates, and integrate with your CI/CD pipeline via REST API.
          </p>
          <Button variant="secondary" size="md" disabled>
            <Lock className="h-4 w-4" />
            Generate API Key
          </Button>
        </div>
      </DashboardPanel>

      {/* ── Save button ───────────────────────────────────── */}
      <div className="flex justify-end">
        <Button variant="primary" size="md" onClick={handleSave} disabled={saving}>
          {saving ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : saved ? (
            <Check className="h-4 w-4" />
          ) : null}
          {saving ? "Saving..." : saved ? "Saved" : "Save Changes"}
        </Button>
      </div>
    </div>
  );
}
