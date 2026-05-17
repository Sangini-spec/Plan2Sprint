"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Copy,
  CheckCheck,
  Info,
  Loader2,
  CheckCircle2,
} from "lucide-react";
import { useAuth } from "@/lib/auth/context";
import { useIntegrations } from "@/lib/integrations/context";
import { DeliveryChannelCard } from "./delivery-channel-card";
import { ConnectPreflightModal } from "./connect-preflight-modal";
import { useChannelStatus } from "./use-channel-status";
import type { UserRole } from "@/lib/types/auth";

/* -------------------------------------------------------------------------- */
/*  HELPERS                                                                     */
/* -------------------------------------------------------------------------- */

function isPORole(role: UserRole): boolean {
  return ["owner", "admin", "product_owner", "engineering_manager"].includes(
    role
  );
}

/* -------------------------------------------------------------------------- */
/*  DEVELOPER ORG-CHECK INLINE PANEL                                            */
/* -------------------------------------------------------------------------- */

interface DevOrgCheckProps {
  platform: "slack" | "teams";
  orgConnected: boolean;
  onClose: () => void;
}

function DevOrgCheckPanel({ platform, orgConnected, onClose }: DevOrgCheckProps) {
  const [copiedLink, setCopiedLink] = useState(false);

  const platformName = platform === "slack" ? "Slack" : "Microsoft Teams";

  function handleCopyAdminLink() {
    const link = `${window.location.origin}/settings/connections`;
    navigator.clipboard.writeText(link);
    setCopiedLink(true);
    setTimeout(() => setCopiedLink(false), 2500);
  }

  if (orgConnected) {
    // Scenario A: Org is connected - map this developer
    return (
      <motion.div
        initial={{ opacity: 0, height: 0 }}
        animate={{ opacity: 1, height: "auto" }}
        exit={{ opacity: 0, height: 0 }}
        className="overflow-hidden"
      >
        <div className="rounded-xl border border-[var(--color-rag-green)]/20 bg-[var(--color-rag-green)]/5 p-4 space-y-3">
          <div className="flex items-start gap-3">
            <CheckCircle2
              size={18}
              className="text-[var(--color-rag-green)] shrink-0 mt-0.5"
            />
            <div>
              <p className="text-sm font-medium text-[var(--text-primary)]">
                Your workspace is already connected
              </p>
              <p className="text-xs text-[var(--text-secondary)] mt-1 leading-relaxed">
                {platformName} was set up by your admin. We&apos;re matching
                your account now - your standup reports will arrive in your{" "}
                {platform === "slack" ? "Slack DMs" : "Teams chats"} once
                complete.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 pl-[30px]">
            <Loader2
              size={14}
              className="animate-spin text-[var(--color-brand-secondary)]"
            />
            <span className="text-xs text-[var(--text-secondary)]">
              Matching your account...
            </span>
          </div>
        </div>
      </motion.div>
    );
  }

  // Scenario B: Org NOT connected - tell developer to ask admin
  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: "auto" }}
      exit={{ opacity: 0, height: 0 }}
      className="overflow-hidden"
    >
      <div className="rounded-xl border border-[var(--color-rag-amber)]/20 bg-[var(--color-rag-amber)]/5 p-4 space-y-3">
        <div className="flex items-start gap-3">
          <Info
            size={18}
            className="text-[var(--color-rag-amber)] shrink-0 mt-0.5"
          />
          <div className="space-y-2">
            <p className="text-sm font-medium text-[var(--text-primary)]">
              {platformName} hasn&apos;t been set up for your workspace yet
            </p>
            <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
              Ask your Product Owner or Admin to connect {platformName} from
              the Settings page, then come back here to get your account
              linked.
            </p>
            <div className="flex items-center gap-3">
              <button
                onClick={handleCopyAdminLink}
                className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--color-brand-secondary)] hover:underline cursor-pointer"
              >
                {copiedLink ? (
                  <>
                    <CheckCheck size={12} />
                    Link copied!
                  </>
                ) : (
                  <>
                    <Copy size={12} />
                    Copy link for your admin
                  </>
                )}
              </button>
              <button
                onClick={onClose}
                className="text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] cursor-pointer"
              >
                Dismiss
              </button>
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );
}

/* -------------------------------------------------------------------------- */
/*  DELIVERY CHANNELS SECTION                                                   */
/*                                                                              */
/*  Orchestrates: card display, status polling, preflight modal, dev checks.    */
/* -------------------------------------------------------------------------- */

export function DeliveryChannelsSection() {
  const { role } = useAuth();
  const isAdmin = isPORole(role);

  // Hotfix 73/74 - non-PO callers use /me/status (per-user link state).
  // PO callers keep the org-level /status.
  const { slack, teams, refreshStatus } = useChannelStatus(
    isAdmin ? "org" : "me"
  );

  // Pre-flight modal state (PO only)
  const [preflightPlatform, setPreflightPlatform] = useState<
    "slack" | "teams" | null
  >(null);

  function handleConnect(platform: "slack" | "teams") {
    if (isAdmin) {
      // PO/Admin: show preflight transparency modal before workspace OAuth
      setPreflightPlatform(platform);
    } else {
      // Hotfix 73/74 - Developer/Stakeholder: directly initiate per-user
      // OAuth. The DevOrgCheckPanel email-match flow is gone - we now do
      // proper OAuth so the user picks (and consents to) which Slack /
      // Teams identity gets linked.
      const endpoint =
        platform === "slack"
          ? "/api/integrations/slack/me/connect"
          : "/api/integrations/teams/me/connect";
      window.location.href = endpoint;
    }
  }

  function handlePreflightContinue() {
    const platform = preflightPlatform;
    setPreflightPlatform(null);

    if (!platform) return;

    // Redirect to OAuth endpoint (PO workspace install)
    const endpoint =
      platform === "slack"
        ? "/api/integrations/slack/connect"
        : "/api/integrations/teams/connect";

    window.location.href = endpoint;
  }

  function handleDisconnect() {
    // Refresh status after disconnect
    setTimeout(refreshStatus, 500);
  }

  return (
    <>
      <div className="space-y-4">
        {/* Section header */}
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
            Delivery Channels
          </h3>
          <p className="mt-1.5 text-sm text-[var(--text-secondary)]">
            Connect Slack or Microsoft Teams to receive your notifications
            where you already work.
          </p>
        </div>

        {/* Hotfix 73/74 - DevOrgCheckPanel removed. Non-PO callers now go
            through proper per-user OAuth via /me/connect, which gives them
            consent + identity selection for free. The card itself shows
            their per-user link state via useChannelStatus("me"). */}

        {/* Platform cards - side by side on sm+, stacked on mobile */}
        <div className="grid gap-4 sm:grid-cols-2">
          <DeliveryChannelCard
            platform="slack"
            status={slack}
            onConnect={() => handleConnect("slack")}
            onDisconnect={handleDisconnect}
          />
          <DeliveryChannelCard
            platform="teams"
            status={teams}
            onConnect={() => handleConnect("teams")}
            onDisconnect={handleDisconnect}
          />
        </div>
      </div>

      {/* Pre-flight transparency modal (PO/Admin only) */}
      {preflightPlatform && (
        <ConnectPreflightModal
          open={!!preflightPlatform}
          onClose={() => setPreflightPlatform(null)}
          onContinue={handlePreflightContinue}
          platform={preflightPlatform}
        />
      )}
    </>
  );
}
