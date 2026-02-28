"use client";

import { Download, FileText, FileSpreadsheet, CalendarClock } from "lucide-react";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Button } from "@/components/ui";

export function ExportPanel() {
  return (
    <DashboardPanel title="Export & Reports" icon={Download}>
      <p className="mb-4 text-sm text-[var(--text-secondary)]">
        Export portfolio dashboard data for board presentations and external
        stakeholders.
      </p>

      <div className="flex flex-col gap-3">
        <Button variant="primary" onClick={() => {}}>
          <FileText className="h-4 w-4" />
          Export as PDF
        </Button>
        <Button variant="secondary" onClick={() => {}}>
          <FileSpreadsheet className="h-4 w-4" />
          Export as CSV
        </Button>
        <Button variant="ghost" onClick={() => {}}>
          <CalendarClock className="h-4 w-4" />
          Schedule Weekly Report
        </Button>
      </div>

      <p className="mt-4 text-xs text-[var(--text-secondary)]">
        Last exported: Feb 17, 2026
      </p>
    </DashboardPanel>
  );
}
