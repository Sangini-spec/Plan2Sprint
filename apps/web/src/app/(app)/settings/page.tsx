"use client";

import { useState, useEffect } from "react";
import { Settings, Loader2, Check } from "lucide-react";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Button, Input, Select, FormField } from "@/components/ui";
import { useAuth } from "@/lib/auth/context";
import { isAdmin } from "@/lib/types/auth";

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
        // API unavailable — keep defaults
      }
      setLoading(false);
    })();
  }, []);

  const handleSave = async () => {
    setSaving(true);
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
        setSaved(true);
        setTimeout(() => setSaved(false), 2000);
      }
    } catch {
      // Handle error silently
    }
    setSaving(false);
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
        <div className="flex justify-end">
          <Button
            variant="primary"
            size="md"
            onClick={handleSave}
            disabled={saving}
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
