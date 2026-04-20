"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Loader2,
  AlertTriangle,
  MessageSquare,
  Construction,
  Hash,
  CheckCircle2,
  History,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button, Input } from "@/components/ui";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { MyNotificationInbox } from "@/components/dev/my-notification-inbox";
import { DeliveryChannelsSection } from "@/components/notifications/delivery-channels-section";
import { SlackMessageComposer } from "@/components/notifications/slack-message-composer";
import { TeamsMessageComposer } from "@/components/notifications/teams-message-composer";
import { PlatformTabs, usePlatformTab, type Platform } from "@/components/notifications/platform-tabs";
import { useSelectedProject } from "@/lib/project/context";
import { useAutoRefresh } from "@/lib/ws/context";

interface ProjectInfo {
  id: string;
  name: string;
  hasChannel: boolean;
  channelName?: string;
}

export default function NotificationsPage() {
  const [slackConnected, setSlackConnected] = useState(false);
  const [teamsConnected, setTeamsConnected] = useState(false);
  const { selectedProject } = useSelectedProject();

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch("/api/integrations/slack/status");
        if (res.ok) {
          const data = await res.json();
          setSlackConnected(data.connected === true);
        }
      } catch {}
      try {
        const res = await fetch("/api/integrations/teams/status");
        if (res.ok) {
          const data = await res.json();
          setTeamsConnected(data.connected === true);
        }
      } catch {}
    })();
  }, []);

  return (
    <div className="space-y-8">
      <MyNotificationInbox />
      <DeliveryChannelsSection />

      {(slackConnected || teamsConnected) && (
        <DevPlatformSections
          slackConnected={slackConnected}
          teamsConnected={teamsConnected}
          selectedProject={selectedProject}
        />
      )}
    </div>
  );
}

function DevPlatformSections({
  slackConnected,
  teamsConnected,
  selectedProject,
}: {
  slackConnected: boolean;
  teamsConnected: boolean;
  selectedProject: { internalId?: string; name: string } | null;
}) {
  const [platform, setPlatform] = usePlatformTab(slackConnected, teamsConnected);
  const [channelInfo, setChannelInfo] = useState<{ hasChannel: boolean; channelName?: string }>({ hasChannel: false });

  const base = platform === "slack" ? "/api/integrations/slack" : "/api/integrations/teams";
  const channelCreatedKey = useAutoRefresh(["channel_created"]);

  useEffect(() => {
    if (!selectedProject?.internalId) {
      setChannelInfo({ hasChannel: false });
      return;
    }
    (async () => {
      try {
        const res = await fetch(`${base}/project-channel?projectId=${selectedProject.internalId}`);
        if (res.ok) {
          const data = await res.json();
          setChannelInfo({ hasChannel: data.hasChannel, channelName: data.channelName });
        } else {
          setChannelInfo({ hasChannel: false });
        }
      } catch {
        setChannelInfo({ hasChannel: false });
      }
    })();
  }, [selectedProject?.internalId, base, channelCreatedKey]);

  const projectInfo: ProjectInfo | null = selectedProject ? {
    id: selectedProject.internalId || "",
    name: selectedProject.name,
    hasChannel: channelInfo.hasChannel,
    channelName: channelInfo.channelName,
  } : null;

  const platformConnected = platform === "slack" ? slackConnected : teamsConnected;
  const platformLabel = platform === "slack" ? "Slack" : "Microsoft Teams";

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h3 className="text-base font-semibold text-[var(--text-primary)]">
          Channel Communication
        </h3>
        <PlatformTabs
          value={platform}
          onChange={setPlatform}
          slackConnected={slackConnected}
          teamsConnected={teamsConnected}
        />
      </div>

      {!platformConnected && (
        <DashboardPanel title={`${platformLabel} not connected`} icon={Hash}>
          <p className="text-sm text-[var(--text-secondary)]">
            {platform === "teams"
              ? `Microsoft Teams is set up by your Product Owner. Once they connect Teams and create a project channel, you'll be able to post standups and flag blockers here.`
              : `Connect ${platformLabel} from Delivery Channels above to use quick actions.`}
          </p>
        </DashboardPanel>
      )}

      {platformConnected && projectInfo && (
        <DevQuickActions project={projectInfo} platform={platform} />
      )}

      {platformConnected && !projectInfo && (
        <DashboardPanel title={`${platformLabel} Quick Actions`} icon={MessageSquare}>
          <div className="flex flex-col items-center py-8 gap-2">
            <Hash size={20} className="text-[var(--text-tertiary)]" />
            <p className="text-sm text-[var(--text-secondary)]">Select a project to use quick actions</p>
          </div>
        </DashboardPanel>
      )}

      {platform === "slack" && platformConnected && <SlackMessageComposer />}
      {platform === "teams" && platformConnected && <TeamsMessageComposer />}
    </div>
  );
}


