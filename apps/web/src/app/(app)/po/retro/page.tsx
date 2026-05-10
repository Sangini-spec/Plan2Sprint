"use client";

import dynamic from "next/dynamic";
import { Loader2 } from "lucide-react";

const RetrospectiveHubPanel = dynamic(
  () => import("@/components/po/retrospective-hub-panel").then((m) => ({ default: m.RetrospectiveHubPanel })),
  { loading: () => <PageLoader /> }
);

const SprintHistoryTimeline = dynamic(
  () => import("@/components/po/sprint-history-timeline").then((m) => ({ default: m.SprintHistoryTimeline })),
  { ssr: false }
);

// Hotfix 83 — Project Cycle Concluded card. Renders only when the
// selected project has passed its target launch date; renders nothing
// for healthy projects so it has no visual effect on the regular
// retrospective flow.
const ProjectCycleConcludedCard = dynamic(
  () => import("@/components/po/project-cycle-concluded-card").then((m) => ({ default: m.ProjectCycleConcludedCard })),
  { ssr: false }
);

function PageLoader() {
  return (
    <div className="flex items-center justify-center py-16">
      <Loader2 className="h-5 w-5 animate-spin text-[var(--text-secondary)]" />
    </div>
  );
}

export default function RetroPage() {
  return (
    <div className="space-y-6">
      <ProjectCycleConcludedCard />
      <RetrospectiveHubPanel />
      <SprintHistoryTimeline />
    </div>
  );
}
