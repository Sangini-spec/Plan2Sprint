"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  X,
  Shield,
  CheckCircle2,
  Ban,
  AlertTriangle,
  Copy,
  CheckCheck,
  ExternalLink,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui";
import { SlackLogo, TeamsLogo } from "./platform-logos";

/* -------------------------------------------------------------------------- */
/*  PERMISSION DEFINITIONS                                                      */
/* -------------------------------------------------------------------------- */

interface PermissionItem {
  label: string;
  description: string;
}

const SLACK_ALLOWED: PermissionItem[] = [
  {
    label: "Send messages as Plan2Sprint",
    description:
      "Deliver standup reports, blocker alerts, and sprint notifications via DM.",
  },
  {
    label: "Read workspace user list",
    description:
      "Match Slack accounts to Plan2Sprint users by email for delivery routing.",
  },
  {
    label: "Read public channel list",
    description:
      "Let you pick a channel for team-wide digests (optional).",
  },
  {
    label: "Read user email addresses",
    description:
      "Used exclusively for account matching — never stored or shared.",
  },
];

const SLACK_DENIED: PermissionItem[] = [
  {
    label: "Read your messages or files",
    description: "Plan2Sprint never accesses message history or uploaded files.",
  },
  {
    label: "Join channels or modify workspace",
    description: "The bot cannot join channels, create groups, or change settings.",
  },
  {
    label: "Access private channels or DMs",
    description:
      "No access to any existing conversations — only sends new messages.",
  },
];

const TEAMS_ALLOWED: PermissionItem[] = [
  {
    label: "Send chat messages as Plan2Sprint",
    description:
      "Deliver standup reports, alerts, and notifications via 1:1 chat.",
  },
  {
    label: "Read organization user directory",
    description:
      "Match Teams accounts to Plan2Sprint users for delivery routing.",
  },
  {
    label: "Read channel information",
    description:
      "Let you pick a Teams channel for team-wide digests (optional).",
  },
];

const TEAMS_DENIED: PermissionItem[] = [
  {
    label: "Read your messages or files",
    description:
      "Plan2Sprint never accesses your chat history or shared documents.",
  },
  {
    label: "Modify teams or channels",
    description:
      "Cannot create, delete, or modify any teams, channels, or memberships.",
  },
  {
    label: "Access email or calendar",
    description:
      "No access to Outlook mail, calendar events, or OneDrive files.",
  },
];

/* -------------------------------------------------------------------------- */
/*  CONNECT PREFLIGHT MODAL                                                     */
/*                                                                              */
/*  Transparency layer shown to PO/Admin before OAuth redirect.                 */
/*  Shows exactly what permissions are requested and what is NOT accessed.       */
/* -------------------------------------------------------------------------- */

interface ConnectPreflightModalProps {
  open: boolean;
  onClose: () => void;
  onContinue: () => void;
  platform: "slack" | "teams";
}

