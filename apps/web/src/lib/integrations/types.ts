/**
 * Integration layer types for tool connections (Jira, ADO, GitHub).
 */

// ============================================================================
// TOOL TYPES
// ============================================================================

export type ToolType = "jira" | "ado" | "github" | "slack" | "linear";

export type ConnectionVariant =
  | "cloud"       // Jira Cloud, ADO Cloud
  | "datacenter"  // Jira Data Center
  | "server";     // ADO Server

export type ConnectionStatus =
  | "disconnected"
  | "connecting"
  | "connected"
  | "syncing"
  | "error"
  | "token_expired";

export type SyncMode = "webhook" | "polling" | "manual";

// ============================================================================
// CREDENTIALS
// ============================================================================

export interface ConnectionCredentials {
  // ADO: orgUrl + pat
  orgUrl?: string;
  pat?: string;
  // Jira: siteUrl + email + apiToken
  email?: string;
  apiToken?: string;
  // GitHub: installationId + token
  installationId?: string;
  accessToken?: string;
}

// ============================================================================
// SELECTED PROJECT
// ============================================================================

export interface SelectedProject {
  id: string;
  internalId?: string;   // DB primary key (CUID) from imported_projects table
  name: string;
  key?: string;          // Jira project key
  description?: string;
  source: ToolType;
  url?: string;
}

// ============================================================================
// CONNECTION STATE
// ============================================================================

export interface ConnectionInfo {
  id: string;
  tool: ToolType;
  variant: ConnectionVariant;
  status: ConnectionStatus;
  displayName: string;
  siteUrl?: string;
  projectCount?: number;
  repoCount?: number;
  syncMode: SyncMode;
  lastSyncedAt?: string;
  connectedAt?: string;
  error?: string;
  credentials?: ConnectionCredentials;
  selectedProjects?: SelectedProject[];
}

// ============================================================================
// ADO WORK ITEM (real shape from API)
// ============================================================================

export interface AdoWorkItem {
  id: number;
  title: string;
  state: string;
  workItemType: string;
  assignedTo?: string;
  areaPath?: string;
  iterationPath?: string;
  storyPoints?: number;
  priority?: number;
  tags?: string;
  createdDate?: string;
  changedDate?: string;
  description?: string;
}

export interface AdoTeamMember {
  id: string;
  displayName: string;
  uniqueName: string;
  imageUrl?: string;
}

// ============================================================================
// OAUTH CONFIG
// ============================================================================

export interface OAuthConfig {
  clientId: string;
  redirectUri: string;
  scopes: string[];
  authorizeUrl: string;
  tokenUrl: string;
}

// ============================================================================
// SYNC STATUS
// ============================================================================

export interface SyncStatus {
  tool: ToolType;
  inProgress: boolean;
  lastSyncedAt?: string;
  itemsSynced?: number;
  error?: string;
}

// ============================================================================
// INTEGRATION CONTEXT
// ============================================================================

export interface IntegrationContextType {
  connections: ConnectionInfo[];
  loading: boolean;
  getConnection: (tool: ToolType) => ConnectionInfo | undefined;
  isConnected: (tool: ToolType) => boolean;
  hasAnyConnection: boolean;
  connect: (tool: ToolType, variant: ConnectionVariant, config?: Record<string, string>) => Promise<void>;
  disconnect: (tool: ToolType) => Promise<void>;
  triggerSync: (tool: ToolType) => Promise<void>;
  getSyncStatus: (tool: ToolType) => SyncStatus | undefined;
  fetchProjects: (tool: ToolType) => Promise<SelectedProject[]>;
  selectProjects: (tool: ToolType, projects: SelectedProject[]) => void;
  refreshJiraStatus?: () => void;
  refreshAdoStatus?: () => void;
  modalOpen: boolean;
  openModal: () => void;
  closeModal: () => void;
}

// ============================================================================
// AUDIT LOG (integration events)
// ============================================================================

export interface IntegrationAuditEntry {
  id: string;
  timestamp: string;
  tool: ToolType;
  action: "connected" | "disconnected" | "synced" | "sync_failed" | "writeback" | "writeback_failed" | "webhook_received" | "token_refreshed" | "token_expired";
  details?: string;
  success: boolean;
}

// ============================================================================
// API RESPONSE SHAPES
// ============================================================================

export interface JiraProject {
  id: string;
  key: string;
  name: string;
  projectType: string;
  avatarUrl?: string;
}

export interface JiraSprint {
  id: string;
  name: string;
  state: "active" | "closed" | "future";
  startDate?: string;
  endDate?: string;
  boardId: string;
}

export interface AdoProject {
  id: string;
  name: string;
  description?: string;
  state: string;
  url: string;
}

export interface AdoIteration {
  id: string;
  name: string;
  path: string;
  startDate?: string;
  finishDate?: string;
}

export interface GitHubRepo {
  id: string;
  name: string;
  fullName: string;
  defaultBranch: string;
  url: string;
  isPrivate: boolean;
  language?: string;
  openIssuesCount: number;
  stargazersCount: number;
}
