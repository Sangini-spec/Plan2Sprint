"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import {
  FolderKanban,
  ChevronRight,
  Users,
  ListTodo,
  Loader2,
  AlertCircle,
  Search,
  Plug,
  LayoutDashboard,
  Layers,
  BookOpen,
  IterationCw,
  ClipboardList,
  RefreshCw,
  PanelLeftOpen,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useIntegrations } from "@/lib/integrations/context";
import type { SelectedProject, ToolType, AdoWorkItem, AdoTeamMember, AdoIteration } from "@/lib/integrations/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface JiraIssue {
  id: string;
  key: string;
  summary: string;
  status: string;
  issueType: string;
  assignee?: string;
  priority?: string;
  storyPoints?: number;
  sprint?: string;
  created?: string;
  updated?: string;
  labels?: string[];
}

interface JiraMember {
  accountId: string;
  displayName: string;
  emailAddress?: string;
  avatarUrl?: string;
}

interface ProjectData {
  workItems: AdoWorkItem[] | JiraIssue[];
  teamMembers: AdoTeamMember[] | JiraMember[];
  iterations: AdoIteration[];
  loading: boolean;
  error?: string;
}

type DetailTab = "overview" | "features" | "stories" | "sprints" | "backlog" | "team";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getStatusColor(status: string): string {
  const l = status.toLowerCase();
  if (l.includes("done") || l.includes("closed") || l.includes("resolved") || l.includes("completed"))
    return "bg-[var(--color-rag-green)]/10 text-[var(--color-rag-green)] border-[var(--color-rag-green)]/20";
  if (l.includes("progress") || l.includes("active") || l.includes("doing") || l.includes("committed"))
    return "bg-[var(--color-brand-secondary)]/10 text-[var(--color-brand-secondary)] border-[var(--color-brand-secondary)]/20";
  if (l.includes("blocked") || l.includes("impediment") || l.includes("removed"))
    return "bg-[var(--color-rag-red)]/10 text-[var(--color-rag-red)] border-[var(--color-rag-red)]/20";
  if (l.includes("review") || l.includes("testing"))
    return "bg-[var(--color-rag-amber)]/10 text-[var(--color-rag-amber)] border-[var(--color-rag-amber)]/20";
  return "bg-[var(--bg-surface-raised)] text-[var(--text-secondary)] border-[var(--border-subtle)]";
}

function getTypeIcon(type: string): string {
  const l = type.toLowerCase();
  if (l.includes("epic")) return "E";
  if (l.includes("feature")) return "F";
  if (l.includes("bug")) return "B";
  if (l.includes("task")) return "T";
  if (l.includes("story") || l.includes("user story")) return "S";
  return "W";
}

function getTypeIconColor(type: string): string {
  const l = type.toLowerCase();
  if (l.includes("epic")) return "bg-[#FF7B00]/10 text-[#FF7B00] border-[#FF7B00]/20";
  if (l.includes("feature")) return "bg-[#773B93]/10 text-[#773B93] border-[#773B93]/20";
  if (l.includes("bug")) return "bg-[var(--color-rag-red)]/10 text-[var(--color-rag-red)] border-[var(--color-rag-red)]/20";
  if (l.includes("task")) return "bg-[#F2CB1D]/10 text-[#F2CB1D] border-[#F2CB1D]/20";
  if (l.includes("story") || l.includes("user story")) return "bg-[#009CCC]/10 text-[#009CCC] border-[#009CCC]/20";
  return "bg-[var(--bg-surface-raised)] text-[var(--text-secondary)] border-[var(--border-subtle)]";
}

// ---------------------------------------------------------------------------
// WorkItemRow
// ---------------------------------------------------------------------------

