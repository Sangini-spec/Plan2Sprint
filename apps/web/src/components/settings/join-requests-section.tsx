"use client";

/**
 * Founder-side approval UI for canonical-match join requests
 * (Hotfix 86).
 *
 * Renders a card with one row per pending request, each with Approve
 * and Reject buttons. Founder-only — the API decides who's the
 * founder; for non-founders the API returns isFounder=false and we
 * render nothing.
 *
 * Lives on Settings → Team, above the existing "Pending Invitations"
 * card so the workflow is grouped: invites you sent + requests
 * coming in.
 */

import { useEffect, useState, useCallback } from "react";
import { ShieldCheck, Loader2, X as XIcon, Check, Inbox } from "lucide-react";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Button, Badge } from "@/components/ui";
import { useAutoRefresh } from "@/lib/ws/context";
import { cn } from "@/lib/utils";

interface JoinRequest {
  id: string;
  requesterEmail: string;
  requesterName: string | null;
  targetOrgName: string;
  createdAt: string | null;
}

function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const ms = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(ms / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function JoinRequestsSection() {
  const [requests, setRequests] = useState<JoinRequest[]>([]);
  const [isFounder, setIsFounder] = useState(false);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState<{ id: string; kind: "approve" | "reject" } | null>(null);
  const [feedback, setFeedback] = useState<{ kind: "ok" | "err"; msg: string } | null>(null);

  const wsKey = useAutoRefresh(["join_request_created", "join_request_resolved"]);

  const fetchRequests = useCallback(async () => {
    try {
      const res = await fetch("/api/organizations/current/join-requests");
      if (res.ok) {
        const d = await res.json();
        setIsFounder(d.isFounder === true);
        setRequests(d.requests || []);
      }
    } catch { /* keep silent */ }
    setLoading(false);
  }, []);

  useEffect(() => { fetchRequests(); }, [fetchRequests, wsKey]);

  const act = async (id: string, kind: "approve" | "reject") => {
    setActing({ id, kind });
    setFeedback(null);
    try {
      const res = await fetch(`/api/organizations/join-requests/${id}/${kind}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: kind === "reject" ? JSON.stringify({}) : "{}",
      });
      if (res.ok) {
        setFeedback({ kind: "ok", msg: kind === "approve" ? "Approved — user has been moved into your organisation." : "Rejected." });
        setRequests((rs) => rs.filter((r) => r.id !== id));
      } else {
        const err = await res.json().catch(() => ({}));
        setFeedback({ kind: "err", msg: err?.detail || `${kind} failed` });
      }
    } catch {
      setFeedback({ kind: "err", msg: "Network error" });
    }
    setActing(null);
    setTimeout(() => setFeedback(null), 4000);
  };

  // Hide the entire card for non-founders OR when there are no requests
  // (avoids visual noise — founders without pending requests don't need
  // an empty section either).
  if (loading) return null;
  if (!isFounder) return null;
  if (requests.length === 0) return null;

  return (
    <DashboardPanel
      title="Join Requests"
      icon={ShieldCheck}
      actions={<Badge variant="rag-amber">{requests.length} pending</Badge>}
    >
      <p className="text-sm text-[var(--text-secondary)] mb-4">
        These users typed your organisation name when renaming their own
        organisation, so Plan2Sprint queued them for your approval.
        Approving moves them (and any data they own) into your tenant
        as a Product Owner. Rejecting leaves them in their own
        organisation untouched.
      </p>

      {feedback && (
        <div
          className="mb-3 p-3 rounded-lg text-sm flex items-center gap-2"
          style={{
            background: feedback.kind === "ok"
              ? "color-mix(in srgb, var(--color-rag-green) 8%, var(--bg-surface))"
              : "color-mix(in srgb, var(--color-rag-red) 8%, var(--bg-surface))",
            color: feedback.kind === "ok"
              ? "var(--color-rag-green)"
              : "var(--color-rag-red)",
            border: `1px solid ${feedback.kind === "ok" ? "var(--color-rag-green)" : "var(--color-rag-red)"}`,
          }}
        >
          {feedback.kind === "ok" ? <Check className="h-4 w-4" /> : <XIcon className="h-4 w-4" />}
          {feedback.msg}
        </div>
      )}

      <div className="space-y-2">
        {requests.map((r) => (
          <div
            key={r.id}
            className="flex items-center justify-between gap-3 p-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/30"
          >
            <div className="flex items-center gap-3 min-w-0">
              <div className="flex h-9 w-9 items-center justify-center rounded-full bg-[var(--color-brand-secondary)]/15 shrink-0">
                <Inbox className="h-4 w-4 text-[var(--color-brand-secondary)]" />
              </div>
              <div className="min-w-0">
                <p className="text-sm font-medium text-[var(--text-primary)] truncate">
                  {r.requesterName || r.requesterEmail}
                </p>
                <p className="text-xs text-[var(--text-secondary)] truncate">
                  {r.requesterEmail}
                  {r.createdAt && (
                    <span className="text-[var(--text-tertiary)]"> &middot; {timeAgo(r.createdAt)}</span>
                  )}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={() => act(r.id, "reject")}
                disabled={!!acting}
                className={cn(
                  "px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors cursor-pointer",
                  "border-[var(--border-subtle)] text-[var(--text-secondary)]",
                  "hover:border-[var(--color-rag-red)] hover:text-[var(--color-rag-red)]",
                  "disabled:opacity-40 disabled:cursor-not-allowed"
                )}
              >
                {acting?.id === r.id && acting.kind === "reject"
                  ? <Loader2 className="h-3 w-3 animate-spin" />
                  : "Reject"}
              </button>
              <Button
                size="sm"
                variant="primary"
                onClick={() => act(r.id, "approve")}
                disabled={!!acting}
              >
                {acting?.id === r.id && acting.kind === "approve"
                  ? <Loader2 className="h-3 w-3 animate-spin mr-1" />
                  : <Check className="h-3 w-3 mr-1" />}
                Approve
              </Button>
            </div>
          </div>
        ))}
      </div>
    </DashboardPanel>
  );
}
