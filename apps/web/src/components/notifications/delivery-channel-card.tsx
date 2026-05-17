"use client";

import { motion } from "framer-motion";
import { useState, useEffect } from "react";
import {
  CheckCircle2,
  AlertTriangle,
  Loader2,
  Unplug,
  RefreshCw,
  MessageSquare,
  Video,
  Phone,
  Copy,
  Check,
  ShieldCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui";
import { useAuth } from "@/lib/auth/context";
import { SlackLogo, TeamsLogo } from "./platform-logos";
import type { ChannelStatus } from "./use-channel-status";
import type { UserRole } from "@/lib/types/auth";

/* -------------------------------------------------------------------------- */
/*  PLATFORM CONFIGURATION                                                      */
/* -------------------------------------------------------------------------- */

interface PlatformConfig {
  name: string;
  brandColor: string;
  brandBg: string;
  description: string;
  devBullets: string[];
  poBullets: string[];
  adminNote: string;
}

const PLATFORMS: Record<"slack" | "teams", PlatformConfig> = {
  slack: {
    name: "Slack",
    brandColor: "#4A154B",
    brandBg: "bg-[#4A154B]/10",
    description:
      "Receive your standup reports, blocker alerts, and sprint updates directly in Slack.",
    devBullets: [
      "Standup report (daily DM)",
      "Blocker flag confirmations",
      "Sprint assignment notifications",
      "CI/CD failure alerts on your PRs",
      "Retrospective action items assigned to you",
    ],
    poBullets: [
      "Sprint plan approval requests",
      "Team standup digest (daily)",
      "Burnout & health alerts (private DM)",
      "Blocker flags raised by developers",
      "At-risk sprint & PR review lag alerts",
      "Retrospective summary delivery",
    ],
    adminNote: "Requires Slack workspace admin",
  },
  teams: {
    name: "Microsoft Teams",
    brandColor: "#5059C9",
    brandBg: "bg-[#5059C9]/10",
    description:
      "Get standup reports, approval requests, and alerts delivered to Microsoft Teams.",
    devBullets: [
      "Standup report (daily chat)",
      "Blocker flag confirmations",
      "Sprint assignment notifications",
      "CI/CD failure alerts on your PRs",
      "Retrospective action items assigned to you",
    ],
    poBullets: [
      "Sprint plan approval requests",
      "Team standup digest (daily)",
      "Burnout & health alerts (private chat)",
      "Blocker flags raised by developers",
      "At-risk sprint & PR review lag alerts",
      "Retrospective summary delivery",
    ],
    adminNote: "Requires tenant admin approval",
  },
};

function isPORole(role: UserRole): boolean {
  return ["owner", "admin", "product_owner", "engineering_manager"].includes(
    role
  );
}

/* -------------------------------------------------------------------------- */
/*  STATUS BADGE                                                                */
/* -------------------------------------------------------------------------- */

function StatusBadge({ status }: { status: ChannelStatus }) {
  if (status.state === "loading") {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full",
          "px-2.5 py-1 text-xs font-medium whitespace-nowrap",
          "text-[var(--text-secondary)]",
          "bg-[var(--bg-surface-raised)] border border-[var(--border-subtle)]"
        )}
      >
        <Loader2 size={10} className="animate-spin" />
        Checking...
      </span>
    );
  }

  if (status.state === "connected") {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full",
          "px-2.5 py-1 text-xs font-medium whitespace-nowrap",
          "text-[var(--color-rag-green)]",
          "bg-[var(--color-rag-green)]/10 border border-[var(--color-rag-green)]/20"
        )}
      >
        <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-rag-green)] animate-pulse" />
        Connected
      </span>
    );
  }

  if (status.state === "error") {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full",
          "px-2.5 py-1 text-xs font-medium whitespace-nowrap",
          "text-[var(--color-rag-red)]",
          "bg-[var(--color-rag-red)]/10 border border-[var(--color-rag-red)]/20"
        )}
      >
        <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-rag-red)]" />
        Error
      </span>
    );
  }

  // Disconnected
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full",
        "px-2.5 py-1 text-xs font-medium whitespace-nowrap",
        "text-[var(--text-secondary)]",
        "bg-[var(--bg-surface-raised)] border border-[var(--border-subtle)]"
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-[var(--text-secondary)]/40" />
      Not connected
    </span>
  );
}

