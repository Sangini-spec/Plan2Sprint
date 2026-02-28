"use client";

import { useState, useEffect, useCallback } from "react";
import { MessageSquareText, Check, X, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { StatCard } from "@/components/dashboard/stat-card";
import { useAutoRefresh } from "@/lib/ws/context";
import { cachedFetch } from "@/lib/fetch-cache";

interface TeamStandupData {
  id: string;
  teamName: string;
  activated: boolean;
  activatedDate: string | null;
  reportsThisSprint: number;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export function StandupReplacementStatus() {
  const [teams, setTeams] = useState<TeamStandupData[]>([]);
  const [totalReports, setTotalReports] = useState(0);
  const [loading, setLoading] = useState(true);
  const refreshKey = useAutoRefresh(["sync_complete", "standup_generated"]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [teamRes, standupRes] = await Promise.all([
        cachedFetch("/api/dashboard/team"),
        cachedFetch("/api/standups"),
      ]);

      const memberList: { id: string; name: string }[] = [];
      if (teamRes.ok) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const data = teamRes.data as any;
        for (const m of data.team ?? []) {
          memberList.push({ id: m.id, name: m.name });
        }
      }

      let reportCount = 0;
      const teamStandups: TeamStandupData[] = [];

      if (standupRes.ok) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const data = standupRes.data as any;
        const reports = data.individualReports ?? [];
        reportCount = reports.length;

        // Map team members to their standup status
        const reportedMembers = new Set<string>();
        for (const r of reports) {
          reportedMembers.add(r.teamMemberId ?? r.teamMember);
        }

        for (const m of memberList) {
          const hasReport = reportedMembers.has(m.id) || reportedMembers.has(m.name);
          const memberReports = reports.filter(
            (r: { teamMemberId?: string; teamMember?: string }) =>
              r.teamMemberId === m.id || r.teamMember === m.name
          );
          teamStandups.push({
            id: m.id,
            teamName: m.name,
            activated: hasReport,
            activatedDate: hasReport ? new Date().toISOString() : null,
            reportsThisSprint: memberReports.length,
          });
        }

        // If no team members but we have reports, create entries from reports
        if (memberList.length === 0 && reports.length > 0) {
          const seen = new Set<string>();
          for (const r of reports) {
            const name = r.displayName ?? r.teamMember ?? "Unknown";
            if (!seen.has(name)) {
              seen.add(name);
              teamStandups.push({
                id: r.teamMemberId ?? name,
                teamName: name,
                activated: true,
                activatedDate: r.reportDate ?? new Date().toISOString(),
                reportsThisSprint: reports.filter(
                  (rr: { displayName?: string; teamMember?: string }) =>
                    (rr.displayName ?? rr.teamMember) === name
                ).length,
              });
            }
          }
        }
      }

      setTeams(teamStandups);
      setTotalReports(reportCount);
    } catch {
      setTeams([]);
      setTotalReports(0);
    }
    setLoading(false);
  }, []);

  useEffect(() => { fetchData(); }, [fetchData, refreshKey]);

  if (loading) {
    return (
      <DashboardPanel title="Standup Replacement" icon={MessageSquareText}>
        <div className="flex items-center justify-center py-8">
          <Loader2 size={20} className="animate-spin text-[var(--color-brand-secondary)]" />
        </div>
      </DashboardPanel>
    );
  }

  const activatedCount = teams.filter((t) => t.activated).length;

  return (
    <DashboardPanel title="Standup Replacement" icon={MessageSquareText}>
      {/* Summary stats */}
      <div className="grid grid-cols-2 gap-3 mb-6">
        <StatCard label="Members Reporting" value={activatedCount} />
        <StatCard label="Reports Generated" value={totalReports} />
      </div>

      {teams.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-6 gap-2">
          <MessageSquareText size={24} className="text-[var(--text-tertiary)]" />
          <p className="text-sm text-[var(--text-secondary)]">No standup data available</p>
          <p className="text-xs text-[var(--text-tertiary)]">
            Generate standups to see replacement status.
          </p>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {teams.map((team) => (
            <div
              key={team.id}
              className={cn(
                "rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] p-4",
                "transition-shadow duration-200 hover:shadow-md",
                !team.activated && "opacity-50"
              )}
            >
              <div className="flex items-center justify-between mb-2">
                <h3 className={cn("text-sm font-semibold", team.activated ? "text-[var(--text-primary)]" : "text-[var(--text-secondary)]")}>
                  {team.teamName}
                </h3>
                {team.activated ? (
                  <div className="flex h-5 w-5 items-center justify-center rounded-full bg-[var(--color-rag-green)]/15">
                    <Check className="h-3 w-3 text-[var(--color-rag-green)]" />
                  </div>
                ) : (
                  <div className="flex h-5 w-5 items-center justify-center rounded-full bg-[var(--border-subtle)]">
                    <X className="h-3 w-3 text-[var(--text-secondary)]" />
                  </div>
                )}
              </div>

              {team.activated && team.activatedDate ? (
                <div className="space-y-1">
                  <p className="text-xs text-[var(--text-secondary)]">
                    Active since {formatDate(team.activatedDate)}
                  </p>
                  <p className="text-xs text-[var(--text-secondary)]">
                    <span className="font-semibold text-[var(--text-primary)] tabular-nums">{team.reportsThisSprint}</span>{" "}
                    reports this sprint
                  </p>
                </div>
              ) : (
                <p className="text-xs text-[var(--text-secondary)]">Not yet activated</p>
              )}
            </div>
          ))}
        </div>
      )}
    </DashboardPanel>
  );
}
