"use client";

import { PlugZap, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui";
import { useIntegrations } from "@/lib/integrations/context";

/**
 * Shared "Welcome to Plan2Sprint" empty state.
 * Shown on ANY role's dashboard when the user has no projects connected.
 */
export function EmptyDashboard() {
  const { openModal } = useIntegrations();

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
