"use client";

import { useState } from "react";
import { ArrowLeft, Clock, Check, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button, Select } from "@/components/ui";

/* ------------------------------------------------------------------ */
/*  Options                                                            */
/* ------------------------------------------------------------------ */

const TIME_SLOTS = [
  "07:00",
  "07:30",
  "08:00",
  "08:30",
  "09:00",
  "09:30",
  "10:00",
  "10:30",
  "11:00",
  "11:30",
  "12:00",
];

const TIMEZONES = [
  { value: "UTC", label: "UTC" },
  { value: "US/Eastern", label: "US / Eastern" },
  { value: "US/Pacific", label: "US / Pacific" },
  { value: "Europe/London", label: "Europe / London" },
  { value: "Asia/Tokyo", label: "Asia / Tokyo" },
];

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export function SetStandupTimeStep({
  onFinish,
  onBack,
}: {
  onFinish: () => void;
  onBack: () => void;
}) {
  const [time, setTime] = useState("09:00");
  const [timezone, setTimezone] = useState("UTC");
  const [weekdaysOnly, setWeekdaysOnly] = useState(true);

  return (
    <div className="flex flex-col items-center text-center">
      {/* Header */}
      <div className="mb-2 flex h-12 w-12 items-center justify-center rounded-2xl bg-[var(--color-brand-secondary)]/10">
        <Clock className="h-6 w-6 text-[var(--color-brand-secondary)]" />
      </div>

      <h2 className="mt-4 text-2xl font-bold text-[var(--text-primary)]">
        Set Your Standup Schedule
      </h2>
      <p className="mt-2 max-w-lg text-sm text-[var(--text-secondary)]">
        Configure when Plan2Sprint generates daily standup reports for your team.
      </p>

      {/* Form */}
      <div className="mt-8 w-full max-w-md rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-6 text-left">
        {/* Time picker */}
        <div>
          <label className="text-sm font-medium text-[var(--text-primary)]">
            Standup Time
          </label>
          <div className="relative mt-1.5">
            <Clock className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-secondary)] pointer-events-none z-10" />
            <Select
              value={time}
              onChange={(e) => setTime(e.target.value)}
              className="pl-9"
            >
              {TIME_SLOTS.map((slot) => (
                <option key={slot} value={slot}>
                  {slot}
                </option>
              ))}
            </Select>
          </div>
        </div>

        {/* Timezone */}
        <div className="mt-5">
          <label className="text-sm font-medium text-[var(--text-primary)]">
            Timezone
          </label>
          <Select
            value={timezone}
            onChange={(e) => setTimezone(e.target.value)}
            className="mt-1.5"
          >
            {TIMEZONES.map((tz) => (
              <option key={tz.value} value={tz.value}>
                {tz.label}
              </option>
            ))}
          </Select>
        </div>

        {/* Weekdays only */}
        <div className="mt-5">
          <button
            type="button"
            onClick={() => setWeekdaysOnly((v) => !v)}
            className={cn(
              "flex w-full items-center gap-3 rounded-xl border px-4 py-3 text-left transition-all duration-200 cursor-pointer",
              weekdaysOnly
                ? "border-[var(--color-brand-secondary)]/40 bg-[var(--color-brand-secondary)]/5"
                : "border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] hover:border-[var(--color-brand-secondary)]/20"
            )}
          >
            <div
              className={cn(
                "flex h-5 w-5 shrink-0 items-center justify-center rounded-md border-2 transition-all duration-200",
                weekdaysOnly
                  ? "border-[var(--color-brand-secondary)] bg-[var(--color-brand-secondary)]"
                  : "border-[var(--border-subtle)]"
              )}
            >
              {weekdaysOnly && <Check className="h-3 w-3 text-white" />}
            </div>
            <span className="text-sm font-medium text-[var(--text-primary)]">
              Generate reports on weekdays only
            </span>
          </button>
        </div>
      </div>

      {/* Navigation */}
      <div className="mt-10 flex items-center gap-3">
        <Button variant="secondary" onClick={onBack}>
          <ArrowLeft className="h-4 w-4" />
          Back
        </Button>
        <Button onClick={onFinish}>
          <Sparkles className="h-4 w-4" />
          Finish Setup
        </Button>
      </div>
    </div>
  );
}
