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
import { TeamsLogo } from "./platform-logos";

/* -------------------------------------------------------------------------- */
/*  TYPES                                                                       */
/* -------------------------------------------------------------------------- */

interface TeamsUser {
  id: string;
  displayName: string;
  mail?: string;
  userPrincipalName?: string;
}

interface TeamsProjectChannel {
  id: string;            // project internalId
  name: string;          // project name
  channelName: string;   // teams channel displayName
}

/* -------------------------------------------------------------------------- */
/*  COMPONENT                                                                   */
/* -------------------------------------------------------------------------- */

export function TeamsMessageComposer() {
  const [message, setMessage] = useState("");
  const [targetType, setTargetType] = useState<"channel" | "dm">("dm");
  const [users, setUsers] = useState<TeamsUser[]>([]);
  const [projects, setProjects] = useState<TeamsProjectChannel[]>([]);
  const [selectedTarget, setSelectedTarget] = useState("");
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<"success" | "error" | null>(null);
  const [errorDetail, setErrorDetail] = useState("");
  const [loadingTargets, setLoadingTargets] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);

  // Fetch users (DM) and project channels on mount
  const fetchTargets = useCallback(async () => {
    setLoadingTargets(true);
    try {
      // Teams users (for DM)
      const usersRes = await fetch("/api/integrations/teams/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (usersRes.ok) {
        const data = await usersRes.json();
        setUsers(data.users ?? []);
      }

      // Project channels (channel posting goes via project channel)
      const projRes = await fetch("/api/projects");
      if (projRes.ok) {
        const projData = await projRes.json();
        const list = projData.projects || [];
        const withCh = await Promise.all(
          list.map(async (p: { internalId: string; id: string; name: string }) => {
            const projId = p.internalId || p.id;
            try {
              const r = await fetch(`/api/integrations/teams/project-channel?projectId=${projId}`);
              if (r.ok) {
                const d = await r.json();
                if (d.hasChannel) {
                  return { id: projId, name: p.name, channelName: d.channelName };
                }
              }
            } catch { /* ignore */ }
            return null;
          })
        );
        setProjects(withCh.filter((x): x is TeamsProjectChannel => x !== null));
      }
    } catch {
      // Ignore — targets just won't load
    } finally {
      setLoadingTargets(false);
    }
  }, []);

  useEffect(() => {
    fetchTargets();
  }, [fetchTargets]);

  // When target type changes, reset selection
  useEffect(() => {
    if (targetType === "dm" && users.length > 0) {
      setSelectedTarget(users[0].id);
    } else if (targetType === "channel" && projects.length > 0) {
      setSelectedTarget(projects[0].id);
    } else {
      setSelectedTarget("");
    }
  }, [targetType, users, projects]);

  async function handleSend() {
    if (!message.trim() || !selectedTarget) return;

    setSending(true);
    setResult(null);
    setErrorDetail("");

    try {
      let res: Response;
      if (targetType === "dm") {
        res = await fetch("/api/integrations/teams/send", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            user_id: selectedTarget,
            content: message.trim(),
            content_type: "text",
          }),
        });
      } else {
        res = await fetch("/api/integrations/teams/post-to-channel", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            projectId: selectedTarget,
            type: "custom_message",
            data: { message: message.trim() },
          }),
        });
      }

      const data = await res.json().catch(() => ({}));
      if (res.ok && (data.ok !== false)) {
        setResult("success");
        setMessage("");
      } else {
        setResult("error");
        setErrorDetail(data.message || data.detail || "Failed to send message");
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
      ? users.find((u) => u.id === selectedTarget)?.displayName || "Select user"
      : projects.find((p) => p.id === selectedTarget)?.channelName || "Select channel";

  const targetList =
    targetType === "dm"
      ? users.map((u) => ({ id: u.id, label: u.displayName || u.mail || "Unknown" }))
      : projects.map((p) => ({ id: p.id, label: p.channelName }));

  return (
    <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]/80 backdrop-blur-xl p-5 space-y-4">
      {/* Header */}
      <div className="flex items-center gap-2.5">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#5059C9]/10">
          <TeamsLogo size={18} />
        </div>
        <div>
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">
            Send Message to Microsoft Teams
          </h3>
          <p className="text-[11px] text-[var(--text-secondary)]">
            Send a 1:1 chat to a teammate or post to a project channel
          </p>
        </div>
      </div>

      {/* Target selector */}
      <div className="flex items-center gap-2">
        {/* Type toggle */}
        <div className="flex rounded-lg border border-[var(--border-subtle)] overflow-hidden shrink-0">
          <button
            onClick={() => setTargetType("dm")}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer",
              targetType === "dm"
                ? "bg-[#5059C9]/10 text-[#5059C9]"
                : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            )}
          >
            <AtSign size={12} />
            DM
          </button>
          {projects.length > 0 && (
            <button
              onClick={() => setTargetType("channel")}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer border-l border-[var(--border-subtle)]",
                targetType === "channel"
                  ? "bg-[#5059C9]/10 text-[#5059C9]"
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
              "hover:border-[#5059C9]/40 transition-colors cursor-pointer"
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
                      ? "bg-[#5059C9]/10 text-[#5059C9]"
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
            "focus:outline-none focus:ring-2 focus:ring-[#5059C9]/40",
            "resize-none"
          )}
        />
        <div className="absolute right-2 bottom-2">
          <MessageSquare size={14} className="text-[var(--text-tertiary)]" />
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
            "bg-[#5059C9] text-white",
            "hover:bg-[#5059C9]/90 transition-all cursor-pointer",
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
              Send to Teams
            </>
          )}
        </button>
      </div>
    </div>
  );
}
