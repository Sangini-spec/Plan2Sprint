"use client";

import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Inbox,
  Bell,
  AlertTriangle,
  CheckCircle2,
  Info,
  HeartPulse,
  GitPullRequest,
  CheckCheck,
  MessageSquareText,
  Zap,
  Bot,
  ShieldAlert,
  Activity,
  FileText,
  Trash2,
  ChevronDown,
  Hash,
  Plus,
  ExternalLink,
  Users,
  Megaphone,
  Loader2,
  Send,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button, Input, Badge } from "@/components/ui";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { DeliveryChannelsSection } from "@/components/notifications/delivery-channels-section";
import { SlackMessageComposer } from "@/components/notifications/slack-message-composer";
import { TeamsMessageComposer } from "@/components/notifications/teams-message-composer";
import { PlatformTabs, usePlatformTab, type Platform } from "@/components/notifications/platform-tabs";
import { useAutoRefresh } from "@/lib/ws/context";

/* -------------------------------------------------------------------------- */
/*  TYPES                                                                      */
/* -------------------------------------------------------------------------- */

interface Notification {
  id: string;
  type: string;
  title: string;
  message: string;
  time: string;
  read: boolean;
}

const TYPE_CONFIG: Record<
  string,
  { icon: typeof Bell; color: string; bg: string }
> = {
  sprint_approval: {
    icon: CheckCircle2,
    color: "text-[var(--color-brand-secondary)]",
    bg: "bg-[var(--color-brand-secondary)]/10",
  },
  blocker_alert: {
    icon: AlertTriangle,
    color: "text-[var(--color-rag-red)]",
    bg: "bg-[var(--color-rag-red)]/10",
  },
  health_alert: {
    icon: HeartPulse,
    color: "text-[var(--color-rag-amber)]",
    bg: "bg-[var(--color-rag-amber)]/10",
  },
  writeback_success: {
    icon: GitPullRequest,
    color: "text-[var(--color-rag-green)]",
    bg: "bg-[var(--color-rag-green)]/10",
  },
  standup_report: {
    icon: MessageSquareText,
    color: "text-[var(--color-brand-secondary)]",
    bg: "bg-[var(--color-brand-secondary)]/10",
  },
  standup_digest: {
    icon: MessageSquareText,
    color: "text-[var(--color-rag-green)]",
    bg: "bg-[var(--color-rag-green)]/10",
  },
  sprint_assignment: {
    icon: Zap,
    color: "text-[var(--color-brand-secondary)]",
    bg: "bg-[var(--color-brand-secondary)]/10",
  },
  ci_failure: {
    icon: AlertTriangle,
    color: "text-[var(--color-rag-red)]",
    bg: "bg-[var(--color-rag-red)]/10",
  },
  retro_action: {
    icon: Info,
    color: "text-[var(--color-rag-amber)]",
    bg: "bg-[var(--color-rag-amber)]/10",
  },
  // Agent notification types
  agent_standup: {
    icon: Bot,
    color: "text-[var(--color-brand-secondary)]",
    bg: "bg-[var(--color-brand-secondary)]/10",
  },
  agent_blocker: {
    icon: ShieldAlert,
    color: "text-[var(--color-rag-red)]",
    bg: "bg-[var(--color-rag-red)]/10",
  },
  agent_health: {
    icon: Activity,
    color: "text-[var(--color-rag-amber)]",
    bg: "bg-[var(--color-rag-amber)]/10",
  },
  agent_retro: {
    icon: FileText,
    color: "text-[var(--color-rag-green)]",
    bg: "bg-[var(--color-rag-green)]/10",
  },
};

const defaultConfig = {
  icon: Bell,
  color: "text-[var(--text-secondary)]",
  bg: "bg-[var(--bg-surface-raised)]",
};

/* -------------------------------------------------------------------------- */
/*  HELPERS                                                                    */
/* -------------------------------------------------------------------------- */

function timeAgo(iso: string): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "Yesterday";
  return `${days} days ago`;
}

