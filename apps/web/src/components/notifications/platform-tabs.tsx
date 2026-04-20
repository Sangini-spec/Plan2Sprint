"use client";

import { useState, useEffect } from "react";
import { cn } from "@/lib/utils";
import { SlackLogo, TeamsLogo } from "./platform-logos";

export type Platform = "slack" | "teams";

const STORAGE_KEY = "plan2sprint_channels_platform";

export function usePlatformTab(
  slackConnected: boolean,
  teamsConnected: boolean,
): [Platform, (p: Platform) => void] {
  const [platform, setPlatformState] = useState<Platform>("slack");
  const [initialized, setInitialized] = useState(false);

  // Compute smart default after connection status loads
  useEffect(() => {
    if (initialized) return;
    if (!slackConnected && !teamsConnected) return; // wait for status

    let def: Platform = "slack";
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored === "slack" || stored === "teams") {
        def = stored as Platform;
      } else if (slackConnected) {
        def = "slack";
      } else if (teamsConnected) {
        def = "teams";
      }
    } catch {
      def = slackConnected ? "slack" : teamsConnected ? "teams" : "slack";
    }
    setPlatformState(def);
    setInitialized(true);
  }, [slackConnected, teamsConnected, initialized]);

  const setPlatform = (p: Platform) => {
    setPlatformState(p);
    try {
      localStorage.setItem(STORAGE_KEY, p);
    } catch {
      // ignore
    }
  };

  return [platform, setPlatform];
}

interface PlatformTabsProps {
  value: Platform;
  onChange: (p: Platform) => void;
  slackConnected: boolean;
  teamsConnected: boolean;
  className?: string;
}

export function PlatformTabs({
  value,
  onChange,
  slackConnected,
  teamsConnected,
  className,
}: PlatformTabsProps) {
  const tabs: { id: Platform; label: string; connected: boolean; Logo: typeof SlackLogo }[] = [
    { id: "slack", label: "Slack", connected: slackConnected, Logo: SlackLogo },
    { id: "teams", label: "Microsoft Teams", connected: teamsConnected, Logo: TeamsLogo },
  ];

  return (
    <div
      className={cn(
        "inline-flex items-center gap-1 p-1 rounded-xl bg-[var(--bg-surface-raised)] border border-[var(--border-subtle)]",
        className,
      )}
    >
      {tabs.map((tab) => {
        const active = value === tab.id;
        return (
          <button
            key={tab.id}
            onClick={() => onChange(tab.id)}
            className={cn(
              "relative flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all cursor-pointer",
              active
                ? "bg-[var(--bg-surface)] text-[var(--text-primary)] shadow-sm"
                : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
            )}
          >
            <tab.Logo className="h-4 w-4" />
            {tab.label}
            <span
              className={cn(
                "ml-1 h-1.5 w-1.5 rounded-full",
                tab.connected ? "bg-[var(--color-rag-green)]" : "bg-[var(--text-tertiary)]/40",
              )}
            />
          </button>
        );
      })}
    </div>
  );
}
