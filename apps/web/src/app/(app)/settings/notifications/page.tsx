"use client";

import { useState, useEffect, useCallback } from "react";
import { BellRing, CalendarClock, Loader2, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Button } from "@/components/ui";
import { useAuth } from "@/lib/auth/context";

// ─────────────────────────────────────────────────────────────────────
//  Notification Center - Settings → Notifications
//
//  Two sections:
//    1. Digest Schedule (NEW)  - controls WHEN morning / evening
//       digest notifications fire for this user. Backed by
//       /api/notifications/schedule.
//    2. Notification Channels  - controls WHERE each notification type
//       gets routed (Slack / Teams / Email / In-App). Existing UI;
//       client-side state only for now (not yet wired to a backend).
// ─────────────────────────────────────────────────────────────────────

type Channel = "slack" | "teams" | "email" | "inApp";

interface NotificationPreference {
  id: string;
  label: string;
  description: string;
  channels: Record<Channel, boolean>;
  /** If set, only show this preference for these roles */
  roles?: string[];
}

const INITIAL_PREFERENCES: NotificationPreference[] = [
  {
    id: "weekly-report",
    label: "Weekly Project Report",
    description: "Automated weekly summary of project progress, delivery metrics, and epic status - delivered every Monday",
    channels: { slack: false, teams: false, email: true, inApp: true },
    roles: ["stakeholder", "owner", "admin", "product_owner", "engineering_manager"],
  },
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

// ─────────────────────────────────────────────────────────────────────
//  Digest schedule types - match the API's camelCase contract.
// ─────────────────────────────────────────────────────────────────────

type ScheduleMode = "every_weekday" | "alternate_days" | "weekly" | "custom";

interface DigestSchedule {
  scheduleMode: ScheduleMode;
  selectedDays: number[]; // 0=Mon..6=Sun
  sendMorning: boolean;
  sendEvening: boolean;
  /** Server-side flag: false for roles that don't receive the digest
   *  (developer, stakeholder). Used to render a read-only state. */
  applies: boolean;
}

const DEFAULT_SCHEDULE: DigestSchedule = {
  scheduleMode: "every_weekday",
  selectedDays: [],
  sendMorning: true,
  sendEvening: true,
  applies: true,
};

// Roles allowed to see the digest schedule section. Matches the
// audience set the backend enforces (see notifications.py).
const DIGEST_AUDIENCE_ROLES = new Set([
  "product_owner",
  "owner",
  "admin",
  "engineering_manager",
]);

const DAY_LABELS: { value: number; short: string; long: string }[] = [
  { value: 0, short: "Mon", long: "Monday" },
  { value: 1, short: "Tue", long: "Tuesday" },
  { value: 2, short: "Wed", long: "Wednesday" },
  { value: 3, short: "Thu", long: "Thursday" },
  { value: 4, short: "Fri", long: "Friday" },
  { value: 5, short: "Sat", long: "Saturday" },
  { value: 6, short: "Sun", long: "Sunday" },
];

const SCHEDULE_MODE_OPTIONS: {
  value: ScheduleMode;
  label: string;
  description: string;
}[] = [
  {
    value: "every_weekday",
    label: "Every weekday",
    description: "Monday through Friday (current default).",
  },
  {
    value: "alternate_days",
    label: "Alternate days",
    description: "Mon, Wed, Fri only.",
  },
  {
    value: "weekly",
    label: "Once a week",
    description: "Pick one day below.",
  },
  {
    value: "custom",
    label: "Custom",
    description: "Pick any combination of days below.",
  },
];

function ToggleSwitch({
  checked,
  onChange,
  disabled = false,
}: {
  checked: boolean;
  onChange: (val: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => !disabled && onChange(!checked)}
      disabled={disabled}
      className={cn(
        "relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent",
        "transition-colors duration-200 ease-in-out",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-brand-secondary)] focus-visible:ring-offset-2",
        disabled && "opacity-40 cursor-not-allowed",
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

// ─────────────────────────────────────────────────────────────────────
//  DigestScheduleSection
//
//  The new section. Renders four mutually-exclusive cards for mode
//  selection, a day-of-week picker (only enabled for weekly/custom
//  modes), two time-slot toggles, and a Save button. State is local
//  until Save fires the PATCH.
// ─────────────────────────────────────────────────────────────────────

function DigestScheduleSection({ role }: { role: string }) {
  const [schedule, setSchedule] = useState<DigestSchedule>(DEFAULT_SCHEDULE);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchSchedule = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/notifications/schedule");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as DigestSchedule;
      setSchedule({
        scheduleMode: data.scheduleMode ?? "every_weekday",
        selectedDays: data.selectedDays ?? [],
        sendMorning: data.sendMorning ?? true,
        sendEvening: data.sendEvening ?? true,
        applies: data.applies ?? true,
      });
    } catch (e: any) {
      setError(e?.message || "Failed to load schedule");
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchSchedule();
  }, [fetchSchedule]);

  // Roles outside the audience set get a read-only "not applicable"
  // pane. Backend enforces the same gate; this just avoids showing a
  // misleading save form to people whose changes would be rejected.
  if (!DIGEST_AUDIENCE_ROLES.has(role.toLowerCase())) {
    return (
      <DashboardPanel title="Digest Schedule" icon={CalendarClock}>
        <p className="text-sm text-[var(--text-secondary)]">
          The morning / evening digest is sent to product owners, owners, admins,
          and engineering managers. Your role doesn&apos;t receive it, so there&apos;s
          nothing to configure here.
        </p>
      </DashboardPanel>
    );
  }

  if (loading) {
    return (
      <DashboardPanel title="Digest Schedule" icon={CalendarClock}>
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-5 w-5 animate-spin text-[var(--text-secondary)]" />
        </div>
      </DashboardPanel>
    );
  }

  const dayPickerEnabled =
    schedule.scheduleMode === "weekly" || schedule.scheduleMode === "custom";
  const weeklyMode = schedule.scheduleMode === "weekly";
  const bothSlotsOff = !schedule.sendMorning && !schedule.sendEvening;

  function setMode(mode: ScheduleMode) {
    setSchedule((s) => {
      // When switching modes, sensibly reset selectedDays:
      //   weekly → keep first day or default Monday
      //   custom → keep current set
      //   every_weekday / alternate_days → clear (not used)
      if (mode === "weekly") {
        const first = s.selectedDays.length > 0 ? [s.selectedDays[0]] : [0];
        return { ...s, scheduleMode: mode, selectedDays: first };
      }
      if (mode === "custom") {
        return { ...s, scheduleMode: mode };
      }
      return { ...s, scheduleMode: mode, selectedDays: [] };
    });
  }

  function toggleDay(d: number) {
    setSchedule((s) => {
      if (!dayPickerEnabled) return s;
      if (weeklyMode) {
        // Only one day in weekly mode - clicking another picks it.
        return { ...s, selectedDays: [d] };
      }
      // Custom mode: toggle multi-select.
      const has = s.selectedDays.includes(d);
      const next = has
        ? s.selectedDays.filter((x) => x !== d)
        : [...s.selectedDays, d].sort((a, b) => a - b);
      return { ...s, selectedDays: next };
    });
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const res = await fetch("/api/notifications/schedule", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scheduleMode: schedule.scheduleMode,
          selectedDays: schedule.selectedDays,
          sendMorning: schedule.sendMorning,
          sendEvening: schedule.sendEvening,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body?.detail || `HTTP ${res.status}`);
      }
      setSavedAt(Date.now());
      // Auto-clear the saved indicator after 3s
      setTimeout(() => setSavedAt(null), 3000);
    } catch (e: any) {
      setError(e?.message || "Failed to save");
    }
    setSaving(false);
  }

  return (
    <DashboardPanel title="Digest Schedule" icon={CalendarClock}>
      <div className="space-y-5">
        <p className="text-sm text-[var(--text-secondary)]">
          Choose when the morning (9 AM) and evening (5 PM) project digest
          notifications fire for you. Other notifications - blockers, sprint
          alerts, plan ready - always fire instantly regardless of this
          schedule.
        </p>

        {/* Mode cards (radio behaviour) */}
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] mb-2">
            How often
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {SCHEDULE_MODE_OPTIONS.map((opt) => {
              const selected = schedule.scheduleMode === opt.value;
              return (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setMode(opt.value)}
                  className={cn(
                    "text-left rounded-xl border px-4 py-3 transition-all cursor-pointer",
                    selected
                      ? "border-[var(--color-brand-secondary)] bg-[var(--color-brand-secondary)]/5 ring-1 ring-[var(--color-brand-secondary)]"
                      : "border-[var(--border-subtle)] hover:bg-[var(--bg-surface-raised)]/50"
                  )}
                >
                  <div className="flex items-start gap-2">
                    <div
                      className={cn(
                        "mt-0.5 h-4 w-4 rounded-full border-2 shrink-0",
                        selected
                          ? "border-[var(--color-brand-secondary)] bg-[var(--color-brand-secondary)]"
                          : "border-[var(--border-subtle)]"
                      )}
                    />
                    <div>
                      <p className="text-sm font-medium text-[var(--text-primary)]">
                        {opt.label}
                      </p>
                      <p className="text-xs text-[var(--text-secondary)] mt-0.5">
                        {opt.description}
                      </p>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Day-of-week picker (only meaningful for weekly + custom) */}
        <div>
          <p
            className={cn(
              "text-xs font-semibold uppercase tracking-wider mb-2 transition-colors",
              dayPickerEnabled
                ? "text-[var(--text-secondary)]"
                : "text-[var(--text-tertiary)]"
            )}
          >
            {weeklyMode ? "Pick a day" : "Pick days"}
            {!dayPickerEnabled && " (only for Once a week / Custom)"}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {DAY_LABELS.map((d) => {
              const selected = schedule.selectedDays.includes(d.value);
              return (
                <button
                  key={d.value}
                  type="button"
                  onClick={() => toggleDay(d.value)}
                  disabled={!dayPickerEnabled}
                  className={cn(
                    "rounded-lg border px-3 py-1.5 text-xs font-medium transition-all",
                    !dayPickerEnabled && "opacity-40 cursor-not-allowed",
                    dayPickerEnabled && "cursor-pointer",
                    selected
                      ? "border-[var(--color-brand-secondary)] bg-[var(--color-brand-secondary)] text-white"
                      : "border-[var(--border-subtle)] text-[var(--text-primary)] hover:bg-[var(--bg-surface-raised)]/50"
                  )}
                >
                  {d.short}
                </button>
              );
            })}
          </div>
        </div>

        {/* Time-slot toggles */}
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] mb-2">
            Which times
          </p>
          <div className="space-y-2">
            <div className="flex items-center justify-between rounded-xl border border-[var(--border-subtle)] px-4 py-3">
              <div>
                <p className="text-sm font-medium text-[var(--text-primary)]">
                  Morning digest
                </p>
                <p className="text-xs text-[var(--text-secondary)]">
                  9:00 AM IST - start-of-day status across your projects
                </p>
              </div>
              <ToggleSwitch
                checked={schedule.sendMorning}
                onChange={(v) =>
                  setSchedule((s) => ({ ...s, sendMorning: v }))
                }
              />
            </div>
            <div className="flex items-center justify-between rounded-xl border border-[var(--border-subtle)] px-4 py-3">
              <div>
                <p className="text-sm font-medium text-[var(--text-primary)]">
                  Evening summary
                </p>
                <p className="text-xs text-[var(--text-secondary)]">
                  5:00 PM IST - end-of-day completion + flags
                </p>
              </div>
              <ToggleSwitch
                checked={schedule.sendEvening}
                onChange={(v) =>
                  setSchedule((s) => ({ ...s, sendEvening: v }))
                }
              />
            </div>
          </div>
          {bothSlotsOff && (
            <p className="mt-2 text-xs text-[var(--color-rag-amber)]">
              Both slots are off - you&apos;ll receive no digests at all. Event
              alerts (blockers, plan-ready, sprint health) still fire normally.
            </p>
          )}
        </div>

        {error && (
          <div className="rounded-lg border border-[var(--color-rag-red)]/30 bg-[var(--color-rag-red)]/10 px-4 py-2 text-sm text-[var(--color-rag-red)]">
            {error}
          </div>
        )}

        <div className="flex items-center justify-end gap-3">
          {savedAt && (
            <span className="flex items-center gap-1.5 text-sm text-[var(--color-rag-green)]">
              <CheckCircle2 size={14} />
              Saved
            </span>
          )}
          <Button
            variant="primary"
            size="md"
            disabled={saving}
            onClick={save}
          >
            {saving ? "Saving…" : "Save schedule"}
          </Button>
        </div>
      </div>
    </DashboardPanel>
  );
}

// ─────────────────────────────────────────────────────────────────────
//  NotificationsSettingsPage
// ─────────────────────────────────────────────────────────────────────

export default function NotificationsSettingsPage() {
  const { role } = useAuth();
  const [preferences, setPreferences] = useState<NotificationPreference[]>(
    INITIAL_PREFERENCES
  );

  const visiblePreferences = preferences.filter(
    (p) => !p.roles || p.roles.includes(role)
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
          Choose when notifications fire and how they reach you.
        </p>
      </div>

      {/* Schedule control (NEW - backed by /api/notifications/schedule) */}
      <DigestScheduleSection role={role} />

      {/* Existing channel-routing UI. Note: still client-side state only;
          wiring this to a backend is a separate piece of work. */}
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
          {visiblePreferences.map((pref) => (
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
    </div>
  );
}
