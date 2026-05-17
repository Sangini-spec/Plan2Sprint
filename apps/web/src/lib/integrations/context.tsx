"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  useCallback,
  useRef,
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

  // Check Jira OAuth status from backend - merge with existing connection to preserve selectedProjects
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
                // Restore selected projects from backend config, fallback to localStorage
                selectedProjects: data.selectedProjects?.length
                  ? data.selectedProjects
                  : existingJira?.selectedProjects,
                projectCount: existingJira?.projectCount,
                credentials: existingJira?.credentials,
              },
            ];
          });
        } else {
          // Backend says Jira is NOT connected - remove stale localStorage entry
          setConnections((prev) => {
            const hadJira = prev.some((c) => c.tool === "jira");
            if (hadJira) {
              const updated = prev.filter((c) => c.tool !== "jira");
              saveToLocalStorage(updated);
              return updated;
            }
            return prev;
          });
        }
      }
    } catch {
      // Ignore - Jira status check is optional
    }
  }, []);

  // Check ADO OAuth status from backend - merge with existing connection to preserve selectedProjects
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
                // Restore selected projects from backend config, fallback to localStorage
                selectedProjects: data.selectedProjects?.length
                  ? data.selectedProjects
                  : existingAdo?.selectedProjects,
                credentials: existingAdo?.credentials,
              },
            ];
          });
        } else {
          // Backend says ADO is NOT connected - remove stale localStorage entry
          setConnections((prev) => {
            const hadAdo = prev.some((c) => c.tool === "ado");
            if (hadAdo) {
              const updated = prev.filter((c) => c.tool !== "ado");
              saveToLocalStorage(updated);
              return updated;
            }
            return prev;
          });
        }
      }
    } catch {
      // Ignore - ADO status check is optional
    }
  }, []);

  // Check GitHub token status from backend - a developer may have persisted their token
  const refreshGithubStatus = useCallback(async () => {
    try {
      const res = await fetch("/api/integrations/github/status");
      if (res.ok) {
        const data = await res.json();
        if (data.connected) {
          setConnections((prev) => {
            const existingGh = prev.find((c) => c.tool === "github");
            const others = prev.filter((c) => c.tool !== "github");
            return [
              ...others,
              {
                id: existingGh?.id ?? `conn-github-oauth`,
                tool: "github" as const,
                variant: "cloud" as const,
                status: "connected" as const,
                displayName: data.user_name || data.user_login || existingGh?.displayName || "GitHub",
                syncMode: "manual" as const,
                connectedAt: data.connected_at || existingGh?.connectedAt,
                lastSyncedAt: existingGh?.lastSyncedAt || data.connected_at,
                selectedProjects: existingGh?.selectedProjects,
                credentials: existingGh?.credentials,
              },
            ];
          });
        }
      }
    } catch {
      // Ignore - GitHub status check is optional
    }
  }, []);

  // Check Slack connection status from backend
  const refreshSlackStatus = useCallback(async () => {
    try {
      const res = await fetch("/api/integrations/slack/status");
      if (res.ok) {
        const data = await res.json();
        if (data.connected) {
          setConnections((prev) => {
            const existing = prev.find((c) => c.tool === "slack");
            const others = prev.filter((c) => c.tool !== "slack");
            return [
              ...others,
              {
                id: existing?.id ?? `conn-slack-oauth`,
                tool: "slack" as const,
                variant: "cloud" as const,
                status: "connected" as const,
                displayName: data.team_name || existing?.displayName || "Slack",
                syncMode: "manual" as const,
                connectedAt: data.connected_at || existing?.connectedAt,
                lastSyncedAt: existing?.lastSyncedAt || data.connected_at,
              },
            ];
          });
        } else {
          setConnections((prev) => {
            const had = prev.some((c) => c.tool === "slack");
            if (had) {
              const updated = prev.filter((c) => c.tool !== "slack");
              saveToLocalStorage(updated);
              return updated;
            }
            return prev;
          });
        }
      }
    } catch {
      // Ignore
    }
  }, []);

  // Check Teams connection status from backend
  const refreshTeamsStatus = useCallback(async () => {
    try {
      const res = await fetch("/api/integrations/teams/status");
      if (res.ok) {
        const data = await res.json();
        if (data.connected) {
          setConnections((prev) => {
            const existing = prev.find((c) => c.tool === "teams");
            const others = prev.filter((c) => c.tool !== "teams");
            return [
              ...others,
              {
                id: existing?.id ?? `conn-teams-oauth`,
                tool: "teams" as const,
                variant: "cloud" as const,
                status: data.token_expired ? "token_expired" as const : "connected" as const,
                displayName: data.tenant_name || existing?.displayName || "Microsoft Teams",
                syncMode: "manual" as const,
                connectedAt: data.connected_at || existing?.connectedAt,
                lastSyncedAt: existing?.lastSyncedAt || data.connected_at,
              },
            ];
          });
        } else {
          setConnections((prev) => {
            const had = prev.some((c) => c.tool === "teams");
            if (had) {
              const updated = prev.filter((c) => c.tool !== "teams");
              saveToLocalStorage(updated);
              return updated;
            }
            return prev;
          });
        }
      }
    } catch {
      // Ignore
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
    refreshGithubStatus();
    refreshSlackStatus();
    refreshTeamsStatus();
  }, [refreshJiraStatus, refreshAdoStatus, refreshGithubStatus, refreshSlackStatus, refreshTeamsStatus]);

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
      setConnections((prev) => {
        const updated = prev.filter((c) => c.tool !== tool);
        // Save to localStorage using the fresh updated value (fixes stale closure)
        saveToLocalStorage(updated);
        return updated;
      });
    } catch {
      // Silently fail
    }
  }, []);

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
          // Jira uses OAuth - backend has stored tokens, just GET
          res = await fetch("/api/integrations/jira/projects");
        } else if (tool === "ado") {
          // ADO uses OAuth - backend has stored tokens, just GET
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

  /** Save selected projects for a tool (localStorage + backend) */
  const selectProjects = useCallback(
    (tool: ToolType, projects: SelectedProject[]) => {
      setConnections((prev) =>
        prev.map((c) =>
          c.tool === tool
            ? { ...c, selectedProjects: projects, projectCount: projects.length }
            : c
        )
      );
      // Persist to backend so selection survives across browsers/sessions
      const endpoint =
        tool === "ado" ? "/api/integrations/ado/selected-projects"
        : tool === "jira" ? "/api/integrations/jira/selected-projects"
        : null;
      if (endpoint) {
        fetch(endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ projects }),
        }).catch(() => {});
      }
    },
    []
  );

  // Stable callbacks for modal
  const openModal = useCallback(() => setModalOpen(true), []);
  const closeModal = useCallback(() => setModalOpen(false), []);

  // Memoize context value to prevent child re-renders
  const value = useMemo(
    () => ({
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
      openModal,
      closeModal,
    }),
    [
      connections, loading, getConnection, isConnected, hasAnyConnection,
      connect, disconnect, triggerSync, getSyncStatus, fetchProjects,
      selectProjects, refreshJiraStatus, refreshAdoStatus, modalOpen,
      openModal, closeModal,
    ]
  );

  return (
    <IntegrationContext.Provider value={value}>
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
