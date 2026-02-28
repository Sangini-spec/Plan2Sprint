"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  type ReactNode,
} from "react";
import type {
  ConnectionInfo,
  ConnectionVariant,
  IntegrationContextType,
  SelectedProject,
  SyncStatus,
  ToolType,
} from "./types";
import {
  loadConnections,
  saveConnections as saveToLocalStorage,
  simulateDisconnect,
  simulateSync,
} from "./demo-connections";

// ============================================================================
// DEMO MODE DETECTION
// ============================================================================

const isDemoMode =
  !process.env.NEXT_PUBLIC_SUPABASE_URL ||
  process.env.NEXT_PUBLIC_SUPABASE_URL === "https://your-project.supabase.co";

// ============================================================================
// CONTEXT
// ============================================================================

const IntegrationContext = createContext<IntegrationContextType>({
  connections: [],
  loading: true,
  getConnection: () => undefined,
  isConnected: () => false,
  hasAnyConnection: false,
  connect: async () => {},
  disconnect: async () => {},
  triggerSync: async () => {},
  getSyncStatus: () => undefined,
  fetchProjects: async () => [],
  selectProjects: () => {},
  refreshJiraStatus: () => {},
  refreshAdoStatus: () => {},
  modalOpen: false,
  openModal: () => {},
  closeModal: () => {},
});

// ============================================================================
// PROVIDER
// ============================================================================

