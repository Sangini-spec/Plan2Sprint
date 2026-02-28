"use client";

import { RetrospectiveHubPanel } from "@/components/po/retrospective-hub-panel";
import { EpicReleasePanel } from "@/components/po/epic-release-panel";

export default function RetroPage() {
  return (
    <div className="space-y-6">
      <RetrospectiveHubPanel />
      <EpicReleasePanel />
    </div>
  );
}
