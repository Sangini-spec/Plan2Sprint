"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Github,
  GitPullRequest,
  GitCommit,
  Eye,
  Loader2,
  CheckCircle2,
  AlertCircle,
  ExternalLink,
  GitBranch,
  Activity,
  RefreshCw,
  X,
  Check,
  Search,
  ArrowUpRight,
  GitMerge,
  Plus,
  Lock,
  Globe,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { Badge } from "@/components/ui";
import type { PRStatus, CIStatus } from "@/lib/types/models";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface GitHubUser {
  login: string;
  name: string;
  avatarUrl: string;
}

interface LinkedRepo {
  id: string;
  name: string;
  fullName: string;
  isPrivate: boolean;
  language?: string;
  description?: string;
  url: string;
  defaultBranch: string;
  owner: string;
  updatedAt?: string;
}

interface RealPR {
  id: string;
  number: number;
  title: string;
  status: string;
  state: string;
  author: string;
  authorAvatar: string;
  repo: string;
  url: string;
  createdAt: string;
  updatedAt: string;
  mergedAt?: string;
  draft: boolean;
  reviewers: string[];
  branch: string;
  baseBranch: string;
}

interface RealCommit {
  sha: string;
  message: string;
  author: string;
  authorLogin: string;
  authorAvatar: string;
  date: string;
  repo: string;
  url: string;
}

interface RepoEvent {
  id: string;
  type: string;
  rawType: string;
  repo: string;
  actor: string;
  actorAvatar: string;
  description: string;
  branch: string;
  commits: Array<{ sha: string; message: string; author: string }>;
  commitCount: number;
  createdAt: string;
  url: string;
}

// ---------------------------------------------------------------------------
// LocalStorage
// ---------------------------------------------------------------------------

const STORAGE_KEY = "plan2sprint_github";