export function IntegrationProvider({ children }: { children: ReactNode }) {
  const [connections, setConnections] = useState<ConnectionInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncStatuses, setSyncStatuses] = useState<Map<ToolType, SyncStatus>>(new Map());
  const [modalOpen, setModalOpen] = useState(false);

  // Check Jira OAuth status from backend — merge with existing connection to preserve selectedProjects
  const refreshJiraStatus = useCallback(async () => {
    try {
      const res = await fetch("/api/integrations/jira/status");
      if (res.ok) {
        const data = await res.json();
        if (data.connected) {
          setConnections((prev) => {
            const existingJira = prev.find((c) => c.tool === "jira");
            const others = prev.filter((c) => c.tool !== "jira");
            return [
              ...others,
              {
                id: existingJira?.id ?? `conn-jira-oauth`,
                tool: "jira" as const,
                variant: "cloud" as const,
                status: "connected" as const,
                displayName: data.site_name || existingJira?.displayName || "Jira Cloud",
                siteUrl: data.site_url || existingJira?.siteUrl,
                syncMode: "manual" as const,
                connectedAt: data.connected_at || existingJira?.connectedAt,
                lastSyncedAt: existingJira?.lastSyncedAt || data.connected_at,
                // Preserve selected projects and credentials from stored connection
                selectedProjects: existingJira?.selectedProjects,
                projectCount: existingJira?.projectCount,
                credentials: existingJira?.credentials,
              },
            ];
          });
        }
      }
    } catch {
      // Ignore — Jira status check is optional
    }
  }, []);

  // Check ADO OAuth status from backend — merge with existing connection to preserve selectedProjects
  const refreshAdoStatus = useCallback(async () => {
    try {
      const res = await fetch("/api/integrations/ado/status");
      if (res.ok) {
        const data = await res.json();
        if (data.connected) {
          setConnections((prev) => {
            const existingAdo = prev.find((c) => c.tool === "ado");
            const others = prev.filter((c) => c.tool !== "ado");
            return [
              ...others,
              {
                id: existingAdo?.id ?? `conn-ado-oauth`,
                tool: "ado" as const,
                variant: "cloud" as const,
                status: "connected" as const,
                displayName: data.org_name || existingAdo?.displayName || "Azure DevOps",
                siteUrl: data.org_url || existingAdo?.siteUrl,
                projectCount: existingAdo?.projectCount ?? data.project_count,
                syncMode: "manual" as const,
                connectedAt: data.connected_at || existingAdo?.connectedAt,
                lastSyncedAt: existingAdo?.lastSyncedAt || data.connected_at,
                // Preserve selected projects and credentials from stored connection
                selectedProjects: existingAdo?.selectedProjects,
                credentials: existingAdo?.credentials,
              },
            ];
          });
        }
      }
    } catch {
      // Ignore — ADO status check is optional
    }
  }, []);

  // Load connections on mount
  useEffect(() => {
    const stored = loadConnections();
    setConnections(stored);
    setLoading(false);

    // Also check OAuth-based connections from backend
    refreshJiraStatus();
    refreshAdoStatus();
  }, [refreshJiraStatus, refreshAdoStatus]);

  // Persist whenever connections change
  useEffect(() => {
    if (connections.length > 0) {
      saveToLocalStorage(connections);
    }
  }, [connections]);

  const getConnection = useCallback(
    (tool: ToolType) => connections.find((c) => c.tool === tool),
    [connections]
  );

  const isConnected = useCallback(
    (tool: ToolType) => {
      const conn = connections.find((c) => c.tool === tool);
      return conn?.status === "connected" || conn?.status === "syncing";
    },
    [connections]
  );

  const hasAnyConnection = connections.some(
    (c) => c.status === "connected" || c.status === "syncing"
  );

  /**
   * Connect a tool with credentials.
   * config contains: orgUrl, pat (ADO) or siteUrl, email, apiToken (Jira)
   */
  const connect = useCallback(
    async (tool: ToolType, variant: ConnectionVariant, config?: Record<string, string>) => {
      // Mark as connecting
      setConnections((prev) => {
        const existing = prev.filter((c) => c.tool !== tool);
        return [
          ...existing,
          {
            id: `conn-${tool}-temp`,
            tool,
            variant,
            status: "connecting" as const,
            displayName: `Connecting ${tool}...`,
            syncMode: "manual" as const,
          },
        ];
      });

      try {
        // Validate credentials via API
        const res = await fetch("/api/integrations/connections", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tool, variant, config }),
        });
        const data = await res.json();

        if (!res.ok || data.error) {
          throw new Error(data.error ?? "Connection failed");
        }

        const connection: ConnectionInfo = {
          id: data.connection?.id ?? `conn-${tool}-${Date.now()}`,
          tool,
          variant,
          status: "connected",
          displayName: data.connection?.displayName ?? config?.orgUrl ?? config?.siteUrl ?? tool,
          siteUrl: config?.orgUrl ?? config?.siteUrl,
          projectCount: data.connection?.projectCount,
          syncMode: "manual",
          connectedAt: new Date().toISOString(),
          lastSyncedAt: new Date().toISOString(),
          credentials: {
            orgUrl: config?.orgUrl ?? config?.siteUrl,
            pat: config?.pat,
            email: config?.email,
            apiToken: config?.apiToken,
          },
        };

        setConnections((prev) => {
          const existing = prev.filter((c) => c.tool !== tool);
          return [...existing, connection];
        });
      } catch (err) {
        setConnections((prev) =>
          prev.map((c) =>
            c.tool === tool
              ? { ...c, status: "error" as const, error: err instanceof Error ? err.message : "Connection failed" }
              : c
          )
        );
        throw err;
      }
    },
    []
  );

  const disconnect = useCallback(async (tool: ToolType) => {
    try {
      if (isDemoMode) {
        await simulateDisconnect(tool);
      }
      setConnections((prev) => prev.filter((c) => c.tool !== tool));
      // Clear localStorage
      saveToLocalStorage(connections.filter((c) => c.tool !== tool));
    } catch {
      // Silently fail
    }
  }, [connections]);

  const triggerSync = useCallback(async (tool: ToolType) => {
    setConnections((prev) =>
      prev.map((c) => (c.tool === tool ? { ...c, status: "syncing" as const } : c))
    );
    setSyncStatuses((prev) => {
      const next = new Map(prev);
      next.set(tool, { tool, inProgress: true });
      return next;
    });

    try {
      let result: SyncStatus;
      if (isDemoMode) {
        result = await simulateSync(tool);
      } else {
        const res = await fetch("/api/integrations/sync", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tool }),
        });
        result = await res.json();
      }

      setConnections((prev) =>
        prev.map((c) =>
          c.tool === tool
            ? { ...c, status: "connected" as const, lastSyncedAt: result.lastSyncedAt }
            : c
        )
      );
      setSyncStatuses((prev) => {
        const next = new Map(prev);
        next.set(tool, result);
        return next;
      });
    } catch {
      setConnections((prev) =>
        prev.map((c) =>
          c.tool === tool ? { ...c, status: "error" as const, error: "Sync failed" } : c
        )
      );
    }
  }, []);

  const getSyncStatus = useCallback(
    (tool: ToolType) => syncStatuses.get(tool),
    [syncStatuses]
  );

  /** Fetch available projects from a connected tool */
  const fetchProjects = useCallback(
    async (tool: ToolType): Promise<SelectedProject[]> => {
      const conn = connections.find((c) => c.tool === tool);
      if (!conn) return [];

      try {
        let res: Response;

        if (tool === "jira") {
          // Jira uses OAuth — backend has stored tokens, just GET
          res = await fetch("/api/integrations/jira/projects");
        } else if (tool === "ado") {
          // ADO uses OAuth — backend has stored tokens, just GET
          res = await fetch("/api/integrations/ado/projects");
        } else {
          return [];
        }

        const data = await res.json();

        if (tool === "ado") {
          return (data.projects ?? []).map((p: { id: string; name: string; description?: string; url?: string }) => ({
            id: p.id,
            name: p.name,
            description: p.description,
            source: "ado" as const,
            url: p.url,
          }));
        } else if (tool === "jira") {
          return (data.projects ?? []).map((p: { id: string; key: string; name: string }) => ({
            id: p.id,
            name: p.name,
            key: p.key,
            source: "jira" as const,
          }));
        }
        return [];
      } catch {
        return [];
      }
    },
    [connections]
  );

  /** Save selected projects for a tool */
  const selectProjects = useCallback(
    (tool: ToolType, projects: SelectedProject[]) => {
      setConnections((prev) =>
        prev.map((c) =>
          c.tool === tool
            ? { ...c, selectedProjects: projects, projectCount: projects.length }
            : c
        )
      );
    },
    []
  );

  return (
    <IntegrationContext.Provider
      value={{
        connections,
        loading,
        getConnection,
        isConnected,
        hasAnyConnection,
        connect,
        disconnect,
        triggerSync,
        getSyncStatus,
        fetchProjects,
        selectProjects,
        refreshJiraStatus,
        refreshAdoStatus,
        modalOpen,
        openModal: () => setModalOpen(true),
        closeModal: () => setModalOpen(false),
      }}
    >
      {children}
    </IntegrationContext.Provider>
  );
}

// ============================================================================
// HOOK
// ============================================================================

export function useIntegrations() {
  const context = useContext(IntegrationContext);
  if (!context) {
    throw new Error("useIntegrations must be used within an IntegrationProvider");
  }
  return context;
}
