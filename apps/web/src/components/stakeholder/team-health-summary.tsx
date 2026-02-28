"use client";

import { useState, useEffect, useCallback } from "react";
import { HeartPulse, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { RagIndicator } from "@/components/dashboard/rag-indicator";
import type { HealthSeverity } from "@/lib/types/models";
import { useAutoRefresh } from "@/lib/ws/context";
import { cachedFetch } from "@/lib/fetch-cache";

interface TeamHealthData {
  id: string;
  teamName: string;
  health: HealthSeverity;
  tooltip: string;
}

const borderColors: Record<HealthSeverity, string> = {
  GREEN: "border-l-[var(--color-rag-green)]",
  AMBER: "border-l-[var(--color-rag-amber)]",
  RED: "border-l-[var(--color-rag-red)]",
};

function mapSeverity(raw: string): HealthSeverity {
  const upper = raw.toUpperCase();
  if (upper === "HIGH" || upper === "RED" || upper === "CRITICAL") return "RED";
  if (upper === "MEDIUM" || upper === "AMBER" || upper === "WARNING") return "AMBER";
  return "GREEN";
}

export function TeamHealthSummary() {
  const [teams, setTeams] = useState<TeamHealthData[]>([]);
  const [loading, setLoading] = useState(true);
  const refreshKey = useAutoRefresh(["sync_complete", "health_evaluated"]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [healthRes, teamRes] = await Promise.all([
        cachedFetch("/api/team-health"),
        cachedFetch("/api/dashboard/team"),
      ]);

      // Get team members
      const memberMap: Record<string, string> = {};
      if (teamRes.ok) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const data = teamRes.data as any;
        for (const m of data.team ?? []) {
          memberMap[m.id] = m.name;
        }
      }

      // Get health signals and group by member
      if (healthRes.ok) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const data = healthRes.data as any;
        const signals = data.signals ?? [];

        // Group signals by member to create team health cards
        const memberHealth: Record<string, { worst: HealthSeverity; messages: string[] }> = {};
        for (const sig of signals) {
          const memberId = sig.memberId ?? sig.member ?? "unknown";
          const sev = mapSeverity(sig.severity);
          if (!memberHealth[memberId]) {
            memberHealth[memberId] = { worst: "GREEN", messages: [] };
          }
          // Track worst severity
          if (sev === "RED") memberHealth[memberId].worst = "RED";
          else if (sev === "AMBER" && memberHealth[memberId].worst !== "RED") memberHealth[memberId].worst = "AMBER";
          memberHealth[memberId].messages.push(sig.message);
        }

        // Also include team members with no signals (they are GREEN)
        for (const [id, name] of Object.entries(memberMap)) {
          if (!memberHealth[id] && !memberHealth[name]) {
            memberHealth[id] = { worst: "GREEN", messages: ["No health signals"] };
          }
        }

        const teamList: TeamHealthData[] = Object.entries(memberHealth).map(([key, val], idx) => ({
          id: `th-${idx}`,
          teamName: memberMap[key] ?? key,
          health: val.worst,
          tooltip: val.messages.slice(0, 2).join(". ") || "Healthy",
        }));

        setTeams(teamList);
      } else {
        setTeams([]);
      }
    } catch {
      setTeams([]);
    }
    setLoading(false);
  }, []);

  useEffect(() => { fetchData(); }, [fetchData, refreshKey]);

  if (loading) {
    return (
      <DashboardPanel title="Team Health" icon={HeartPulse}>
        <div className="flex items-center justify-center py-8">
          <Loader2 size={20} className="animate-spin text-[var(--color-brand-secondary)]" />
        </div>
      </DashboardPanel>
    );
  }

  if (teams.length === 0) {
    return (
      <DashboardPanel title="Team Health" icon={HeartPulse}>
        <div className="flex flex-col items-center justify-center py-8 gap-2">
          <HeartPulse size={24} className="text-[var(--text-tertiary)]" />
          <p className="text-sm text-[var(--text-secondary)]">No team health data available</p>
          <p className="text-xs text-[var(--text-tertiary)]">
            Health signals will appear after syncing and evaluating team data.
          </p>
        </div>
      </DashboardPanel>
    );
  }

  return (
    <DashboardPanel title="Team Health" icon={HeartPulse}>
      <div className="grid gap-3 sm:grid-cols-2">
        {teams.map((team) => (
          <div
            key={team.id}
            className={cn(
              "rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] p-4",
              "border-l-4",
              borderColors[team.health],
              "transition-shadow duration-200 hover:shadow-md"
            )}
          >
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-[var(--text-primary)]">{team.teamName}</h3>
              <RagIndicator severity={team.health} size="sm" />
            </div>
            <p className="mt-1.5 text-xs text-[var(--text-secondary)]">{team.tooltip}</p>
          </div>
        ))}
      </div>
    </DashboardPanel>
  );
}
