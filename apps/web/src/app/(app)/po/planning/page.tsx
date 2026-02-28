"use client";

import { useState, useEffect, useCallback } from "react";
import { SprintGenerationPanel } from "@/components/po/sprint-generation-panel";
import { PlanApprovalModal } from "@/components/po/plan-approval-modal";
import { WritebackConfirmationPanel } from "@/components/po/writeback-confirmation-panel";
import { SprintForecastPanel } from "@/components/po/sprint-forecast-panel";
import { Tabs } from "@/components/ui";
import { useSelectedProject } from "@/lib/project/context";
import { useAutoRefresh } from "@/lib/ws/context";

const TAB_ITEMS = [
  { id: "plan", label: "Sprint Plan" },
  { id: "forecast", label: "Sprint Forecast" },
];

export default function PlanningPage() {
  const { selectedProject } = useSelectedProject();
  const [planModalOpen, setPlanModalOpen] = useState(false);
  const [activeTab, setActiveTab] = useState("plan");
  const [isRebalancing, setIsRebalancing] = useState(false);
  const [rebalancingRecommended, setRebalancingRecommended] = useState(false);
  const refreshKey = useAutoRefresh(["sprint_plan_generated", "sprint_plan_updated", "sync_complete"]);

  // Check if rebalancing is recommended (for amber dot on forecast tab)
  const checkRebalancing = useCallback(async () => {
    if (!selectedProject) return;
    try {
      const res = await fetch(
        `/api/sprints/forecast?projectId=${selectedProject.internalId}`
      );
      if (res.ok) {
        const data = await res.json();
        setRebalancingRecommended(data.rebalancingRecommended ?? false);
      }
    } catch {
      // swallow
    }
  }, [selectedProject]);

  useEffect(() => {
    checkRebalancing();
  }, [checkRebalancing, refreshKey]);

  const handleRebalance = () => {
    setIsRebalancing(true);
    setPlanModalOpen(true);
  };

  return (
    <div className="space-y-6">
      {/* Segmented tab toggle */}
      <div className="relative">
        <Tabs
          items={TAB_ITEMS}
          activeId={activeTab}
          onChange={setActiveTab}
          className="max-w-sm"
        />
        {/* Amber dot on Forecast tab when rebalancing recommended */}
        {rebalancingRecommended && (
          <span
            className="absolute top-1.5 rounded-full h-2 w-2 bg-[var(--color-rag-amber)]"
            style={{ left: "calc(50% + 4.5rem)" }}
          />
        )}
      </div>

      {/* Tab 1: Sprint Plan (existing content, unchanged) */}
      {activeTab === "plan" && (
        <>
          <SprintGenerationPanel onViewPlan={() => {
            setIsRebalancing(false);
            setPlanModalOpen(true);
          }} />
          <WritebackConfirmationPanel />
        </>
      )}

      {/* Tab 2: Sprint Forecast */}
      {activeTab === "forecast" && (
        <SprintForecastPanel onRebalance={handleRebalance} />
      )}

      <PlanApprovalModal
        open={planModalOpen}
        onClose={() => {
          setPlanModalOpen(false);
          setIsRebalancing(false);
        }}
        isRebalancing={isRebalancing}
      />
    </div>
  );
}
