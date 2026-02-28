"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Send,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  Hash,
  AtSign,
  ChevronDown,
  MessageSquare,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { SlackLogo } from "./platform-logos";

/* -------------------------------------------------------------------------- */
/*  TYPES                                                                       */
/* -------------------------------------------------------------------------- */

interface SlackChannel {
  id: string;
  name: string;
  type: "channel" | "dm";
}

interface SlackUser {
  id: string;
  name: string;
  real_name: string;
  email: string;
}

/* -------------------------------------------------------------------------- */
/*  COMPONENT                                                                   */
/* -------------------------------------------------------------------------- */

export function SlackMessageComposer() {
  const [message, setMessage] = useState("");
  const [targetType, setTargetType] = useState<"channel" | "dm">("dm");
  const [channels, setChannels] = useState<SlackChannel[]>([]);
  const [users, setUsers] = useState<SlackUser[]>([]);
  const [selectedTarget, setSelectedTarget] = useState("");
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<"success" | "error" | null>(null);
  const [errorDetail, setErrorDetail] = useState("");
  const [loadingTargets, setLoadingTargets] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);

  // Fetch channels and users on mount
  const fetchTargets = useCallback(async () => {
    setLoadingTargets(true);
    try {
      // Fetch Slack users for DM
      const usersRes = await fetch("/api/integrations/slack/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (usersRes.ok) {
        const data = await usersRes.json();
        setUsers(data.users ?? []);
        if (data.users?.length > 0 && !selectedTarget) {
          setSelectedTarget(data.users[0].id);
        }
      }

      // Fetch channels
      const channelsRes = await fetch("/api/integrations/slack/channels", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (channelsRes.ok) {
        const data = await channelsRes.json();
        setChannels(
          (data.channels ?? []).map((c: { id: string; name: string }) => ({
            id: c.id,
            name: c.name,
            type: "channel" as const,
          }))
        );
      }
    } catch {
      // Ignore — targets just won't load
    } finally {
      setLoadingTargets(false);
    }
  }, [selectedTarget]);

  useEffect(() => {
    fetchTargets();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // When target type changes, reset selection
  useEffect(() => {
    if (targetType === "dm" && users.length > 0) {
      setSelectedTarget(users[0].id);
    } else if (targetType === "channel" && channels.length > 0) {
      setSelectedTarget(channels[0].id);
    }
  }, [targetType, users, channels]);

  async function handleSend() {
    if (!message.trim() || !selectedTarget) return;

    setSending(true);
    setResult(null);
    setErrorDetail("");

    try {
      const res = await fetch("/api/integrations/slack/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          channel: selectedTarget,
          text: message.trim(),
        }),
      });

      if (res.ok) {
        setResult("success");
        setMessage("");
      } else {
        const data = await res.json().catch(() => ({}));
        setResult("error");
        setErrorDetail(data.detail || "Failed to send message");
      }
    } catch {
      setResult("error");
      setErrorDetail("Network error");
    } finally {
      setSending(false);
      setTimeout(() => setResult(null), 4000);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  const currentTargetName =
    targetType === "dm"
      ? users.find((u) => u.id === selectedTarget)?.real_name || "Select user"
      : channels.find((c) => c.id === selectedTarget)?.name || "Select channel";

  const targetList =
    targetType === "dm"
      ? users.map((u) => ({ id: u.id, label: u.real_name || u.name }))
      : channels.map((c) => ({ id: c.id, label: `#${c.name}` }));

  return (
    <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]/80 backdrop-blur-xl p-5 space-y-4">
      {/* Header */}
      <div className="flex items-center gap-2.5">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#4A154B]/10">
          <SlackLogo size={18} />
        </div>
        <div>
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">
            Send Message to Slack
          </h3>
          <p className="text-[11px] text-[var(--text-secondary)]">
            Type a message and send it directly to a Slack channel or DM
          </p>
        </div>
      </div>

      {/* Target selector */}
      <div className="flex items-center gap-2">
        {/* Type toggle — only show Channel option if channels are available */}
        <div className="flex rounded-lg border border-[var(--border-subtle)] overflow-hidden shrink-0">
          <button
            onClick={() => setTargetType("dm")}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer",
              targetType === "dm"
                ? "bg-[var(--color-brand-secondary)]/10 text-[var(--color-brand-secondary)]"
                : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            )}
          >
            <AtSign size={12} />
            DM
          </button>
          {channels.length > 0 && (
            <button
              onClick={() => setTargetType("channel")}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer border-l border-[var(--border-subtle)]",
                targetType === "channel"
                  ? "bg-[var(--color-brand-secondary)]/10 text-[var(--color-brand-secondary)]"
                  : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
              )}
            >
              <Hash size={12} />
              Channel
            </button>
          )}
        </div>

        {/* Target dropdown */}
        <div className="relative flex-1">
          <button
            onClick={() => setDropdownOpen(!dropdownOpen)}
            disabled={loadingTargets}
            className={cn(
              "w-full flex items-center justify-between rounded-lg border border-[var(--border-subtle)] px-3 py-1.5",
              "text-sm text-[var(--text-primary)] bg-[var(--bg-surface)]",
              "hover:border-[var(--color-brand-secondary)]/40 transition-colors cursor-pointer"
            )}
          >
            <span className="truncate">
              {loadingTargets ? "Loading..." : currentTargetName}
            </span>
            <ChevronDown
              size={14}
              className={cn(
                "shrink-0 text-[var(--text-secondary)] transition-transform",
                dropdownOpen && "rotate-180"
              )}
            />
          </button>

          {dropdownOpen && targetList.length > 0 && (
            <div className="absolute z-50 top-full mt-1 w-full max-h-48 overflow-y-auto rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-xl">
              {targetList.map((item) => (
                <button
                  key={item.id}
                  onClick={() => {
                    setSelectedTarget(item.id);
                    setDropdownOpen(false);
                  }}
                  className={cn(
                    "w-full text-left px-3 py-2 text-sm transition-colors cursor-pointer",
                    selectedTarget === item.id
                      ? "bg-[var(--color-brand-secondary)]/10 text-[var(--color-brand-secondary)]"
                      : "text-[var(--text-primary)] hover:bg-[var(--bg-surface-raised)]"
                  )}
                >
                  {item.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Message input */}
      <div className="relative">
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type your message... (Enter to send, Shift+Enter for new line)"
          rows={3}
          className={cn(
            "w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-4 py-3 pr-12",
            "text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)]",
            "focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)]/40",
            "resize-none"
          )}
        />
        <div className="absolute right-2 bottom-2">
          <MessageSquare
            size={14}
            className="text-[var(--text-tertiary)]"
          />
        </div>
      </div>

      {/* Send button + result */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {result === "success" && (
            <span className="inline-flex items-center gap-1 text-xs font-medium text-[var(--color-rag-green)]">
              <CheckCircle2 size={12} />
              Message sent!
            </span>
          )}
          {result === "error" && (
            <span className="inline-flex items-center gap-1 text-xs font-medium text-[var(--color-rag-red)]">
              <AlertTriangle size={12} />
              {errorDetail || "Failed to send"}
            </span>
          )}
        </div>

        <button
          onClick={handleSend}
          disabled={sending || !message.trim() || !selectedTarget}
          className={cn(
            "flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium",
            "bg-[#4A154B] text-white",
            "hover:bg-[#4A154B]/90 transition-all cursor-pointer",
            "disabled:opacity-50 disabled:cursor-not-allowed"
          )}
        >
          {sending ? (
            <>
              <Loader2 size={14} className="animate-spin" />
              Sending...
            </>
          ) : (
            <>
              <Send size={14} />
              Send to Slack
            </>
          )}
        </button>
      </div>
    </div>
  );
}
