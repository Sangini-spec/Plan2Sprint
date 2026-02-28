"use client";

import { useState, useEffect } from "react";
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
} from "lucide-react";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { DeliveryChannelsSection } from "@/components/notifications/delivery-channels-section";
import { SlackMessageComposer } from "@/components/notifications/slack-message-composer";
import { SlackQuickActions } from "@/components/notifications/slack-quick-actions";

/* -------------------------------------------------------------------------- */
/*  PO NOTIFICATION TYPES & MOCK DATA                                          */
/* -------------------------------------------------------------------------- */

type NotificationType =
  | "approval"
  | "blocker"
  | "health"
  | "writeback"
  | "info";

interface Notification {
  id: string;
  type: NotificationType;
  title: string;
  body: string;
  time: string;
  read: boolean;
}

const MOCK_NOTIFICATIONS: Notification[] = [
  {
    id: "1",
    type: "approval",
    title: "Sprint plan ready for approval",
    body: "Sprint 14 plan for Team Alpha has been generated with 34 story points across 8 tickets.",
    time: "12 min ago",
    read: false,
  },
  {
    id: "2",
    type: "blocker",
    title: "Blocker flagged by Sarah Chen",
    body: "AUTH-245: OAuth token refresh failing in staging — blocking QA for 2 days.",
    time: "1 hour ago",
    read: false,
  },
  {
    id: "3",
    type: "health",
    title: "Burnout risk detected",
    body: "Marcus Johnson has worked 6 consecutive late evenings. Consider reassigning DASH-189.",
    time: "3 hours ago",
    read: false,
  },
  {
    id: "4",
    type: "writeback",
    title: "Write-back completed",
    body: "Sprint 13 assignments synced to Jira — 12 tickets updated (assignee + sprint field).",
    time: "Yesterday",
    read: true,
  },
  {
    id: "5",
    type: "info",
    title: "Retrospective summary ready",
    body: "Sprint 13 retro highlights: 3 action items, top theme was \"deployment pipeline delays\".",
    time: "2 days ago",
    read: true,
  },
];

const TYPE_CONFIG: Record<
  NotificationType,
  { icon: typeof Bell; color: string; bg: string }
> = {
  approval: {
    icon: CheckCircle2,
    color: "text-[var(--color-brand-secondary)]",
    bg: "bg-[var(--color-brand-secondary)]/10",
  },
  blocker: {
    icon: AlertTriangle,
    color: "text-[var(--color-rag-red)]",
    bg: "bg-[var(--color-rag-red)]/10",
  },
  health: {
    icon: HeartPulse,
    color: "text-[var(--color-rag-amber)]",
    bg: "bg-[var(--color-rag-amber)]/10",
  },
  writeback: {
    icon: GitPullRequest,
    color: "text-[var(--color-rag-green)]",
    bg: "bg-[var(--color-rag-green)]/10",
  },
  info: {
    icon: Info,
    color: "text-[var(--text-secondary)]",
    bg: "bg-[var(--bg-surface-raised)]",
  },
};

/* -------------------------------------------------------------------------- */
/*  PO NOTIFICATIONS PAGE                                                       */
/* -------------------------------------------------------------------------- */

export default function PONotificationsPage() {
  const [notifications, setNotifications] = useState(MOCK_NOTIFICATIONS);
  const [slackConnected, setSlackConnected] = useState(false);
  const [teamsConnected, setTeamsConnected] = useState(false);

  const unreadCount = notifications.filter((n) => !n.read).length;

  // Check if Slack / Teams are connected
  useEffect(() => {
    let cancelled = false;

    async function checkConnections() {
      // Check Slack
      try {
        const res = await fetch("/api/integrations/slack/status");
        if (res.ok) {
          const data = await res.json();
          if (!cancelled) setSlackConnected(data.connected === true);
        }
      } catch {
        // Ignore
      }

      // Check Teams
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

  function markAllRead() {
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
  }

  function toggleRead(id: string) {
    setNotifications((prev) =>
      prev.map((n) => (n.id === id ? { ...n, read: !n.read } : n))
    );
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
          <AnimatePresence initial={false}>
            {notifications.map((notification) => {
              const config = TYPE_CONFIG[notification.type];
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
                        {notification.time}
                      </span>
                    </div>
                    <p className="text-xs text-[var(--text-secondary)] mt-0.5 leading-relaxed line-clamp-2">
                      {notification.body}
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
