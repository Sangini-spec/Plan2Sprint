"use client";

import { MySprintOverviewBar } from "@/components/dev/my-sprint-overview-bar";
import { MyStandupCompact } from "@/components/dev/my-standup-compact";
import { MySprintBoard } from "@/components/dev/my-sprint-board";

export default function DevDashboardPage() {
  return (
    <div className="space-y-4">
      {/* Sprint overview bar (full width) */}
      <MySprintOverviewBar />

      {/* Standup report (compact) + Sprint board (side by side on lg) */}
      <div className="grid gap-4 lg:grid-cols-2">
        <MyStandupCompact />
        <MySprintBoard />
      </div>
    </div>
  );
}