function loadGitHubState(): { token?: string; user?: GitHubUser; linkedRepos?: LinkedRepo[] } {
  if (typeof window === "undefined") return {};
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function saveGitHubState(state: { token?: string; user?: GitHubUser; linkedRepos?: LinkedRepo[] }) {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const prStatusVariant: Record<string, "brand" | "rag-green" | "rag-amber" | "rag-red"> = {
  OPEN: "brand",
  AWAITING_REVIEW: "rag-amber",
  CHANGES_REQUESTED: "rag-red",
  APPROVED: "rag-green",
  MERGED: "rag-green",
  CLOSED: "rag-red",
};

const ciStatusVariant: Record<CIStatus, "rag-green" | "rag-red" | "rag-amber" | "brand"> = {
  PASSING: "rag-green",
  FAILING: "rag-red",
  PENDING: "rag-amber",
  UNKNOWN: "brand",
};

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function formatDateTime(iso: string) {
  return new Date(iso).toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
}

function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(ms / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function getEventIcon(type: string) {
  switch (type) {
    case "push": return <GitCommit size={14} className="text-[var(--color-rag-green)]" />;
    case "pull_request": return <GitPullRequest size={14} className="text-[var(--color-brand-secondary)]" />;
    case "create": return <GitBranch size={14} className="text-[#773B93]" />;
    case "review": return <Eye size={14} className="text-[var(--color-rag-amber)]" />;
    case "issue": return <AlertCircle size={14} className="text-[var(--color-rag-red)]" />;
    case "comment": return <Activity size={14} className="text-[var(--text-secondary)]" />;
    default: return <Activity size={14} className="text-[var(--text-tertiary)]" />;
  }
}

// (No mock tabs — real data only when connected)

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export function MyGithubActivity() {
  // Auth state
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<GitHubUser | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);

  // Repo linking
  const [availableRepos, setAvailableRepos] = useState<LinkedRepo[]>([]);
  const [linkedRepos, setLinkedRepos] = useState<LinkedRepo[]>([]);
  const [showRepoSelector, setShowRepoSelector] = useState(false);
  const [repoSearch, setRepoSearch] = useState("");
  const [loadingRepos, setLoadingRepos] = useState(false);

  // Create repo modal
  const [showCreateRepo, setShowCreateRepo] = useState(false);
  const [createRepoName, setCreateRepoName] = useState("");
  const [createRepoDesc, setCreateRepoDesc] = useState("");
  const [createRepoPrivate, setCreateRepoPrivate] = useState(true);
  const [createRepoAutoInit, setCreateRepoAutoInit] = useState(true);
  const [creatingRepo, setCreatingRepo] = useState(false);
  const [createRepoError, setCreateRepoError] = useState<string | null>(null);
  const [createRepoSuccess, setCreateRepoSuccess] = useState<string | null>(null);

  // Real data
  const [pulls, setPulls] = useState<RealPR[]>([]);
  const [commits, setCommits] = useState<RealCommit[]>([]);
  const [events, setEvents] = useState<RepoEvent[]>([]);
  const [dataLoading, setDataLoading] = useState(false);

  // Tabs
  const [realTab, setRealTab] = useState("my-prs");

  const isConnected = Boolean(token);

  // ---------- Load from localStorage, fallback to backend ----------
  useEffect(() => {
    const saved = loadGitHubState();
    if (saved.token && saved.user) {
      // Restore from localStorage
      setToken(saved.token);
      setUser(saved.user);
      if (saved.linkedRepos?.length) setLinkedRepos(saved.linkedRepos);

      // Bootstrap: persist to backend (one-time per session)
      const key = "plan2sprint_github_synced";
      if (!sessionStorage.getItem(key)) {
        sessionStorage.setItem(key, "1");
        fetch("/api/integrations/github/save-token", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            accessToken: saved.token,
            userLogin: saved.user.login,
            userName: saved.user.name,
            avatarUrl: saved.user.avatarUrl,
            linkedRepos: (saved.linkedRepos ?? []).map((r) => r.fullName),
          }),
        }).catch(() => {});
      }
    } else {
      // No localStorage data — try restoring from backend
      fetch("/api/integrations/github/status")
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => {
          if (data?.connected && data.access_token) {
            const restoredUser: GitHubUser = {
              login: data.user_login || "",
              name: data.user_name || "",
              avatarUrl: data.avatar_url || "",
            };
            setToken(data.access_token);
            setUser(restoredUser);
            // Restore linked repos from backend
            if (data.linked_repos?.length) {
              const repos: LinkedRepo[] = data.linked_repos.map((fullName: string) => ({
                fullName,
                name: fullName.split("/").pop() || fullName,
              }));
              setLinkedRepos(repos);
            }
            // Save to localStorage for future loads
            saveGitHubState({
              token: data.access_token,
              user: restoredUser,
              linkedRepos: data.linked_repos?.length
                ? data.linked_repos.map((fullName: string) => ({
                    fullName,
                    name: fullName.split("/").pop() || fullName,
                  }))
                : [],
            });
          }
        })
        .catch(() => {});
    }
  }, []);

  // ---------- Handle OAuth code from URL ----------
  // GitHub redirects back with ?code=... to whatever callback URL is configured.
  // We handle it here — wherever the page loads with a `code` param.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const error = params.get("error");

    if (error) {
      setAuthError(params.get("error_description") ?? error);
      window.history.replaceState({}, "", window.location.pathname);
      return;
    }

    // Also handle token passed directly (from callback route)
    const ghToken = params.get("github_token");
    if (ghToken) {
      const userObj: GitHubUser = {
        login: params.get("github_user") ?? "",
        name: params.get("github_name") ?? "",
        avatarUrl: params.get("github_avatar") ?? "",
      };
      setToken(ghToken);
      setUser(userObj);
      saveGitHubState({ token: ghToken, user: userObj, linkedRepos: [] });
      // Persist token to backend so PO can see activity (org-level)
      fetch("/api/integrations/github/save-token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          accessToken: ghToken,
          userLogin: userObj.login,
          userName: userObj.name,
          avatarUrl: userObj.avatarUrl,
          linkedRepos: [],
        }),
      }).catch(() => {});
      // Also link to this developer's personal record
      fetch("/api/integrations/github/link-developer-github", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          accessToken: ghToken,
          userLogin: userObj.login,
          userName: userObj.name,
        }),
      }).catch(() => {});
      window.history.replaceState({}, "", window.location.pathname);
      setShowRepoSelector(true);
      return;
    }

    if (!code) return;

    // Exchange the code for a token via our API
    setConnecting(true);
    setAuthError(null);
    window.history.replaceState({}, "", window.location.pathname);

    (async () => {
      try {
        const res = await fetch("/api/integrations/github/auth", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code }),
        });
        const data = await res.json();

        if (!res.ok || data.error) {
          setAuthError(data.error ?? "Failed to exchange code");
          setConnecting(false);
          return;
        }

        const userObj: GitHubUser = {
          login: data.user?.login ?? "",
          name: data.user?.name ?? data.user?.login ?? "",
          avatarUrl: data.user?.avatarUrl ?? "",
        };
        setToken(data.accessToken);
        setUser(userObj);
        saveGitHubState({ token: data.accessToken, user: userObj, linkedRepos: [] });
        // Persist token to backend so PO can see activity (org-level)
        fetch("/api/integrations/github/save-token", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            accessToken: data.accessToken,
            userLogin: userObj.login,
            userName: userObj.name,
            avatarUrl: userObj.avatarUrl,
            linkedRepos: [],
          }),
        }).catch(() => {});
        // Also link to this developer's personal record
        fetch("/api/integrations/github/link-developer-github", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            accessToken: data.accessToken,
            userLogin: userObj.login,
            userName: userObj.name,
          }),
        }).catch(() => {});
        setShowRepoSelector(true);
      } catch {
        setAuthError("OAuth exchange failed");
      }
      setConnecting(false);
    })();
  }, []);

  // ---------- Fetch available repos ----------
  const fetchAvailableRepos = useCallback(async () => {
    if (!token) return;
    setLoadingRepos(true);
    try {
      const res = await fetch("/api/integrations/github/repos", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ accessToken: token }),
      });
      const data = await res.json();
      setAvailableRepos(data.repos ?? []);
    } catch {
      setAvailableRepos([]);
    }
    setLoadingRepos(false);
  }, [token]);

  useEffect(() => {
    if (token && showRepoSelector) fetchAvailableRepos();
  }, [token, showRepoSelector, fetchAvailableRepos]);

  // ---------- Fetch real data ----------
  const fetchData = useCallback(async () => {
    if (!token || linkedRepos.length === 0) return;
    setDataLoading(true);
    const repoNames = linkedRepos.map((r) => r.fullName);
    try {
      const [prRes, commitRes, eventRes] = await Promise.all([
        fetch("/api/integrations/github/pulls", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ accessToken: token, repos: repoNames }),
        }),
        fetch("/api/integrations/github/commits", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ accessToken: token, repos: repoNames }),
        }),
        fetch("/api/integrations/github/events", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ accessToken: token, repos: repoNames }),
        }),
      ]);
      const [prData, commitData, eventData] = await Promise.all([prRes.json(), commitRes.json(), eventRes.json()]);
      setPulls(prData.pulls ?? []);
      setCommits(commitData.commits ?? []);
      setEvents(eventData.events ?? []);
    } catch { /* keep existing */ }
    setDataLoading(false);
  }, [token, linkedRepos]);

  useEffect(() => {
    if (token && linkedRepos.length > 0) fetchData();
  }, [token, linkedRepos, fetchData]);

  // ---------- Connect ----------
  const handleConnect = async () => {
    setConnecting(true);
    setAuthError(null);
    try {
      const res = await fetch("/api/integrations/github/auth");
      const data = await res.json();
      if (data.authorizeUrl) {
        window.location.href = data.authorizeUrl;
      } else {
        setAuthError(data.error ?? "Failed to get authorization URL");
        setConnecting(false);
      }
    } catch {
      setAuthError("Failed to initiate GitHub connection");
      setConnecting(false);
    }
  };

  // ---------- Disconnect ----------
  const handleDisconnect = () => {
    setToken(null);
    setUser(null);
    setLinkedRepos([]);
    setAvailableRepos([]);
    setPulls([]);
    setCommits([]);
    setEvents([]);
    localStorage.removeItem(STORAGE_KEY);
  };

  // Sync linked repos to backend so PO monitoring can use them
  const syncLinkedReposToBackend = (repos: LinkedRepo[]) => {
    fetch("/api/integrations/github/update-linked-repos", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        linkedRepos: repos.map((r) => r.fullName),
      }),
    }).catch(() => {});
  };

  // ---------- Repo toggle ----------
  const toggleRepo = (repo: LinkedRepo) => {
    setLinkedRepos((prev) => {
      const exists = prev.find((r) => r.id === repo.id);
      const next = exists ? prev.filter((r) => r.id !== repo.id) : [...prev, repo];
      saveGitHubState({ token: token!, user: user!, linkedRepos: next });
      syncLinkedReposToBackend(next);
      return next;
    });
  };

  const removeLinkedRepo = (repoId: string) => {
    setLinkedRepos((prev) => {
      const next = prev.filter((r) => r.id !== repoId);
      saveGitHubState({ token: token!, user: user!, linkedRepos: next });
      syncLinkedReposToBackend(next);
      return next;
    });
  };

  // ---------- Create new repo ----------
  const handleCreateRepo = async () => {
    if (!token || !createRepoName.trim()) return;
    setCreatingRepo(true);
    setCreateRepoError(null);
    setCreateRepoSuccess(null);
    try {
      const res = await fetch("/api/integrations/github/repos/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          accessToken: token,
          name: createRepoName.trim(),
          description: createRepoDesc.trim(),
          isPrivate: createRepoPrivate,
          autoInit: createRepoAutoInit,
        }),
      });
      const data = await res.json();
      if (!res.ok || !data.success) {
        setCreateRepoError(data.detail ?? data.error ?? "Failed to create repository");
        setCreatingRepo(false);
        return;
      }
      const newRepo: LinkedRepo = data.repo;
      setLinkedRepos((prev) => {
        const next = [...prev, newRepo];
        saveGitHubState({ token: token!, user: user!, linkedRepos: next });
        syncLinkedReposToBackend(next);
        return next;
      });
      setAvailableRepos((prev) => [newRepo, ...prev]);
      setCreateRepoSuccess(`Repository "${newRepo.fullName}" created and linked!`);
      setTimeout(() => {
        setShowCreateRepo(false);
        setCreateRepoName("");
        setCreateRepoDesc("");
        setCreateRepoPrivate(true);
        setCreateRepoAutoInit(true);
        setCreateRepoSuccess(null);
      }, 1500);
    } catch {
      setCreateRepoError("Failed to create repository");
    }
    setCreatingRepo(false);
  };

  // Filtered repos for selector
  const filteredAvailableRepos = availableRepos.filter((r) =>
    repoSearch ? r.fullName.toLowerCase().includes(repoSearch.toLowerCase()) : true
  );

  // Separate real PRs
  const myPRs = pulls.filter((pr) => pr.author === user?.login);
  const toReview = pulls.filter(
    (pr) => pr.author !== user?.login && pr.state === "open"
  );

  const hasRealData = isConnected && linkedRepos.length > 0;

  // Real-data tabs
  const realTabs = [
    { id: "my-prs", label: "My PRs", icon: GitPullRequest, count: myPRs.length },
    { id: "to-review", label: "To Review", icon: Eye, count: toReview.length },
    { id: "commits", label: "Commits", icon: GitCommit, count: commits.length },
    { id: "activity", label: "Code Activity", icon: Activity, count: events.length },
  ];

  // ===========================================================================
  // RENDER
  // ===========================================================================

  return (
    <DashboardPanel title="GitHub Activity" icon={Github}>
      <div className="space-y-4">

        {/* ====== CONNECT GITHUB BUTTON / CONNECTED STATUS ====== */}
        {!isConnected ? (
          <div className="flex items-center justify-between rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/30 px-5 py-4">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#24292f]/10">
                <Github size={20} className="text-[#24292f] dark:text-white" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">Connect your GitHub account</h3>
                <p className="text-xs text-[var(--text-secondary)]">
                  Link repositories to track real PRs, commits, and code activity.
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              {authError && (
                <span className="text-xs text-[var(--color-rag-red)] max-w-[200px] truncate">{authError}</span>
              )}
              <button onClick={handleConnect} disabled={connecting}
                className={cn(
                  "flex items-center gap-2 rounded-lg px-5 py-2.5 text-sm font-medium text-white transition-all cursor-pointer",
                  "bg-[#24292f] hover:bg-[#24292f]/90 disabled:opacity-50"
                )}>
                {connecting ? <Loader2 size={16} className="animate-spin" /> : <Github size={16} />}
                {connecting ? "Connecting..." : "Connect GitHub"}
              </button>
            </div>
          </div>
        ) : (
          <>
            {/* Connected header */}
            <div className="flex items-center justify-between rounded-xl border border-[var(--color-rag-green)]/20 bg-[var(--color-rag-green)]/5 px-4 py-2.5">
              <div className="flex items-center gap-3">
                <CheckCircle2 size={16} className="text-[var(--color-rag-green)]" />
                {user?.avatarUrl && (
                  <img src={user.avatarUrl} alt={user.login} className="h-6 w-6 rounded-full" />
                )}
                <span className="text-sm font-medium text-[var(--text-primary)]">{user?.name ?? user?.login}</span>
                <span className="text-xs text-[var(--text-tertiary)]">@{user?.login}</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => { setShowCreateRepo(true); setCreateRepoError(null); setCreateRepoSuccess(null); }}
                  className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium border border-[var(--color-brand-secondary)]/30 text-[var(--color-brand-secondary)] hover:bg-[var(--color-brand-secondary)]/10 transition-colors cursor-pointer"
                >
                  <Plus size={12} /> New Repo
                </button>
                <button onClick={() => { setShowRepoSelector(true); fetchAvailableRepos(); }}
                  className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:bg-[var(--bg-surface-raised)] transition-colors cursor-pointer">
                  <GitBranch size={12} /> Manage Repos
                </button>
                {hasRealData && (
                  <button onClick={fetchData} disabled={dataLoading}
                    className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:bg-[var(--bg-surface-raised)] transition-colors cursor-pointer disabled:opacity-50">
                    <RefreshCw size={12} className={dataLoading ? "animate-spin" : ""} /> Refresh
                  </button>
                )}
                <button onClick={handleDisconnect}
                  className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium border border-[var(--color-rag-red)]/20 text-[var(--color-rag-red)] hover:bg-[var(--color-rag-red)]/5 transition-colors cursor-pointer">
                  Disconnect
                </button>
              </div>
            </div>

            {/* Linked repos chips */}
            {linkedRepos.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {linkedRepos.map((repo) => (
                  <div key={repo.id} className="flex items-center gap-1.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/30 px-2.5 py-1.5">
                    <GitBranch size={12} className="text-[var(--text-tertiary)]" />
                    <span className="text-xs font-medium text-[var(--text-primary)]">{repo.fullName}</span>
                    {repo.language && <span className="text-[10px] text-[var(--text-tertiary)]">· {repo.language}</span>}
                    <button onClick={() => removeLinkedRepo(repo.id)} className="ml-1 text-[var(--text-tertiary)] hover:text-[var(--color-rag-red)] cursor-pointer">
                      <X size={12} />
                    </button>
                  </div>
                ))}
              </div>
            )}

            {linkedRepos.length === 0 && !showRepoSelector && (
              <div className="text-center py-4">
                <p className="text-sm text-[var(--text-secondary)] mb-2">No repositories linked yet.</p>
                <button onClick={() => { setShowRepoSelector(true); fetchAvailableRepos(); }}
                  className="text-sm font-medium text-[var(--color-brand-secondary)] hover:underline cursor-pointer">
                  + Link Repositories
                </button>
              </div>
            )}

            {/* Repo selector */}
            {showRepoSelector && (
              <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] overflow-hidden">
                <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/20">
                  <h4 className="text-sm font-semibold text-[var(--text-primary)]">Select Repositories to Track</h4>
                  <button onClick={() => setShowRepoSelector(false)} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] cursor-pointer">
                    <X size={16} />
                  </button>
                </div>
                <div className="px-4 py-3 border-b border-[var(--border-subtle)]">
                  <div className="relative">
                    <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)]" />
                    <input type="text" placeholder="Search repositories..." value={repoSearch} onChange={(e) => setRepoSearch(e.target.value)}
                      className="w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] pl-9 pr-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)]/40" />
                  </div>
                </div>
                <div className="max-h-64 overflow-y-auto divide-y divide-[var(--border-subtle)]">
                  {loadingRepos ? (
                    <div className="flex items-center justify-center py-8">
                      <Loader2 size={20} className="animate-spin text-[var(--color-brand-secondary)]" />
                    </div>
                  ) : filteredAvailableRepos.length === 0 ? (
                    <div className="py-6 text-center text-sm text-[var(--text-tertiary)]">No repositories found.</div>
                  ) : (
                    filteredAvailableRepos.map((repo) => {
                      const isLinked = linkedRepos.some((r) => r.id === repo.id);
                      return (
                        <button key={repo.id} onClick={() => toggleRepo(repo)}
                          className={cn("w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors cursor-pointer",
                            isLinked ? "bg-[var(--color-brand-secondary)]/5" : "hover:bg-[var(--bg-surface-raised)]/30")}>
                          <div className={cn("flex h-5 w-5 items-center justify-center rounded border transition-colors",
                            isLinked ? "bg-[var(--color-brand-secondary)] border-[var(--color-brand-secondary)]" : "border-[var(--border-subtle)]")}>
                            {isLinked && <Check size={12} className="text-white" />}
                          </div>
                          <GitBranch size={14} className="text-[var(--text-tertiary)] shrink-0" />
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-[var(--text-primary)] truncate">{repo.fullName}</p>
                            {repo.description && <p className="text-[11px] text-[var(--text-tertiary)] truncate">{repo.description}</p>}
                          </div>
                          {repo.isPrivate && (
                            <span className="text-[9px] font-medium px-1.5 py-0.5 rounded bg-[var(--bg-surface-raised)] text-[var(--text-tertiary)] border border-[var(--border-subtle)]">Private</span>
                          )}
                          {repo.language && <span className="text-[10px] text-[var(--text-tertiary)]">{repo.language}</span>}
                        </button>
                      );
                    })
                  )}
                </div>
                <div className="flex items-center justify-between px-4 py-3 border-t border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/10">
                  <span className="text-xs text-[var(--text-tertiary)]">{linkedRepos.length} selected</span>
                  <button onClick={() => setShowRepoSelector(false)}
                    className="flex items-center gap-1.5 rounded-lg px-4 py-2 text-xs font-medium text-white bg-[var(--color-brand-secondary)] hover:bg-[var(--color-brand-secondary)]/90 transition-all cursor-pointer">
                    Done
                  </button>
                </div>
              </div>
            )}

            {/* Create Repo Modal */}
            <AnimatePresence>
              {showCreateRepo && (
                <>
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.2 }}
                    className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
                    onClick={() => setShowCreateRepo(false)}
                  />
                  <motion.div
                    initial={{ opacity: 0, scale: 0.95, y: 20 }}
                    animate={{ opacity: 1, scale: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.95, y: 20 }}
                    transition={{ duration: 0.2, ease: "easeOut" }}
                    className={cn(
                      "fixed left-1/2 top-1/2 z-50 -translate-x-1/2 -translate-y-1/2",
                      "w-[90vw] max-w-md",
                      "rounded-2xl border border-[var(--border-subtle)]",
                      "bg-[var(--bg-surface)]/95 backdrop-blur-xl",
                      "shadow-2xl"
                    )}
                  >
                    {/* Header */}
                    <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border-subtle)]">
                      <div>
                        <h2 className="text-base font-semibold text-[var(--text-primary)]">Create Repository</h2>
                        <p className="text-xs text-[var(--text-secondary)] mt-0.5">Create a new GitHub repository and link it to this project</p>
                      </div>
                      <button onClick={() => setShowCreateRepo(false)} className="flex h-8 w-8 items-center justify-center rounded-lg text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-surface-raised)] transition-colors cursor-pointer">
                        <X size={18} />
                      </button>
                    </div>

                    {/* Form */}
                    <div className="px-6 py-5 space-y-4">
                      <div className="space-y-1.5">
                        <label className="text-sm font-medium text-[var(--text-primary)]">Repository Name <span className="text-[var(--color-rag-red)]">*</span></label>
                        <input
                          type="text"
                          value={createRepoName}
                          onChange={(e) => setCreateRepoName(e.target.value)}
                          placeholder="my-awesome-project"
                          className="w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-secondary)]/50 focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)]/40"
                        />
                      </div>

                      <div className="space-y-1.5">
                        <label className="text-sm font-medium text-[var(--text-primary)]">Description</label>
                        <input
                          type="text"
                          value={createRepoDesc}
                          onChange={(e) => setCreateRepoDesc(e.target.value)}
                          placeholder="A brief description of the repository"
                          className="w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-secondary)]/50 focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)]/40"
                        />
                      </div>

                      {/* Visibility toggle */}
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          {createRepoPrivate ? <Lock size={14} className="text-[var(--text-secondary)]" /> : <Globe size={14} className="text-[var(--text-secondary)]" />}
                          <span className="text-sm font-medium text-[var(--text-primary)]">{createRepoPrivate ? "Private" : "Public"}</span>
                          <span className="text-xs text-[var(--text-secondary)]">
                            {createRepoPrivate ? "Only you and collaborators" : "Anyone on the internet"}
                          </span>
                        </div>
                        <button
                          onClick={() => setCreateRepoPrivate(!createRepoPrivate)}
                          className={cn(
                            "relative h-6 w-11 rounded-full transition-colors cursor-pointer",
                            createRepoPrivate ? "bg-[var(--color-brand-secondary)]" : "bg-[var(--border-subtle)]"
                          )}
                        >
                          <span className={cn(
                            "absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform",
                            createRepoPrivate ? "translate-x-5" : "translate-x-0"
                          )} />
                        </button>
                      </div>

                      {/* Auto-init checkbox */}
                      <label className="flex items-center gap-2 cursor-pointer">
                        <button
                          onClick={() => setCreateRepoAutoInit(!createRepoAutoInit)}
                          className={cn(
                            "flex h-5 w-5 items-center justify-center rounded border transition-colors",
                            createRepoAutoInit ? "bg-[var(--color-brand-secondary)] border-[var(--color-brand-secondary)]" : "border-[var(--border-subtle)]"
                          )}
                        >
                          {createRepoAutoInit && <Check size={12} className="text-white" />}
                        </button>
                        <span className="text-sm text-[var(--text-primary)]">Initialize with a README</span>
                      </label>

                      {createRepoError && (
                        <div className="flex items-center gap-2 rounded-lg bg-[var(--color-rag-red)]/10 border border-[var(--color-rag-red)]/20 px-3 py-2">
                          <AlertCircle size={14} className="text-[var(--color-rag-red)] shrink-0" />
                          <span className="text-xs text-[var(--color-rag-red)]">{createRepoError}</span>
                        </div>
                      )}
                      {createRepoSuccess && (
                        <div className="flex items-center gap-2 rounded-lg bg-[var(--color-rag-green)]/10 border border-[var(--color-rag-green)]/20 px-3 py-2">
                          <CheckCircle2 size={14} className="text-[var(--color-rag-green)] shrink-0" />
                          <span className="text-xs text-[var(--color-rag-green)]">{createRepoSuccess}</span>
                        </div>
                      )}
                    </div>

                    {/* Footer */}
                    <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-[var(--border-subtle)] bg-[var(--bg-surface-raised)]/30 rounded-b-2xl">
                      <button onClick={() => setShowCreateRepo(false)} className="rounded-lg px-4 py-2 text-sm font-medium border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-surface-raised)] transition-colors cursor-pointer">
                        Cancel
                      </button>
                      <button
                        onClick={handleCreateRepo}
                        disabled={!createRepoName.trim() || creatingRepo}
                        className={cn(
                          "flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium text-white",
                          "bg-[var(--color-brand-secondary)] hover:bg-[var(--color-brand-secondary)]/90",
                          "transition-all cursor-pointer",
                          "disabled:opacity-50 disabled:cursor-not-allowed"
                        )}
                      >
                        {creatingRepo ? <><Loader2 size={14} className="animate-spin" /> Creating...</> : <><Plus size={14} /> Create Repository</>}
                      </button>
                    </div>
                  </motion.div>
                </>
              )}
            </AnimatePresence>
          </>
        )}

        {/* ====== SECTIONS BELOW CONNECT BUTTON ====== */}
        {/* If connected + has linked repos → show REAL data tabs */}
        {/* Otherwise → show MOCK data tabs */}

        {hasRealData && !showRepoSelector ? (
          <>
            {/* Real data tab bar */}
            <div className="flex gap-1 border-b border-[var(--border-subtle)] overflow-x-auto">
              {realTabs.map((tab) => (
                <button key={tab.id} onClick={() => setRealTab(tab.id)}
                  className={cn("flex items-center gap-1.5 px-3 py-2.5 text-xs font-medium transition-all cursor-pointer border-b-2 -mb-px whitespace-nowrap",
                    realTab === tab.id
                      ? "border-[var(--color-brand-secondary)] text-[var(--color-brand-secondary)]"
                      : "border-transparent text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--text-tertiary)]")}>
                  <tab.icon size={14} />
                  {tab.label}
                  <span className={cn("text-[10px] px-1.5 py-0.5 rounded-full",
                    realTab === tab.id ? "bg-[var(--color-brand-secondary)]/10 text-[var(--color-brand-secondary)]" : "bg-[var(--bg-surface-raised)] text-[var(--text-tertiary)]")}>
                    {tab.count}
                  </span>
                </button>
              ))}
            </div>

            {dataLoading ? (
              <div className="flex flex-col items-center py-10">
                <Loader2 size={24} className="animate-spin text-[var(--color-brand-secondary)] mb-2" />
                <p className="text-sm text-[var(--text-secondary)]">Fetching data from GitHub...</p>
              </div>
            ) : (
              <>
                {/* My PRs (real) */}
                {realTab === "my-prs" && (
                  <div className="space-y-2">
                    {myPRs.length === 0 ? (
                      <p className="text-sm text-[var(--text-secondary)] py-6 text-center">No pull requests found.</p>
                    ) : myPRs.map((pr) => (
                      <a key={pr.id} href={pr.url} target="_blank" rel="noopener noreferrer"
                        className="flex flex-wrap items-center gap-2 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] p-3 hover:border-[var(--color-brand-secondary)]/30 transition-colors group">
                        {pr.status === "MERGED" ? <GitMerge className="h-4 w-4 shrink-0 text-[var(--color-rag-green)]" /> : <GitPullRequest className="h-4 w-4 shrink-0 text-[var(--color-brand-secondary)]" />}
                        <span className="text-sm font-medium text-[var(--text-primary)] flex-1 min-w-0 group-hover:text-[var(--color-brand-secondary)] transition-colors">{pr.title}</span>
                        <Badge variant="brand" className="text-[10px] px-2 py-0.5">#{pr.number}</Badge>
                        <Badge variant={prStatusVariant[pr.status] ?? "brand"} className="text-[10px] px-2 py-0.5">{pr.status.replace(/_/g, " ")}</Badge>
                        <span className="text-[10px] text-[var(--text-tertiary)] max-w-[140px] truncate">{pr.repo.split("/")[1]}</span>
                        <span className="text-xs text-[var(--text-secondary)] shrink-0">{formatDate(pr.createdAt)}</span>
                        <ArrowUpRight size={12} className="text-[var(--text-tertiary)] opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
                      </a>
                    ))}
                  </div>
                )}

                {/* To Review (real) */}
                {realTab === "to-review" && (
                  <div className="space-y-2">
                    {toReview.length === 0 ? (
                      <p className="text-sm text-[var(--text-secondary)] py-6 text-center">No reviews pending</p>
                    ) : toReview.map((pr) => (
                      <a key={pr.id} href={pr.url} target="_blank" rel="noopener noreferrer"
                        className="flex flex-wrap items-center gap-2 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] p-3 hover:border-[var(--color-rag-amber)]/30 transition-colors group">
                        <Eye className="h-4 w-4 shrink-0 text-[var(--color-rag-amber)]" />
                        <span className="text-sm font-medium text-[var(--text-primary)] flex-1 min-w-0">{pr.title}</span>
                        <Badge variant="brand" className="text-[10px] px-2 py-0.5">#{pr.number}</Badge>
                        <Badge variant={prStatusVariant[pr.status] ?? "rag-amber"} className="text-[10px] px-2 py-0.5">{pr.status.replace(/_/g, " ")}</Badge>
                        <span className="text-[10px] text-[var(--text-tertiary)] max-w-[140px] truncate">{pr.repo.split("/")[1]}</span>
                        <span className="text-xs text-[var(--text-secondary)] shrink-0">{formatDate(pr.createdAt)}</span>
                      </a>
                    ))}
                  </div>
                )}

                {/* Commits (real) */}
                {realTab === "commits" && (
                  <div className="space-y-2">
                    {commits.length === 0 ? (
                      <p className="text-sm text-[var(--text-secondary)] py-6 text-center">No recent commits.</p>
                    ) : commits.slice(0, 50).map((c) => (
                      <a key={c.sha} href={c.url} target="_blank" rel="noopener noreferrer"
                        className="flex flex-wrap items-center gap-2 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] p-3 hover:border-[var(--color-brand-secondary)]/30 transition-colors group">
                        <GitCommit className="h-4 w-4 shrink-0 text-[var(--text-secondary)]" />
                        <code className="rounded-md bg-[var(--color-brand-secondary)]/10 px-1.5 py-0.5 text-[11px] font-mono text-[var(--color-brand-secondary)]">{c.sha.slice(0, 7)}</code>
                        <span className="text-sm text-[var(--text-primary)] flex-1 min-w-0 truncate">{c.message.split("\n")[0]}</span>
                        <span className="text-[10px] text-[var(--text-tertiary)] max-w-[140px] truncate">{c.repo.split("/")[1]}</span>
                        <span className="text-xs text-[var(--text-secondary)] shrink-0">{formatDateTime(c.date)}</span>
                      </a>
                    ))}
                  </div>
                )}

                {/* Code Activity (real) */}
                {realTab === "activity" && (
                  <div className="space-y-2">
                    {events.length === 0 ? (
                      <p className="text-sm text-[var(--text-secondary)] py-6 text-center">No recent activity.</p>
                    ) : events.slice(0, 60).map((event) => (
                      <div key={event.id} className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] p-3 hover:bg-[var(--bg-surface-raised)]/80 transition-colors">
                        <div className="flex items-start gap-2.5">
                          <div className="mt-0.5 shrink-0">{getEventIcon(event.type)}</div>
                          <div className="flex-1 min-w-0">
                            <span className="text-sm font-medium text-[var(--text-primary)]">{event.description}</span>
                            <div className="flex items-center gap-2 mt-1 flex-wrap">
                              <span className="text-[10px] text-[var(--text-tertiary)]">{event.repo.split("/")[1]}</span>
                              {event.branch && (
                                <>
                                  <span className="text-[10px] text-[var(--text-tertiary)]">·</span>
                                  <span className="text-[10px] font-mono text-[var(--color-brand-secondary)]">{event.branch}</span>
                                </>
                              )}
                              <span className="text-[10px] text-[var(--text-tertiary)]">· {timeAgo(event.createdAt)}</span>
                              <span className="text-[10px] text-[var(--text-tertiary)]">· {event.actor}</span>
                            </div>
                            {event.type === "push" && event.commits.length > 0 && (
                              <div className="mt-2 space-y-1 pl-1 border-l-2 border-[var(--border-subtle)]">
                                {event.commits.slice(0, 5).map((c, idx) => (
                                  <div key={idx} className="flex items-center gap-2 pl-2">
                                    <code className="text-[10px] font-mono text-[var(--color-brand-secondary)]">{c.sha}</code>
                                    <span className="text-[11px] text-[var(--text-secondary)] truncate">{c.message?.split("\n")[0]}</span>
                                  </div>
                                ))}
                                {event.commits.length > 5 && (
                                  <p className="text-[10px] text-[var(--text-tertiary)] pl-2">+ {event.commits.length - 5} more</p>
                                )}
                              </div>
                            )}
                          </div>
                          {event.url && (
                            <a href={event.url} target="_blank" rel="noopener noreferrer" className="shrink-0 text-[var(--text-tertiary)] hover:text-[var(--color-brand-secondary)] cursor-pointer">
                              <ExternalLink size={12} />
                            </a>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </>
        ) : !isConnected ? null : (
          <div className="flex flex-col items-center py-6">
            <p className="text-sm text-[var(--text-secondary)]">Link repositories above to see your GitHub activity.</p>
          </div>
        )}
      </div>
    </DashboardPanel>
  );
}