/* -------------------------------------------------------------------------- */
/*  PO NOTIFICATIONS PAGE                                                       */
/* -------------------------------------------------------------------------- */

export default function PONotificationsPage() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);
  const [slackConnected, setSlackConnected] = useState(false);
  const [teamsConnected, setTeamsConnected] = useState(false);
  const [visibleCount, setVisibleCount] = useState(5);

  // Auto-refresh when WS notification events arrive
  const refreshKey = useAutoRefresh([
    "notification",
    "standup_generated",
    "blockers_detected",
    "health_analysis_complete",
    "retro_generated",
    "standup_note_submitted",
    "blocker_flagged",
  ]);

  const unreadCount = notifications.filter((n) => !n.read).length;

  const fetchNotifications = useCallback(async () => {
    try {
      const res = await fetch("/api/notifications?limit=50");
      if (res.ok) {
        const data = await res.json();
        setNotifications(data.notifications ?? []);
      }
    } catch {
      // API unavailable — keep existing state
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchNotifications();
  }, [fetchNotifications, refreshKey]);

  // Check if Slack / Teams are connected
  useEffect(() => {
    let cancelled = false;

    async function checkConnections() {
      try {
        const res = await fetch("/api/integrations/slack/status");
        if (res.ok) {
          const data = await res.json();
          if (!cancelled) setSlackConnected(data.connected === true);
        }
      } catch {
        // Ignore
      }

      try {
        const res = await fetch("/api/integrations/teams/status");
        if (res.ok) {
          const data = await res.json();
          if (!cancelled) setTeamsConnected(data.connected === true);
        }
      } catch {
        // Ignore
      }
    }

    checkConnections();
    return () => { cancelled = true; };
  }, []);

  async function markAllRead() {
    // Optimistic update
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
    // Mark each unread notification as read via API
    const unread = notifications.filter((n) => !n.read);
    for (const n of unread) {
      try {
        await fetch(`/api/notifications/${n.id}/read`, { method: "PATCH" });
      } catch {
        // ignore
      }
    }
  }

  async function clearAll() {
    setNotifications([]);
    setVisibleCount(5);
    try {
      await fetch("/api/notifications/clear", { method: "DELETE" });
    } catch {
      // ignore
    }
  }

  async function toggleRead(id: string) {
    const notif = notifications.find((n) => n.id === id);
    if (notif && !notif.read) {
      try {
        await fetch(`/api/notifications/${id}/read`, { method: "PATCH" });
        setNotifications((prev) =>
          prev.map((n) => (n.id === id ? { ...n, read: true } : n))
        );
      } catch {
        // ignore
      }
    }
  }

  return (
    <div className="space-y-8">
      {/* Notification Inbox */}
      <DashboardPanel
        title="Notification Inbox"
        actions={
          <span className="text-xs font-medium text-[var(--text-secondary)]">
            {unreadCount > 0
              ? `${unreadCount} unread`
              : "All caught up"}
          </span>
        }
      >
        {/* Header actions */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Inbox size={16} className="text-[var(--text-secondary)]" />
            <span className="text-sm font-medium text-[var(--text-secondary)]">
              Recent
            </span>
          </div>
          <div className="flex items-center gap-4">
            {unreadCount > 0 && (
              <button
                onClick={markAllRead}
                className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--color-brand-secondary)] hover:underline cursor-pointer"
              >
                <CheckCheck size={14} />
                Mark all as read
              </button>
            )}
            {notifications.length > 0 && (
              <button
                onClick={clearAll}
                className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--color-rag-red)]/70 hover:text-[var(--color-rag-red)] hover:underline cursor-pointer"
              >
                <Trash2 size={14} />
                Clear all
              </button>
            )}
          </div>
        </div>

        {/* Notification list */}
        <div className="space-y-2">
          {loading ? (
            <div className="flex flex-col items-center justify-center py-8 gap-2">
              <div className="h-5 w-5 animate-spin rounded-full border-2 border-[var(--color-brand-secondary)] border-t-transparent" />
              <span className="text-xs text-[var(--text-tertiary)]">Loading notifications...</span>
            </div>
          ) : notifications.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 gap-2">
              <Bell size={20} className="text-[var(--text-tertiary)]" />
              <span className="text-xs text-[var(--text-tertiary)]">
                No notifications yet. Agent activity and team events will appear here.
              </span>
            </div>
          ) : (
            <>
              <AnimatePresence initial={false}>
                {notifications.slice(0, visibleCount).map((notification) => {
                  const config = TYPE_CONFIG[notification.type] ?? defaultConfig;
                  const Icon = config.icon;

                  return (
                    <motion.button
                      key={notification.id}
                      layout
                      initial={{ opacity: 0, y: 4 }}
                      animate={{ opacity: 1, y: 0 }}
                      onClick={() => toggleRead(notification.id)}
                      className={cn(
                        "w-full flex items-start gap-3 rounded-xl p-3.5 text-left",
                        "transition-colors duration-200 cursor-pointer",
                        notification.read
                          ? "bg-transparent hover:bg-[var(--bg-surface-raised)]/50"
                          : "bg-[var(--color-brand-secondary)]/[0.03] hover:bg-[var(--color-brand-secondary)]/[0.06]"
                      )}
                    >
                      {/* Icon */}
                      <div
                        className={cn(
                          "flex h-8 w-8 items-center justify-center rounded-lg shrink-0",
                          config.bg
                        )}
                      >
                        <Icon size={16} className={config.color} />
                      </div>

                      {/* Content */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-start justify-between gap-2">
                          <p
                            className={cn(
                              "text-sm leading-snug",
                              notification.read
                                ? "text-[var(--text-secondary)] font-normal"
                                : "text-[var(--text-primary)] font-medium"
                            )}
                          >
                            {notification.title}
                          </p>
                          <span className="text-[11px] text-[var(--text-secondary)]/60 whitespace-nowrap shrink-0">
                            {timeAgo(notification.time)}
                          </span>
                        </div>
                        <p className="text-xs text-[var(--text-secondary)] mt-0.5 leading-relaxed line-clamp-2">
                          {notification.message}
                        </p>
                      </div>

                      {/* Unread dot */}
                      {!notification.read && (
                        <span className="h-2 w-2 rounded-full bg-[var(--color-brand-secondary)] shrink-0 mt-2" />
                      )}
                    </motion.button>
                  );
                })}
              </AnimatePresence>
              {notifications.length > visibleCount && (
                <button
                  onClick={() => setVisibleCount((prev) => prev + 5)}
                  className="w-full flex items-center justify-center gap-1.5 py-3 mt-2 rounded-lg text-xs font-medium text-[var(--color-brand-secondary)] hover:bg-[var(--color-brand-secondary)]/5 transition-colors cursor-pointer"
                >
                  <ChevronDown size={14} />
                  Show more ({notifications.length - visibleCount} remaining)
                </button>
              )}
            </>
          )}
        </div>
      </DashboardPanel>

      {/* Delivery Channels Section */}
      <DeliveryChannelsSection />

      {/* Platform-specific Channels & Quick Actions */}
      {(slackConnected || teamsConnected) && (
        <PlatformScopedSections
          slackConnected={slackConnected}
          teamsConnected={teamsConnected}
        />
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  PLATFORM SCOPED SECTIONS (tab-switched)                                   */
/* -------------------------------------------------------------------------- */

function PlatformScopedSections({
  slackConnected,
  teamsConnected,
}: {
  slackConnected: boolean;
  teamsConnected: boolean;
}) {
  const [platform, setPlatform] = usePlatformTab(slackConnected, teamsConnected);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h3 className="text-base font-semibold text-[var(--text-primary)]">
          Channel Communication
        </h3>
        <PlatformTabs
          value={platform}
          onChange={setPlatform}
          slackConnected={slackConnected}
          teamsConnected={teamsConnected}
        />
      </div>

      {platform === "slack" && slackConnected && (
        <>
          <ProjectChannelManager platform="slack" />
          <POQuickActions platform="slack" />
          <SlackMessageComposer />
        </>
      )}
      {platform === "slack" && !slackConnected && (
        <DashboardPanel title="Slack not connected" icon={Hash}>
          <p className="text-sm text-[var(--text-secondary)]">
            Connect Slack from Delivery Channels above to use project channels and quick actions.
          </p>
        </DashboardPanel>
      )}

      {platform === "teams" && teamsConnected && (
        <>
          <ParentTeamSelector />
          <ProjectChannelManager platform="teams" />
          <POQuickActions platform="teams" />
          <TeamsMessageComposer />
        </>
      )}
      {platform === "teams" && !teamsConnected && (
        <DashboardPanel title="Microsoft Teams not connected" icon={Hash}>
          <p className="text-sm text-[var(--text-secondary)]">
            Connect Microsoft Teams from Delivery Channels above to use project channels and quick actions.
          </p>
        </DashboardPanel>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  PARENT TEAM SELECTOR (Teams only)                                          */
/* -------------------------------------------------------------------------- */

function ParentTeamSelector() {
  const [selected, setSelected] = useState<{ id: string; name: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [picking, setPicking] = useState(false);
  const [teams, setTeams] = useState<{ id: string; displayName: string; description: string }[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch("/api/integrations/teams/parent-team");
        if (res.ok) {
          const data = await res.json();
          if (data.selected) {
            setSelected({ id: data.parentTeamId, name: data.parentTeamName });
          }
        }
      } catch {}
      setLoading(false);
    })();
  }, []);

  const [needsReconsent, setNeedsReconsent] = useState(false);

  const loadTeams = async () => {
    setPicking(true);
    setError(null);
    setNeedsReconsent(false);
    try {
      const res = await fetch("/api/integrations/teams/list-teams", { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setTeams(data.teams || []);
      } else {
        const err = await res.json().catch(() => ({ detail: "Failed" }));
        // Normalise both FastAPI shapes: {detail: {code, message}} or {detail: "..."}
        const detail = err?.detail;
        if (detail && typeof detail === "object" && detail.code === "reconsent_required") {
          setNeedsReconsent(true);
          setError(detail.message);
        } else if (typeof detail === "string") {
          setError(detail);
        } else {
          setError("Could not list Teams");
        }
      }
    } catch {
      setError("Network error");
    }
  };

  const reconnectTeams = async () => {
    try {
      await fetch("/api/integrations/teams/disconnect", { method: "DELETE" });
    } catch { /* ignore */ }
    // Hand off to the server-side OAuth connect URL (full redirect)
    window.location.href = "/api/integrations/teams/connect";
  };

  const pick = async (id: string, name: string) => {
    setSaving(true);
    setError(null);
    try {
      const res = await fetch("/api/integrations/teams/select-parent-team", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ teamId: id, teamName: name }),
      });
      if (res.ok) {
        setSelected({ id, name });
        setPicking(false);
      } else {
        const err = await res.json().catch(() => ({ detail: "Failed" }));
        setError(err.detail || "Could not save");
      }
    } catch {
      setError("Network error");
    }
    setSaving(false);
  };

  if (loading) return null;

  return (
    <DashboardPanel title="Parent Microsoft Team" icon={Users}>
      <p className="text-xs text-[var(--text-secondary)] mb-3">
        Plan2Sprint creates project channels inside one of your existing MS Teams. Pick which Team should host them.
      </p>
      {error && !needsReconsent && (
        <div className="mb-3 p-3 rounded-lg bg-[var(--color-rag-red)]/5 border border-[var(--color-rag-red)]/20">
          <p className="text-xs text-[var(--color-rag-red)]">⚠ {error}</p>
        </div>
      )}
      {needsReconsent && (
        <div className="mb-3 p-3 rounded-lg bg-[var(--color-rag-amber)]/5 border border-[var(--color-rag-amber)]/20 space-y-2">
          <div className="flex items-start gap-3">
            <div className="flex-1">
              <p className="text-xs font-medium text-[var(--color-rag-amber)] mb-0.5">
                New Microsoft permissions required
              </p>
              <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
                {error}
              </p>
            </div>
            <Button size="sm" onClick={reconnectTeams}>
              Reconnect Teams
            </Button>
          </div>
          <p className="text-[11px] text-[var(--text-tertiary)] leading-relaxed pl-0.5">
            Seeing &ldquo;Approval required&rdquo; from Microsoft? Your tenant admin
            needs to grant consent first.{" "}
            <a
              href="/api/integrations/teams/admin-consent"
              target="_blank"
              rel="noopener noreferrer"
              className="underline font-medium text-[var(--color-rag-amber)] hover:text-[var(--color-rag-amber)]/80"
            >
              Open tenant-wide admin consent link →
            </a>
          </p>
        </div>
      )}

      {selected && !picking && (
        <div className="flex items-center justify-between p-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--color-brand-secondary)]/10">
              <Users size={14} className="text-[var(--color-brand-secondary)]" />
            </div>
            <div>
              <p className="text-sm font-medium text-[var(--text-primary)]">{selected.name}</p>
              <p className="text-[11px] text-[var(--text-tertiary)]">Hosts all Plan2Sprint project channels</p>
            </div>
          </div>
          <Button size="sm" variant="secondary" onClick={loadTeams}>
            Change
          </Button>
        </div>
      )}

      {(!selected || picking) && (
        <div className="space-y-2">
          {teams.length === 0 ? (
            <Button size="sm" onClick={loadTeams} disabled={picking && teams.length === 0}>
              {picking ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : <Users className="h-3 w-3 mr-1" />}
              Load my Teams
            </Button>
          ) : (
            teams.map((t) => (
              <div
                key={t.id}
                className="flex items-center justify-between p-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]"
              >
                <div>
                  <p className="text-sm font-medium text-[var(--text-primary)]">{t.displayName}</p>
                  {t.description && (
                    <p className="text-[11px] text-[var(--text-tertiary)]">{t.description}</p>
                  )}
                </div>
                <Button
                  size="sm"
                  variant={selected?.id === t.id ? "primary" : "secondary"}
                  onClick={() => pick(t.id, t.displayName)}
                  disabled={saving}
                >
                  {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : selected?.id === t.id ? "Selected" : "Pick"}
                </Button>
              </div>
            ))
          )}
        </div>
      )}
    </DashboardPanel>
  );
}