/* -------------------------------------------------------------------------- */
/*  DEVELOPER QUICK ACTIONS                                                    */
/* -------------------------------------------------------------------------- */

function DevQuickActions({ project, platform }: { project: ProjectInfo; platform: Platform }) {
  const base = platform === "slack" ? "/api/integrations/slack" : "/api/integrations/teams";
  const prefix = platform === "slack" ? "#" : "";
  const platformLabel = platform === "slack" ? "Slack" : "Microsoft Teams";
  const [blockerTicket, setBlockerTicket] = useState("");
  const [blockerDesc, setBlockerDesc] = useState("");
  const [sending, setSending] = useState<string | null>(null);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [historyBumpKey, setHistoryBumpKey] = useState(0);

  const hasChannel = project.hasChannel;

  const postToChannel = async (type: string, data: Record<string, string>) => {
    setSending(type);
    setResult(null);
    try {
      const res = await fetch(`${base}/post-to-channel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ projectId: project.id, type, data }),
      });
      const resp = await res.json();
      if (resp.ok) {
        setResult({ ok: true, message: `Sent to ${prefix}${resp.channelName}` });
        if (type === "blocker_to_channel") {
          setBlockerTicket(""); setBlockerDesc("");
        }
      } else {
        setResult({ ok: false, message: resp.message || "Failed to send" });
      }
    } catch {
      setResult({ ok: false, message: "Network error" });
    }
    setSending(null);
  };

  return (
    <DashboardPanel title={`${platformLabel} Quick Actions`} icon={MessageSquare}>
      {/* Project info */}
      <div className="flex items-center gap-2 mb-4 p-2 rounded-lg bg-[var(--bg-surface-raised)]">
        <Hash size={14} className="text-[var(--color-brand-secondary)]" />
        <span className="text-sm font-medium text-[var(--text-primary)]">{project.name}</span>
        {hasChannel ? (
          <span className="text-xs text-[var(--color-rag-green)]">{prefix}{project.channelName}</span>
        ) : (
          <span className="text-xs text-[var(--text-tertiary)]">No channel</span>
        )}
      </div>

      {/* No channel warning */}
      {!hasChannel && (
        <div className="p-4 rounded-lg bg-[var(--color-rag-amber)]/5 border border-[var(--color-rag-amber)]/20 mb-4">
          <div className="flex items-center gap-2 mb-1">
            <AlertTriangle size={14} className="text-[var(--color-rag-amber)]" />
            <p className="text-sm font-medium text-[var(--text-primary)]">
              No {platformLabel} channel for this project
            </p>
          </div>
          <p className="text-xs text-[var(--text-secondary)]">
            A {platformLabel} channel hasn&apos;t been created for {project.name} yet. Ask your PO to create one from the Channels page.
          </p>
        </div>
      )}

      <div className="space-y-6">
          {/* Update About Your Blockers */}
          <div className="p-4 rounded-lg border border-[var(--border-subtle)]">
            <div className="flex items-center gap-2 mb-3">
              <Construction size={16} className="text-[var(--color-rag-red)]" />
              <h4 className="text-sm font-medium text-[var(--text-primary)]">Update About Your Blockers</h4>
            </div>
            <div className="space-y-2">
              <Input
                value={blockerTicket}
                onChange={e => setBlockerTicket(e.target.value)}
                placeholder="Ticket reference (e.g., PROJ-123)"
                className="text-sm"
              />
              <Input
                value={blockerDesc}
                onChange={e => setBlockerDesc(e.target.value)}
                placeholder="Describe the blocker..."
                className="text-sm"
              />
              <button
                onClick={async () => {
                  await postToChannel("blocker_to_channel", {
                    ticket: blockerTicket,
                    description: blockerDesc,
                  });
                  setHistoryBumpKey(k => k + 1);
                }}
                disabled={!hasChannel || !blockerDesc || sending === "blocker_to_channel"}
                className={cn(
                  "w-full flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold text-white transition-all cursor-pointer",
                  "bg-[var(--color-brand-secondary)] hover:bg-[var(--color-brand-secondary)]/90",
                  "disabled:opacity-40 disabled:cursor-not-allowed"
                )}
              >
                {sending === "blocker_to_channel" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <AlertTriangle className="h-3.5 w-3.5" />
                )}
                Flag Blocker to {prefix}{project.channelName || "channel"}
              </button>
            </div>

            {/* Blocker History */}
            <MyBlockerHistory projectId={project.id} bumpKey={historyBumpKey} />
          </div>

        </div>

      {/* Result feedback */}
      {result && (
        <p className={cn("text-xs mt-3", result.ok ? "text-[var(--color-rag-green)]" : "text-[var(--color-rag-red)]")}>
          {result.ok ? "✓" : "✗"} {result.message}
        </p>
      )}
    </DashboardPanel>
  );
}

/* -------------------------------------------------------------------------- */
/*  MY BLOCKER HISTORY                                                         */
/*                                                                             */
/*  Lists the dev's recent blockers with a colored status tag.                 */
/*  Auto-refreshes when a PO clicks Escalate/Resolve in Slack/Teams (via the   */
/*  blocker_status_changed WebSocket event).                                   */
/* -------------------------------------------------------------------------- */

interface BlockerHistoryItem {
  id: string;
  ticket: string;
  description: string;
  status: "OPEN" | "ACKNOWLEDGED" | "ESCALATED" | "RESOLVED" | string;
  flaggedAt: string | null;
  resolvedAt: string | null;
}

function MyBlockerHistory({ projectId, bumpKey }: { projectId: string; bumpKey: number }) {
  const [items, setItems] = useState<BlockerHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);

  // Refresh when PO escalates/resolves in Slack/Teams (WS event)
  const wsKey = useAutoRefresh(["blocker_status_changed"]);

  const fetchHistory = useCallback(async () => {
    try {
      const res = await fetch(`/api/blockers/my?projectId=${encodeURIComponent(projectId)}&limit=10`);
      if (res.ok) {
        const data = await res.json();
        setItems(data.blockers || []);
      }
    } catch {
      // ignore
    }
    setLoading(false);
  }, [projectId]);

  useEffect(() => {
    if (projectId) fetchHistory();
  }, [projectId, bumpKey, wsKey, fetchHistory]);

  if (loading) return null;
  if (items.length === 0) {
    return (
      <p className="mt-4 text-xs text-[var(--text-tertiary)] italic">
        No blockers flagged yet for this project.
      </p>
    );
  }

  return (
    <div className="mt-5 space-y-2">
      <div className="flex items-center gap-1.5 mb-1">
        <History size={12} className="text-[var(--text-secondary)]" />
        <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
          Blocker History
        </span>
      </div>
      {items.map((b) => (
        <BlockerHistoryRow key={b.id} blocker={b} />
      ))}
    </div>
  );
}

function BlockerHistoryRow({ blocker }: { blocker: BlockerHistoryItem }) {
  // Map status → display. OPEN/ACKNOWLEDGED both count as "Active" to the dev.
  const tag =
    blocker.status === "ESCALATED"
      ? { label: "Escalated", color: "var(--color-rag-red)", bg: "var(--color-rag-red)" }
      : blocker.status === "RESOLVED"
      ? { label: "Resolved", color: "var(--color-rag-green)", bg: "var(--color-rag-green)" }
      : { label: "Active", color: "var(--color-brand-secondary)", bg: "var(--color-brand-secondary)" };

  const flagged = blocker.flaggedAt
    ? new Date(blocker.flaggedAt).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
      })
    : "";

  return (
    <div className="flex items-start gap-3 p-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)]">
      <div className="flex-1 min-w-0">
        {blocker.ticket && (
          <span className="block text-[11px] font-mono font-semibold text-[var(--text-primary)] mb-1">
            {blocker.ticket}
          </span>
        )}
        <p className="text-xs text-[var(--text-secondary)] leading-snug line-clamp-2">
          {blocker.description}
        </p>
      </div>
      <div className="shrink-0 flex items-center gap-2">
        {flagged && (
          <span className="text-[10px] text-[var(--text-tertiary)]">{flagged}</span>
        )}
        <span
          className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider"
          style={{
            color: tag.color,
            backgroundColor: `color-mix(in srgb, ${tag.bg} 15%, transparent)`,
          }}
        >
          {tag.label}
        </span>
      </div>
    </div>
  );
}