/* -------------------------------------------------------------------------- */
/*  DELIVERY CHANNEL CARD                                                       */
/* -------------------------------------------------------------------------- */

interface DeliveryChannelCardProps {
  platform: "slack" | "teams";
  status: ChannelStatus;
  onConnect?: () => void;
  onDisconnect?: () => void;
}

export function DeliveryChannelCard({
  platform,
  status,
  onConnect,
  onDisconnect,
}: DeliveryChannelCardProps) {
  const { role } = useAuth();
  const config = PLATFORMS[platform];
  const Logo = platform === "slack" ? SlackLogo : TeamsLogo;
  const bullets = isPORole(role) ? config.poBullets : config.devBullets;
  const isAdmin = isPORole(role);

  async function handleDisconnect() {
    // Hotfix 73/74 - non-admin callers use /me/disconnect to clear
    // their personal Slack/Teams identity link. PO uses /disconnect
    // which removes the org connection (also gated PO-only on the
    // backend, so a non-PO calling it would 403).
    const url = isAdmin
      ? `/api/integrations/${platform}/disconnect`
      : `/api/integrations/${platform}/me/disconnect`;
    const method = isAdmin ? "DELETE" : "POST";
    try {
      await fetch(url, { method });
      onDisconnect?.();
    } catch {
      // Ignore
    }
  }

  const isConnected = status.state === "connected";
  const isError = status.state === "error";

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: platform === "teams" ? 0.1 : 0 }}
      className={cn(
        "rounded-2xl border",
        "bg-[var(--bg-surface)]/80 backdrop-blur-xl",
        "shadow-sm shadow-black/[0.03] dark:shadow-black/20",
        "p-6 flex flex-col",
        "transition-colors duration-200",
        isConnected
          ? "border-[var(--color-rag-green)]/20 hover:border-[var(--color-rag-green)]/30"
          : isError
            ? "border-[var(--color-rag-red)]/20 hover:border-[var(--color-rag-red)]/30"
            : "border-[var(--border-subtle)] hover:border-[var(--border-subtle)]/80"
      )}
    >
      {/* Header: Logo + Name + Status Badge */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <div
            className={cn(
              "flex h-11 w-11 items-center justify-center rounded-xl shrink-0",
              config.brandBg
            )}
          >
            <Logo size={26} />
          </div>
          <div>
            <h3 className="text-base font-semibold text-[var(--text-primary)]">
              {config.name}
            </h3>
            {isConnected && status.teamName && (
              <p className="text-xs text-[var(--text-secondary)] mt-0.5">
                {status.teamName}
              </p>
            )}
          </div>
        </div>
        <StatusBadge status={status} />
      </div>

      {/* Error state message */}
      {isError && status.error && (
        <div className="mt-4 rounded-xl border border-[var(--color-rag-red)]/15 bg-[var(--color-rag-red)]/5 px-4 py-3">
          <div className="flex items-start gap-2.5">
            <AlertTriangle
              size={15}
              className="text-[var(--color-rag-red)] shrink-0 mt-0.5"
            />
            <div>
              <p className="text-sm font-medium text-[var(--text-primary)]">
                Connection failed
              </p>
              <p className="text-xs text-[var(--text-secondary)] mt-0.5 leading-relaxed">
                {status.error.replace(/_/g, " ")}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Connected state: workspace info + actions */}
      {isConnected && (
        <div className="mt-4 space-y-3">
          <div className="flex items-center gap-2">
            <CheckCircle2
              size={14}
              className="text-[var(--color-rag-green)]"
            />
            <span className="text-sm text-[var(--text-secondary)]">
              {platform === "slack"
                ? "Notifications will be delivered to Slack DMs"
                : "Teams is connected - open chats, meetings & calls directly"}
            </span>
          </div>

          {/* Teams quick actions - deeplinks to open Teams directly */}
          {platform === "teams" && (
            <div className="flex gap-2">
              <a
                href="https://teams.microsoft.com"
                target="_blank"
                rel="noopener noreferrer"
                className={cn(
                  "flex-1 flex items-center justify-center gap-1.5 rounded-lg px-3 py-2",
                  "text-xs font-medium border border-[var(--border-subtle)]",
                  "text-[var(--text-secondary)] hover:text-[#5059C9] hover:border-[#5059C9]/30 hover:bg-[#5059C9]/5",
                  "transition-colors"
                )}
              >
                <MessageSquare size={13} />
                Chat
              </a>
              <a
                href="https://teams.microsoft.com/l/meeting/new"
                target="_blank"
                rel="noopener noreferrer"
                className={cn(
                  "flex-1 flex items-center justify-center gap-1.5 rounded-lg px-3 py-2",
                  "text-xs font-medium border border-[var(--border-subtle)]",
                  "text-[var(--text-secondary)] hover:text-[#5059C9] hover:border-[#5059C9]/30 hover:bg-[#5059C9]/5",
                  "transition-colors"
                )}
              >
                <Video size={13} />
                Meet
              </a>
              <a
                href="https://teams.microsoft.com/l/call/0/0"
                target="_blank"
                rel="noopener noreferrer"
                className={cn(
                  "flex-1 flex items-center justify-center gap-1.5 rounded-lg px-3 py-2",
                  "text-xs font-medium border border-[var(--border-subtle)]",
                  "text-[var(--text-secondary)] hover:text-[#5059C9] hover:border-[#5059C9]/30 hover:bg-[#5059C9]/5",
                  "transition-colors"
                )}
              >
                <Phone size={13} />
                Call
              </a>
            </div>
          )}

          {status.connectedAt && (
            <p className="text-xs text-[var(--text-secondary)]/60">
              Connected{" "}
              {new Date(status.connectedAt).toLocaleDateString("en-US", {
                month: "short",
                day: "numeric",
                year: "numeric",
              })}
            </p>
          )}
        </div>
      )}

      {/* Description (disconnected only) */}
      {!isConnected && !isError && (
        <p className="mt-4 text-sm text-[var(--text-secondary)] leading-relaxed">
          {config.description}
        </p>
      )}

      {/* Feature bullet list (disconnected only) */}
      {!isConnected && !isError && (
        <div className="mt-4 space-y-2.5 flex-1">
          {bullets.map((bullet, i) => (
            <div key={i} className="flex items-start gap-2.5">
              <span
                className="mt-[7px] h-1.5 w-1.5 rounded-full shrink-0"
                style={{ backgroundColor: config.brandColor, opacity: 0.35 }}
              />
              <span className="text-sm text-[var(--text-secondary)] leading-snug">
                {bullet}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Footer actions */}
      <div
        className={cn(
          "mt-6 pt-5 border-t border-[var(--border-subtle)]",
          "flex flex-col items-center gap-2.5"
        )}
      >
        {isConnected ? (
          /* Connected: disabled label + Disconnect. PO disconnect
             clears the org-level workspace install; non-PO disconnect
             clears the per-user OAuth link (handleDisconnect routes to
             the right endpoint based on isAdmin). Visible to both roles
             so each manages their own state. */
          <div className="w-full space-y-2">
            <button
              disabled
              className={cn(
                "w-full inline-flex items-center justify-center gap-2",
                "px-6 py-2.5 text-sm font-medium rounded-xl",
                "bg-[#93C5FD]/10 text-[#93C5FD]/50 border border-[#93C5FD]/15",
                "opacity-60 cursor-not-allowed select-none pointer-events-none"
              )}
            >
              <CheckCircle2 size={15} />
              Connected to {config.name}
            </button>
            {(
              <button
                onClick={handleDisconnect}
                className="w-full flex items-center justify-center gap-1.5 text-xs font-medium text-[var(--text-secondary)]/60 hover:text-[var(--color-rag-red)] transition-colors cursor-pointer py-1"
              >
                <Unplug size={12} />
                Disconnect
              </button>
            )}
          </div>
        ) : isError ? (
          /* Error: Retry + details */
          <div className="w-full space-y-2">
            <Button variant="primary" onClick={onConnect}>
              <RefreshCw size={14} className="mr-1.5" />
              Reconnect {config.name}
            </Button>
          </div>
        ) : (
          /* Disconnected: Connect CTA. For non-admin this kicks off
             per-user OAuth (handled in
             DeliveryChannelsSection.handleConnect). The
             admin-onboarding text + TeamsAdminConsentHint only render
             for PO/admin since they're the ones who actually install
             the workspace bot / grant tenant consent. */
          <>
            <Button variant="primary" onClick={onConnect}>
              Connect {config.name}
            </Button>
            {isAdmin && (
              <p className="text-[11px] text-[var(--text-secondary)]/60">
                {config.adminNote}
              </p>
            )}
            {isAdmin && platform === "teams" && <TeamsAdminConsentHint />}
          </>
        )}
      </div>
    </motion.div>
  );
}

/* -------------------------------------------------------------------------- */
/*  TEAMS ADMIN CONSENT HINT                                                  */
/*                                                                            */
/*  Microsoft's user-consent flow hits an "Approval required" wall for admin- */
/*  only scopes (User.Read.All, Team.ReadBasic.All, Channel.Create). Give the */
/*  user an explicit path: open the Microsoft admin-consent URL (opens cold,  */
/*  no Plan2Sprint login needed) or copy it to send to their IT admin.        */
/* -------------------------------------------------------------------------- */

function TeamsAdminConsentHint() {
  const [expanded, setExpanded] = useState(false);
  const [url, setUrl] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!expanded || url) return;
    (async () => {
      try {
        const res = await fetch("/api/integrations/teams/admin-consent-url");
        if (res.ok) {
          const data = await res.json();
          setUrl(data.url ?? null);
        }
      } catch { /* ignore */ }
    })();
  }, [expanded, url]);

  const copy = async () => {
    if (!url) return;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* ignore */ }
  };

  if (!expanded) {
    return (
      <button
        onClick={() => setExpanded(true)}
        className="text-[11px] text-[var(--color-brand-secondary)] hover:underline cursor-pointer"
      >
        Seeing &ldquo;Approval required&rdquo;? →
      </button>
    );
  }

  return (
    <div className="mt-2 w-full max-w-[320px] rounded-lg bg-[var(--bg-surface-raised)] border border-[var(--border-subtle)] p-3 space-y-2.5 text-left">
      <div className="flex items-start gap-2">
        <ShieldCheck size={14} className="shrink-0 text-[var(--color-brand-secondary)] mt-0.5" />
        <div className="space-y-1.5">
          <p className="text-[11px] font-semibold text-[var(--text-primary)] leading-snug">
            Needs IT admin approval
          </p>
          <p className="text-[11px] text-[var(--text-secondary)] leading-relaxed">
            Three of the Microsoft scopes are admin-only. Send the link below
            to a Microsoft tenant admin (Global / Application / Cloud Application
            Administrator). When they open it in any browser and click{" "}
            <span className="font-medium">Accept</span>, consent is granted
            tenant-wide - every user can then Connect without individual
            approval requests.
          </p>
        </div>
      </div>

      {url ? (
        <div className="flex items-center gap-1.5 rounded-md bg-[var(--bg-surface)] border border-[var(--border-subtle)] px-2 py-1.5">
          <code className="flex-1 text-[10px] text-[var(--text-secondary)] truncate font-mono">
            {url}
          </code>
          <button
            onClick={copy}
            title="Copy link"
            className="shrink-0 p-1 rounded hover:bg-[var(--bg-surface-raised)] cursor-pointer"
          >
            {copied ? (
              <Check size={12} className="text-[var(--color-rag-green)]" />
            ) : (
              <Copy size={12} className="text-[var(--text-secondary)]" />
            )}
          </button>
        </div>
      ) : (
        <p className="text-[11px] text-[var(--text-tertiary)]">Loading link…</p>
      )}

      {url && (
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-[11px] font-medium text-[var(--color-brand-secondary)] hover:underline"
        >
          Open it now (I am the IT admin) →
        </a>
      )}

      <p className="text-[10px] text-[var(--text-tertiary)] leading-relaxed">
        Heads up: Plan2Sprint isn&apos;t Microsoft-verified yet, so the consent
        screen shows an &ldquo;Unverified app&rdquo; banner. That&apos;s a
        label, not a block - the admin can still click Accept. Only Global /
        Application / Cloud Application Administrators in your tenant can
        grant consent; a regular user clicking this link will be denied by
        Microsoft.
      </p>
    </div>
  );
}
