"use client";

import { useState } from "react";
import { SprintOverviewBar } from "@/components/po/sprint-overview-bar";
import { SprintGenerationPanel } from "@/components/po/sprint-generation-panel";
import { PlanApprovalModal } from "@/components/po/plan-approval-modal";
import { DeveloperProgressBoard } from "@/components/po/developer-progress-board";
import { BlockerActionPanel } from "@/components/po/blocker-action-panel";

export default function PODashboardPage() {
  const [planModalOpen, setPlanModalOpen] = useState(false);

  return (
    <div className="space-y-6">
      {/* Sprint Overview — sticky header */}
      <SprintOverviewBar />

      {/* AI Sprint Generation + Blocker Actions (side by side on lg) */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <SprintGenerationPanel onViewPlan={() => setPlanModalOpen(true)} />
        <BlockerActionPanel />
      </div>

      {/* Developer Progress Board */}
      <DeveloperProgressBoard />

      {/* Plan Approval Modal */}
      <PlanApprovalModal
        open={planModalOpen}
        onClose={() => setPlanModalOpen(false)}
      />
    </div>
  );
}
