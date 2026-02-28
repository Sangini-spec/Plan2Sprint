"use client";

import { useState } from "react";
import {
  Link2,
  Github,
  RefreshCw,
  Unplug,
  Plus,
  Clock,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Button, Badge } from "@/components/ui";
import { useIntegrations } from "@/lib/integrations/context";
import { ConnectionStatusBadge } from "@/components/integrations/connection-status";
import type { ToolType, ConnectionInfo, ConnectionStatus } from "@/lib/integrations/types";

// ---------------------------------------------------------------------------
// Tool metadata (icons, colors, descriptions)
// ---------------------------------------------------------------------------

const TOOL_META: Record<
  ToolType,
  {
    name: string;
    description: string;
    iconBg: string;
    iconColor: string;
    icon: React.ReactNode;
  }
> = {
  jira: {
    name: "Jira",
    description: "Sync sprints, issues, and team data",
    iconBg: "bg-[#0052CC]/10",
    iconColor: "text-[#0052CC]",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
        <path d="M11.53 2c0 4.97 3.93 9 8.47 9-.27 4.97-4.39 9-9.47 9C5.48 20 1 15.52 1 10.5S5.48 1 10.53 1c.34 0 .67.03 1 .07V2z" fill="#0052CC" />
        <path d="M11.53 2c0 4.97 3.93 9 8.47 9 .28 0 .56-.01.83-.04C20.53 6.51 16.53 2.58 11.53 2z" fill="#2684FF" />
      </svg>
    ),
  },
  ado: {
    name: "Azure DevOps",
    description: "Sync iterations, work items, and boards",
    iconBg: "bg-[#0078D4]/10",
    iconColor: "text-[#0078D4]",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
        <path d="M22 4v16l-6 2V6l-8-2v14l-6 2V4l12 3 8-3z" fill="#0078D4" />
      </svg>
    ),
  },
  github: {
    name: "GitHub",
    description: "Monitor repos, PRs, commits, and CI (read-only)",
    iconBg: "bg-[var(--text-primary)]/10",
    iconColor: "text-[var(--text-primary)]",
    icon: <Github size={18} />,
  },
  slack: {
    name: "Slack",
    description: "Send notifications and standup summaries",
    iconBg: "bg-[#4A154B]/10",
    iconColor: "text-[#4A154B]",
    icon: <span className="text-sm font-bold">S</span>,
  },
  linear: {
    name: "Linear",
    description: "Sync issues and cycles",
    iconBg: "bg-[#5E6AD2]/10",
    iconColor: "text-[#5E6AD2]",
    icon: <span className="text-sm font-bold">L</span>,
  },
};

const ALL_TOOLS: ToolType[] = ["jira", "ado", "github", "slack", "linear"];

// ---------------------------------------------------------------------------
// Tool Card
// ---------------------------------------------------------------------------

