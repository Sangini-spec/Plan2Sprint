"use client";

/**
 * StakeholderProjectSelector — dropdown for stakeholders to pick from
 * projects assigned to them by PO/admin. Does NOT use integrations context.
 */

import { useState, useRef, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, FolderKanban, Check, Layers, Loader2, Info } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth/context";
import { useSelectedProject, type ProjectItem } from "@/lib/project/context";

export function StakeholderProjectSelector() {
  const { selectedProject, selectProject } = useSelectedProject();
  const { appUser } = useAuth();
  const [open, setOpen] = useState(false);
  const [projects, setProjects] = useState<ProjectItem[]>([]);
  const [loading, setLoading] = useState(true);
  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Fetch assigned projects — pass email so backend can identify user
  const fetchProjects = useCallback(async () => {
    if (!appUser?.email) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/projects/stakeholder-assignments/my-projects?email=${encodeURIComponent(appUser.email)}`);
      if (res.ok) {
        const data = await res.json();
        setProjects(data.projects ?? []);
      }
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [appUser?.email]);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  const handleSelect = (project: ProjectItem | null) => {
    selectProject(project);
    setOpen(false);
  };

  function getSourceBadge(source: string) {
    if (source === "ado")
      return { label: "ADO", color: "bg-[#0078D4]/10 text-[#0078D4]" };
    return { label: "Jira", color: "bg-[#0052CC]/10 text-[#0052CC]" };
  }

  // Auto-select the first project on mount if nothing's selected and
  // we have at least one. Stakeholders are scoped per-project (their
  // dashboards have no "aggregate everything" mode that makes sense)
  // so a null selectedProject just means broken dashboards.
  useEffect(() => {
    if (!loading && !selectedProject && projects.length > 0) {
      selectProject(projects[0]);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, selectedProject, projects.length]);

  const buttonLabel = loading
    ? "Loading..."
    : selectedProject
      ? selectedProject.name
      : projects.length > 0
        ? projects[0].name  // shouldn't render, the effect above selects it
        : "No Projects";

  return (
    <div ref={ref} className="relative" data-onboarding="project-picker">
      <button
        onClick={() => setOpen(!open)}
        className={cn(
          "flex items-center gap-2 rounded-lg px-3 py-1.5",
          "border border-[var(--border-subtle)]",
          "hover:bg-[var(--bg-surface-raised)]",
          "transition-colors duration-200 cursor-pointer",
          "max-w-[220px]"
        )}
      >
        {loading ? (
          <Loader2 size={14} className="shrink-0 text-[var(--text-secondary)] animate-spin" />
        ) : (
          <FolderKanban size={14} className="shrink-0 text-[var(--color-brand-secondary)]" />
        )}
        <span className={cn(
          "text-[13px] font-medium truncate",
          projects.length === 0 && !loading
            ? "text-[var(--text-secondary)]"
            : "text-[var(--text-primary)]"
        )}>
          {buttonLabel}
        </span>
        {selectedProject && (
          <span
            className={cn(
              "text-[9px] font-bold uppercase px-1.5 py-0.5 rounded shrink-0",
              getSourceBadge(selectedProject.source).color
            )}
          >
            {getSourceBadge(selectedProject.source).label}
          </span>
        )}
        <ChevronDown
          size={12}
          className={cn(
            "shrink-0 text-[var(--text-tertiary)] transition-transform duration-200",
            open && "rotate-180"
          )}
        />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.97 }}
            transition={{ duration: 0.12 }}
            className="absolute left-0 top-full mt-1.5 w-72 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]/95 backdrop-blur-xl shadow-xl z-50 overflow-hidden"
          >
            {projects.length === 0 ? (
              <div className="px-4 py-5 text-center">
                <FolderKanban size={24} className="mx-auto mb-2 text-[var(--text-tertiary)]" />
                <p className="text-sm font-medium text-[var(--text-primary)] mb-1">
                  No projects assigned
                </p>
                <p className="text-xs text-[var(--text-secondary)] mb-1">
                  Ask your admin or product owner to assign projects to you.
                </p>
                <div className="flex items-center justify-center gap-1 text-[10px] text-[var(--text-tertiary)] mt-2">
                  <Info size={10} />
                  Settings &gt; Team &gt; Assign Projects
                </div>
              </div>
            ) : (
              <>
                {/* "All Assigned Projects" option removed — stakeholder
                    dashboards aren't meaningful in aggregate mode (export
                    totals zero out, predictability averages across
                    unrelated teams, etc). Users always operate on one
                    project at a time. */}

                {/* Project list */}
                <div className="max-h-64 overflow-y-auto py-1">
                  {projects.map((project) => {
                    const isSelected = selectedProject?.internalId === project.internalId;
                    const badge = getSourceBadge(project.source);

                    return (
                      <button
                        key={`${project.source}-${project.id}`}
                        onClick={() => handleSelect(project)}
                        className={cn(
                          "w-full flex items-center gap-3 px-4 py-2.5 text-left",
                          "hover:bg-[var(--bg-surface-raised)] transition-colors cursor-pointer",
                          isSelected &&
                            "bg-[var(--color-brand-secondary)]/5 text-[var(--color-brand-secondary)]"
                        )}
                      >
                        <div
                          className={cn(
                            "flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[9px] font-bold",
                            badge.color
                          )}
                        >
                          {project.source === "ado" ? "AD" : "JR"}
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium truncate">{project.name}</p>
                          {project.key && (
                            <p className="text-[10px] text-[var(--text-tertiary)]">{project.key}</p>
                          )}
                        </div>
                        {isSelected && (
                          <Check size={14} className="shrink-0 text-[var(--color-brand-secondary)]" />
                        )}
                      </button>
                    );
                  })}
                </div>
              </>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
