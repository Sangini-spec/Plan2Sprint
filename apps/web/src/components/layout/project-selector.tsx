"use client";

/**
 * ProjectSelector — dropdown in the topbar for selecting the active project.
 *
 * Visible on PO and Developer dashboard routes. Shows all imported projects
 * from connected Jira/ADO tools. Selecting a project scopes every data query
 * across every page to that single project.
 */

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, FolderKanban, Check, Layers, Plug, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useSelectedProject, type ProjectItem } from "@/lib/project/context";
import { useIntegrations } from "@/lib/integrations/context";

function getSourceBadge(source: string) {
  if (source === "ado")
    return { label: "ADO", color: "bg-[#0078D4]/10 text-[#0078D4]" };
  return { label: "Jira", color: "bg-[#0052CC]/10 text-[#0052CC]" };
}

export function ProjectSelector() {
  const { projects, selectedProject, loading, switching, selectProject } =
    useSelectedProject();
  const { openModal } = useIntegrations();
  const [open, setOpen] = useState(false);
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

  const handleSelect = (project: ProjectItem | null) => {
    selectProject(project);
    setOpen(false);
  };

  // Determine button label
  const buttonLabel = loading
    ? "Loading..."
    : switching
      ? "Switching project..."
      : selectedProject
        ? selectedProject.name
        : projects.length > 0
          ? "All Projects"
          : "No Projects";

  return (
    <div ref={ref} className="relative" data-onboarding="project-picker">
      {/* Trigger button */}
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
        {loading || switching ? (
          <Loader2
            size={14}
            className="shrink-0 text-[var(--text-secondary)] animate-spin"
          />
        ) : (
          <FolderKanban
            size={14}
            className="shrink-0 text-[var(--color-brand-secondary)]"
          />
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

      {/* Dropdown */}
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
              /* Empty state — no projects imported yet */
              <div className="px-4 py-5 text-center">
                <FolderKanban size={24} className="mx-auto mb-2 text-[var(--text-tertiary)]" />
                <p className="text-sm font-medium text-[var(--text-primary)] mb-1">
                  No projects imported
                </p>
                <p className="text-xs text-[var(--text-secondary)] mb-3">
                  Connect a tool and import projects to get started.
                </p>
                <button
                  onClick={() => {
                    setOpen(false);
                    openModal();
                  }}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5",
                    "bg-[var(--color-brand-secondary)] text-white text-xs font-medium",
                    "hover:bg-[var(--color-brand-secondary)]/90",
                    "transition-colors cursor-pointer"
                  )}
                >
                  <Plug size={12} />
                  Connect Tools
                </button>
              </div>
            ) : (
              <>
                {/* "All Projects" option */}
                <button
                  onClick={() => handleSelect(null)}
                  className={cn(
                    "w-full flex items-center gap-3 px-4 py-2.5 text-left",
                    "hover:bg-[var(--bg-surface-raised)] transition-colors cursor-pointer",
                    "border-b border-[var(--border-subtle)]",
                    !selectedProject &&
                      "bg-[var(--color-brand-secondary)]/5 text-[var(--color-brand-secondary)]"
                  )}
                >
                  <Layers size={16} className="shrink-0 opacity-60" />
                  <span className="text-sm font-medium flex-1">All Projects</span>
                  {!selectedProject && (
                    <Check
                      size={14}
                      className="shrink-0 text-[var(--color-brand-secondary)]"
                    />
                  )}
                </button>

                {/* Project list */}
                <div className="max-h-64 overflow-y-auto py-1">
                  {projects.map((project) => {
                    const isSelected =
                      selectedProject?.internalId === project.internalId;
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
                          <p className="text-sm font-medium truncate">
                            {project.name}
                          </p>
                          {project.key && (
                            <p className="text-[10px] text-[var(--text-tertiary)]">
                              {project.key}
                            </p>
                          )}
                        </div>
                        {isSelected && (
                          <Check
                            size={14}
                            className="shrink-0 text-[var(--color-brand-secondary)]"
                          />
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
