"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Inbox,
  Bell,
  UserPlus,
  XCircle,
  Eye,
  ClipboardCheck,
  CheckCheck,
  AlertTriangle,
  MessageSquareText,
  HeartPulse,
  Bot,
  ShieldAlert,
  Activity,
  FileText,
  Zap,
  Info,
  GitPullRequest,
  CheckCircle2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Button } from "@/components/ui";
import { useAutoRefresh } from "@/lib/ws/context";
import type { LucideIcon } from "lucide-react";

interface Notification {
  id: string;
  type: string;
  title: string;
  message: string;
  time: string;
  read: boolean;
}

const typeConfig: Record<string, { icon: LucideIcon; color: string }> = {
  assignment: { icon: UserPlus, color: "var(--color-brand-secondary)" },
  ci_failure: { icon: XCircle, color: "var(--color-rag-red)" },
  review_request: { icon: Eye, color: "var(--color-rag-amber)" },
  action_item: { icon: ClipboardCheck, color: "var(--color-rag-green)" },
  sprint_assignment: { icon: Zap, color: "var(--color-brand-secondary)" },
  standup_report: { icon: MessageSquareText, color: "var(--color-brand-secondary)" },
  standup_digest: { icon: MessageSquareText, color: "var(--color-rag-green)" },
  blocker_alert: { icon: AlertTriangle, color: "var(--color-rag-red)" },
  health_alert: { icon: HeartPulse, color: "var(--color-rag-amber)" },
  sprint_approval: { icon: CheckCircle2, color: "var(--color-brand-secondary)" },
  writeback_success: { icon: GitPullRequest, color: "var(--color-rag-green)" },
  retro_action: { icon: Info, color: "var(--color-rag-amber)" },
  // Agent notification types
  agent_standup: { icon: Bot, color: "var(--color-brand-secondary)" },
  agent_blocker: { icon: ShieldAlert, color: "var(--color-rag-red)" },
  agent_health: { icon: Activity, color: "var(--color-rag-amber)" },
  agent_retro: { icon: FileText, color: "var(--color-rag-green)" },
};

const defaultConfig = { icon: Bell, color: "var(--text-secondary)" };

function timeAgo(iso: string): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "Yesterday";
  return `${days}d ago`;
}

export function MyNotificationInbox() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);

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
      const res = await fetch("/api/notifications?limit=30");
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

  async function markAllRead() {
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
    const unread = notifications.filter((n) => !n.read);
    for (const n of unread) {
      try {
        await fetch(`/api/notifications/${n.id}/read`, { method: "PATCH" });
      } catch { /* ignore */ }
    }
  }

  async function markRead(id: string) {
    try {
      await fetch(`/api/notifications/${id}/read`, { method: "PATCH" });
      setNotifications((prev) =>
        prev.map((n) => (n.id === id ? { ...n, read: true } : n))
      );
    } catch { /* ignore */ }
  }

  return (
    <DashboardPanel
      title="Notifications"
      icon={Inbox}
      actions={
        unreadCount > 0 ? (
          <span className="flex h-5 min-w-[20px] items-center justify-center rounded-full bg-[var(--color-rag-red)] px-1.5 text-[10px] font-bold text-white">
            {unreadCount}
          </span>
        ) : null
      }
    >
      <div className="space-y-3">
        {loading ? (
          <div className="flex flex-col items-center justify-center py-8 gap-2">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-[var(--color-brand-secondary)] border-t-transparent" />
            <span className="text-xs text-[var(--text-tertiary)]">Loading notifications...</span>
          </div>
        ) : notifications.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 gap-2">
            <Bell size={20} className="text-[var(--text-tertiary)]" />
            <span className="text-xs text-[var(--text-tertiary)]">
              No notifications yet
            </span>
          </div>
        ) : (
          notifications.map((notif) => {
            const { icon: Icon, color } = typeConfig[notif.type] ?? defaultConfig;
            return (
              <div
                key={notif.id}
                onClick={() => !notif.read && markRead(notif.id)}
                className={cn(
                  "flex items-start gap-3 rounded-xl border p-3 transition-colors cursor-pointer",
                  notif.read
                    ? "border-[var(--border-subtle)] bg-transparent"
                    : "border-[var(--color-brand-secondary)]/20 bg-[var(--color-brand-secondary)]/5"
                )}
              >
                <div
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg"
                  style={{
                    backgroundColor: `color-mix(in srgb, ${color} 15%, transparent)`,
                  }}
                >
                  <Icon className="h-3.5 w-3.5" style={{ color }} />
                </div>
                <div className="flex-1 min-w-0">
                  <p
                    className={cn(
                      "text-sm leading-snug",
                      notif.read
                        ? "text-[var(--text-secondary)]"
                        : "text-[var(--text-primary)] font-medium"
                    )}
                  >
                    {notif.title}
                  </p>
                  <p className="text-xs text-[var(--text-secondary)] mt-0.5 leading-relaxed line-clamp-2">
                    {notif.message}
                  </p>
                  <span className="text-xs text-[var(--text-secondary)]/60 mt-0.5 block">
                    {timeAgo(notif.time)}
                  </span>
                </div>
                {!notif.read && (
                  <div className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-[var(--color-brand-secondary)]" />
                )}
              </div>
            );
          })
        )}

        {/* Mark all as read */}
        {unreadCount > 0 && (
          <div className="pt-2 border-t border-[var(--border-subtle)]">
            <Button variant="ghost" size="sm" onClick={markAllRead}>
              <CheckCheck className="h-4 w-4 mr-1.5" />
              Mark all as read
            </Button>
          </div>
        )}
      </div>
    </DashboardPanel>
  );
}
