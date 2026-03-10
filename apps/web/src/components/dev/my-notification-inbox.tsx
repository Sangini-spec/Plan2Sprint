"use client";

import { useState } from "react";
import {
  Inbox,
  UserPlus,
  XCircle,
  Eye,
  ClipboardCheck,
  CheckCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Button } from "@/components/ui";
import type { LucideIcon } from "lucide-react";

interface Notification {
  type: "assignment" | "ci_failure" | "review_request" | "action_item";
  message: string;
  time: string;
  read: boolean;
}

const initialNotifications: Notification[] = [
  {
    type: "assignment",
    message: "You were assigned PROJ-211: Checkout flow E2E tests",
    time: "2h ago",
    read: false,
  },
  {
    type: "ci_failure",
    message: "CI failed on PR #301: lint error in CheckoutStep.tsx",
    time: "4h ago",
    read: false,
  },
  {
    type: "review_request",
    message: "James Wilson requested review on PR #303",
    time: "1d ago",
    read: true,
  },
  {
    type: "action_item",
    message:
      "Retro action item due: Add 10% tech debt buffer to capacity model",
    time: "2d ago",
    read: true,
  },
];

const typeConfig: Record<
  Notification["type"],
  { icon: LucideIcon; color: string }
> = {
  assignment: {
    icon: UserPlus,
    color: "var(--color-brand-secondary)",
  },
  ci_failure: {
    icon: XCircle,
    color: "var(--color-rag-red)",
  },
  review_request: {
    icon: Eye,
    color: "var(--color-rag-amber)",
  },
  action_item: {
    icon: ClipboardCheck,
    color: "var(--color-rag-green)",
  },
};

export function MyNotificationInbox() {
  const [notifications, setNotifications] = useState(initialNotifications);

  const unreadCount = notifications.filter((n) => !n.read).length;

  function markAllRead() {
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
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
        {notifications.map((notif, i) => {
          const { icon: Icon, color } = typeConfig[notif.type];
          return (
            <div
              key={`${notif.type}-${notif.time}-${i}`}
              className={cn(
                "flex items-start gap-3 rounded-xl border p-3 transition-colors",
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
                  {notif.message}
                </p>
                <span className="text-xs text-[var(--text-secondary)] mt-0.5 block">
                  {notif.time}
                </span>
              </div>
              {!notif.read && (
                <div className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-[var(--color-brand-secondary)]" />
              )}
            </div>
          );
        })}

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
