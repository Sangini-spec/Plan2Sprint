"use client";

import { useState, useEffect } from "react";
import { Unplug, RefreshCw, ExternalLink, Loader2, KeyRound } from "lucide-react";
import { cn } from "@/lib/utils";
import { useIntegrations } from "@/lib/integrations/context";
import { apiFetch } from "@/lib/api-fetch";
import { ConnectionStatusBadge } from "./connection-status";

type ConnectMode = "oauth" | "token";

export function JiraConnectCard() {
  const { getConnection, disconnect, triggerSync, refreshJiraStatus } = useIntegrations();
  const connection = getConnection("jira");
  const isConnected = connection?.status === "connected" || connection?.status === "syncing";

  const [mode, setMode] = useState<ConnectMode>("oauth");
  const [isRedirecting, setIsRedirecting] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");

  // Token form fields
  const [siteUrl, setSiteUrl] = useState("");
  const [email, setEmail] = useState("");
  const [apiToken, setApiToken] = useState("");

  // Check URL params for OAuth callback result
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const jiraParam = params.get("jira");
    const jiraError = params.get("jira_error");

    if (jiraParam === "connected" || jiraParam === "demo") {
      refreshJiraStatus?.();
      const url = new URL(window.location.href);
      url.searchParams.delete("jira");
      window.history.replaceState({}, "", url.pathname);
    }

    if (jiraError) {
      console.error("Jira OAuth error:", jiraError);
      const url = new URL(window.location.href);
      url.searchParams.delete("jira_error");
      window.history.replaceState({}, "", url.pathname);
    }
  }, [refreshJiraStatus]);

  const handleOAuthConnect = () => {
    setIsRedirecting(true);
    // Pass auth token as query param for full-page navigation (no Bearer header)
    const sb = JSON.parse(localStorage.getItem(`sb-obmbpfoormxbbizudrrp-auth-token`) || "{}");
    const token = sb?.access_token || "";
    window.location.href = `/api/integrations/jira/connect${token ? `?token=${token}` : ""}`;
  };

  const handleTokenConnect = async () => {
    if (!siteUrl || !email || !apiToken) {
      setError("All fields are required");
      return;
    }

    setIsSubmitting(true);
    setError("");

    try {
      const res = await apiFetch("/api/integrations/jira/connect-token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          site_url: siteUrl.startsWith("http") ? siteUrl : `https://${siteUrl}`,
          email,
          api_token: apiToken,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        setError(data.detail || "Connection failed");
        setIsSubmitting(false);
        return;
      }

      // Success — refresh status
      refreshJiraStatus?.();
      setSiteUrl("");
      setEmail("");
      setApiToken("");
    } catch {
      setError("Network error. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDisconnect = async () => {
    try {
      await apiFetch("/api/integrations/jira/disconnect", { method: "POST" });
      await disconnect("jira");
    } catch {
      // Silently handle
    }
  };

  const handleSync = async () => {
    await triggerSync("jira");
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[#0052CC]/10">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
            <path d="M11.53 2c0 4.97 3.93 9 8.47 9-.27 4.97-4.39 9-9.47 9C5.48 20 1 15.52 1 10.5S5.48 1 10.53 1c.34 0 .67.03 1 .07V2z" fill="#0052CC" />
            <path d="M11.53 2c0 4.97 3.93 9 8.47 9 .28 0 .56-.01.83-.04C20.53 6.51 16.53 2.58 11.53 2z" fill="#2684FF" />
          </svg>
        </div>
        <div className="flex-1">
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">Jira</h3>
          <p className="text-xs text-[var(--text-secondary)]">
            Sync sprints, issues, and team data
          </p>
        </div>
        {connection && <ConnectionStatusBadge status={connection.status} />}
      </div>

      {isConnected ? (
        /* Connected state */
        <div className="space-y-3">
          <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/50 p-3 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-[var(--text-secondary)]">Site</span>
              <span className="text-xs font-medium text-[var(--text-primary)]">
                {connection.siteUrl ?? connection.displayName ?? "Jira Cloud"}
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
                  ? "bg-[#0052CC]/10 text-[#0052CC] border-r border-[var(--border-subtle)]"
                  : "text-[var(--text-secondary)] hover:bg-[var(--bg-surface-raised)] border-r border-[var(--border-subtle)]"
              )}
            >
              <ExternalLink size={12} />
              My Account
            </button>
            <button
              onClick={() => { setMode("token"); setError(""); }}
              className={cn(
                "flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors cursor-pointer",
                mode === "token"
                  ? "bg-[#0052CC]/10 text-[#0052CC]"
                  : "text-[var(--text-secondary)] hover:bg-[var(--bg-surface-raised)]"
              )}
            >
              <KeyRound size={12} />
              Shared Site
            </button>
          </div>

          {mode === "oauth" ? (
            /* OAuth mode */
            <div className="space-y-3">
              <p className="text-xs text-[var(--text-tertiary)]">
                Connect your own Atlassian account to sync your Jira projects.
              </p>

              <button
                onClick={handleOAuthConnect}
                disabled={isRedirecting}
                className={cn(
                  "w-full flex items-center justify-center gap-2 rounded-lg px-4 py-2.5",
                  "text-sm font-medium text-white",
                  "bg-[#0052CC] hover:bg-[#0052CC]/90",
                  "transition-all cursor-pointer",
                  "disabled:opacity-50 disabled:cursor-not-allowed"
                )}
              >
                {isRedirecting ? (
                  <>
                    <Loader2 size={14} className="animate-spin" />
                    Redirecting to Atlassian...
                  </>
                ) : (
                  <>
                    <ExternalLink size={14} />
                    Connect with Atlassian
                  </>
                )}
              </button>
            </div>
          ) : (
            /* Access token mode — for shared/external sites */
            <div className="space-y-3">
              <p className="text-xs text-[var(--text-tertiary)]">
                Access a shared Jira site using your work email and an access token.
              </p>

              <div className="space-y-2">
                <input
                  type="text"
                  placeholder="Jira site URL (e.g. company.atlassian.net)"
                  value={siteUrl}
                  onChange={(e) => setSiteUrl(e.target.value)}
                  className={cn(
                    "w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-3 py-2",
                    "text-xs text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)]",
                    "focus:outline-none focus:ring-1 focus:ring-[#0052CC]/50"
                  )}
                />
                <input
                  type="email"
                  placeholder="Work email address"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className={cn(
                    "w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-3 py-2",
                    "text-xs text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)]",
                    "focus:outline-none focus:ring-1 focus:ring-[#0052CC]/50"
                  )}
                />
                <input
                  type="password"
                  placeholder="Access token"
                  value={apiToken}
                  onChange={(e) => setApiToken(e.target.value)}
                  className={cn(
                    "w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-3 py-2",
                    "text-xs text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)]",
                    "focus:outline-none focus:ring-1 focus:ring-[#0052CC]/50"
                  )}
                />
              </div>

              {error && (
                <p className="text-[11px] text-[var(--color-rag-red)]">{error}</p>
              )}

              <button
                onClick={handleTokenConnect}
                disabled={isSubmitting}
                className={cn(
                  "w-full flex items-center justify-center gap-2 rounded-lg px-4 py-2.5",
                  "text-sm font-medium text-white",
                  "bg-[#0052CC] hover:bg-[#0052CC]/90",
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
                    Connect to Shared Site
                  </>
                )}
              </button>

              {/* User-friendly token generation guide */}
              <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/30 p-2.5 space-y-1">
                <p className="text-[10px] font-medium text-[var(--text-secondary)]">
                  How to get your access token (30 seconds):
                </p>
                <ol className="text-[10px] text-[var(--text-tertiary)] space-y-0.5 list-decimal list-inside">
                  <li>
                    Go to{" "}
                    <a
                      href="https://id.atlassian.com/manage-profile/security/api-tokens"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[#0052CC] hover:underline font-medium"
                    >
                      Atlassian Account Settings
                    </a>
                  </li>
                  <li>Click &quot;Create API token&quot; and give it a name</li>
                  <li>Copy the token and paste it above</li>
                </ol>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