function ToolCard({
  tool,
  connection,
  onConnect,
  onDisconnect,
  onSync,
}: {
  tool: ToolType;
  connection?: ConnectionInfo;
  onConnect: () => void;
  onDisconnect: () => void;
  onSync: () => void;
}) {
  const meta = TOOL_META[tool];
  const isConnected = connection?.status === "connected" || connection?.status === "syncing";
  const isSyncing = connection?.status === "syncing";
  const isPlaceholder = tool === "slack" || tool === "linear";

  return (
    <div
      className={cn(
        "rounded-xl border p-4",
        "border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/50",
        "transition-colors duration-200 hover:bg-[var(--bg-surface-raised)]"
      )}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div
            className={cn(
              "flex h-10 w-10 items-center justify-center rounded-lg shrink-0",
              meta.iconBg,
              meta.iconColor
            )}
          >
            {meta.icon}
          </div>

          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-[var(--text-primary)]">
                {meta.name}
              </span>
              {connection && <ConnectionStatusBadge status={connection.status} />}
              {!connection && !isPlaceholder && (
                <span className="text-xs text-[var(--text-tertiary)]">Not connected</span>
              )}
              {isPlaceholder && (
                <Badge variant="brand" className="text-[10px]">Coming Soon</Badge>
              )}
            </div>
            <p className="text-xs text-[var(--text-secondary)]">{meta.description}</p>

            {isConnected && connection && (
              <div className="flex items-center gap-4 pt-1">
                {connection.siteUrl && (
                  <span className="text-[11px] text-[var(--text-tertiary)]">
                    {connection.siteUrl.replace("https://", "")}
                  </span>
                )}
                {connection.projectCount !== undefined && (
                  <span className="text-[11px] text-[var(--text-tertiary)]">
                    {connection.projectCount} projects
                  </span>
                )}
                {connection.repoCount !== undefined && (
                  <span className="text-[11px] text-[var(--text-tertiary)]">
                    {connection.repoCount} repos
                  </span>
                )}
                {connection.lastSyncedAt && (
                  <span className="flex items-center gap-1 text-[11px] text-[var(--text-tertiary)]">
                    <Clock size={10} />
                    Synced {new Date(connection.lastSyncedAt).toLocaleTimeString()}
                  </span>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 shrink-0">
          {isConnected && (
            <>
              <button
                onClick={onSync}
                disabled={isSyncing}
                className={cn(
                  "flex items-center gap-1.5 rounded-lg px-3 py-1.5",
                  "text-xs font-medium",
                  "border border-[var(--border-subtle)]",
                  "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
                  "hover:bg-[var(--bg-surface-raised)]",
                  "transition-colors cursor-pointer",
                  "disabled:opacity-50 disabled:cursor-not-allowed"
                )}
              >
                <RefreshCw size={12} className={isSyncing ? "animate-spin" : ""} />
                Sync
              </button>
              <button
                onClick={onDisconnect}
                className={cn(
                  "flex items-center gap-1.5 rounded-lg px-3 py-1.5",
                  "text-xs font-medium",
                  "text-[var(--color-rag-red)] hover:bg-[var(--color-rag-red)]/5",
                  "transition-colors cursor-pointer"
                )}
              >
                <Unplug size={12} />
                Disconnect
              </button>
            </>
          )}
          {!isConnected && !isPlaceholder && (
            <Button variant="secondary" size="sm" onClick={onConnect}>
              Connect
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ConnectionsSettingsPage() {
  const { connections, getConnection, disconnect, triggerSync, openModal } = useIntegrations();

  const connectedCount = connections.filter(
    (c) => c.status === "connected" || c.status === "syncing"
  ).length;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)]">
            Tool Connections
          </h1>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            Manage integrations with your project management and development tools.
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={openModal}>
          <Plus size={14} />
          Add Connection
        </Button>
      </div>

      {/* Summary bar */}
      <div className="flex items-center gap-6 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]/80 p-4">
        <div className="flex items-center gap-2">
          <CheckCircle2 size={16} className="text-[var(--color-rag-green)]" />
          <span className="text-sm text-[var(--text-primary)]">
            <span className="font-semibold">{connectedCount}</span> tool{connectedCount !== 1 ? "s" : ""} connected
          </span>
        </div>
        {connections.some((c) => c.status === "error") && (
          <div className="flex items-center gap-2">
            <AlertCircle size={16} className="text-[var(--color-rag-red)]" />
            <span className="text-sm text-[var(--color-rag-red)]">
              {connections.filter((c) => c.status === "error").length} error{connections.filter((c) => c.status === "error").length !== 1 ? "s" : ""}
            </span>
          </div>
        )}
      </div>

      <DashboardPanel title="Integrations" icon={Link2}>
        <div className="space-y-3">
          {ALL_TOOLS.map((tool) => (
            <ToolCard
              key={tool}
              tool={tool}
              connection={getConnection(tool)}
              onConnect={openModal}
              onDisconnect={() => disconnect(tool)}
              onSync={() => triggerSync(tool)}
            />
          ))}
        </div>
      </DashboardPanel>
    </div>
  );
}