function WorkItemRow({ item }: { item: AdoWorkItem | JiraIssue }) {
  const isAdo = "workItemType" in item;
  const id = isAdo ? `#${(item as AdoWorkItem).id}` : (item as JiraIssue).key;
  const title = isAdo ? (item as AdoWorkItem).title : (item as JiraIssue).summary;
  const type = isAdo ? (item as AdoWorkItem).workItemType : (item as JiraIssue).issueType;
  const status = isAdo ? (item as AdoWorkItem).state : (item as JiraIssue).status;
  const assignee = isAdo ? (item as AdoWorkItem).assignedTo : (item as JiraIssue).assignee;
  const points = isAdo ? (item as AdoWorkItem).storyPoints : (item as JiraIssue).storyPoints;
  const priority = isAdo ? (item as AdoWorkItem).priority : undefined;

  return (
    <div className="flex items-center gap-3 px-4 py-3 hover:bg-[var(--bg-surface-raised)]/30 transition-colors group">
      <div className={cn("flex h-6 w-6 shrink-0 items-center justify-center rounded text-[10px] font-bold border", getTypeIconColor(type))} title={type}>
        {getTypeIcon(type)}
      </div>
      <span className="text-xs font-mono text-[var(--text-tertiary)] w-16 shrink-0">{id}</span>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-[var(--text-primary)] truncate group-hover:text-[var(--color-brand-secondary)] transition-colors">{title}</p>
      </div>
      {priority != null && (
        <span className="text-[10px] font-medium text-[var(--text-tertiary)] w-6 text-center shrink-0" title={`Priority ${priority}`}>P{priority}</span>
      )}
      {points != null && (
        <div className="flex h-5 w-5 items-center justify-center rounded-full bg-[var(--color-brand-secondary)]/10 text-[10px] font-bold text-[var(--color-brand-secondary)] shrink-0" title="Story Points">{points}</div>
      )}
      <div className="w-28 shrink-0">
        {assignee ? (
          <div className="flex items-center gap-1.5">
            <div className="flex h-5 w-5 items-center justify-center rounded-full bg-[var(--color-brand-secondary)]/20 text-[9px] font-semibold text-[var(--color-brand-secondary)]">{assignee.charAt(0).toUpperCase()}</div>
            <span className="text-xs text-[var(--text-secondary)] truncate">{assignee.split(" ")[0]}</span>
          </div>
        ) : (
          <span className="text-[11px] text-[var(--text-tertiary)] italic">Unassigned</span>
        )}
      </div>
      <span className={cn("text-[10px] font-medium px-2.5 py-0.5 rounded-full border shrink-0 truncate max-w-[100px] text-center", getStatusColor(status))}>{status}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section wrapper
// ---------------------------------------------------------------------------

function SectionCard({ title, icon: Icon, count, children, emptyMessage }: {
  title: string; icon: typeof ListTodo; count: number; children: React.ReactNode; emptyMessage?: string;
}) {
  return (
    <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]/50 overflow-hidden">
      <div className="flex items-center gap-2 px-5 py-3 border-b border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/20">
        <Icon size={16} className="text-[var(--color-brand-secondary)]" />
        <h3 className="text-sm font-semibold text-[var(--text-primary)]">{title}</h3>
        <span className="ml-auto text-xs text-[var(--text-tertiary)]">{count} items</span>
      </div>
      {count === 0 ? (
        <div className="py-8 text-center text-sm text-[var(--text-tertiary)]">{emptyMessage ?? `No ${title.toLowerCase()} found.`}</div>
      ) : (
        <div className="divide-y divide-[var(--border-subtle)]">{children}</div>
      )}
    </div>
  );
}

function SearchBar({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder: string }) {
  return (
    <div className="relative">
      <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)]" />
      <input type="text" placeholder={placeholder} value={value} onChange={(e) => onChange(e.target.value)}
        className={cn("w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] pl-9 pr-3 py-2 text-sm", "text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)]", "focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)]/40")} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function ProjectsPage() {
  const { connections, getConnection, openModal } = useIntegrations();
  const [selectedProject, setSelectedProject] = useState<SelectedProject | null>(null);
  const [activeTab, setActiveTab] = useState<DetailTab>("overview");
  const [searchQuery, setSearchQuery] = useState("");
  const [projectData, setProjectData] = useState<ProjectData>({ workItems: [], teamMembers: [], iterations: [], loading: false });
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [dbProjects, setDbProjects] = useState<SelectedProject[]>([]);

  // Load persisted projects from database on mount
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch("/api/projects");
        if (res.ok) {
          const data = await res.json();
          setDbProjects((data.projects ?? []).map((p: Record<string, unknown>) => ({
            id: p.id as string,
            internalId: p.internalId as string | undefined,
            name: p.name as string,
            key: p.key as string | undefined,
            description: p.description as string | undefined,
            source: p.source as string,
            cachedData: p.cachedData as Record<string, unknown> | undefined,
          })));
        }
      } catch { /* backend may be down */ }
    })();
  }, []);

  // Live projects from active connections
  const liveProjects: SelectedProject[] = connections
    .filter((c) => c.status === "connected" || c.status === "syncing")
    .flatMap((c) => c.selectedProjects ?? []);

  // Save new live projects to DB when they appear
  useEffect(() => {
    for (const p of liveProjects) {
      if (!dbProjects.some((e) => String(e.id) === String(p.id) && e.source === p.source)) {
        fetch("/api/projects", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: p.id, name: p.name, key: p.key, description: p.description, source: p.source }),
        }).then(async (res) => {
          const result = res.ok ? await res.json() : {};
          setDbProjects((prev) => {
            if (prev.some((e) => String(e.id) === String(p.id) && e.source === p.source)) return prev;
            return [...prev, { ...p, internalId: result.internalId }];
          });
        }).catch(() => {});
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveProjects.length]);

  // Merge: DB projects + any live projects not yet in DB
  const allProjects = useMemo(() => {
    const merged = [...dbProjects];
    for (const p of liveProjects) {
      if (!merged.some((e) => String(e.id) === String(p.id) && e.source === p.source)) {
        merged.push(p);
      }
    }
    return merged;
  }, [dbProjects, liveProjects]);

  const hasConnections = connections.some((c) => c.status === "connected" || c.status === "syncing");
  const hasProjects = allProjects.length > 0;

  useEffect(() => {
    if (allProjects.length > 0 && !selectedProject) setSelectedProject(allProjects[0]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allProjects.length]);

  const fetchProjectData = useCallback(async (project: SelectedProject) => {
    setProjectData({ workItems: [], teamMembers: [], iterations: [], loading: true });
    setActiveTab("overview");
    try {
      const conn = getConnection(project.source as ToolType);
      const isConnected = conn && conn.status === "connected";

      // If tool is connected, fetch live data from the integration
      if (isConnected) {
        let workItems: AdoWorkItem[] | JiraIssue[] = [];
        let teamMembers: AdoTeamMember[] | JiraMember[] = [];
        let iterations: AdoIteration[] = [];

        if (project.source === "ado") {
          const [wiRes, tmRes, itRes] = await Promise.all([
            fetch("/api/integrations/ado/work-items", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ projectName: project.name }) }),
            fetch("/api/integrations/ado/team-members", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ projectName: project.name }) }),
            fetch("/api/integrations/ado/iterations", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ projectName: project.name }) }),
          ]);
          // Check for "not connected" 404 specifically — surface reconnection message
          if (wiRes.status === 404 || tmRes.status === 404 || itRes.status === 404) {
            throw new Error("Azure DevOps connection not found. Please reconnect ADO from the Integrations page.");
          }
          if (!wiRes.ok) throw new Error(`Work items: ${wiRes.status} ${wiRes.statusText}`);
          if (!tmRes.ok) throw new Error(`Team members: ${tmRes.status} ${tmRes.statusText}`);
          if (!itRes.ok) throw new Error(`Iterations: ${itRes.status} ${itRes.statusText}`);
          const wiData = await wiRes.json();
          const tmData = await tmRes.json();
          const itData = await itRes.json();
          workItems = wiData.workItems ?? [];
          teamMembers = tmData.members ?? [];
          iterations = itData.iterations ?? [];
        } else if (project.source === "jira") {
          const [issRes, memRes] = await Promise.all([
            fetch("/api/integrations/jira/issues", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ projectKey: project.key ?? project.name }) }),
            fetch("/api/integrations/jira/members", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ projectKey: project.key ?? project.name }) }),
          ]);
          if (issRes.status === 404 || memRes.status === 404) {
            throw new Error("Jira connection not found. Please reconnect Jira from the Integrations page.");
          }
          if (!issRes.ok) throw new Error(`Issues: ${issRes.status} ${issRes.statusText}`);
          if (!memRes.ok) throw new Error(`Members: ${memRes.status} ${memRes.statusText}`);
          const issData = await issRes.json();
          const memData = await memRes.json();
          workItems = issData.issues ?? [];
          teamMembers = memData.members ?? [];
        }

        setProjectData({ workItems, teamMembers, iterations, loading: false });

        // Cache the fetched data in the database for offline access
        fetch(`/api/projects/${project.id}/cache`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ cachedData: { workItems, teamMembers, iterations } }),
        }).catch(() => {});

        // Sync: normalise + upsert into DB (background, fire-and-forget)
        if (project.internalId) {
          fetch("/api/integrations/sync/project", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              projectId: project.internalId,
              sourceTool: project.source?.toUpperCase(),
              iterations,
              members: teamMembers,
              workItems,
            }),
          }).catch(() => {});
        }
        return;
      }

      // Tool not connected — try loading cached data from DB
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const cached = (project as any).cachedData as { workItems?: AdoWorkItem[]; teamMembers?: AdoTeamMember[]; iterations?: AdoIteration[] } | undefined;
      if (cached && ((cached.workItems?.length ?? 0) > 0 || (cached.teamMembers?.length ?? 0) > 0)) {
        setProjectData({
          workItems: (cached.workItems ?? []) as AdoWorkItem[],
          teamMembers: (cached.teamMembers ?? []) as AdoTeamMember[],
          iterations: cached.iterations ?? [],
          loading: false,
        });
        return;
      }

      // No cached data and not connected
      setProjectData({ workItems: [], teamMembers: [], iterations: [], loading: false, error: "Tool disconnected. Reconnect to fetch latest data." });
    } catch (err) {
      setProjectData({ workItems: [], teamMembers: [], iterations: [], loading: false, error: err instanceof Error ? err.message : "Failed to fetch project data" });
    }
  }, [getConnection]);

  useEffect(() => { if (selectedProject) fetchProjectData(selectedProject); }, [selectedProject, fetchProjectData]);

  const allItems = projectData.workItems as (AdoWorkItem | JiraIssue)[];

  const categorized = useMemo(() => {
    const features: (AdoWorkItem | JiraIssue)[] = [];
    const stories: (AdoWorkItem | JiraIssue)[] = [];
    const backlog: (AdoWorkItem | JiraIssue)[] = [];
    for (const item of allItems) {
      const type = ("workItemType" in item ? (item as AdoWorkItem).workItemType : (item as JiraIssue).issueType).toLowerCase();
      if (type.includes("epic") || type.includes("feature")) features.push(item);
      else if (type.includes("story") || type.includes("user story")) stories.push(item);
      else backlog.push(item);
    }
    return { features, stories, backlog };
  }, [allItems]);

  const stats = useMemo(() => {
    const stateCount: Record<string, number> = {};
    const typeCount: Record<string, number> = {};
    for (const item of allItems) {
      const state = "workItemType" in item ? (item as AdoWorkItem).state : (item as JiraIssue).status;
      const type = "workItemType" in item ? (item as AdoWorkItem).workItemType : (item as JiraIssue).issueType;
      stateCount[state] = (stateCount[state] ?? 0) + 1;
      typeCount[type] = (typeCount[type] ?? 0) + 1;
    }
    return { stateCount, typeCount };
  }, [allItems]);

  const filterItems = useCallback((items: (AdoWorkItem | JiraIssue)[]) => {
    if (!searchQuery) return items;
    const q = searchQuery.toLowerCase();
    return items.filter((item) => {
      const title = "workItemType" in item ? (item as AdoWorkItem).title : (item as JiraIssue).summary;
      const id = "workItemType" in item ? String((item as AdoWorkItem).id) : (item as JiraIssue).key;
      return title.toLowerCase().includes(q) || id?.toLowerCase().includes(q);
    });
  }, [searchQuery]);

  // ---------- Empty state ----------
  if (!hasProjects) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] px-6">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-[var(--color-brand-secondary)]/10 mb-4">
          <FolderKanban size={32} className="text-[var(--color-brand-secondary)]" />
        </div>
        <h2 className="text-lg font-semibold text-[var(--text-primary)] mb-2">No Projects Imported</h2>
        <p className="text-sm text-[var(--text-secondary)] text-center max-w-md mb-6">
          {!hasConnections ? "Connect Azure DevOps or Jira to import your projects, work items, sprints, and team data." : "You've connected tools but haven't selected projects yet. Open Connect Tools to choose projects."}
        </p>
        <button onClick={openModal} className={cn("flex items-center gap-2 rounded-lg px-5 py-2.5 text-sm font-medium text-white bg-[var(--color-brand-secondary)] hover:bg-[var(--color-brand-secondary)]/90 transition-all cursor-pointer")}>
          <Plug size={16} />
          {!hasConnections ? "Connect Tools" : "Select Projects"}
        </button>
      </div>
    );
  }

  // ---------- Tabs ----------
  const tabs: { id: DetailTab; label: string; icon: typeof ListTodo; count: number }[] = [
    { id: "overview", label: "Overview", icon: LayoutDashboard, count: allItems.length },
    { id: "features", label: "Features & Epics", icon: Layers, count: categorized.features.length },
    { id: "stories", label: "User Stories", icon: BookOpen, count: categorized.stories.length },
    { id: "sprints", label: "Sprints", icon: IterationCw, count: projectData.iterations.length },
    { id: "backlog", label: "Backlog", icon: ClipboardList, count: categorized.backlog.length },
    { id: "team", label: "Team", icon: Users, count: projectData.teamMembers.length },
  ];

  return (
    <div className="flex h-[calc(100vh-4rem)] overflow-hidden">
      {/* Left sidebar — collapsible */}
      <div className={cn(
        "shrink-0 border-r border-[var(--border-subtle)] bg-[var(--bg-surface)]/50 overflow-y-auto transition-all duration-300 ease-in-out",
        sidebarOpen ? "w-64" : "w-0 border-r-0 overflow-hidden"
      )}>
        <div className={cn("p-4 transition-opacity duration-200", sidebarOpen ? "opacity-100" : "opacity-0")}>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-[10px] font-semibold uppercase tracking-widest text-[var(--text-tertiary)]">Projects</h3>
            <button onClick={() => setSidebarOpen(false)} title="Close project panel"
              className="flex h-7 w-7 items-center justify-center rounded-lg border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-[var(--color-rag-red)] hover:border-[var(--color-rag-red)]/30 hover:bg-[var(--color-rag-red)]/5 transition-colors cursor-pointer">
              <X size={14} />
            </button>
          </div>
          <div className="space-y-1">
            {allProjects.map((project) => (
              <button key={`${project.source}-${project.id}`} onClick={() => { setSelectedProject(project); setSearchQuery(""); }}
                className={cn("w-full flex items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-all cursor-pointer",
                  selectedProject?.id === project.id && selectedProject?.source === project.source
                    ? "bg-[var(--color-brand-secondary)]/10 text-[var(--color-brand-secondary)]"
                    : "text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-surface-raised)]")}>
                <div className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[10px] font-bold",
                  project.source === "ado" ? "bg-[#0078D4]/10 text-[#0078D4]" : "bg-[#0052CC]/10 text-[#0052CC]")}>
                  {project.source === "ado" ? "AD" : "JR"}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{project.name}</p>
                  {project.key && <p className="text-[10px] text-[var(--text-tertiary)]">{project.key}</p>}
                </div>
                <ChevronRight size={14} className="shrink-0 opacity-40" />
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Main */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {selectedProject ? (
          <>
            {/* Header */}
            <div className="px-6 pt-5 pb-0 shrink-0">
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-start gap-3">
                  {!sidebarOpen && (
                    <button onClick={() => setSidebarOpen(true)} title="Show projects panel"
                      className="flex h-8 items-center gap-1.5 mt-0.5 px-2.5 rounded-lg border border-[var(--border-subtle)] text-xs font-medium text-[var(--text-secondary)] hover:text-[var(--color-brand-secondary)] hover:border-[var(--color-brand-secondary)]/30 hover:bg-[var(--color-brand-secondary)]/5 transition-colors cursor-pointer">
                      <PanelLeftOpen size={14} />
                      <span>Projects</span>
                    </button>
                  )}
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <span className={cn("text-[10px] font-bold uppercase px-2 py-0.5 rounded",
                        selectedProject.source === "ado" ? "bg-[#0078D4]/10 text-[#0078D4]" : "bg-[#0052CC]/10 text-[#0052CC]")}>
                        {selectedProject.source === "ado" ? "Azure DevOps" : "Jira"}
                      </span>
                    </div>
                    <h2 className="text-xl font-bold text-[var(--text-primary)]">{selectedProject.name}</h2>
                    {selectedProject.description && <p className="text-sm text-[var(--text-secondary)] mt-1 max-w-2xl">{selectedProject.description}</p>}
                  </div>
                </div>
                <button onClick={() => fetchProjectData(selectedProject)} disabled={projectData.loading}
                  className={cn("flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:bg-[var(--bg-surface-raised)] transition-colors cursor-pointer disabled:opacity-50")}>
                  <RefreshCw size={12} className={projectData.loading ? "animate-spin" : ""} /> Refresh
                </button>
              </div>
              {/* Tab bar */}
              <div className="flex gap-1 border-b border-[var(--border-subtle)] -mx-6 px-6 overflow-x-auto">
                {tabs.map((tab) => (
                  <button key={tab.id} onClick={() => { setActiveTab(tab.id); setSearchQuery(""); }}
                    className={cn("flex items-center gap-1.5 px-3 py-2.5 text-xs font-medium transition-all cursor-pointer border-b-2 -mb-px whitespace-nowrap",
                      activeTab === tab.id
                        ? "border-[var(--color-brand-secondary)] text-[var(--color-brand-secondary)]"
                        : "border-transparent text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--text-tertiary)]")}>
                    <tab.icon size={14} />
                    {tab.label}
                    <span className={cn("text-[10px] px-1.5 py-0.5 rounded-full",
                      activeTab === tab.id ? "bg-[var(--color-brand-secondary)]/10 text-[var(--color-brand-secondary)]" : "bg-[var(--bg-surface-raised)] text-[var(--text-tertiary)]")}>
                      {tab.count}
                    </span>
                  </button>
                ))}
              </div>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto px-6 py-5">
              {projectData.loading ? (
                <div className="flex flex-col items-center justify-center py-20">
                  <Loader2 size={32} className="animate-spin text-[var(--color-brand-secondary)] mb-3" />
                  <p className="text-sm text-[var(--text-secondary)]">Fetching data from {selectedProject.source === "ado" ? "Azure DevOps" : "Jira"}...</p>
                </div>
              ) : projectData.error ? (
                <div className="flex flex-col items-center justify-center py-20">
                  <AlertCircle size={32} className="text-[var(--color-rag-red)] mb-3" />
                  <p className="text-sm text-[var(--color-rag-red)] mb-3">{projectData.error}</p>
                  <button onClick={() => fetchProjectData(selectedProject)} className="text-sm text-[var(--color-brand-secondary)] hover:underline cursor-pointer">Retry</button>
                </div>
              ) : (
                <div className="space-y-5">
                  {/* ===== OVERVIEW ===== */}
                  {activeTab === "overview" && (
                    <>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                        {[
                          { label: "Total Items", val: allItems.length },
                          { label: "Features & Epics", val: categorized.features.length },
                          { label: "User Stories", val: categorized.stories.length },
                          { label: "Team Members", val: projectData.teamMembers.length },
                        ].map((s) => (
                          <div key={s.label} className="rounded-xl border border-[var(--border-subtle)] p-4 bg-[var(--bg-surface)]/50">
                            <p className="text-2xl font-bold text-[var(--text-primary)]">{s.val}</p>
                            <p className="text-xs text-[var(--text-tertiary)]">{s.label}</p>
                          </div>
                        ))}
                      </div>

                      <div className="rounded-xl border border-[var(--border-subtle)] p-5 bg-[var(--bg-surface)]/50">
                        <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3">By State</h3>
                        <div className="flex flex-wrap gap-2">
                          {Object.entries(stats.stateCount).sort(([, a], [, b]) => b - a).map(([state, count]) => (
                            <div key={state} className={cn("flex items-center gap-2 px-3 py-1.5 rounded-full border text-xs font-medium", getStatusColor(state))}>
                              {state} <span className="font-bold">{count}</span>
                            </div>
                          ))}
                        </div>
                      </div>

                      <div className="rounded-xl border border-[var(--border-subtle)] p-5 bg-[var(--bg-surface)]/50">
                        <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3">By Type</h3>
                        <div className="flex flex-wrap gap-2">
                          {Object.entries(stats.typeCount).sort(([, a], [, b]) => b - a).map(([type, count]) => (
                            <div key={type} className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/30">
                              <div className={cn("flex h-5 w-5 items-center justify-center rounded text-[9px] font-bold border", getTypeIconColor(type))}>{getTypeIcon(type)}</div>
                              <span className="text-xs text-[var(--text-primary)]">{type}</span>
                              <span className="text-xs font-bold text-[var(--text-secondary)]">{count}</span>
                            </div>
                          ))}
                        </div>
                      </div>

                      {projectData.iterations.length > 0 && (
                        <div className="rounded-xl border border-[var(--border-subtle)] p-5 bg-[var(--bg-surface)]/50">
                          <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3">Sprints / Iterations</h3>
                          <div className="space-y-2">
                            {projectData.iterations.map((iter) => {
                              const itemsInIter = allItems.filter((item) => "iterationPath" in item && (item as AdoWorkItem).iterationPath === iter.path).length;
                              return (
                                <div key={iter.id} className="flex items-center justify-between px-3 py-2 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/20">
                                  <div>
                                    <p className="text-sm font-medium text-[var(--text-primary)]">{iter.name}</p>
                                    {(iter.startDate || iter.finishDate) && (
                                      <p className="text-[10px] text-[var(--text-tertiary)]">
                                        {iter.startDate ? new Date(iter.startDate).toLocaleDateString() : "No start"} — {iter.finishDate ? new Date(iter.finishDate).toLocaleDateString() : "No end"}
                                      </p>
                                    )}
                                  </div>
                                  <span className="text-xs font-medium text-[var(--text-secondary)]">{itemsInIter} items</span>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}
                    </>
                  )}

                  {/* ===== FEATURES & EPICS ===== */}
                  {activeTab === "features" && (
                    <>
                      <SearchBar value={searchQuery} onChange={setSearchQuery} placeholder="Search features & epics..." />
                      <SectionCard title="Features & Epics" icon={Layers} count={filterItems(categorized.features).length} emptyMessage="No features or epics found in this project.">
                        {filterItems(categorized.features).map((item, i) => <WorkItemRow key={item.id} item={item} />)}
                      </SectionCard>
                    </>
                  )}

                  {/* ===== USER STORIES ===== */}
                  {activeTab === "stories" && (
                    <>
                      <SearchBar value={searchQuery} onChange={setSearchQuery} placeholder="Search user stories..." />
                      <SectionCard title="User Stories" icon={BookOpen} count={filterItems(categorized.stories).length} emptyMessage="No user stories found in this project.">
                        {filterItems(categorized.stories).map((item, i) => <WorkItemRow key={item.id} item={item} />)}
                      </SectionCard>
                    </>
                  )}

                  {/* ===== SPRINTS ===== */}
                  {activeTab === "sprints" && (
                    <>
                      {projectData.iterations.length === 0 ? (
                        <div className="py-12 text-center text-sm text-[var(--text-tertiary)]">No sprints/iterations found for this project.</div>
                      ) : (
                        <div className="space-y-4">
                          {projectData.iterations.map((iter) => {
                            const items = allItems.filter((item) => "iterationPath" in item && (item as AdoWorkItem).iterationPath === iter.path);
                            return (
                              <div key={iter.id} className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]/50 overflow-hidden">
                                <div className="flex items-center justify-between px-5 py-3 border-b border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/20">
                                  <div className="flex items-center gap-2">
                                    <IterationCw size={15} className="text-[var(--color-brand-secondary)]" />
                                    <h3 className="text-sm font-semibold text-[var(--text-primary)]">{iter.name}</h3>
                                    {(iter.startDate || iter.finishDate) && (
                                      <span className="text-[10px] text-[var(--text-tertiary)] ml-2">
                                        {iter.startDate ? new Date(iter.startDate).toLocaleDateString() : "?"} — {iter.finishDate ? new Date(iter.finishDate).toLocaleDateString() : "?"}
                                      </span>
                                    )}
                                  </div>
                                  <span className="text-xs text-[var(--text-tertiary)]">{items.length} items</span>
                                </div>
                                {items.length === 0 ? (
                                  <div className="py-6 text-center text-xs text-[var(--text-tertiary)]">No items assigned to this sprint.</div>
                                ) : (
                                  <div className="divide-y divide-[var(--border-subtle)]">{items.map((item, i) => <WorkItemRow key={item.id} item={item} />)}</div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </>
                  )}

                  {/* ===== BACKLOG ===== */}
                  {activeTab === "backlog" && (
                    <>
                      <SearchBar value={searchQuery} onChange={setSearchQuery} placeholder="Search backlog (bugs, tasks...)..." />
                      <SectionCard title="Backlog" icon={ClipboardList} count={filterItems(categorized.backlog).length} emptyMessage="No bugs, tasks, or other items in backlog.">
                        {filterItems(categorized.backlog).map((item, i) => <WorkItemRow key={item.id} item={item} />)}
                      </SectionCard>
                    </>
                  )}

                  {/* ===== TEAM ===== */}
                  {activeTab === "team" && (
                    <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]/50 overflow-hidden">
                      <div className="flex items-center gap-2 px-5 py-3 border-b border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/20">
                        <Users size={16} className="text-[var(--color-brand-secondary)]" />
                        <h3 className="text-sm font-semibold text-[var(--text-primary)]">Team Members</h3>
                        <span className="ml-auto text-xs text-[var(--text-tertiary)]">{projectData.teamMembers.length} members</span>
                      </div>
                      {projectData.teamMembers.length === 0 ? (
                        <div className="py-8 text-center text-sm text-[var(--text-tertiary)]">No team members found.</div>
                      ) : (
                        <div className="p-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                          {(projectData.teamMembers as (AdoTeamMember | JiraMember)[]).map((member, idx) => {
                            const name = "displayName" in member ? member.displayName : (member as JiraMember).displayName;
                            const email = "uniqueName" in member ? (member as AdoTeamMember).uniqueName : (member as JiraMember).emailAddress;
                            const assignedCount = allItems.filter((item) => {
                              const a = "assignedTo" in item ? (item as AdoWorkItem).assignedTo : (item as JiraIssue).assignee;
                              return a === name;
                            }).length;
                            return (
                              <div key={idx} className="flex items-center gap-3 rounded-xl border border-[var(--border-subtle)] px-4 py-3 bg-[var(--bg-surface-raised)]/20 hover:bg-[var(--bg-surface-raised)]/40 transition-colors">
                                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[var(--color-brand-secondary)]/20 text-sm font-semibold text-[var(--color-brand-secondary)]">{name?.charAt(0)?.toUpperCase() ?? "?"}</div>
                                <div className="flex-1 min-w-0">
                                  <p className="text-sm font-medium text-[var(--text-primary)] truncate">{name}</p>
                                  {email && <p className="text-[11px] text-[var(--text-tertiary)] truncate">{email}</p>}
                                </div>
                                <div className="text-center shrink-0">
                                  <p className="text-sm font-bold text-[var(--text-primary)]">{assignedCount}</p>
                                  <p className="text-[9px] text-[var(--text-tertiary)]">assigned</p>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="flex flex-col items-center justify-center h-full">
            <FolderKanban size={32} className="text-[var(--text-tertiary)] mb-3" />
            <p className="text-sm text-[var(--text-secondary)]">Select a project from the sidebar</p>
          </div>
        )}
      </div>
    </div>
  );
}
