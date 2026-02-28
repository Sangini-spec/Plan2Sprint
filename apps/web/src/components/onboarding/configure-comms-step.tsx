"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowRight,
  ArrowLeft,
  MessageSquare,
  Hash,
  Check,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button, Input } from "@/components/ui";

/* ------------------------------------------------------------------ */
/*  Platform definitions                                               */
/* ------------------------------------------------------------------ */

interface Platform {
  id: string;
  name: string;
  letter: string;
  letterColor: string;
  letterBg: string;
  description: string;
}

const PLATFORMS: Platform[] = [
  {
    id: "slack",
    name: "Slack",
    letter: "S",
    letterColor: "text-[#E01E5A]",
    letterBg: "bg-[#E01E5A]/10",
    description: "Send notifications and digests to Slack channels.",
  },
  {
    id: "teams",
    name: "Microsoft Teams",
    letter: "T",
    letterColor: "text-[#6264A7]",
    letterBg: "bg-[#6264A7]/10",
    description: "Post updates and alerts to Microsoft Teams channels.",
  },
];

/* ------------------------------------------------------------------ */
/*  Notification types                                                 */
/* ------------------------------------------------------------------ */

interface NotificationType {
  id: string;
  label: string;
}

const NOTIFICATION_TYPES: NotificationType[] = [
  { id: "standup", label: "Standup Digests" },
  { id: "health", label: "Sprint Health Alerts" },
  { id: "blocker", label: "Blocker Notifications" },
  { id: "retro", label: "Retro Reminders" },
];

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export function ConfigureCommsStep({
  onNext,
  onBack,
}: {
  onNext: () => void;
  onBack: () => void;
}) {
  const [selectedPlatform, setSelectedPlatform] = useState<string | null>(null);
  const [channelName, setChannelName] = useState("#sprint-updates");
  const [enabledNotifications, setEnabledNotifications] = useState<string[]>([
    "standup",
    "health",
    "blocker",
    "retro",
  ]);

  const toggleNotification = (id: string) => {
    setEnabledNotifications((prev) =>
      prev.includes(id) ? prev.filter((n) => n !== id) : [...prev, id]
    );
  };

  return (
    <div className="flex flex-col items-center text-center">
      {/* Header */}
      <div className="mb-2 flex h-12 w-12 items-center justify-center rounded-2xl bg-[var(--color-brand-secondary)]/10">
        <MessageSquare className="h-6 w-6 text-[var(--color-brand-secondary)]" />
      </div>

      <h2 className="mt-4 text-2xl font-bold text-[var(--text-primary)]">
        Configure Communication Channel
      </h2>
      <p className="mt-2 max-w-lg text-sm text-[var(--text-secondary)]">
        Set up Slack or Microsoft Teams to receive standup digests, alerts, and
        sprint notifications.
      </p>

      {/* Platform Cards */}
      <div className="mt-8 grid w-full max-w-lg grid-cols-2 gap-4">
        {PLATFORMS.map((platform) => {
          const isSelected = selectedPlatform === platform.id;

          return (
            <motion.button
              key={platform.id}
              type="button"
              whileHover={{ y: -2 }}
              whileTap={{ scale: 0.98 }}
              onClick={() => setSelectedPlatform(platform.id)}
              className={cn(
                "relative flex flex-col items-center gap-3 rounded-2xl border p-5 transition-all duration-200 cursor-pointer",
                "bg-[var(--bg-surface)] hover:bg-[var(--bg-surface-raised)]",
                isSelected
                  ? "border-[var(--color-brand-secondary)] shadow-lg shadow-[var(--color-brand-secondary)]/10"
                  : "border-[var(--border-subtle)]"
              )}
            >
              {isSelected && (
                <motion.div
                  layoutId="comms-selection"
                  className="absolute inset-0 rounded-2xl border-2 border-[var(--color-brand-secondary)] pointer-events-none"
                  transition={{ type: "spring", stiffness: 300, damping: 30 }}
                />
              )}

              <div
                className={cn(
                  "flex h-10 w-10 items-center justify-center rounded-xl text-lg font-bold",
                  platform.letterBg,
                  platform.letterColor
                )}
              >
                {platform.letter}
              </div>
              <p className="text-sm font-semibold text-[var(--text-primary)]">
                {platform.name}
              </p>
              <p className="text-xs text-[var(--text-secondary)]">
                {platform.description}
              </p>
            </motion.button>
          );
        })}
      </div>

      {/* Channel Configuration (visible once a platform is selected) */}
      <AnimatePresence>
        {selectedPlatform && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.3 }}
            className="mt-6 w-full max-w-lg overflow-hidden"
          >
            <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-6 text-left">
              {/* Channel name */}
              <label className="text-sm font-medium text-[var(--text-primary)]">
                Channel Name
              </label>
              <div className="relative mt-1.5">
                <Hash className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-secondary)]" />
                <Input
                  value={channelName.replace(/^#/, "")}
                  onChange={(e) => setChannelName(`#${e.target.value}`)}
                  className="pl-9"
                  placeholder="sprint-updates"
                />
              </div>

              {/* Notification types */}
              <p className="mt-5 text-sm font-medium text-[var(--text-primary)]">
                Notification Types
              </p>
              <div className="mt-2 space-y-2">
                {NOTIFICATION_TYPES.map((notif) => {
                  const isEnabled = enabledNotifications.includes(notif.id);
                  return (
                    <button
                      key={notif.id}
                      type="button"
                      onClick={() => toggleNotification(notif.id)}
                      className={cn(
                        "flex w-full items-center gap-3 rounded-xl border px-4 py-3 text-left transition-all duration-200 cursor-pointer",
                        isEnabled
                          ? "border-[var(--color-brand-secondary)]/40 bg-[var(--color-brand-secondary)]/5"
                          : "border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] hover:border-[var(--color-brand-secondary)]/20"
                      )}
                    >
                      <div
                        className={cn(
                          "flex h-5 w-5 shrink-0 items-center justify-center rounded-md border-2 transition-all duration-200",
                          isEnabled
                            ? "border-[var(--color-brand-secondary)] bg-[var(--color-brand-secondary)]"
                            : "border-[var(--border-subtle)]"
                        )}
                      >
                        {isEnabled && (
                          <Check className="h-3 w-3 text-white" />
                        )}
                      </div>
                      <span className="text-sm font-medium text-[var(--text-primary)]">
                        {notif.label}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Navigation */}
      <div className="mt-10 flex items-center gap-3">
        <Button variant="secondary" onClick={onBack}>
          <ArrowLeft className="h-4 w-4" />
          Back
        </Button>
        <Button
          disabled={!selectedPlatform || enabledNotifications.length === 0}
          onClick={onNext}
        >
          Continue
          <ArrowRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
