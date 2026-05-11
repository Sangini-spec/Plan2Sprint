"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Download,
  FileText,
  FileSpreadsheet,
  CalendarClock,
  Loader2,
  CheckCircle2,
  AlertCircle,
  Clock,
  FileDown,
} from "lucide-react";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Button } from "@/components/ui";
import { useSelectedProject } from "@/lib/project/context";

interface OverviewData {
  project_name: string;
  generated_at: string;
  summary: {
    total_work_items: number;
    completed: number;
    in_progress: number;
    not_started: number;
    completion_percentage: number;
    total_story_points: number;
    completed_story_points: number;
    total_sprints: number;
    active_sprint: string | null;
    team_size: number;
  };
}

type ExportStatus = "idle" | "loading" | "success" | "error";

export function ExportPanel() {
  const { selectedProject } = useSelectedProject();
  const [overview, setOverview] = useState<OverviewData | null>(null);
  const [loadingOverview, setLoadingOverview] = useState(true);
  const [pdfStatus, setPdfStatus] = useState<ExportStatus>("idle");
  const [csvStatus, setCsvStatus] = useState<ExportStatus>("idle");
  const [lastExported, setLastExported] = useState<string | null>(null);

  const projectParam = selectedProject?.internalId
    ? `?projectId=${selectedProject.internalId}`
    : "";

  // Fetch overview data for preview
  const fetchOverview = useCallback(async () => {
    setLoadingOverview(true);
    try {
      const res = await fetch(`/api/export/overview${projectParam}`);
      if (res.ok) {
        const data = await res.json();
        setOverview(data);
      }
    } catch {
      // silent
    } finally {
      setLoadingOverview(false);
    }
  }, [projectParam]);

  useEffect(() => {
    fetchOverview();
  }, [fetchOverview]);

  // Export CSV
  const handleExportCSV = async () => {
    setCsvStatus("loading");
    try {
      const res = await fetch(`/api/export/csv${projectParam}`, {
        method: "POST",
      });
      if (!res.ok) throw new Error("Export failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `plan2sprint-report.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      setCsvStatus("success");
      setLastExported(new Date().toLocaleDateString());
      setTimeout(() => setCsvStatus("idle"), 3000);
    } catch {
      setCsvStatus("error");
      setTimeout(() => setCsvStatus("idle"), 3000);
    }
  };

  // Export PDF report (downloads as HTML file — open in browser and Ctrl+P to save as PDF)
  const handleExportPDF = async () => {
    setPdfStatus("loading");
    try {
      const res = await fetch(`/api/export/pdf${projectParam}`, {
        method: "POST",
      });
      if (!res.ok) throw new Error("Export failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `Plan2Sprint-Report.html`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      setPdfStatus("success");
      setLastExported(new Date().toLocaleDateString());
      setTimeout(() => setPdfStatus("idle"), 3000);
    } catch {
      setPdfStatus("error");
      setTimeout(() => setPdfStatus("idle"), 3000);
    }
  };

  const statusIcon = (status: ExportStatus) => {
    switch (status) {
      case "loading":
        return <Loader2 size={16} className="animate-spin" />;
      case "success":
        return <CheckCircle2 size={16} className="text-emerald-400" />;
      case "error":
        return <AlertCircle size={16} className="text-red-400" />;
      default:
        return null;
    }
  };

  return (
    <div className="space-y-6" data-onboarding="export-button">
      {/* Overview Preview */}
      <DashboardPanel title="Project Overview" icon={FileDown}>
        {loadingOverview ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 size={24} className="animate-spin text-[var(--text-secondary)]" />
          </div>
        ) : overview ? (
          <div className="space-y-4">
            <p className="text-sm text-[var(--text-secondary)]">
              Preview of data that will be included in the export for{" "}
              <span className="font-semibold text-[var(--text-primary)]">
                {overview.project_name}
              </span>
            </p>

            {/* Stats grid */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
              {[
                { label: "Total Items", value: overview.summary.total_work_items },
                { label: "Completed", value: overview.summary.completed },
                { label: "In Progress", value: overview.summary.in_progress },
                { label: "Completion", value: `${overview.summary.completion_percentage}%` },
                { label: "Story Points", value: overview.summary.total_story_points },
              ].map((stat) => (
                <div
                  key={stat.label}
                  className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] p-3"
                >
                  <p className="text-xl font-bold text-[var(--text-primary)]">{stat.value}</p>
                  <p className="text-[11px] uppercase tracking-wider text-[var(--text-secondary)]">
                    {stat.label}
                  </p>
                </div>
              ))}
            </div>

            {/* Active sprint & team info */}
            <div className="flex flex-wrap gap-4 text-sm text-[var(--text-secondary)]">
              <span>
                <Clock size={14} className="inline mr-1" />
                Active Sprint: {overview.summary.active_sprint || "None"}
              </span>
              <span>
                {overview.summary.total_sprints} sprints total
              </span>
              <span>
                {overview.summary.team_size} team members
              </span>
            </div>
          </div>
        ) : (
          <p className="text-sm text-[var(--text-secondary)] py-4">
            No project data available. Select a project to preview export data.
          </p>
        )}
      </DashboardPanel>

      {/* Export Actions */}
      <DashboardPanel title="Export & Reports" icon={Download}>
        <p className="mb-4 text-sm text-[var(--text-secondary)]">
          Export the project overview as a report for presentations and stakeholders.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {/* PDF Export */}
          <button
            onClick={handleExportPDF}
            disabled={pdfStatus === "loading" || !overview}
            className="flex items-center gap-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] p-4 hover:bg-[var(--bg-surface-raised)]/80 transition-colors text-left cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-red-500/10">
              <FileText size={20} className="text-red-400" />
            </div>
            <div className="flex-1">
              <p className="text-sm font-semibold text-[var(--text-primary)]">Export as PDF</p>
              <p className="text-xs text-[var(--text-secondary)]">
                Printable report with charts
              </p>
            </div>
            {statusIcon(pdfStatus)}
          </button>

          {/* CSV Export */}
          <button
            onClick={handleExportCSV}
            disabled={csvStatus === "loading" || !overview}
            className="flex items-center gap-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] p-4 hover:bg-[var(--bg-surface-raised)]/80 transition-colors text-left cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-emerald-500/10">
              <FileSpreadsheet size={20} className="text-emerald-400" />
            </div>
            <div className="flex-1">
              <p className="text-sm font-semibold text-[var(--text-primary)]">Export as CSV</p>
              <p className="text-xs text-[var(--text-secondary)]">
                Spreadsheet-ready data
              </p>
            </div>
            {statusIcon(csvStatus)}
          </button>
        </div>

        {lastExported && (
          <p className="mt-4 text-xs text-[var(--text-secondary)]">
            Last exported: {lastExported}
          </p>
        )}
      </DashboardPanel>

      {/* Weekly Report Section */}
      <WeeklyReportSection projectId={selectedProject?.internalId} />
    </div>
  );
}


// ---------------------------------------------------------------------------
// Weekly Report Sub-Component
// Clicks "Generate Now" → downloads the same one-page PDF that gets emailed
// to stakeholders every Friday at 5:00 PM IST via the backend scheduler.
// ---------------------------------------------------------------------------

function WeeklyReportSection({ projectId }: { projectId: string | undefined }) {
  const [status, setStatus] = useState<ExportStatus>("idle");

  // "Generate Now" triggers a browser download of the one-page weekly PDF —
  // the same PDF that's emailed to stakeholders every Friday at 5:00 PM IST.
  const handleGenerate = async () => {
    if (!projectId) return;
    setStatus("loading");
    try {
      const res = await fetch(`/api/reports/weekly?projectId=${projectId}`);
      if (!res.ok) throw new Error("Failed to generate report");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `plan2sprint-weekly-report.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      setStatus("success");
      setTimeout(() => setStatus("idle"), 3000);
    } catch {
      setStatus("error");
      setTimeout(() => setStatus("idle"), 3000);
    }
  };

  const buttonLabel = () => {
    if (status === "loading") return "Generating...";
    if (status === "success") return "Downloaded";
    if (status === "error") return "Try again";
    return "Generate Now";
  };

  return (
    <DashboardPanel title="Weekly Report" icon={CalendarClock}>
      <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] p-4">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-500/10">
              <CalendarClock size={20} className="text-blue-400" />
            </div>
            <div>
              <p className="text-sm font-semibold text-[var(--text-primary)]">
                Weekly stakeholder PDF
              </p>
              <p className="text-xs text-[var(--text-secondary)]">
                Reports are generated every Friday at 5:00 PM IST
              </p>
            </div>
          </div>
          <Button
            variant="primary"
            onClick={handleGenerate}
            disabled={status === "loading" || !projectId}
          >
            {status === "loading" ? (
              <Loader2 size={14} className="animate-spin" />
            ) : status === "success" ? (
              <CheckCircle2 size={14} />
            ) : status === "error" ? (
              <AlertCircle size={14} />
            ) : (
              <FileDown size={14} />
            )}
            {buttonLabel()}
          </Button>
        </div>
      </div>
    </DashboardPanel>
  );
}
