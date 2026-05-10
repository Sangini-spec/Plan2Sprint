"use client";

/**
 * SelectedProjectContext — Project Selection & Auto-Import
 *
 * Provides the currently selected project across the entire app shell.
 * Every data-fetching page reads `selectedProject` from this context to
 * scope its queries to a single project.
 *
 * Data flow:
 *   1. Load DB projects (GET /api/projects)
 *   2. Merge with liveProjects from IntegrationProvider (localStorage + status endpoints)
 *   3. If still 0 projects, discover from tool APIs (GET /api/integrations/ado|jira/projects)
 *   4. Auto-import first project to DB if it has no internalId
 *   5. Trigger sync to fetch work items from ADO/Jira
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
import { invalidateCache } from "@/lib/fetch-cache";

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
  /** True briefly after switching projects (cache cleared, data re-fetching) */
  switching: boolean;
  /** Select a project (pass null for "All Projects") */
  selectProject: (project: ProjectItem | null) => void;
  /** Refresh the project list from the API */
  refreshProjects: () => Promise<void>;
}

const SelectedProjectContext = createContext<SelectedProjectContextType>({
  projects: [],
  selectedProject: null,
  loading: true,
  switching: false,
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
  const [switching, setSwitching] = useState(false);
  const [initialized, setInitialized] = useState(false);
  const switchingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { connections } = useIntegrations();

  // Track auto-import to prevent duplicate calls
  const autoImportDone = useRef(false);

  // ── Derive liveProjects from connections ──
  // FIX: source comes from the CONNECTION's tool, not the project object
  // (localStorage may not have `source` stored on the project)
  const liveProjects = useMemo<ProjectItem[]>(() => {
    return connections
      .filter((c) => c.status === "connected" || c.status === "syncing")
      .flatMap((c) => (c.selectedProjects ?? []).map((p: SelectedProject) => ({
        internalId: p.internalId || "",
        id: String(p.id),
        name: p.name,
        key: p.key,
        description: p.description,
        source: p.source || c.tool, // FIX: fallback to connection's tool type
      })));
  }, [connections]);

  // Stable stringified key for liveProjects to avoid infinite re-renders.
  // Only re-run init when the actual project list changes, not on every
  // connections reference change.
  const liveProjectsKey = useMemo(() => {
    return liveProjects.map((p) => `${p.source}:${p.id}`).sort().join(",");
  }, [liveProjects]);

  // ── Helper: save a project to DB and trigger sync ──
  async function importAndSync(project: ProjectItem): Promise<ProjectItem> {
    try {
      const saveRes = await fetch("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: project.id,
          name: project.name,
          key: project.key,
          description: project.description,
          sourceTool: project.source,
          boardId: project.boardId,
        }),
      });
      if (saveRes.ok) {
        const saved = await saveRes.json();
        if (saved.internalId) {
          const updated = { ...project, internalId: saved.internalId };
          // Fire-and-forget: trigger full data sync from ADO/Jira
          fetch("/api/integrations/sync/auto", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ projectId: saved.internalId }),
          }).catch(() => {});
          return updated;
        }
      }
    } catch {
      // Non-fatal
    }
    return project;
  }

  // ── Helper: discover projects from connected tool APIs ──
  async function discoverProjectsFromTools(): Promise<ProjectItem[]> {
    const discovered: ProjectItem[] = [];
    // Try ADO
    try {
      const res = await fetch("/api/integrations/ado/projects");
      if (res.ok) {
        const data = await res.json();
        for (const p of data.projects ?? []) {
          discovered.push({
            internalId: "",
            id: String(p.id),
            name: p.name,
            key: p.key,
            description: p.description,
            source: "ado",
          });
        }
      }
    } catch { /* ADO not connected — skip */ }
    // Try Jira
    try {
      const res = await fetch("/api/integrations/jira/projects");
      if (res.ok) {
        const data = await res.json();
        for (const p of data.projects ?? []) {
          discovered.push({
            internalId: "",
            id: String(p.id),
            name: p.name,
            key: p.key,
            description: p.description,
            source: "jira",
          });
        }
      }
    } catch { /* Jira not connected — skip */ }
    return discovered;
  }

  // ── STEP 1: Initial load from DB ──
  // Runs once on mount. Loads DB projects + saved preference.
  //
  // Hotfix 31 — cold-start retry. The API runs on Azure Container Apps
  // with minReplicas=0 (cost-saving), so when a user opens the app after
  // ~5 min of idle the container has scaled to zero and the first
  // request hits a cold start (10-30s before a replica is ready). The
  // previous one-shot ``fetch`` would time out at the browser level and
  // render "No Projects" with the user's data fully intact in the DB.
  // ``fetchProjectsWithRetry`` retries on network errors, 5xx, and
  // 408/504 with exponential backoff (1s, 2s, 4s, 8s, 16s, 30s — total
  // ~60s max wait), giving the cold start time to complete. A 200 with
  // an empty projects array is NOT retried (that's a legitimate "no
  // projects yet" state for a new org).
  useEffect(() => {
    let cancelled = false;

    const RETRY_DELAYS_MS = [1_000, 2_000, 4_000, 8_000, 16_000];
    const COLD_START_RETRYABLE_STATUS = new Set([408, 502, 503, 504]);

    async function fetchWithRetry<T>(url: string): Promise<T | null> {
      let lastErr: unknown = null;
      for (let attempt = 0; attempt <= RETRY_DELAYS_MS.length; attempt++) {
        if (cancelled) return null;
        try {
          const r = await fetch(url);
          if (r.ok) return (await r.json()) as T;
          // 4xx (except retryable 408) — don't retry, no amount of waiting fixes a 401/403/404
          if (!COLD_START_RETRYABLE_STATUS.has(r.status)) return null;
          lastErr = new Error(`HTTP ${r.status}`);
        } catch (e) {
          // Network error / timeout / DNS — exactly the cold-start case
          lastErr = e;
        }
        if (attempt < RETRY_DELAYS_MS.length) {
          await new Promise((res) => setTimeout(res, RETRY_DELAYS_MS[attempt]));
        }
      }
      // All retries exhausted
      if (lastErr) console.warn("[project context] fetchWithRetry exhausted for", url, lastErr);
      return null;
    }

    async function init() {
      try {
        const [projectsRes, prefRes] = await Promise.allSettled([
          fetchWithRetry<{ projects?: Array<Record<string, unknown>> }>("/api/projects").then((d) => d ?? null),
          fetchWithRetry<{ selectedProject?: { internalId?: string } }>("/api/projects/preferences/selected").then((d) => d ?? null),
        ]);

        if (cancelled) return;

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

        if (cancelled) return;

        if (dbProjects.length > 0) {
          setProjects(dbProjects);

          // Restore preference
          const prefData =
            prefRes.status === "fulfilled" && prefRes.value
              ? prefRes.value.selectedProject
              : null;

          if (prefData?.internalId) {
            const match = dbProjects.find((p) => p.internalId === prefData.internalId);
            setSelectedProject(match ?? dbProjects[0]);
          } else {
            setSelectedProject(dbProjects[0]);
          }

          setLoading(false);
          setInitialized(true);
        } else {
          // No DB projects — mark initialized but keep loading=true
          // so STEP 2 can pick up liveProjects when connections load.
          setInitialized(true);
        }
      } catch {
        setInitialized(true);
      }
    }

    init();
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── STEP 2: When liveProjects arrive (connections loaded), auto-import ──
  // This runs when connections finish loading from localStorage/status endpoints.
  // Uses liveProjectsKey (stable string) to avoid infinite loops.
  useEffect(() => {
    if (!initialized) return;
    // If we already have a project with an internalId, we're good
    if (selectedProject?.internalId) return;
    // If auto-import already done, skip
    if (autoImportDone.current) return;

    let cancelled = false;

    async function handleLiveProjects() {
      let projectsToUse = [...liveProjects];

      // If liveProjects is also empty, try discovering from tool APIs
      if (projectsToUse.length === 0) {
        const discovered = await discoverProjectsFromTools();
        if (cancelled) return;
        projectsToUse = discovered;
      }

      if (projectsToUse.length === 0) {
        // No projects anywhere — show welcome screen
        setProjects([]);
        setSelectedProject(null);
        setLoading(false);
        return;
      }

      // Set projects immediately so UI shows the project name
      setProjects(projectsToUse);
      setSelectedProject(projectsToUse[0]);

      // Now auto-import the first project to DB + trigger sync
      autoImportDone.current = true;
      const imported = await importAndSync(projectsToUse[0]);
      if (cancelled) return;

      if (imported.internalId) {
        const updated = projectsToUse.map((p, i) =>
          i === 0 ? imported : p
        );
        setProjects(updated);
        setSelectedProject(imported);
      }

      setLoading(false);
    }

    handleLiveProjects();
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialized, liveProjectsKey]);

  // Save preference to DB whenever selectedProject changes (after init)
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
    }, 500);

    return () => {
      if (savePrefTimer.current) clearTimeout(savePrefTimer.current);
    };
  }, [selectedProject, initialized]);

  const selectProject = useCallback(async (project: ProjectItem | null) => {
    invalidateCache();
    setSwitching(true);

    // Auto-import if project has no internalId
    if (project && !project.internalId) {
      const imported = await importAndSync(project);
      if (imported.internalId) {
        project = imported;
        setProjects((prev) =>
          prev.map((p) =>
            String(p.id) === String(project!.id) && p.source === project!.source
              ? project! : p
          )
        );
      }
    }

    setSelectedProject(project);

    if (switchingTimer.current) clearTimeout(switchingTimer.current);
    switchingTimer.current = setTimeout(() => setSwitching(false), 400);
  }, []);

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

      const current = selectedProjectRef.current;
      if (current && !newProjects.some((p) => p.internalId === current.internalId)) {
        setSelectedProject(newProjects[0] ?? null);
      }
    } catch {
      // ignore
    }
  }, []);

  const value = useMemo(
    () => ({
      projects,
      selectedProject,
      loading,
      switching,
      selectProject,
      refreshProjects,
    }),
    [projects, selectedProject, loading, switching, selectProject, refreshProjects]
  );

  return (
    <SelectedProjectContext.Provider value={value}>
      {children}
    </SelectedProjectContext.Provider>
  );
}