export function ConnectPreflightModal({
  open,
  onClose,
  onContinue,
  platform,
}: ConnectPreflightModalProps) {
  const [copiedLink, setCopiedLink] = useState(false);

  const isSlack = platform === "slack";
  const platformName = isSlack ? "Slack" : "Microsoft Teams";
  const Logo = isSlack ? SlackLogo : TeamsLogo;
  const allowed = isSlack ? SLACK_ALLOWED : TEAMS_ALLOWED;
  const denied = isSlack ? SLACK_DENIED : TEAMS_DENIED;

  function handleCopyApprovalLink() {
    const link = `${window.location.origin}/settings/connections`;
    navigator.clipboard.writeText(link);
    setCopiedLink(true);
    setTimeout(() => setCopiedLink(false), 2500);
  }

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm"
            onClick={onClose}
          />

          {/* Modal */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 8 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
            className={cn(
              "fixed left-1/2 top-1/2 z-50 -translate-x-1/2 -translate-y-1/2",
              "w-full max-w-lg max-h-[85vh] overflow-y-auto",
              "rounded-2xl border border-[var(--border-subtle)]",
              "bg-[var(--bg-surface)] shadow-2xl shadow-black/20"
            )}
          >
            {/* Header */}
            <div className="sticky top-0 z-10 flex items-center justify-between gap-4 px-6 py-5 border-b border-[var(--border-subtle)] bg-[var(--bg-surface)]">
              <div className="flex items-center gap-3">
                <div
                  className={cn(
                    "flex h-10 w-10 items-center justify-center rounded-xl shrink-0",
                    isSlack ? "bg-[#4A154B]/10" : "bg-[#5059C9]/10"
                  )}
                >
                  <Logo size={24} />
                </div>
                <div>
                  <h2 className="text-base font-semibold text-[var(--text-primary)]">
                    Connect {platformName}
                  </h2>
                  <p className="text-xs text-[var(--text-secondary)]">
                    Review permissions before connecting
                  </p>
                </div>
              </div>
              <button
                onClick={onClose}
                className="flex h-8 w-8 items-center justify-center rounded-lg text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-surface-raised)] transition-colors cursor-pointer"
              >
                <X size={18} />
              </button>
            </div>

            {/* Body */}
            <div className="px-6 py-5 space-y-6">
              {/* What we access */}
              <div className="space-y-3">
                <h3 className="text-sm font-semibold text-[var(--text-primary)] flex items-center gap-2">
                  <CheckCircle2
                    size={16}
                    className="text-[var(--color-rag-green)]"
                  />
                  What Plan2Sprint will access
                </h3>
                <div className="space-y-2.5">
                  {allowed.map((item, i) => (
                    <div
                      key={i}
                      className="flex items-start gap-3 rounded-xl bg-[var(--color-rag-green)]/5 border border-[var(--color-rag-green)]/10 px-4 py-3"
                    >
                      <CheckCircle2
                        size={15}
                        className="text-[var(--color-rag-green)] shrink-0 mt-0.5"
                      />
                      <div>
                        <p className="text-sm font-medium text-[var(--text-primary)]">
                          {item.label}
                        </p>
                        <p className="text-xs text-[var(--text-secondary)] mt-0.5 leading-relaxed">
                          {item.description}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* What we DON'T access */}
              <div className="space-y-3">
                <h3 className="text-sm font-semibold text-[var(--text-primary)] flex items-center gap-2">
                  <Ban size={16} className="text-[var(--color-rag-red)]" />
                  What Plan2Sprint will never do
                </h3>
                <div className="space-y-2.5">
                  {denied.map((item, i) => (
                    <div
                      key={i}
                      className="flex items-start gap-3 rounded-xl bg-[var(--color-rag-red)]/5 border border-[var(--color-rag-red)]/10 px-4 py-3"
                    >
                      <Ban
                        size={15}
                        className="text-[var(--color-rag-red)] shrink-0 mt-0.5"
                      />
                      <div>
                        <p className="text-sm font-medium text-[var(--text-primary)]">
                          {item.label}
                        </p>
                        <p className="text-xs text-[var(--text-secondary)] mt-0.5 leading-relaxed">
                          {item.description}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Teams-specific: IT admin warning */}
              {!isSlack && (
                <div className="rounded-xl border border-[var(--color-rag-amber)]/20 bg-[var(--color-rag-amber)]/5 p-4">
                  <div className="flex items-start gap-3">
                    <AlertTriangle
                      size={16}
                      className="text-[var(--color-rag-amber)] shrink-0 mt-0.5"
                    />
                    <div className="space-y-2">
                      <p className="text-sm font-medium text-[var(--text-primary)]">
                        Tenant admin approval may be required
                      </p>
                      <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
                        Your Microsoft 365 tenant admin may need to grant
                        consent for Plan2Sprint to send messages. If the
                        connection fails, share the approval link with your IT
                        team.
                      </p>
                      <button
                        onClick={handleCopyApprovalLink}
                        className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--color-brand-secondary)] hover:underline cursor-pointer"
                      >
                        {copiedLink ? (
                          <>
                            <CheckCheck size={12} />
                            Copied!
                          </>
                        ) : (
                          <>
                            <Copy size={12} />
                            Copy approval request link for IT admin
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {/* Slack-specific: minimal scopes note */}
              {isSlack && (
                <div className="flex items-start gap-2.5 rounded-xl bg-[var(--bg-surface-raised)] px-4 py-3">
                  <Shield
                    size={15}
                    className="text-[var(--color-brand-secondary)] shrink-0 mt-0.5"
                  />
                  <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
                    Plan2Sprint uses minimal bot-level scopes only. Your
                    personal Slack data, messages, and files remain completely
                    private.
                  </p>
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="sticky bottom-0 flex items-center justify-end gap-3 px-6 py-4 border-t border-[var(--border-subtle)] bg-[var(--bg-surface)]">
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] rounded-xl hover:bg-[var(--bg-surface-raised)] transition-colors cursor-pointer"
              >
                Cancel
              </button>
              <Button variant="primary" onClick={onContinue}>
                <ExternalLink size={14} className="mr-1.5" />
                Continue to {platformName}
              </Button>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