/* -------------------------------------------------------------------------- */
/*  PROJECT CHANNEL MANAGER                                                    */
/* -------------------------------------------------------------------------- */

interface ProjectChannel {
  id: string;
  name: string;
  hasChannel: boolean;
  channelId?: string;
  channelName?: string;
}

function ProjectChannelManager({ platform }: { platform: Platform }) {
  const base = platform === "slack" ? "/api/integrations/slack" : "/api/integrations/teams";
  const prefix = platform === "slack" ? "#" : "";
  const [projects, setProjects] = useState<ProjectChannel[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState<string | null>(null);

  // Refresh when a channel is created (on this page or elsewhere via WS)
  const channelCreatedKey = useAutoRefresh(["channel_created"]);

  useEffect(() => {
    setLoading(true);
    (async () => {
      try {
        const projRes = await fetch("/api/projects");
        if (!projRes.ok) return;
        const projData = await projRes.json();
        const projectList = projData.projects || [];

        // Check channel status for each project (use internalId, the DB primary key)
        const withChannels = await Promise.all(
          projectList.map(async (p: { internalId: string; id: string; name: string }) => {
            const projId = p.internalId || p.id;
            try {
              const chRes = await fetch(`${base}/project-channel?projectId=${projId}`);
              if (chRes.ok) {
                const chData = await chRes.json();
                return { id: projId, name: p.name, ...chData };
              }
            } catch { /* ignore */ }
            return { id: projId, name: p.name, hasChannel: false };
          })
        );
        setProjects(withChannels);
      } catch { /* ignore */ }
      setLoading(false);
    })();
  }, [base, channelCreatedKey]);

  const [createError, setCreateError] = useState<string | null>(null);

  const handleCreate = async (projectId: string) => {
    setCreating(projectId);
    setCreateError(null);
    try {
      const res = await fetch(`${base}/create-channel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ projectId }),
      });
      if (res.ok) {
        const data = await res.json();
        setProjects(prev =>
          prev.map(p =>
            p.id === projectId
              ? { ...p, hasChannel: true, channelId: data.channelId, channelName: data.channelName }
              : p
          )
        );
      } else {
        const err = await res.json().catch(() => ({ detail: "Unknown error" }));
        setCreateError(err.detail || "Failed to create channel");
      }
    } catch (e) {
      setCreateError("Network error — please try again");
    }
    setCreating(null);
  };

  if (loading) return null;

  const label = platform === "slack" ? "Slack" : "Microsoft Teams";

  return (
    <DashboardPanel title={`Project Channels (${label})`} icon={Hash}>
      <p className="text-xs text-[var(--text-secondary)] mb-4">
        {platform === "slack"
          ? "Create Slack channels for your projects. Team members are auto-invited."
          : "Create channels inside your selected parent Team. Members of the parent Team get automatic access."}
      </p>
      {createError && (
        <div className="mb-3 p-3 rounded-lg bg-[var(--color-rag-red)]/5 border border-[var(--color-rag-red)]/20">
          <p className="text-xs text-[var(--color-rag-red)]">⚠ {createError}</p>
        </div>
      )}
      <div className="space-y-2">
        {projects.map(proj => (
          <div
            key={proj.id}
            className="flex items-center justify-between p-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]"
          >
            <div className="flex items-center gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--color-brand-secondary)]/10">
                <Hash size={14} className="text-[var(--color-brand-secondary)]" />
              </div>
              <div>
                <p className="text-sm font-medium text-[var(--text-primary)]">{proj.name}</p>
                {proj.hasChannel ? (
                  <p className="text-xs text-[var(--color-rag-green)]">
                    {prefix}{proj.channelName}
                  </p>
                ) : (
                  <p className="text-xs text-[var(--text-tertiary)]">No channel</p>
                )}
              </div>
            </div>
            {proj.hasChannel ? (
              <Badge variant="rag-green" className="text-[10px]">Connected</Badge>
            ) : (
              <Button
                size="sm"
                variant="secondary"
                onClick={() => handleCreate(proj.id)}
                disabled={creating === proj.id}
              >
                {creating === proj.id ? (
                  <Loader2 className="h-3 w-3 animate-spin mr-1" />
                ) : (
                  <Plus className="h-3 w-3 mr-1" />
                )}
                Create Channel
              </Button>
            )}
          </div>
        ))}
        {projects.length === 0 && (
          <p className="text-xs text-[var(--text-tertiary)] text-center py-4">
            No projects imported yet.
          </p>
        )}
      </div>
    </DashboardPanel>
  );
}


/* -------------------------------------------------------------------------- */
/*  PO QUICK ACTIONS                                                           */
/* -------------------------------------------------------------------------- */

function POQuickActions({ platform }: { platform: Platform }) {
  const base = platform === "slack" ? "/api/integrations/slack" : "/api/integrations/teams";
  const prefix = platform === "slack" ? "#" : "";
  const [projects, setProjects] = useState<ProjectChannel[]>([]);
  const [selectedProject, setSelectedProject] = useState("");
  const [announcementText, setAnnouncementText] = useState("");
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);

  const channelCreatedKey = useAutoRefresh(["channel_created"]);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch("/api/projects");
        if (res.ok) {
          const data = await res.json();
          const list = data.projects || [];
          // Get channel status (use internalId, the DB primary key)
          const withCh = await Promise.all(
            list.map(async (p: { internalId: string; id: string; name: string }) => {
              const projId = p.internalId || p.id;
              try {
                const r = await fetch(`${base}/project-channel?projectId=${projId}`);
                if (r.ok) {
                  const d = await r.json();
                  return { id: projId, name: p.name, ...d };
                }
              } catch {}
              return { id: projId, name: p.name, hasChannel: false };
            })
          );
          setProjects(withCh);
          if (withCh.length > 0) setSelectedProject(prev => prev || withCh[0].id);
        }
      } catch {}
    })();
  }, [base, channelCreatedKey]);

  const selectedProj = projects.find(p => p.id === selectedProject);
  const hasChannel = selectedProj?.hasChannel ?? false;

  const sendToChannel = async (type: string, data: Record<string, string>) => {
    if (!selectedProject) return;
    setSending(true);
    setResult(null);
    try {
      const res = await fetch(`${base}/post-to-channel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ projectId: selectedProject, type, data }),
      });
      const resp = await res.json();
      if (resp.ok) {
        setResult({ ok: true, message: `Sent to ${prefix}${resp.channelName}` });
        setAnnouncementText("");
      } else {
        setResult({ ok: false, message: resp.message || "Failed to send" });
      }
    } catch {
      setResult({ ok: false, message: "Network error" });
    }
    setSending(false);
  };

  return (
    <DashboardPanel title="Quick Actions" icon={Megaphone}>
      {/* Project selector */}
      <div className="mb-4">
        <label className="text-xs text-[var(--text-secondary)] mb-1 block">Project:</label>
        <select
          value={selectedProject}
          onChange={e => { setSelectedProject(e.target.value); setResult(null); }}
          className="w-full max-w-xs rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] px-3 py-2 text-sm text-[var(--text-primary)]"
        >
          {projects.map(p => (
            <option key={p.id} value={p.id}>{p.name} {p.hasChannel ? `(${prefix}${p.channelName})` : "(no channel)"}</option>
          ))}
        </select>
      </div>

      {!hasChannel && selectedProject && (
        <div className="p-3 rounded-lg bg-[var(--color-rag-amber)]/5 border border-[var(--color-rag-amber)]/20 mb-4">
          <p className="text-xs text-[var(--color-rag-amber)]">
            No {platform === "slack" ? "Slack" : "Teams"} channel for {selectedProj?.name}. Create one above first.
          </p>
        </div>
      )}

      {/* Announcement */}
      <div className="space-y-3">
        <div>
          <label className="text-xs text-[var(--text-secondary)] mb-1 block">Send Announcement:</label>
          <div className="flex gap-2">
            <Input
              value={announcementText}
              onChange={e => setAnnouncementText(e.target.value)}
              placeholder="Type your announcement..."
              className="flex-1 text-sm"
              disabled={!hasChannel}
            />
            <Button
              size="sm"
              onClick={() => sendToChannel("announcement", { message: announcementText })}
              disabled={!hasChannel || !announcementText.trim() || sending}
            >
              {sending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Send className="h-3 w-3" />}
            </Button>
          </div>
        </div>

        {/* Share Sprint Plan */}
        <Button
          variant="secondary"
          size="sm"
          onClick={() => sendToChannel("sprint_plan_channel", {})}
          disabled={!hasChannel || sending}
          className="w-full justify-start"
        >
          <Zap className="h-3.5 w-3.5 mr-2" />
          Share Sprint Plan to Channel
        </Button>
      </div>

      {/* Result feedback */}
      {result && (
        <p className={cn("text-xs mt-3", result.ok ? "text-[var(--color-rag-green)]" : "text-[var(--color-rag-red)]")}>
          {result.ok ? "✓" : "✗"} {result.message}
        </p>
      )}
    </DashboardPanel>
  );
}
