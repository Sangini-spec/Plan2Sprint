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
} from "lucide-react";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { DeliveryChannelsSection } from "@/components/notifications/delivery-channels-section";
import { SlackMessageComposer } from "@/components/notifications/slack-message-composer";
import { SlackQuickActions } from "@/components/notifications/slack-quick-actions";
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
          {unreadCount > 0 && (
            <button
              onClick={markAllRead}
              className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--color-brand-secondary)] hover:underline cursor-pointer"
            >
              <CheckCheck size={14} />
              Mark all as read
            </button>
          )}
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
            <AnimatePresence initial={false}>
              {notifications.map((notification) => {
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
          )}
        </div>
      </DashboardPanel>

      {/* Delivery Channels Section */}
      <DeliveryChannelsSection />

      {/* Quick Actions & Message Composer — when any channel is connected */}
      {(slackConnected || teamsConnected) && (
        <>
          <SlackQuickActions role="po" />
          {slackConnected && <SlackMessageComposer />}
        </>
      )}
    </div>
  );
}
