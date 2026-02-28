"use client";

import { useState } from "react";
import { BellRing } from "lucide-react";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Button } from "@/components/ui";

type Channel = "slack" | "teams" | "email" | "inApp";

interface NotificationPreference {
  id: string;
  label: string;
  description: string;
  channels: Record<Channel, boolean>;
}

const INITIAL_PREFERENCES: NotificationPreference[] = [
  {
    id: "standup-digest",
    label: "Standup Digest",
    description: "Daily summary of team standup reports",
    channels: { slack: true, teams: true, email: true, inApp: true },
  },
  {
    id: "sprint-health",
    label: "Sprint Health Alerts",
    description: "Alerts when sprint health changes to amber or red",
    channels: { slack: true, teams: true, email: false, inApp: true },
  },
  {
    id: "blocker-notifications",
    label: "Blocker Notifications",
    description: "Immediate alerts when blockers are flagged",
    channels: { slack: true, teams: true, email: true, inApp: true },
  },
  {
    id: "retro-reminders",
    label: "Retro Reminders",
    description: "Reminders before retrospective sessions",
    channels: { slack: false, teams: false, email: true, inApp: true },
  },
  {
    id: "plan-ready",
    label: "Plan Ready",
    description: "Notification when AI sprint plan is ready for review",
    channels: { slack: true, teams: true, email: true, inApp: true },
  },
];

const CHANNEL_LABELS: { key: Channel; label: string }[] = [
  { key: "slack", label: "Slack" },
  { key: "teams", label: "Teams" },
  { key: "email", label: "Email" },
  { key: "inApp", label: "In-App" },
];

function ToggleSwitch({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (val: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent",
        "transition-colors duration-200 ease-in-out",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-brand-secondary)] focus-visible:ring-offset-2",
        checked
          ? "bg-[var(--color-brand-secondary)]"
          : "bg-[var(--bg-surface-raised)] border-[var(--border-subtle)]"
      )}
    >
      <span
        className={cn(
          "pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow-lg ring-0",
          "transition-transform duration-200 ease-in-out",
          checked ? "translate-x-5" : "translate-x-0"
        )}
      />
    </button>
  );
}

export default function NotificationsSettingsPage() {
  const [preferences, setPreferences] = useState<NotificationPreference[]>(
    INITIAL_PREFERENCES
  );

  function toggleChannel(prefId: string, channel: Channel) {
    setPreferences((prev) =>
      prev.map((p) =>
        p.id === prefId
          ? {
              ...p,
              channels: { ...p.channels, [channel]: !p.channels[channel] },
            }
          : p
      )
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-[var(--text-primary)]">
          Notification Preferences
        </h1>
        <p className="mt-1 text-sm text-[var(--text-secondary)]">
          Choose how and where you receive notifications.
        </p>
      </div>

      <DashboardPanel title="Notification Channels" icon={BellRing}>
        <div className="space-y-1">
          {/* Header */}
          <div className="hidden sm:grid grid-cols-[1fr_repeat(4,80px)] gap-4 px-4 py-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
            <span>Notification Type</span>
            {CHANNEL_LABELS.map((ch) => (
              <span key={ch.key} className="text-center">
                {ch.label}
              </span>
            ))}
          </div>

          {/* Rows */}
          {preferences.map((pref) => (
            <div
              key={pref.id}
              className={cn(
                "grid grid-cols-1 sm:grid-cols-[1fr_repeat(4,80px)] gap-3 sm:gap-4 items-center",
                "rounded-xl px-4 py-4",
                "border border-[var(--border-subtle)] sm:border-transparent",
                "hover:bg-[var(--bg-surface-raised)]/50 transition-colors duration-200"
              )}
            >
              {/* Label + Description */}
              <div>
                <p className="text-sm font-medium text-[var(--text-primary)]">
                  {pref.label}
                </p>
                <p className="text-xs text-[var(--text-secondary)] mt-0.5">
                  {pref.description}
                </p>
              </div>

              {/* Channel toggles */}
              {CHANNEL_LABELS.map((ch) => (
                <div
                  key={ch.key}
                  className="flex items-center gap-2 sm:justify-center"
                >
                  <span className="text-xs text-[var(--text-secondary)] sm:hidden">
                    {ch.label}
                  </span>
                  <ToggleSwitch
                    checked={pref.channels[ch.key]}
                    onChange={() => toggleChannel(pref.id, ch.key)}
                  />
                </div>
              ))}
            </div>
          ))}
        </div>
      </DashboardPanel>

      {/* Save */}
      <div className="flex justify-end">
        <Button variant="primary" size="md">
          Save Preferences
        </Button>
      </div>
    </div>
  );
}
