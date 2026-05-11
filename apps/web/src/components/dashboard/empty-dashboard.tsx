"use client";

/**
 * EmptyDashboard — shown on any role's dashboard when the user has no
 * projects available.
 *
 * Two flavours, picked by role:
 *
 *   • Privileged (PO / admin / owner / engineering_manager)
 *     → "Welcome to Plan2Sprint" + Connect Tools CTA. They drive
 *       project import, so this is the right action for them.
 *
 *   • Non-privileged (developer / stakeholder)
 *     → "Waiting on your Product Owner" + their own email so they
 *       can pass it to the PO for assignment. No Connect Tools button
 *       — stakeholders + devs don't connect tools, the PO does.
 *       They just need to be assigned to the projects that already
 *       exist in the org.
 */

import { PlugZap, ArrowRight, Mail, Eye } from "lucide-react";
import { Button } from "@/components/ui";
import { useIntegrations } from "@/lib/integrations/context";
import { useAuth } from "@/lib/auth/context";
import { PO_DASHBOARD_ROLES } from "@/lib/types/auth";

export function EmptyDashboard() {
  const { openModal } = useIntegrations();
  const { appUser, role } = useAuth();
  const isPrivileged = PO_DASHBOARD_ROLES.includes(role);

  // -------------------- Non-privileged (dev / stakeholder) --------------------
  if (!isPrivileged) {
    const isStakeholder = role === "stakeholder";
    return (
      <div className="flex flex-col items-center justify-center py-20 px-6 text-center">
        <div className="flex h-20 w-20 items-center justify-center rounded-2xl bg-[var(--bg-surface-raised)] mb-6">
          <Eye size={36} className="text-[var(--color-brand-secondary)]" />
        </div>

        <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-3">
          {isStakeholder ? "No projects assigned yet" : "No projects yet"}
        </h2>
        <p className="text-sm text-[var(--text-secondary)] max-w-md mb-8 leading-relaxed">
          {isStakeholder ? (
            <>
              Your Product Owner hasn&apos;t added you to any projects in
              Plan2Sprint. Once they assign you to a project, you&apos;ll see
              live portfolio health, delivery predictability, and weekly reports
              here automatically — no tool setup needed on your end.
            </>
          ) : (
            <>
              Your Product Owner hasn&apos;t assigned you to a project yet, or
              your account isn&apos;t linked to any work items. Plan2Sprint
              auto-discovers team members from connected ADO/Jira accounts.
            </>
          )}
        </p>

        {appUser?.email && (
          <div className="flex items-center gap-2 px-4 py-2.5 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]/50 mb-2">
            <Mail size={14} className="text-[var(--text-tertiary)]" />
            <span className="text-xs text-[var(--text-secondary)]">
              Mention this email to your PO when asking to be added:
            </span>
            <span className="text-xs font-medium text-[var(--text-primary)]">
              {appUser.email}
            </span>
          </div>
        )}

        <div className="mt-8 grid grid-cols-1 sm:grid-cols-3 gap-4 max-w-lg w-full">
          {(isStakeholder
            ? [
                { title: "Portfolio Health", desc: "RAG signals across every assigned project" },
                { title: "Predictability", desc: "Velocity, commitment hit rate, forecast confidence" },
                { title: "Weekly PDF", desc: "Friday recap delivered to your inbox" },
              ]
            : [
                { title: "Your Sprint", desc: "Tickets, PRs, commits in one workspace" },
                { title: "Auto Standups", desc: "Pre-filled from work item activity" },
                { title: "Blocker Flow", desc: "Flag once, PO sees it in Slack/Teams" },
              ]
          ).map(({ title, desc }) => (
            <div
              key={title}
              className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]/50 p-4 text-center"
            >
              <p className="text-xs font-semibold text-[var(--text-primary)]">{title}</p>
              <p className="text-[11px] text-[var(--text-secondary)] mt-1">{desc}</p>
            </div>
          ))}
        </div>
      </div>
    );
  }

  // -------------------- Privileged (PO / admin / owner) --------------------
  return (
    <div className="flex flex-col items-center justify-center py-20 px-6 text-center">
      <div className="flex h-20 w-20 items-center justify-center rounded-2xl bg-[var(--bg-surface-raised)] mb-6">
        <PlugZap size={40} className="text-[var(--color-brand-secondary)]" />
      </div>

      <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-3">
        Welcome to Plan2Sprint
      </h2>
      <p className="text-sm text-[var(--text-secondary)] max-w-md mb-8">
        Connect your project management tools to get started. Link Jira or Azure DevOps
        to import your projects, work items, and sprint data.
      </p>

      <Button
        variant="primary"
        size="lg"
        onClick={() => openModal?.()}
        className="gap-2"
      >
        Connect Tools
        <ArrowRight size={16} />
      </Button>

      <div className="mt-8 grid grid-cols-1 sm:grid-cols-3 gap-4 max-w-lg w-full">
        {[
          { title: "Import Projects", desc: "Fetch work items, features & sprints" },
          { title: "AI Sprint Plans", desc: "Auto-generate optimized sprint plans" },
          { title: "Track Progress", desc: "Monitor team health & delivery" },
        ].map(({ title, desc }) => (
          <div
            key={title}
            className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]/50 p-4 text-center"
          >
            <p className="text-xs font-semibold text-[var(--text-primary)]">{title}</p>
            <p className="text-[11px] text-[var(--text-secondary)] mt-1">{desc}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
