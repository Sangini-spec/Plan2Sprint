/**
 * Demo mode connection management using localStorage.
 * Simulates OAuth flows, connection persistence, and sync operations.
 */

import type {
  ConnectionInfo,
  ConnectionVariant,
  ToolType,
  SyncStatus,
  IntegrationAuditEntry,
} from "./types";

// ── Per-user storage scoping ──
// Prevents cross-user data leakage when multiple users share the same browser.
// Uses a user ID stored by AuthProvider on login.
function _getUserSuffix(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem("plan2sprint_uid") || "";
}

function _scopedKey(base: string): string {
  const suffix = _getUserSuffix();
  return suffix ? `${base}_${suffix}` : base;
}

/** Called by AuthProvider on login to set the scoping identifier. */
export function setStorageUserId(uid: string): void {
  if (typeof window === "undefined") return;
  localStorage.setItem("plan2sprint_uid", uid);
}

const BASE_STORAGE_KEY = "plan2sprint_connections";
const BASE_AUDIT_KEY = "plan2sprint_integration_audit";

export function clearAllConnectionStorage(): void {
  if (typeof window === "undefined") return;
  // Clear all plan2sprint connection keys
  const keysToRemove: string[] = [];
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key && (key.startsWith("plan2sprint_connections") || key.startsWith("plan2sprint_integration_audit"))) {
      keysToRemove.push(key);
    }
  }
  keysToRemove.forEach((k) => localStorage.removeItem(k));
}

// ============================================================================
// PERSISTENCE
// ============================================================================

export function loadConnections(): ConnectionInfo[] {
  if (typeof window === "undefined") return [];
  try {
    const key = _scopedKey(BASE_STORAGE_KEY);
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export function saveConnections(connections: ConnectionInfo[]): void {
  if (typeof window === "undefined") return;
  const key = _scopedKey(BASE_STORAGE_KEY);
  localStorage.setItem(key, JSON.stringify(connections));
}

// ============================================================================
// AUDIT LOG
// ============================================================================

export function loadAuditLog(): IntegrationAuditEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(_scopedKey(BASE_AUDIT_KEY));
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function appendAuditEntry(entry: Omit<IntegrationAuditEntry, "id" | "timestamp">): void {
  const log = loadAuditLog();
  log.push({
    ...entry,
    id: `audit-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    timestamp: new Date().toISOString(),
  });
  // Keep last 200 entries
  if (log.length > 200) log.splice(0, log.length - 200);
  localStorage.setItem(_scopedKey(BASE_AUDIT_KEY), JSON.stringify(log));
}

// ============================================================================
// TOOL DISPLAY INFO
// ============================================================================

const TOOL_DEFAULTS: Record<ToolType, { displayName: string; siteUrl: string }> = {
  jira: { displayName: "Acme Corp Jira", siteUrl: "https://acme.atlassian.net" },
  ado: { displayName: "Acme Azure DevOps", siteUrl: "https://dev.azure.com/acme" },
  github: { displayName: "acme-org", siteUrl: "https://github.com/acme-org" },
  slack: { displayName: "Acme Workspace", siteUrl: "https://acme.slack.com" },
  teams: { displayName: "Acme Teams", siteUrl: "https://teams.microsoft.com" },
  linear: { displayName: "Acme Linear", siteUrl: "https://linear.app/acme" },
};

// ============================================================================
// SIMULATED OPERATIONS
// ============================================================================

/** Simulate an OAuth connect flow with a delay */
export async function simulateConnect(
  tool: ToolType,
  variant: ConnectionVariant,
  _config?: Record<string, string>
): Promise<ConnectionInfo> {
  // Simulate network delay
  await new Promise((r) => setTimeout(r, 1500));

  const defaults = TOOL_DEFAULTS[tool];
  const connection: ConnectionInfo = {
    id: `conn-${tool}-${Date.now()}`,
    tool,
    variant,
    status: "connected",
    displayName: defaults.displayName,
    siteUrl: defaults.siteUrl,
    projectCount: tool === "github" ? undefined : Math.floor(Math.random() * 5) + 3,
    repoCount: tool === "github" ? Math.floor(Math.random() * 8) + 5 : undefined,
    syncMode: "webhook",
    lastSyncedAt: new Date().toISOString(),
    connectedAt: new Date().toISOString(),
  };

  const existing = loadConnections();
  // Replace if same tool already exists
  const filtered = existing.filter((c) => c.tool !== tool);
  filtered.push(connection);
  saveConnections(filtered);

  appendAuditEntry({ tool, action: "connected", success: true, details: `Connected ${tool} (${variant})` });

  return connection;
}

/** Simulate disconnecting a tool */
export async function simulateDisconnect(tool: ToolType): Promise<void> {
  await new Promise((r) => setTimeout(r, 800));

  const existing = loadConnections();
  saveConnections(existing.filter((c) => c.tool !== tool));

  appendAuditEntry({ tool, action: "disconnected", success: true, details: `Disconnected ${tool}` });
}

/** Simulate a sync operation */
export async function simulateSync(tool: ToolType): Promise<SyncStatus> {
  // Mark as syncing
  const connections = loadConnections();
  const conn = connections.find((c) => c.tool === tool);
  if (conn) {
    conn.status = "syncing";
    saveConnections(connections);
  }

  // Simulate sync delay
  await new Promise((r) => setTimeout(r, 2000));

  // Mark as synced
  const updated = loadConnections();
  const updatedConn = updated.find((c) => c.tool === tool);
  if (updatedConn) {
    updatedConn.status = "connected";
    updatedConn.lastSyncedAt = new Date().toISOString();
    saveConnections(updated);
  }

  appendAuditEntry({ tool, action: "synced", success: true, details: `Manual sync completed` });

  return {
    tool,
    inProgress: false,
    lastSyncedAt: new Date().toISOString(),
    itemsSynced: Math.floor(Math.random() * 30) + 10,
  };
}
