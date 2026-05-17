"use client";

/**
 * EmptyDashboard - fallback shown on any role's dashboard when the
 * user has no project selected.
 *
 * Three states it can render based on the user + load state:
 *
 *   1. LOADING - show "Your dashboard is loading…" while the project
 *      list is still being fetched. Without this gate the empty
 *      state flashes for ~300ms during every login before real data
 *      arrives, which made the dashboard feel broken.
 *
 *   2. NEW USER - first-time visit, no projects ever connected to
 *      this account / org. Show the "Welcome to Plan2Sprint" card
 *      with role-appropriate CTA. Detected via
 *      ``appUser.onboarding_completed=false``.
 *
 *   3. RETURNING USER, NO PROJECTS - they've been around (completed
 *      or dismissed onboarding before) but currently have nothing.
 *      Skip the Welcome framing - show a quieter "no projects" card
 *      with role-appropriate guidance. Non-privileged users get
 *      "ask your PO to add you"; privileged ones get a direct
 *      Connect Tools CTA.
 */

import { PlugZap, ArrowRight, Mail, Eye, Loader2 } from "lucide-react";
import { Button } from "@/components/ui";
import { useIntegrations } from "@/lib/integrations/context";
import { useAuth } from "@/lib/auth/context";
import { useSelectedProject } from "@/lib/project/context";
import { PO_DASHBOARD_ROLES } from "@/lib/types/auth";

export function EmptyDashboard() {
  const { openModal, hasAnyConnection } = useIntegrations();
  const { appUser, role } = useAuth();
  const { loading } = useSelectedProject();
  const isPrivileged = PO_DASHBOARD_ROLES.includes(role);
  // "Returning user" if any of:
  //   - they've ever connected a project tool (hasAnyConnection) -
  //     the primary signal: once you've connected Jira/ADO/GitHub
  //     you're not "new to Plan2Sprint" anymore
  //   - they've stamped onboarding_completed=true (took the tour
  //     through to the confetti screen)
  // Either is enough to skip the brand-new "Welcome to Plan2Sprint"
  // framing on subsequent logins, even if they're currently between
  // projects.
  const isReturningUser =
    !!appUser?.onboarding_completed || hasAnyConnection;

  // -------------------- LOADING --------------------
  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 px-6 text-center">
        <Loader2
          size={32}
          className="animate-spin mb-4"
          style={{ color: "var(--color-brand-secondary)" }}
        />
        <p className="text-sm font-medium text-[var(--text-primary)]">
          Your dashboard is loading…
        </p>
        <p className="text-xs text-[var(--text-secondary)] mt-1">
          Fetching your projects and recent activity
        </p>
      </div>
    );
  }

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
              here automatically - no tool setup needed on your end.
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

  // -------------------- Privileged + RETURNING USER (no projects right now) --------------------
  // Quieter card - they've been here before so no "Welcome to Plan2Sprint"
  // framing. Just nudge them to reconnect tools.
  if (isReturningUser) {
    return (
      <div className="flex flex-col items-center justify-center py-20 px-6 text-center">
        <div className="flex h-20 w-20 items-center justify-center rounded-2xl bg-[var(--bg-surface-raised)] mb-6">
          <PlugZap size={36} className="text-[var(--color-brand-secondary)]" />
        </div>

        <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-3">
          No projects to show
        </h2>
        <p className="text-sm text-[var(--text-secondary)] max-w-md mb-8">
          Reconnect a project tool to bring your sprints, work items, and
          team back in.
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
      </div>
    );
  }

  // -------------------- Privileged + NEW USER (first time) --------------------
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
