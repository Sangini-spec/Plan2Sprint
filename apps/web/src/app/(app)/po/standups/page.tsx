"use client";

import dynamic from "next/dynamic";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { useAuth } from "@/lib/auth/context";

const StandupDigestPanel = dynamic(
  () => import("@/components/po/standup-digest-panel").then((m) => ({ default: m.StandupDigestPanel })),
  { loading: () => <PageLoader /> }
);

function PageLoader() {
  return (
    <div className="flex items-center justify-center py-16">
      <Loader2 className="h-5 w-5 animate-spin text-[var(--text-secondary)]" />
    </div>
  );
}

export default function StandupsPage() {
  const { role } = useAuth();
  const router = useRouter();

  useEffect(() => {
    // If a developer lands here (e.g. via Slack link), redirect to their own standup
    if (role === "developer") {
      router.replace("/dev/standup");
    }
  }, [role, router]);

  return (
    <div className="space-y-6" data-onboarding="standup-digest-panel">
      <StandupDigestPanel />
    </div>
  );
}
