"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import {
  Bell,
  AlertTriangle,
  CheckCircle2,
  Zap,
  X,
  MessageSquareText,
  HeartPulse,
  GitPullRequest,
  Info,
  Bot,
  ShieldAlert,
  Activity,
  FileText,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAutoRefresh } from "@/lib/ws/context";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Notification {
  id: string;
  type: string;
  title: string;
  message: string;
  time: string;
  read: boolean;
}

// Map API notification types to UI display config
const typeConfig: Record<
  string,
  { icon: typeof Bell; color: string }
> = {
  blocker_alert: { icon: AlertTriangle, color: "var(--color-rag-red)" },
  sprint_approval: { icon: Zap, color: "var(--color-brand-secondary)" },
  health_alert: { icon: HeartPulse, color: "var(--color-rag-amber)" },
  standup_report: { icon: MessageSquareText, color: "var(--color-brand-secondary)" },
  standup_digest: { icon: MessageSquareText, color: "var(--color-rag-green)" },
  writeback_success: { icon: GitPullRequest, color: "var(--color-rag-green)" },
  sprint_assignment: { icon: CheckCircle2, color: "var(--color-brand-secondary)" },
  ci_failure: { icon: AlertTriangle, color: "var(--color-rag-red)" },
  retro_action: { icon: Info, color: "var(--color-rag-amber)" },
  sprint_completed: { icon: CheckCircle2, color: "var(--color-brand-secondary)" },
  // Agent notification types
  agent_standup: { icon: Bot, color: "var(--color-brand-secondary)" },
  agent_blocker: { icon: ShieldAlert, color: "var(--color-rag-red)" },
  agent_health: { icon: Activity, color: "var(--color-rag-amber)" },
  agent_retro: { icon: FileText, color: "var(--color-rag-green)" },
};

const defaultConfig = { icon: Bell, color: "var(--text-secondary)" };

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function timeAgo(iso: string): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const ref = useRef<HTMLDivElement>(null);

  // Auto-refresh when WS notification events arrive
  const refreshKey = useAutoRefresh([
    "notification",
    "standup_note_submitted",
    "blocker_flagged",
    "standup_generated",
    "blockers_detected",
    "health_analysis_complete",
    "retro_generated",
    "sprint_completed",
  ]);

  const fetchNotifications = useCallback(async () => {
    try {
      const res = await fetch("/api/notifications?limit=20");
      if (res.ok) {
        const data = await res.json();
        setNotifications(data.notifications ?? []);
      }
    } catch {
      // API unavailable - keep existing state
    }
  }, []);

  useEffect(() => {
    fetchNotifications();
  }, [fetchNotifications, refreshKey]);

  // Close on outside click
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const unreadCount = notifications.filter((n) => !n.read).length;

  const markAsRead = async (id: string) => {
    try {
      await fetch(`/api/notifications/${id}/read`, { method: "PATCH" });
      setNotifications((prev) =>
        prev.map((n) => (n.id === id ? { ...n, read: true } : n))
      );
    } catch {
      // ignore
    }
  };

  const clearAll = async () => {
    try {
      await fetch("/api/notifications/read-all", { method: "PATCH" });
      setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
    } catch {
      // ignore
    }
  };

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="relative flex h-9 w-9 items-center justify-center rounded-xl hover:bg-[var(--bg-surface-raised)] transition-colors cursor-pointer"
      >
        <Bell className="h-4.5 w-4.5 text-[var(--text-secondary)]" />
        {unreadCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-[var(--color-rag-red)] text-[10px] font-bold text-white">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-80 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]/95 backdrop-blur-xl shadow-xl z-50">
          <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-subtle)]">
            <span className="text-sm font-semibold text-[var(--text-primary)]">
              Notifications
            </span>
            <button
              onClick={() => setOpen(false)}
              className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="max-h-80 overflow-y-auto">
            {notifications.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8 gap-2">
                <Bell size={20} className="text-[var(--text-tertiary)]" />
                <span className="text-xs text-[var(--text-tertiary)]">
                  No notifications yet
                </span>
              </div>
            ) : (
              notifications.map((notif) => {
                const config = typeConfig[notif.type] ?? defaultConfig;
                const Icon = config.icon;
                return (
                  <div
                    key={notif.id}
                    onClick={() => !notif.read && markAsRead(notif.id)}
                    className={cn(
                      "flex gap-3 px-4 py-3 hover:bg-[var(--bg-surface-raised)] transition-colors cursor-pointer",
                      !notif.read && "bg-[var(--color-brand-secondary)]/5"
                    )}
                  >
                    <div
                      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
                      style={{
                        backgroundColor: `color-mix(in srgb, ${config.color} 15%, transparent)`,
                      }}
                    >
                      <Icon
                        className="h-4 w-4"
                        style={{ color: config.color }}
                      />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-[var(--text-primary)] truncate">
                        {notif.title}
                      </p>
                      <p className="text-xs text-[var(--text-secondary)] truncate">
                        {notif.message}
                      </p>
                      <p className="text-xs text-[var(--text-secondary)]/60 mt-0.5">
                        {timeAgo(notif.time)}
                      </p>
                    </div>
                    {!notif.read && (
                      <span className="h-2 w-2 rounded-full bg-[var(--color-brand-secondary)] shrink-0 mt-2" />
                    )}
                  </div>
                );
              })
            )}
          </div>
          <div className="flex items-center justify-between border-t border-[var(--border-subtle)] px-4 py-2">
            <button
              onClick={() => {
                setOpen(false);
                window.location.href = "/po/notifications";
              }}
              className="text-xs font-medium text-[var(--color-brand-secondary)] hover:underline cursor-pointer"
            >
              View all notifications
            </button>
            {unreadCount > 0 && (
              <button
                onClick={clearAll}
                className="text-xs font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer"
              >
                Clear all
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
