"use client";

import { useState, useRef, useEffect } from "react";
import { Bell, AlertTriangle, CheckCircle2, Zap, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface Notification {
  id: string;
  type: "blocker" | "approval" | "health" | "writeback" | "info";
  title: string;
  message: string;
  time: string;
  read: boolean;
}

const MOCK_NOTIFICATIONS: Notification[] = [
  {
    id: "1",
    type: "blocker",
    title: "New Blocker Flagged",
    message: "Alex flagged a blocker on PROJ-245",
    time: "5m ago",
    read: false,
  },
  {
    id: "2",
    type: "approval",
    title: "Sprint Plan Ready",
    message: "Sprint 24 plan is ready for your review",
    time: "1h ago",
    read: false,
  },
  {
    id: "3",
    type: "health",
    title: "Burnout Risk Detected",
    message: "Sarah's capacity utilization at 92% for 3 sprints",
    time: "2h ago",
    read: false,
  },
];

const typeIcons = {
  blocker: AlertTriangle,
  approval: Zap,
  health: AlertTriangle,
  writeback: CheckCircle2,
  info: Bell,
};

const typeColors = {
  blocker: "text-[var(--color-rag-red)]",
  approval: "text-[var(--color-brand-secondary)]",
  health: "text-[var(--color-rag-amber)]",
  writeback: "text-[var(--color-rag-green)]",
  info: "text-[var(--text-secondary)]",
};

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [notifications] = useState<Notification[]>(MOCK_NOTIFICATIONS);
  const ref = useRef<HTMLDivElement>(null);

  const unreadCount = notifications.filter((n) => !n.read).length;

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="relative flex h-9 w-9 items-center justify-center rounded-xl hover:bg-[var(--bg-surface-raised)] transition-colors cursor-pointer"
      >
        <Bell className="h-4.5 w-4.5 text-[var(--text-secondary)]" />
        {unreadCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-[var(--color-rag-red)] text-[10px] font-bold text-white">
            {unreadCount}
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
            {notifications.map((notif) => {
              const Icon = typeIcons[notif.type];
              return (
                <div
                  key={notif.id}
                  className={cn(
                    "flex gap-3 px-4 py-3 hover:bg-[var(--bg-surface-raised)] transition-colors cursor-pointer",
                    !notif.read && "bg-[var(--color-brand-secondary)]/5"
                  )}
                >
                  <div
                    className={cn(
                      "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
                      `${typeColors[notif.type].replace("text-", "bg-")}/10`
                    )}
                  >
                    <Icon className={cn("h-4 w-4", typeColors[notif.type])} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-[var(--text-primary)] truncate">
                      {notif.title}
                    </p>
                    <p className="text-xs text-[var(--text-secondary)] truncate">
                      {notif.message}
                    </p>
                    <p className="text-xs text-[var(--text-secondary)]/60 mt-0.5">
                      {notif.time}
                    </p>
                  </div>
                  {!notif.read && (
                    <span className="h-2 w-2 rounded-full bg-[var(--color-brand-secondary)] shrink-0 mt-2" />
                  )}
                </div>
              );
            })}
          </div>
          <div className="border-t border-[var(--border-subtle)] px-4 py-2">
            <button className="text-xs font-medium text-[var(--color-brand-secondary)] hover:underline cursor-pointer">
              View all notifications
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
