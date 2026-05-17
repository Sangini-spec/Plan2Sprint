"use client";

/**
 * ProjectAccessDeniedBanner (Hotfix 91).
 *
 * Shown above the dashboard content when the selected project is
 * something the caller can't actually see - so they get a clear
 * "you don't have access" message instead of misleading 0s.
 *
 * Decides via a single ``GET /api/projects/{id}/access`` call. That
 * endpoint is a thin wrapper over the same ``assert_project_access``
 * helper that gates every per-project data endpoint, so the banner
 * shows iff the data endpoints would have 403'd anyway.
 *
 * Usage:
 *   <ProjectAccessDeniedBanner>
 *     <YourDashboardContent />
 *   </ProjectAccessDeniedBanner>
 *
 * When access is granted (or still loading), children render
 * normally. When denied, children are replaced by the banner.
 */

import { useEffect, useState } from "react";
import { Lock, Mail } from "lucide-react";
import { useSelectedProject } from "@/lib/project/context";
import { useAuth } from "@/lib/auth/context";

interface AccessState {
  status: "loading" | "ok" | "denied" | "not_found";
  reason?: string;
  projectName?: string;
}

export function useProjectAccess(projectId: string | undefined | null): AccessState {
  const [state, setState] = useState<AccessState>({ status: "loading" });

  useEffect(() => {
    if (!projectId) {
      setState({ status: "loading" });
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`/api/projects/${projectId}/access`);
        if (cancelled) return;
        if (res.status === 404) {
          setState({ status: "not_found" });
          return;
        }
        const data = await res.json().catch(() => ({}));
        if (data?.hasAccess) {
          setState({ status: "ok", projectName: data.projectName });
        } else {
          setState({
            status: "denied",
            reason: data?.reason,
            projectName: data?.projectName,
          });
        }
      } catch {
        if (!cancelled) setState({ status: "loading" });
      }
    })();
    return () => { cancelled = true; };
  }, [projectId]);

  return state;
}

export function ProjectAccessDeniedBanner({
  children,
}: {
  children: React.ReactNode;
}) {
  const { selectedProject } = useSelectedProject();
  const { appUser } = useAuth();
  const access = useProjectAccess(selectedProject?.internalId);

  // While loading OR allowed → render children unchanged.
  // Only intercept on confirmed denial.
  if (access.status === "loading" || access.status === "ok") {
    return <>{children}</>;
  }

  // Project name comes from the API response in priority order:
  //   1. ``access.projectName`` (server-authoritative - set on both
  //      success and denial responses, so it survives a stale
  //      frontend selected-project context or a URL-only navigation)
  //   2. ``selectedProject?.name`` (frontend context fallback)
  //   3. "this project" (last resort, when we have nothing)
  const projectLabel =
    access.projectName ?? selectedProject?.name ?? "this project";

  const title =
    access.status === "not_found"
      ? `${selectedProject?.name ?? "This project"} isn't in your organisation`
      : `You don't have access to ${projectLabel}`;

  const body =
    access.status === "not_found"
      ? `The project you're trying to view either was deleted or belongs to a different organisation. Pick a different project from the picker at the top, or contact your Product Owner.`
      : `Your Plan2Sprint account isn't on ${projectLabel}'s team. To get access, ask your Product Owner to add you in Settings → Team → Assign Project, or get added to the project's team in your project management tool (ADO/Jira).`;

  const role = (appUser?.role || "").toLowerCase();
  const isPrivileged = ["product_owner", "admin", "owner"].includes(role);

  return (
    <div className="space-y-4">
      <div
        className="rounded-xl border-2 p-5 flex items-start gap-4"
        style={{
          borderColor: "var(--color-rag-amber)",
          background: "color-mix(in srgb, var(--color-rag-amber) 8%, var(--bg-surface))",
        }}
      >
        <div
          className="flex h-10 w-10 items-center justify-center rounded-full shrink-0"
          style={{ background: "color-mix(in srgb, var(--color-rag-amber) 20%, transparent)" }}
        >
          <Lock className="h-5 w-5" style={{ color: "var(--color-rag-amber)" }} />
        </div>
        <div className="flex-1 min-w-0">
          <h3
            className="text-base font-bold mb-1"
            style={{ color: "var(--color-rag-amber)" }}
          >
            {title}
          </h3>
          <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
            {body}
          </p>
          {!isPrivileged && (
            <div className="mt-3 flex items-center gap-2 text-xs text-[var(--text-tertiary)]">
              <Mail className="h-3.5 w-3.5" />
              <span>
                If you believe this is a mistake, mention <b>{appUser?.email}</b>
                {" "}when you ask the PO so they can find your account.
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
