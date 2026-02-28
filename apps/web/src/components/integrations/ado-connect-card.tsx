"use client";

import { useState, useEffect } from "react";
import { Unplug, RefreshCw, ExternalLink, Loader2, KeyRound } from "lucide-react";
import { cn } from "@/lib/utils";
import { useIntegrations } from "@/lib/integrations/context";
import { ConnectionStatusBadge } from "./connection-status";

type ConnectMode = "oauth" | "pat";

export function AdoConnectCard() {
  const { getConnection, disconnect, triggerSync, refreshAdoStatus } = useIntegrations();
  const connection = getConnection("ado");
  const isConnected = connection?.status === "connected" || connection?.status === "syncing";

  const [mode, setMode] = useState<ConnectMode>("oauth");
  const [isRedirecting, setIsRedirecting] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");

  // PAT form fields
  const [orgUrl, setOrgUrl] = useState("");
  const [pat, setPat] = useState("");

  // Check URL params for OAuth callback result
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const adoParam = params.get("ado");
    const adoError = params.get("ado_error");

    if (adoParam === "connected" || adoParam === "demo") {
      refreshAdoStatus?.();
      const url = new URL(window.location.href);
      url.searchParams.delete("ado");
      window.history.replaceState({}, "", url.pathname);
    }

    if (adoError) {
      console.error("ADO OAuth error:", adoError);
      const url = new URL(window.location.href);
      url.searchParams.delete("ado_error");
      window.history.replaceState({}, "", url.pathname);
    }
  }, [refreshAdoStatus]);

  const handleOAuthConnect = () => {
    setIsRedirecting(true);
    window.location.href = "/api/integrations/ado/connect";
  };

  const handlePatConnect = async () => {
    if (!orgUrl || !pat) {
      setError("All fields are required");
      return;
    }

    setIsSubmitting(true);
    setError("");

    try {
      const fullOrgUrl = orgUrl.startsWith("http")
        ? orgUrl
        : `https://dev.azure.com/${orgUrl}`;

      const res = await fetch("/api/integrations/ado/connect-token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          org_url: fullOrgUrl,
          pat,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        setError(data.detail || "Connection failed");
        setIsSubmitting(false);
        return;
      }

      // Success — refresh status
      refreshAdoStatus?.();
      setOrgUrl("");
      setPat("");
    } catch {
      setError("Network error. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDisconnect = async () => {
    try {
      await fetch("/api/integrations/ado/disconnect", { method: "POST" });
      await disconnect("ado");
    } catch {
      // Silently handle
    }
  };

  const handleSync = async () => {
    await triggerSync("ado");
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[#0078D4]/10">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
            <path d="M22 4v16l-6 2V6l-8-2v14l-6 2V4l12 3 8-3z" fill="#0078D4" />
          </svg>
        </div>
        <div className="flex-1">
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">Azure DevOps</h3>
          <p className="text-xs text-[var(--text-secondary)]">
            Sync iterations, work items, and boards
          </p>
        </div>
        {connection && <ConnectionStatusBadge status={connection.status} />}
      </div>

      {isConnected ? (
        /* Connected state */
        <div className="space-y-3">
          <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/50 p-3 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-[var(--text-secondary)]">Organization</span>
              <span className="text-xs font-medium text-[var(--text-primary)]">
                {connection.siteUrl ?? connection.displayName ?? "Azure DevOps"}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-[var(--text-secondary)]">Status</span>
              <span className="text-xs font-medium text-[var(--color-rag-green)]">
                Connected
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
        /* Disconnected state — Dual mode */
        <div className="space-y-3">
          {/* Mode toggle */}
          <div className="flex rounded-lg border border-[var(--border-subtle)] overflow-hidden">
            <button
              onClick={() => { setMode("oauth"); setError(""); }}
              className={cn(
                "flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors cursor-pointer",
                mode === "oauth"
                  ? "bg-[#0078D4]/10 text-[#0078D4] border-r border-[var(--border-subtle)]"
                  : "text-[var(--text-secondary)] hover:bg-[var(--bg-surface-raised)] border-r border-[var(--border-subtle)]"
              )}
            >
              <ExternalLink size={12} />
              My Account
            </button>
            <button
              onClick={() => { setMode("pat"); setError(""); }}
              className={cn(
                "flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors cursor-pointer",
                mode === "pat"
                  ? "bg-[#0078D4]/10 text-[#0078D4]"
                  : "text-[var(--text-secondary)] hover:bg-[var(--bg-surface-raised)]"
              )}
            >
              <KeyRound size={12} />
              Shared Org
            </button>
          </div>

          {mode === "oauth" ? (
            /* OAuth mode */
            <div className="space-y-3">
              <p className="text-xs text-[var(--text-tertiary)]">
                Connect your own Microsoft account to sync your Azure DevOps projects.
              </p>

              <button
                onClick={handleOAuthConnect}
                disabled={isRedirecting}
                className={cn(
                  "w-full flex items-center justify-center gap-2 rounded-lg px-4 py-2.5",
                  "text-sm font-medium text-white",
                  "bg-[#0078D4] hover:bg-[#0078D4]/90",
                  "transition-all cursor-pointer",
                  "disabled:opacity-50 disabled:cursor-not-allowed"
                )}
              >
                {isRedirecting ? (
                  <>
                    <Loader2 size={14} className="animate-spin" />
                    Redirecting to Microsoft...
                  </>
                ) : (
                  <>
                    <ExternalLink size={14} />
                    Connect with Microsoft
                  </>
                )}
              </button>
            </div>
          ) : (
            /* PAT mode — for shared/external organizations */
            <div className="space-y-3">
              <p className="text-xs text-[var(--text-tertiary)]">
                Access a shared Azure DevOps organization using the company URL and an access token.
              </p>

              <div className="space-y-2">
                <input
                  type="text"
                  placeholder="Company URL (e.g. dev.azure.com/companyname)"
                  value={orgUrl}
                  onChange={(e) => setOrgUrl(e.target.value)}
                  className={cn(
                    "w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-3 py-2",
                    "text-xs text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)]",
                    "focus:outline-none focus:ring-1 focus:ring-[#0078D4]/50"
                  )}
                />
                <input
                  type="password"
                  placeholder="Personal Access Token (PAT)"
                  value={pat}
                  onChange={(e) => setPat(e.target.value)}
                  className={cn(
                    "w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-3 py-2",
                    "text-xs text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)]",
                    "focus:outline-none focus:ring-1 focus:ring-[#0078D4]/50"
                  )}
                />
              </div>

              {error && (
                <p className="text-[11px] text-[var(--color-rag-red)]">{error}</p>
              )}

              <button
                onClick={handlePatConnect}
                disabled={isSubmitting}
                className={cn(
                  "w-full flex items-center justify-center gap-2 rounded-lg px-4 py-2.5",
                  "text-sm font-medium text-white",
                  "bg-[#0078D4] hover:bg-[#0078D4]/90",
                  "transition-all cursor-pointer",
                  "disabled:opacity-50 disabled:cursor-not-allowed"
                )}
              >
                {isSubmitting ? (
                  <>
                    <Loader2 size={14} className="animate-spin" />
                    Connecting...
                  </>
                ) : (
                  <>
                    <KeyRound size={14} />
                    Connect to Shared Org
                  </>
                )}
              </button>

              {/* User-friendly PAT generation guide */}
              <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/30 p-2.5 space-y-1">
                <p className="text-[10px] font-medium text-[var(--text-secondary)]">
                  How to get your access token (30 seconds):
                </p>
                <ol className="text-[10px] text-[var(--text-tertiary)] space-y-0.5 list-decimal list-inside">
                  <li>
                    Go to{" "}
                    <a
                      href="https://dev.azure.com"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[#0078D4] hover:underline font-medium"
                    >
                      dev.azure.com
                    </a>
                    {" "}and sign in
                  </li>
                  <li>Click your profile icon → Personal Access Tokens</li>
                  <li>Create a new token and paste it above</li>
                </ol>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
