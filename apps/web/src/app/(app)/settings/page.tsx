"use client";

import { useState, useEffect, useCallback } from "react";
import { Settings, Loader2, Check, Clock, X as XIcon, AlertTriangle } from "lucide-react";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Button, Input, Select, FormField } from "@/components/ui";
import { useAuth } from "@/lib/auth/context";
import { isAdmin } from "@/lib/types/auth";
import { useAutoRefresh } from "@/lib/ws/context";

const TIMEZONES = [
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "America/Anchorage",
  "Pacific/Honolulu",
  "Europe/London",
  "Europe/Berlin",
  "Europe/Paris",
  "Asia/Tokyo",
  "Asia/Shanghai",
  "Asia/Kolkata",
  "Asia/Dubai",
  "Australia/Sydney",
  "Pacific/Auckland",
];

// Generate hour options from 00:00 to 23:30 in 30-min increments
const ALL_HOURS = Array.from({ length: 48 }, (_, i) => {
  const h = String(Math.floor(i / 2)).padStart(2, "0");
  const m = i % 2 === 0 ? "00" : "30";
  return `${h}:${m}`;
});

const HOUR_OPTIONS = ALL_HOURS;
const END_HOUR_OPTIONS = ALL_HOURS;

export default function GeneralSettingsPage() {
  const { role } = useAuth();
  const canEdit = isAdmin(role);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const [orgName, setOrgName] = useState("");
  const [timezone, setTimezone] = useState("America/New_York");
  const [workStart, setWorkStart] = useState("09:00");
  const [workEnd, setWorkEnd] = useState("17:00");
  const [saveError, setSaveError] = useState<string | null>(null);

  // Hotfix 86 - pending join request state. When the PO renames their org
  // to a name that matches an existing organisation, the API returns
  // 200 + {joinRequest: {status: "pending_approval", ...}} instead of
  // performing the migration immediately. We surface that here as a
  // distinct yellow card with a Cancel option.
  interface PendingRequest {
    id: string;
    targetOrgId: string;
    targetOrgName: string;
    approverEmail: string | null;
    approverName: string | null;
    createdAt?: string | null;
  }
  const [pending, setPending] = useState<PendingRequest | null>(null);

  // Refresh on join_request_resolved WS event so the moment the founder
  // approves/rejects, this page swaps state automatically.
  const wsKey = useAutoRefresh(["join_request_resolved", "join_request_created"]);

  const fetchPending = useCallback(async () => {
    try {
      const r = await fetch("/api/organizations/join-requests/mine");
      if (r.ok) {
        const d = await r.json();
        setPending(d.request);
      }
    } catch {/* noop */}
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch("/api/organizations/current");
        if (res.ok) {
          const data = await res.json();
          setOrgName(data.name || "");
          setTimezone(data.timezone || "America/New_York");
          setWorkStart(data.workingHoursStart || "09:00");
          setWorkEnd(data.workingHoursEnd || "17:00");
        }
      } catch {
        // API unavailable - keep defaults
      }
      await fetchPending();
      setLoading(false);
    })();
  }, [fetchPending, wsKey]);

  const handleSave = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const res = await fetch("/api/organizations/current", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: orgName,
          timezone,
          workingHoursStart: workStart,
          workingHoursEnd: workEnd,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.joinRequest && data.joinRequest.status === "pending_approval") {
          // Canonical-name match → approval pending. Show pending state.
          setPending({
            id: data.joinRequest.requestId,
            targetOrgId: data.joinRequest.targetOrgId,
            targetOrgName: data.joinRequest.targetOrgName,
            approverEmail: data.joinRequest.approverEmail,
            approverName: data.joinRequest.approverName,
          });
          // Reset the input back to the org's CURRENT name so the form
          // doesn't lie about state.
          setOrgName(data.name || "");
        } else {
          setSaved(true);
          setTimeout(() => setSaved(false), 2000);
        }
      } else {
        const err = await res.json().catch(() => ({}));
        setSaveError(err?.detail || "Save failed. Please try again.");
      }
    } catch {
      setSaveError("Network error. Please try again.");
    }
    setSaving(false);
  };

  const handleCancelRequest = async () => {
    if (!pending) return;
    try {
      await fetch(`/api/organizations/join-requests/${pending.id}/cancel`, {
        method: "POST",
      });
      setPending(null);
    } catch {/* noop */}
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-5 w-5 animate-spin text-[var(--text-secondary)]" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Hotfix 86 - pending join request banner. Visible whenever the
          PO has an open request waiting for the target org's founder. */}
      {pending && (
        <div
          className="rounded-xl border-2 p-4 flex items-start gap-3"
          style={{
            borderColor: "var(--color-rag-amber)",
            background: "color-mix(in srgb, var(--color-rag-amber) 8%, var(--bg-surface))",
          }}
        >
          <Clock className="h-5 w-5 shrink-0 mt-0.5" style={{ color: "var(--color-rag-amber)" }} />
          <div className="flex-1 min-w-0">
            <h3 className="text-sm font-bold" style={{ color: "var(--color-rag-amber)" }}>
              Pending approval to join &lsquo;{pending.targetOrgName}&rsquo;
            </h3>
            <p className="text-sm text-[var(--text-secondary)] mt-1 leading-relaxed">
              Plan2Sprint sent your join request to{" "}
              <b>{pending.approverName || pending.approverEmail || "the organization founder"}</b>
              {pending.approverEmail && pending.approverName && (
                <span className="text-xs text-[var(--text-tertiary)]"> ({pending.approverEmail})</span>
              )}
              . Your account will move into &lsquo;{pending.targetOrgName}&rsquo; the moment they
              approve. Until then you stay where you are.
            </p>
            <div className="mt-3 flex items-center gap-2">
              <Button size="sm" variant="secondary" onClick={handleCancelRequest}>
                <XIcon className="h-3.5 w-3.5 mr-1" />
                Cancel request
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Organization Settings */}
      <DashboardPanel title="Organization" icon={Settings}>
        <div className="space-y-5">
          <FormField label="Organization Name" required>
            <Input
              value={orgName}
              onChange={(e) => setOrgName(e.target.value)}
              placeholder="Your organization name"
              disabled={!canEdit}
            />
          </FormField>

          <FormField label="Timezone">
            <Select
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
              disabled={!canEdit}
            >
              {TIMEZONES.map((tz) => (
                <option key={tz} value={tz}>
                  {tz.replace(/_/g, " ")}
                </option>
              ))}
            </Select>
          </FormField>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <FormField label="Working Hours Start">
              <Select
                value={workStart}
                onChange={(e) => setWorkStart(e.target.value)}
                disabled={!canEdit}
              >
                {HOUR_OPTIONS.map((h) => (
                  <option key={h} value={h}>
                    {h}
                  </option>
                ))}
              </Select>
            </FormField>

            <FormField label="Working Hours End">
              <Select
                value={workEnd}
                onChange={(e) => setWorkEnd(e.target.value)}
                disabled={!canEdit}
              >
                {END_HOUR_OPTIONS.map((h) => (
                  <option key={h} value={h}>
                    {h}
                  </option>
                ))}
              </Select>
            </FormField>
          </div>
        </div>
      </DashboardPanel>

      {/* Save */}
      {canEdit && (
        <div className="flex flex-col items-end gap-2">
          {saveError && (
            <div
              className="flex items-center gap-2 px-3 py-2 rounded-lg border text-sm"
              style={{
                borderColor: "var(--color-rag-red)",
                background: "color-mix(in srgb, var(--color-rag-red) 8%, var(--bg-surface))",
                color: "var(--color-rag-red)",
              }}
            >
              <AlertTriangle className="h-3.5 w-3.5" />
              {saveError}
            </div>
          )}
          <Button
            variant="primary"
            size="md"
            onClick={handleSave}
            disabled={saving || !!pending}
            title={pending ? "Cancel the pending request first" : undefined}
          >
            {saving ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : saved ? (
              <Check className="h-4 w-4" />
            ) : null}
            {saving ? "Saving..." : saved ? "Saved" : "Save Changes"}
          </Button>
        </div>
      )}
    </div>
  );
}
