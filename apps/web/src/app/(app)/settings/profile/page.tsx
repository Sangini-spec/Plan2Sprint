"use client";

import { useState, useEffect, useRef, type KeyboardEvent, type ChangeEvent, type DragEvent } from "react";
import {
  User,
  Building2,
  Code2,
  Lock,
  Loader2,
  Check,
  X,
  Link as LinkIcon,
  Calendar,
  Upload,
  FileText,
  Sparkles,
  AlertTriangle,
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
  skillTags: string[];
}

/* ─────────────────────────── skill tags editor ─────────────── */

function SkillTagsEditor({
  tags,
  onChange,
}: {
  tags: string[];
  onChange: (tags: string[]) => void;
}) {
  const [inputValue, setInputValue] = useState("");

  const addTag = () => {
    const trimmed = inputValue.trim();
    if (trimmed && !tags.includes(trimmed)) {
      onChange([...tags, trimmed]);
    }
    setInputValue("");
  };

  const removeTag = (tag: string) => {
    onChange(tags.filter((t) => t !== tag));
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      addTag();
    }
    // Allow backspace to remove last tag when input is empty
    if (e.key === "Backspace" && inputValue === "" && tags.length > 0) {
      onChange(tags.slice(0, -1));
    }
  };

  return (
    <div className="space-y-3">
      {/* Tag list */}
      {tags.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {tags.map((tag) => (
            <span
              key={tag}
              className="inline-flex items-center gap-1.5 rounded-full bg-[var(--color-brand-secondary)]/10 px-3 py-1 text-xs font-medium text-[var(--color-brand-secondary)]"
            >
              {tag}
              <button
                onClick={() => removeTag(tag)}
                className="rounded-full p-0.5 hover:bg-[var(--color-brand-secondary)]/20 transition-colors cursor-pointer"
              >
                <X size={12} />
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Input */}
      <div className="flex gap-2">
        <Input
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type a skill and press Enter (e.g., React, Python, DevOps)"
          className="flex-1"
        />
        <Button
          variant="secondary"
          size="sm"
          onClick={addTag}
          disabled={!inputValue.trim()}
        >
          Add
        </Button>
      </div>
      <p className="text-xs text-[var(--text-secondary)]">
        Skills are visible to your Product Owner and team leads for project assignment.
      </p>
    </div>
  );
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

/* ─────────────────────────── resume upload card ─────────────── */

const ALLOWED_RESUME_EXT = [".pdf", ".docx", ".txt"];
const MAX_RESUME_MB = 5;

function ResumeUploadCard({
  onSkillsExtracted,
  hasExistingSkills,
}: {
  onSkillsExtracted: (skills: string[]) => void;
  hasExistingSkills: boolean;
}) {
  const [status, setStatus] = useState<"idle" | "uploading" | "done" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const validate = (file: File): string | null => {
    const lower = file.name.toLowerCase();
    if (!ALLOWED_RESUME_EXT.some((e) => lower.endsWith(e))) {
      return `Please upload a PDF, DOCX, or TXT file.`;
    }
    if (file.size > MAX_RESUME_MB * 1024 * 1024) {
      return `File is too large (max ${MAX_RESUME_MB} MB).`;
    }
    return null;
  };

  const upload = async (file: File) => {
    const msg = validate(file);
    if (msg) {
      setError(msg);
      setStatus("error");
      return;
    }

    setFileName(file.name);
    setStatus("uploading");
    setError(null);

    try {
      const formData = new FormData();
      formData.append("file", file);

      const res = await fetch("/api/me/resume", {
        method: "POST",
        body: formData,
      });
      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        setError(data.detail || "Failed to analyze resume.");
        setStatus("error");
        return;
      }

      const skills: string[] = data.skills || [];
      if (skills.length === 0) {
        setError(
          data.message ||
            "We couldn't find any skills in this resume. Try a more detailed file."
        );
        setStatus("error");
        return;
      }

      onSkillsExtracted(skills);
      setStatus("done");
    } catch {
      setError("Network error while uploading. Please try again.");
      setStatus("error");
    }
  };

  const onFilePick = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) upload(file);
    // Reset so the same file can be chosen again
    if (inputRef.current) inputRef.current.value = "";
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) upload(file);
  };

  const openPicker = () => inputRef.current?.click();

  // ---- Uploading state ------------------------------------------------------
  if (status === "uploading") {
    return (
      <div className="flex flex-col items-center justify-center py-10 text-center gap-3">
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-[var(--color-brand-secondary)]/10">
          <Loader2 className="h-6 w-6 animate-spin text-[var(--color-brand-secondary)]" />
        </div>
        <div>
          <p className="text-sm font-semibold text-[var(--text-primary)]">
            Analyzing your resume…
          </p>
          <p className="text-xs text-[var(--text-secondary)] mt-1">
            Our AI is extracting your skills from {fileName ?? "the file"}. This takes ~20 seconds.
          </p>
        </div>
      </div>
    );
  }

  // ---- Idle / error states --------------------------------------------------
  const title = hasExistingSkills ? "Re-upload your resume" : "Upload your resume";
  const subtitle = hasExistingSkills
    ? "Replace your current skills by analyzing a new resume."
    : "We'll use AI to extract the technical skills from your resume so you don't have to add them one by one.";

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={onDrop}
      className={
        "flex flex-col items-center justify-center py-10 px-6 text-center gap-4 rounded-xl border-2 border-dashed transition-colors " +
        (dragOver
          ? "border-[var(--color-brand-secondary)] bg-[var(--color-brand-secondary)]/[0.04]"
          : "border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/40")
      }
    >
      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-[var(--color-brand-secondary)]/10">
        <Sparkles className="h-6 w-6 text-[var(--color-brand-secondary)]" />
      </div>
      <div className="max-w-md">
        <p className="text-base font-semibold text-[var(--text-primary)]">{title}</p>
        <p className="text-xs text-[var(--text-secondary)] mt-1.5 leading-relaxed">
          {subtitle}
        </p>
      </div>

      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.docx,.txt"
        className="hidden"
        onChange={onFilePick}
      />
      <div className="flex items-center gap-3">
        <Button onClick={openPicker} size="md">
          <Upload className="h-4 w-4" />
          Choose file
        </Button>
        <span className="text-xs text-[var(--text-tertiary)]">or drag &amp; drop</span>
      </div>

      <p className="text-[11px] text-[var(--text-tertiary)]">
        PDF, DOCX, or TXT · up to {MAX_RESUME_MB} MB
      </p>

      {status === "error" && error && (
        <div className="mt-2 flex items-start gap-2 px-4 py-2.5 rounded-lg bg-[var(--color-rag-red)]/5 border border-[var(--color-rag-red)]/20 text-left max-w-md">
          <AlertTriangle className="h-4 w-4 text-[var(--color-rag-red)] shrink-0 mt-0.5" />
          <p className="text-xs text-[var(--color-rag-red)]">{error}</p>
        </div>
      )}
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
  const [skillTags, setSkillTags] = useState<string[]>([]);

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

    // Fetch supplementary data (skill_tags) from API
    (async () => {
      try {
        const res = await fetch("/api/me");
        if (res.ok) {
          const data: ProfileData = await res.json();
          setSkillTags(data.skillTags || []);
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
      if (effectiveRole === "developer") {
        payload.skillTags = skillTags;
      }

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
  const isDev = effectiveRole === "developer";

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

      {/* ── Skills & Expertise (Developer only) ───────────── */}
      {isDev && (
        <DashboardPanel title="Skills & Expertise" icon={Code2}>
          {skillTags.length === 0 ? (
            <ResumeUploadCard
              hasExistingSkills={false}
              onSkillsExtracted={(skills) => {
                setSkillTags(skills);
                // Skills are persisted server-side already; keep local state in sync
                // so the regular "Save Changes" button doesn't need to re-push them.
              }}
            />
          ) : (
            <div className="space-y-5">
              <div className="flex flex-wrap gap-2">
                {skillTags.map((tag) => (
                  <span
                    key={tag}
                    className="inline-flex items-center gap-1.5 rounded-full bg-[var(--color-brand-secondary)]/10 px-3 py-1 text-xs font-medium text-[var(--color-brand-secondary)]"
                  >
                    {tag}
                    <button
                      onClick={() =>
                        setSkillTags((prev) => prev.filter((t) => t !== tag))
                      }
                      className="rounded-full p-0.5 hover:bg-[var(--color-brand-secondary)]/20 transition-colors cursor-pointer"
                      aria-label={`Remove ${tag}`}
                    >
                      <X size={12} />
                    </button>
                  </span>
                ))}
              </div>

              <p className="text-xs text-[var(--text-secondary)]">
                Skills are visible to your Product Owner and team leads for project assignment.
                Refine the list below, or re-upload your resume to regenerate it.
              </p>

              <details className="group">
                <summary className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--color-brand-secondary)] cursor-pointer select-none hover:underline">
                  <FileText className="h-3.5 w-3.5" />
                  Add / refine skills manually
                </summary>
                <div className="mt-3">
                  <SkillTagsEditor tags={skillTags} onChange={setSkillTags} />
                </div>
              </details>

              <details className="group">
                <summary className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--text-secondary)] cursor-pointer select-none hover:text-[var(--text-primary)]">
                  <Upload className="h-3.5 w-3.5" />
                  Re-upload resume
                </summary>
                <div className="mt-3">
                  <ResumeUploadCard
                    hasExistingSkills={true}
                    onSkillsExtracted={(skills) => setSkillTags(skills)}
                  />
                </div>
              </details>
            </div>
          )}
        </DashboardPanel>
      )}

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
