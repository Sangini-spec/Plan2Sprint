"use client";

import { Github, ExternalLink, Unplug, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { useIntegrations } from "@/lib/integrations/context";
import { ConnectionStatusBadge } from "./connection-status";

export function GitHubConnectCard() {
  const { getConnection, connect, disconnect, triggerSync } = useIntegrations();
  const connection = getConnection("github");
  const isConnected = connection?.status === "connected" || connection?.status === "syncing";
  const isConnecting = connection?.status === "connecting";

  const handleConnect = async () => {
    await connect("github", "cloud");
  };

  const handleDisconnect = async () => {
    await disconnect("github");
  };

  const handleSync = async () => {
    await triggerSync("github");
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--text-primary)]/10">
          <Github size={20} className="text-[var(--text-primary)]" />
        </div>
        <div className="flex-1">
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">GitHub</h3>
          <p className="text-xs text-[var(--text-secondary)]">
            Monitor repos, PRs, commits, and CI status
          </p>
        </div>
        {connection && <ConnectionStatusBadge status={connection.status} />}
      </div>

      {isConnected ? (
        <div className="space-y-3">
          <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/50 p-3 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-[var(--text-secondary)]">Organization</span>
              <span className="text-xs font-medium text-[var(--text-primary)]">
                {connection.displayName ?? "acme-org"}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-[var(--text-secondary)]">Repositories</span>
              <span className="text-xs font-medium text-[var(--text-primary)]">
                {connection.repoCount ?? 0}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-[var(--text-secondary)]">Last synced</span>
              <span className="text-xs font-medium text-[var(--text-primary)]">
                {connection.lastSyncedAt
                  ? new Date(connection.lastSyncedAt).toLocaleTimeString()
                  : "Never"}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-[var(--text-secondary)]">Access</span>
              <span className="text-xs font-medium text-[var(--color-brand-secondary)]">
                Read-only
              </span>
            </div>
          </div>

          <div className="flex gap-2">
            <button
              onClick={handleSync}
              disabled={connection.status === "syncing"}
              className={cn(
                "flex-1 flex items-center justify-center gap-1.5 rounded-lg px-3 py-2",
                "text-xs font-medium",
                "border border-[var(--border-subtle)]",
                "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
                "hover:bg-[var(--bg-surface-raised)]",
                "transition-colors cursor-pointer",
                "disabled:opacity-50 disabled:cursor-not-allowed"
              )}
            >
              <RefreshCw size={13} className={connection.status === "syncing" ? "animate-spin" : ""} />
              Sync Now
            </button>
            <button
              onClick={handleDisconnect}
              className={cn(
                "flex items-center justify-center gap-1.5 rounded-lg px-3 py-2",
                "text-xs font-medium",
                "border border-[var(--color-rag-red)]/20",
                "text-[var(--color-rag-red)]",
                "hover:bg-[var(--color-rag-red)]/5",
                "transition-colors cursor-pointer"
              )}
            >
              <Unplug size={13} />
              Disconnect
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-xs text-[var(--text-tertiary)]">
            Install the Plan2Sprint GitHub App to grant read-only access to your repositories.
            We never push code or modify your repos.
          </p>

          <button
            onClick={handleConnect}
            disabled={isConnecting}
            className={cn(
              "w-full flex items-center justify-center gap-2 rounded-lg px-4 py-2.5",
              "text-sm font-medium text-white",
              "bg-[var(--text-primary)] hover:bg-[var(--text-primary)]/90",
              "transition-all cursor-pointer",
              "disabled:opacity-50 disabled:cursor-not-allowed"
            )}
          >
            {isConnecting ? (
              <>
                <RefreshCw size={14} className="animate-spin" />
                Installing...
              </>
            ) : (
              <>
                <ExternalLink size={14} />
                Install GitHub App
              </>
            )}
          </button>
        </div>
      )}
    </div>
  );
}
