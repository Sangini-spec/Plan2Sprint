"use client";

import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Check, Loader2, FolderKanban } from "lucide-react";
import { cn } from "@/lib/utils";
import { useIntegrations } from "@/lib/integrations/context";
import { JiraConnectCard } from "./jira-connect-card";
import { AdoConnectCard } from "./ado-connect-card";
import type { ToolType, SelectedProject } from "@/lib/integrations/types";

type Tab = "jira" | "ado";
type ModalStep = "connect" | "select-projects";

export function ConnectToolsModal() {
  const {
    modalOpen,
    closeModal,
    getConnection,
    fetchProjects,
    selectProjects,
  } = useIntegrations();

  const [activeTab, setActiveTab] = useState<Tab>("jira");
  const [step, setStep] = useState<ModalStep>("connect");

  // Project selection state
  const [availableProjects, setAvailableProjects] = useState<SelectedProject[]>([]);
  const [selectedProjectIds, setSelectedProjectIds] = useState<Set<string>>(new Set());
  const [loadingProjects, setLoadingProjects] = useState(false);
  const [projectsError, setProjectsError] = useState<string | null>(null);

  const jiraConnection = getConnection("jira");
  const adoConnection = getConnection("ado");

  // Check if current tab's tool is connected
  const currentConnection = activeTab === "jira" ? jiraConnection : adoConnection;
  const isCurrentConnected =
    currentConnection?.status === "connected" || currentConnection?.status === "syncing";

  // Reset step when modal opens
  useEffect(() => {
    if (modalOpen) {
      setStep("connect");
      setAvailableProjects([]);
      setSelectedProjectIds(new Set());
      setProjectsError(null);
    }
  }, [modalOpen]);

  const handleFetchProjects = useCallback(
    async (tool: ToolType) => {
      setLoadingProjects(true);
      setProjectsError(null);
      try {
        const projects = await fetchProjects(tool);
        setAvailableProjects(projects);
        setStep("select-projects");

        // Pre-select previously selected projects
        const conn = tool === "jira" ? jiraConnection : adoConnection;
        if (conn?.selectedProjects?.length) {
          setSelectedProjectIds(new Set(conn.selectedProjects.map((p) => p.id)));
        } else {
          setSelectedProjectIds(new Set());
        }
      } catch {
        setProjectsError("Failed to fetch projects. Please check your credentials.");
      } finally {
        setLoadingProjects(false);
      }
    },
    [fetchProjects, jiraConnection, adoConnection]
  );

  const toggleProject = (id: string) => {
    setSelectedProjectIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const handleSaveProjects = () => {
    const selected = availableProjects.filter((p) => selectedProjectIds.has(p.id));
    selectProjects(activeTab, selected);
    handleClose();
  };

  const handleClose = () => {
    setStep("connect");
    setAvailableProjects([]);
    setSelectedProjectIds(new Set());
    setProjectsError(null);
    closeModal();
  };

  const handleBack = () => {
    setStep("connect");
    setAvailableProjects([]);
    setSelectedProjectIds(new Set());
    setProjectsError(null);
  };

  return (
    <AnimatePresence>
      {modalOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
            onClick={handleClose}
          />

          {/* Modal */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
            className={cn(
              "fixed left-1/2 top-1/2 z-50 -translate-x-1/2 -translate-y-1/2",
              "w-[90vw] max-w-lg max-h-[85vh] flex flex-col",
              "rounded-2xl border border-[var(--border-subtle)]",
              "bg-[var(--bg-surface)]/95 backdrop-blur-xl",
              "shadow-2xl"
            )}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border-subtle)]">
              <div>
                <h2 className="text-base font-semibold text-[var(--text-primary)]">
                  {step === "connect" ? "Connect Tools" : "Select Projects"}
                </h2>
                <p className="text-xs text-[var(--text-secondary)] mt-0.5">
                  {step === "connect"
                    ? "Link your project management tools to sync data"
                    : `Choose which ${activeTab === "jira" ? "Jira" : "Azure DevOps"} projects to import`}
                </p>
              </div>
              <button
                onClick={handleClose}
                className={cn(
                  "flex h-8 w-8 items-center justify-center rounded-lg",
                  "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
                  "hover:bg-[var(--bg-surface-raised)]",
                  "transition-colors cursor-pointer"
                )}
              >
                <X size={18} />
              </button>
            </div>

            <AnimatePresence mode="wait">
              {step === "connect" ? (
                <motion.div
                  key="connect-step"
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -10 }}
                  transition={{ duration: 0.15 }}
                  className="flex-1 overflow-y-auto"
                >
                  {/* Tab bar */}
                  <div className="flex px-6 pt-4 gap-1">
                    <button
                      onClick={() => setActiveTab("jira")}
                      className={cn(
                        "flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-all cursor-pointer",
                        activeTab === "jira"
                          ? "bg-[var(--bg-surface-raised)] text-[var(--text-primary)] shadow-sm"
                          : "text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-surface-raised)]/50"
                      )}
                    >
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                        <path d="M11.53 2c0 4.97 3.93 9 8.47 9-.27 4.97-4.39 9-9.47 9C5.48 20 1 15.52 1 10.5S5.48 1 10.53 1c.34 0 .67.03 1 .07V2z" fill="#0052CC" />
                        <path d="M11.53 2c0 4.97 3.93 9 8.47 9 .28 0 .56-.01.83-.04C20.53 6.51 16.53 2.58 11.53 2z" fill="#2684FF" />
                      </svg>
                      Jira
                      {jiraConnection?.status === "connected" && (
                        <span className="h-2 w-2 rounded-full bg-[var(--color-rag-green)]" />
                      )}
                    </button>
                    <button
                      onClick={() => setActiveTab("ado")}
                      className={cn(
                        "flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-all cursor-pointer",
                        activeTab === "ado"
                          ? "bg-[var(--bg-surface-raised)] text-[var(--text-primary)] shadow-sm"
                          : "text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-surface-raised)]/50"
                      )}
                    >
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                        <path d="M22 4v16l-6 2V6l-8-2v14l-6 2V4l12 3 8-3z" fill="#0078D4" />
                      </svg>
                      Azure DevOps
                      {adoConnection?.status === "connected" && (
                        <span className="h-2 w-2 rounded-full bg-[var(--color-rag-green)]" />
                      )}
                    </button>
                  </div>

                  {/* Tab content */}
                  <div className="px-6 py-5">
                    <AnimatePresence mode="wait">
                      {activeTab === "jira" ? (
                        <motion.div
                          key="jira"
                          initial={{ opacity: 0, x: -10 }}
                          animate={{ opacity: 1, x: 0 }}
                          exit={{ opacity: 0, x: 10 }}
                          transition={{ duration: 0.15 }}
                        >
                          <JiraConnectCard />
                        </motion.div>
                      ) : (
                        <motion.div
                          key="ado"
                          initial={{ opacity: 0, x: -10 }}
                          animate={{ opacity: 1, x: 0 }}
                          exit={{ opacity: 0, x: 10 }}
                          transition={{ duration: 0.15 }}
                        >
                          <AdoConnectCard />
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>

                  {/* Show "Select Projects" button if connected */}
                  {isCurrentConnected && (
                    <div className="px-6 pb-4">
                      <button
                        onClick={() => handleFetchProjects(activeTab)}
                        disabled={loadingProjects}
                        className={cn(
                          "w-full flex items-center justify-center gap-2 rounded-lg px-4 py-2.5",
                          "text-sm font-medium",
                          "border border-[var(--color-brand-secondary)]/40",
                          "text-[var(--color-brand-secondary)]",
                          "hover:bg-[var(--color-brand-secondary)]/10",
                          "transition-all cursor-pointer",
                          "disabled:opacity-50 disabled:cursor-not-allowed"
                        )}
                      >
                        {loadingProjects ? (
                          <>
                            <Loader2 size={14} className="animate-spin" />
                            Fetching projects...
                          </>
                        ) : (
                          <>
                            <FolderKanban size={14} />
                            {currentConnection?.selectedProjects?.length
                              ? "Change Selected Projects"
                              : "Select Projects to Import"}
                          </>
                        )}
                      </button>
                    </div>
                  )}
                </motion.div>
              ) : (
                <motion.div
                  key="projects-step"
                  initial={{ opacity: 0, x: 10 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: 10 }}
                  transition={{ duration: 0.15 }}
                  className="flex-1 overflow-y-auto"
                >
                  {/* Project selection */}
                  <div className="px-6 py-4 space-y-3">
                    {loadingProjects ? (
                      <div className="flex flex-col items-center gap-3 py-8">
                        <Loader2 size={24} className="animate-spin text-[var(--color-brand-secondary)]" />
                        <p className="text-sm text-[var(--text-secondary)]">
                          Loading projects from {activeTab === "jira" ? "Jira" : "Azure DevOps"}...
                        </p>
                      </div>
                    ) : projectsError ? (
                      <div className="flex flex-col items-center gap-3 py-8">
                        <p className="text-sm text-[var(--color-rag-red)]">{projectsError}</p>
                        <button
                          onClick={() => handleFetchProjects(activeTab)}
                          className="text-sm text-[var(--color-brand-secondary)] hover:underline cursor-pointer"
                        >
                          Retry
                        </button>
                      </div>
                    ) : availableProjects.length === 0 ? (
                      <div className="flex flex-col items-center gap-3 py-8">
                        <FolderKanban size={32} className="text-[var(--text-tertiary)]" />
                        <p className="text-sm text-[var(--text-secondary)]">
                          No projects found. Make sure your credentials have access to at least one project.
                        </p>
                      </div>
                    ) : (
                      <>
                        <div className="flex items-center justify-between">
                          <p className="text-xs text-[var(--text-secondary)]">
                            {availableProjects.length} project{availableProjects.length !== 1 ? "s" : ""} found.
                            Select the ones you want to import.
                          </p>
                          <button
                            onClick={() => {
                              if (selectedProjectIds.size === availableProjects.length) {
                                setSelectedProjectIds(new Set());
                              } else {
                                setSelectedProjectIds(new Set(availableProjects.map((p) => p.id)));
                              }
                            }}
                            className="text-xs text-[var(--color-brand-secondary)] hover:underline cursor-pointer"
                          >
                            {selectedProjectIds.size === availableProjects.length
                              ? "Deselect All"
                              : "Select All"}
                          </button>
                        </div>

                        <div className="space-y-1.5 max-h-[320px] overflow-y-auto">
                          {availableProjects.map((project) => {
                            const selected = selectedProjectIds.has(project.id);
                            return (
                              <button
                                key={project.id}
                                onClick={() => toggleProject(project.id)}
                                className={cn(
                                  "w-full flex items-center gap-3 rounded-lg px-3 py-2.5 text-left",
                                  "border transition-all cursor-pointer",
                                  selected
                                    ? "border-[var(--color-brand-secondary)]/40 bg-[var(--color-brand-secondary)]/5"
                                    : "border-[var(--border-subtle)] hover:border-[var(--text-tertiary)] hover:bg-[var(--bg-surface-raised)]/50"
                                )}
                              >
                                <div
                                  className={cn(
                                    "flex h-5 w-5 shrink-0 items-center justify-center rounded",
                                    "border transition-all",
                                    selected
                                      ? "border-[var(--color-brand-secondary)] bg-[var(--color-brand-secondary)] text-white"
                                      : "border-[var(--border-subtle)]"
                                  )}
                                >
                                  {selected && <Check size={12} />}
                                </div>
                                <div className="flex-1 min-w-0">
                                  <div className="flex items-center gap-2">
                                    <span className="text-sm font-medium text-[var(--text-primary)] truncate">
                                      {project.name}
                                    </span>
                                    {project.key && (
                                      <span className="text-[11px] font-mono text-[var(--text-tertiary)] bg-[var(--bg-surface-raised)] px-1.5 py-0.5 rounded">
                                        {project.key}
                                      </span>
                                    )}
                                  </div>
                                  {project.description && (
                                    <p className="text-xs text-[var(--text-tertiary)] truncate mt-0.5">
                                      {project.description}
                                    </p>
                                  )}
                                </div>
                              </button>
                            );
                          })}
                        </div>
                      </>
                    )}
                  </div>

                  {/* Action buttons */}
                  <div className="px-6 pb-4 flex gap-2">
                    <button
                      onClick={handleBack}
                      className={cn(
                        "flex-1 rounded-lg px-4 py-2.5 text-sm font-medium",
                        "border border-[var(--border-subtle)]",
                        "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
                        "hover:bg-[var(--bg-surface-raised)]",
                        "transition-colors cursor-pointer"
                      )}
                    >
                      Back
                    </button>
                    <button
                      onClick={handleSaveProjects}
                      disabled={selectedProjectIds.size === 0}
                      className={cn(
                        "flex-1 rounded-lg px-4 py-2.5 text-sm font-medium text-white",
                        "bg-[var(--color-brand-secondary)] hover:bg-[var(--color-brand-secondary)]/90",
                        "transition-all cursor-pointer",
                        "disabled:opacity-50 disabled:cursor-not-allowed"
                      )}
                    >
                      Import {selectedProjectIds.size > 0 ? `${selectedProjectIds.size} Project${selectedProjectIds.size > 1 ? "s" : ""}` : "Projects"}
                    </button>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Footer */}
            <div className="px-6 py-3 border-t border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/30 rounded-b-2xl">
              <p className="text-[11px] text-[var(--text-tertiary)] text-center">
                Plan2Sprint only reads data from your tools. Write-back is limited to 3 fields and requires your explicit approval.
              </p>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
