"use client";

/**
 * SelectedProjectContext — Task 1 (Project Selection)
 *
 * Provides the currently selected project across the entire app shell.
 * Every data-fetching page reads `selectedProject` from this context to
 * scope its queries to a single project.
 *
 * Persistence: selected project is saved to the database via
 *   POST /api/projects/preferences/selected
 * so it survives page refreshes and new logins.
 */

import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  useCallback,
  useMemo,
  type ReactNode,
} from "react";
import { useIntegrations } from "@/lib/integrations/context";
import type { SelectedProject } from "@/lib/integrations/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ProjectItem {
  /** Internal DB id (25-char CUID) — used for preference storage */
  internalId: string;
  /** External id from Jira/ADO */
  id: string;
  name: string;
  key?: string;
  description?: string;
  source: string; // "ado" | "jira"
  boardId?: string;
  isActive?: boolean;
}

interface SelectedProjectContextType {
  /** All projects in the org (from /api/projects) */
  projects: ProjectItem[];
  /** Currently selected project, or null for "All Projects" */
  selectedProject: ProjectItem | null;
  /** Whether the initial load is happening */
  loading: boolean;
  /** Select a project (pass null for "All Projects") */
  selectProject: (project: ProjectItem | null) => void;
  /** Refresh the project list from the API */
  refreshProjects: () => Promise<void>;
}

const SelectedProjectContext = createContext<SelectedProjectContextType>({
  projects: [],
  selectedProject: null,
  loading: true,
  selectProject: () => {},
  refreshProjects: async () => {},
});

export function useSelectedProject() {
  return useContext(SelectedProjectContext);
}

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function SelectedProjectProvider({ children }: { children: ReactNode }) {
  const [projects, setProjects] = useState<ProjectItem[]>([]);
  const [selectedProject, setSelectedProject] = useState<ProjectItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [initialized, setInitialized] = useState(false);
  const { connections } = useIntegrations();

  // Derive live projects from integration connections (fallback source)
  const liveProjects = useMemo<ProjectItem[]>(() => {
    return connections
      .filter((c) => c.status === "connected" || c.status === "syncing")
      .flatMap((c) => (c.selectedProjects ?? []).map((p: SelectedProject) => ({
        internalId: p.internalId || `live-${p.source}-${p.id}`,
        id: String(p.id),
        name: p.name,
        key: p.key,
        description: p.description,
        source: p.source as string,
      })));
  }, [connections]);

  // Load projects list + user's saved preference on mount
  useEffect(() => {
    let cancelled = false;

    async function init() {
      try {
        // Fetch projects and preference in parallel
        const [projectsRes, prefRes] = await Promise.allSettled([
          fetch("/api/projects").then((r) => (r.ok ? r.json() : null)),
          fetch("/api/projects/preferences/selected").then((r) => (r.ok ? r.json() : null)),
        ]);

        if (cancelled) return;

        // Parse projects from backend
        const dbProjects: ProjectItem[] =
          projectsRes.status === "fulfilled" && projectsRes.value
            ? (projectsRes.value.projects ?? []).map((p: Record<string, unknown>) => ({
                internalId: (p.internalId as string) || "",
                id: p.id as string,
                name: p.name as string,
                key: p.key as string | undefined,
                description: p.description as string | undefined,
                source: p.source as string,
                boardId: p.boardId as string | undefined,
                isActive: p.isActive as boolean | undefined,
              }))
            : [];

        // Merge: use DB projects, plus any live integration projects not already in DB
        const merged = [...dbProjects];
        for (const lp of liveProjects) {
          if (!merged.some((p) => String(p.id) === String(lp.id) && p.source === lp.source)) {
            merged.push(lp);
          }
        }

        setProjects(merged);

        // Restore saved preference
        const prefData =
          prefRes.status === "fulfilled" && prefRes.value
            ? prefRes.value.selectedProject
            : null;

        if (prefData && prefData.internalId) {
          const match = merged.find(
            (p: ProjectItem) => p.internalId === prefData.internalId
          );
          if (match) {
            setSelectedProject(match);
          } else if (merged.length > 0) {
            setSelectedProject(merged[0]);
          }
        } else if (merged.length > 0) {
          setSelectedProject(merged[0]);
        }
      } catch {
        // API down — fall back to live integration projects
        if (liveProjects.length > 0) {
          setProjects(liveProjects);
          setSelectedProject(liveProjects[0]);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
          setInitialized(true);
        }
      }
    }

    init();
    return () => {
      cancelled = true;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Merge live integration projects when connections change after init
  useEffect(() => {
    if (!initialized || liveProjects.length === 0) return;

    setProjects((prev) => {
      const merged = [...prev];
      let changed = false;
      for (const lp of liveProjects) {
        if (!merged.some((p) => String(p.id) === String(lp.id) && p.source === lp.source)) {
          merged.push(lp);
          changed = true;
        }
      }
      if (!changed) return prev;

      // Auto-select first project if none selected
      if (!selectedProject && merged.length > 0) {
        setSelectedProject(merged[0]);
      }
      return merged;
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveProjects, initialized]);

  // Save preference to DB whenever selectedProject changes (after init)
  // Debounced to avoid rapid-fire POSTs during initialization cascade
  const savePrefTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (!initialized) return;

    if (savePrefTimer.current) clearTimeout(savePrefTimer.current);
    savePrefTimer.current = setTimeout(() => {
      const projectId = selectedProject?.internalId ?? null;
      fetch("/api/projects/preferences/selected", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ projectId }),
      }).catch(() => {});
    }, 500); // 500ms debounce

    return () => {
      if (savePrefTimer.current) clearTimeout(savePrefTimer.current);
    };
  }, [selectedProject, initialized]);

  const selectProject = useCallback((project: ProjectItem | null) => {
    setSelectedProject(project);
  }, []);

  // Use ref for selectedProject to avoid re-creating refreshProjects on every selection
  const selectedProjectRef = useRef(selectedProject);
  selectedProjectRef.current = selectedProject;

  const refreshProjects = useCallback(async () => {
    try {
      const res = await fetch("/api/projects");
      if (!res.ok) return;
      const data = await res.json();
      const newProjects: ProjectItem[] = (data.projects ?? []).map(
        (p: Record<string, unknown>) => ({
          internalId: (p.internalId as string) || "",
          id: p.id as string,
          name: p.name as string,
          key: p.key as string | undefined,
          description: p.description as string | undefined,
          source: p.source as string,
          boardId: p.boardId as string | undefined,
          isActive: p.isActive as boolean | undefined,
        })
      );
      setProjects(newProjects);

      // If current selection no longer exists, reset to first
      const current = selectedProjectRef.current;
      if (
        current &&
        !newProjects.some((p) => p.internalId === current.internalId)
      ) {
        setSelectedProject(newProjects[0] ?? null);
      }
    } catch {
      // ignore
    }
  }, []); // No dependency on selectedProject — uses ref instead

  const value = useMemo(
    () => ({
      projects,
      selectedProject,
      loading,
      selectProject,
      refreshProjects,
    }),
    [projects, selectedProject, loading, selectProject, refreshProjects]
  );

  return (
    <SelectedProjectContext.Provider value={value}>
      {children}
    </SelectedProjectContext.Provider>
  );
}
