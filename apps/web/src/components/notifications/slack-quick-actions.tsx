"use client";

import { useState } from "react";
import {
  AlertTriangle,
  Loader2,
  CheckCircle2,
  Send,
  FileText,
  Flag,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { SlackLogo } from "./platform-logos";

/* -------------------------------------------------------------------------- */
/*  TYPES                                                                       */
/* -------------------------------------------------------------------------- */

type ActionType =
  | "escalate_blocker"
  | "retro_summary"
  | "flag_blocker";

type UserRole = "po" | "dev";

interface QuickAction {
  id: ActionType;
  label: string;
  description: string;
  icon: typeof AlertTriangle;
  color: string;
  bg: string;
}

/* -------------------------------------------------------------------------- */
/*  ROLE-SPECIFIC ACTIONS                                                       */
/* -------------------------------------------------------------------------- */

const PO_ACTIONS: QuickAction[] = [
  {
    id: "escalate_blocker",
    label: "Escalate Blocker",
    description: "Escalate a critical blocker to the team Slack channel",
    icon: AlertTriangle,
    color: "text-[var(--color-rag-red)]",
    bg: "bg-[var(--color-rag-red)]/10",
  },
  {
    id: "retro_summary",
    label: "Send Retrospective Summary",
    description: "Push the sprint retrospective outcomes to the team channel",
    icon: FileText,
    color: "text-[var(--color-brand-secondary)]",
    bg: "bg-[var(--color-brand-secondary)]/10",
  },
];

const DEV_ACTIONS: QuickAction[] = [
  {
    id: "flag_blocker",
    label: "Flag a Blocker",
    description: "Raise a blocker directly to Slack — your PO will be notified",
    icon: Flag,
    color: "text-[var(--color-rag-red)]",
    bg: "bg-[var(--color-rag-red)]/10",
  },
];

/* -------------------------------------------------------------------------- */
/*  COMPONENT                                                                   */
/* -------------------------------------------------------------------------- */

interface SlackQuickActionsProps {
  role?: UserRole;
}

export function SlackQuickActions({ role = "po" }: SlackQuickActionsProps) {
  const [sending, setSending] = useState<ActionType | null>(null);
  const [result, setResult] = useState<Record<string, "success" | "error">>({});

  const actions = role === "dev" ? DEV_ACTIONS : PO_ACTIONS;

  async function handleAction(actionId: ActionType) {
    setSending(actionId);
    setResult((prev) => ({ ...prev, [actionId]: undefined as unknown as "success" | "error" }));

    try {
      const res = await fetch("/api/integrations/slack/trigger-notification", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: actionId }),
      });

      if (res.ok) {
        setResult((prev) => ({ ...prev, [actionId]: "success" }));
      } else {
        setResult((prev) => ({ ...prev, [actionId]: "error" }));
      }
    } catch {
      setResult((prev) => ({ ...prev, [actionId]: "error" }));
    } finally {
      setSending(null);
      setTimeout(() => {
        setResult((prev) => {
          const next = { ...prev };
          delete next[actionId];
          return next;
        });
      }, 4000);
    }
  }

  return (
    <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]/80 backdrop-blur-xl p-5 space-y-4">
      {/* Header */}
      <div className="flex items-center gap-2.5">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#4A154B]/10">
          <SlackLogo size={18} />
        </div>
        <div>
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">
            Send to Slack
          </h3>
          <p className="text-[11px] text-[var(--text-secondary)]">
            {role === "dev"
              ? "Flag blockers directly to Slack — your PO will be notified instantly"
              : "Human-initiated actions — system handles everything else automatically"}
          </p>
        </div>
      </div>

      {/* Action buttons */}
      <div className={cn("grid gap-2", actions.length > 1 ? "sm:grid-cols-2" : "sm:grid-cols-1 max-w-md")}>
        {actions.map((action) => {
          const Icon = action.icon;
          const isSending = sending === action.id;
          const actionResult = result[action.id];

          return (
            <button
              key={action.id}
              onClick={() => handleAction(action.id)}
              disabled={!!sending}
              className={cn(
                "flex items-start gap-3 rounded-xl border border-[var(--border-subtle)] p-3.5",
                "text-left transition-all cursor-pointer",
                "hover:border-[var(--color-brand-secondary)]/30 hover:bg-[var(--bg-surface-raised)]/30",
                "disabled:opacity-50 disabled:cursor-not-allowed",
                actionResult === "success" && "border-[var(--color-rag-green)]/30 bg-[var(--color-rag-green)]/5",
                actionResult === "error" && "border-[var(--color-rag-red)]/30 bg-[var(--color-rag-red)]/5"
              )}
            >
              <div
                className={cn(
                  "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
                  action.bg
                )}
              >
                {isSending ? (
                  <Loader2 size={16} className="animate-spin text-[var(--text-secondary)]" />
                ) : actionResult === "success" ? (
                  <CheckCircle2 size={16} className="text-[var(--color-rag-green)]" />
                ) : (
                  <Icon size={16} className={action.color} />
                )}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5">
                  <p className="text-xs font-semibold text-[var(--text-primary)] truncate">
                    {action.label}
                  </p>
                  <Send size={10} className="shrink-0 text-[var(--text-tertiary)]" />
                </div>
                <p className="text-[10px] text-[var(--text-secondary)] mt-0.5 leading-relaxed line-clamp-2">
                  {actionResult === "success"
                    ? "Sent to Slack!"
                    : actionResult === "error"
                      ? "Failed — check Slack connection"
                      : action.description}
                </p>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
