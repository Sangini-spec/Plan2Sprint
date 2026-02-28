"use client";

import { useState } from "react";
import { Settings } from "lucide-react";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Button, Input, Select, FormField, Badge } from "@/components/ui";

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

const HOUR_OPTIONS = [
  "06:00",
  "06:30",
  "07:00",
  "07:30",
  "08:00",
  "08:30",
  "09:00",
  "09:30",
  "10:00",
  "10:30",
  "11:00",
];

const END_HOUR_OPTIONS = [
  "16:00",
  "16:30",
  "17:00",
  "17:30",
  "18:00",
  "18:30",
  "19:00",
  "19:30",
  "20:00",
];

export default function GeneralSettingsPage() {
  const [orgName, setOrgName] = useState("Acme Corp");
  const [timezone, setTimezone] = useState("America/New_York");
  const [workStart, setWorkStart] = useState("09:00");
  const [workEnd, setWorkEnd] = useState("17:00");
  const [displayName, setDisplayName] = useState("Jordan Rivera");
  const [email] = useState("jordan.rivera@acme.com");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-[var(--text-primary)]">
          General Settings
        </h1>
        <p className="mt-1 text-sm text-[var(--text-secondary)]">
          Manage your organization and account preferences.
        </p>
      </div>

      {/* Organization Settings */}
      <DashboardPanel title="Organization Settings" icon={Settings}>
        <div className="space-y-5">
          <FormField label="Organization Name" required>
            <Input
              value={orgName}
              onChange={(e) => setOrgName(e.target.value)}
              placeholder="Your organization name"
            />
          </FormField>

          <FormField label="Timezone">
            <Select
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
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

      {/* Account Settings */}
      <DashboardPanel title="Account Settings" icon={Settings}>
        <div className="space-y-5">
          <FormField label="Display Name">
            <Input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Your display name"
            />
          </FormField>

          <FormField label="Email Address">
            <Input value={email} disabled />
            <p className="text-xs text-[var(--text-secondary)] mt-1">
              Email is managed through your authentication provider and cannot be
              changed here.
            </p>
          </FormField>

          <FormField label="Role">
            <div className="flex items-center gap-3 h-10">
              <Badge variant="brand">Product Owner</Badge>
              <span className="text-xs text-[var(--text-secondary)]">
                Contact an admin to change your role.
              </span>
            </div>
          </FormField>
        </div>
      </DashboardPanel>

      {/* Save */}
      <div className="flex justify-end">
        <Button variant="primary" size="md">
          Save Changes
        </Button>
      </div>
    </div>
  );
}
