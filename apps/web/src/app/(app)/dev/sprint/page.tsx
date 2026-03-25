"use client";

import dynamic from "next/dynamic";
import { Loader2 } from "lucide-react";

const DevSprintView = dynamic(
  () => import("@/components/dev/dev-sprint-view").then((m) => ({ default: m.DevSprintView })),
  { loading: () => (
    <div className="flex items-center justify-center py-16">
      <Loader2 className="h-5 w-5 animate-spin text-[var(--text-secondary)]" />
    </div>
  )}
);

export default function DevSprintPage() {
  return <DevSprintView />;
}
