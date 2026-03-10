"use client";

import { useState, useEffect, useCallback } from "react";
import { Users, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { RagIndicator } from "@/components/dashboard/rag-indicator";
import { Avatar, Badge, Progress } from "@/components/ui";
import type { HealthSeverity } from "@/lib/types/models";
import { useAutoRefresh } from "@/lib/ws/context";
import { useSelectedProject } from "@/lib/project/context";
import { cachedFetch } from "@/lib/fetch-cache";

interface TeamMemberData {
  id: string;
  name: string;
  email: string;
  avatarUrl: string | null;
  capacity: number;
  totalAssigned: number;
  inProgress: number;
  done: number;
  totalStoryPoints: number;
  skillTags: string[];
}

const severityProgressColor: Record<HealthSeverity, "GREEN" | "AMBER" | "RED"> = {
  GREEN: "GREEN",
  AMBER: "AMBER",
  RED: "RED",
};

const statusBadgeVariant: Record<HealthSeverity, "rag-green" | "rag-amber" | "rag-red"> = {
  GREEN: "rag-green",
  AMBER: "rag-amber",
  RED: "rag-red",
};

export function DeveloperProgressBoard() {
  const { selectedProject } = useSelectedProject();
  const [team, setTeam] = useState<TeamMemberData[]>([]);
  const [loading, setLoading] = useState(true);
  const refreshKey = useAutoRefresh(["sync_complete", "writeback_success", "github_activity"]);

  const projectId = selectedProject?.internalId;

  const fetchTeam = useCallback(async () => {
    setLoading(true);
    try {
      const q = projectId ? `?projectId=${projectId}` : "";
      const res = await cachedFetch<{ team?: TeamMemberData[] }>(`/api/dashboard/team${q}`);
      if (res.ok) {
        setTeam(res.data?.team ?? []);
      } else {
        setTeam([]);
      }
    } catch {
      setTeam([]);
    }
    setLoading(false);
  }, [projectId]);

  useEffect(() => { fetchTeam(); }, [fetchTeam, refreshKey]);

  if (loading) {
    return (
      <DashboardPanel title="Developer Progress" icon={Users}>
        <div className="flex items-center justify-center py-8">
          <Loader2 size={20} className="animate-spin text-[var(--color-brand-secondary)]" />
        </div>
      </DashboardPanel>
    );
  }

  if (team.length === 0) {
    return (
      <DashboardPanel title="Developer Progress" icon={Users}>
        <div className="flex flex-col items-center justify-center py-8 gap-2">
          <Users size={24} className="text-[var(--text-tertiary)]" />
          <p className="text-sm text-[var(--text-secondary)]">No team members found</p>
          <p className="text-xs text-[var(--text-tertiary)]">
            Sync your project data to see developer progress.
          </p>
        </div>
      </DashboardPanel>
    );
  }

  return (
    <DashboardPanel title="Developer Progress" icon={Users}>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {team.map((member) => {
          const assignedSP = member.totalStoryPoints;
          const doneSP = Math.round(assignedSP * (member.done / Math.max(member.totalAssigned, 1)));
          const progressPct = assignedSP > 0 ? Math.round((doneSP / assignedSP) * 100) : 0;

          const pacing: HealthSeverity = progressPct >= 70 ? "GREEN" : progressPct >= 40 ? "AMBER" : "RED";

          return (
            <div key={member.id} className={cn(
              "rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] p-4",
              "transition-all duration-200 hover:border-[var(--color-brand-secondary)]/40",
              "hover:shadow-md hover:shadow-black/5 dark:hover:shadow-black/20 cursor-pointer"
            )}>
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2.5 min-w-0">
                  <Avatar src={member.avatarUrl ?? undefined} fallback={member.name} size="md" />
                  <span className="text-sm font-semibold text-[var(--text-primary)] truncate">{member.name}</span>
                </div>
                <Badge variant={statusBadgeVariant[pacing]}>
                  <RagIndicator severity={pacing} size="sm" />
                </Badge>
              </div>

              <div className="flex items-center justify-between mb-2">
                <span className="text-xs text-[var(--text-secondary)]">{doneSP} / {assignedSP} SP</span>
                <span className="text-xs font-semibold tabular-nums text-[var(--text-primary)]">{progressPct}%</span>
              </div>

              <Progress value={progressPct} severity={severityProgressColor[pacing]} size="sm" className="mb-3" />

              <div className="flex items-center gap-4">
                <div className="flex items-center gap-1.5">
                  <span className="text-xs text-[var(--text-secondary)]">
                    {member.totalAssigned} assigned &bull; {member.done} done
                  </span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="text-xs text-[var(--text-secondary)]">
                    {member.inProgress} in progress
                  </span>
                </div>
              </div>

              {member.skillTags.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-2">
                  {member.skillTags.slice(0, 3).map((tag) => (
                    <span key={tag} className="rounded-md bg-[var(--bg-surface)] border border-[var(--border-subtle)] px-1.5 py-0.5 text-[10px] text-[var(--text-tertiary)]">
                      {tag}
                    </span>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </DashboardPanel>
  );
}
