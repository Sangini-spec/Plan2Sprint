"use client";

import { useState, useRef, useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  Menu,
  LogOut,
  User,
  Settings,
  ChevronDown,
  Plug,
  HelpCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth/context";
import { useIntegrations } from "@/lib/integrations/context";
import { ROLE_LABELS } from "@/lib/types/auth";
import { NotificationBell } from "@/components/dashboard/notification-bell";
import { ProjectSelector } from "@/components/layout/project-selector";
import { StakeholderProjectSelector } from "@/components/layout/stakeholder-project-selector";
import { NotesButton } from "@/components/notes/notes-button";


/* -------------------------------------------------------------------------- */
/*  PAGE TITLE MAPPING                                                         */
/* -------------------------------------------------------------------------- */

const PAGE_TITLES: Record<string, string> = {
  "/po": "Product Owner Dashboard",
  "/po/planning": "Sprint Planning",
  "/po/standups": "Standup Digest",
  "/po/github": "GitHub Monitoring",
  "/po/health": "Team Health",
  "/po/retro": "Retrospectives",
  "/po/projects": "Projects",
  "/po/notifications": "Channels",
  "/dev": "My Sprint Workspace",
  "/dev/sprint": "My Sprint",
  "/dev/standup": "My Standup",
  "/dev/github": "My GitHub Activity",
  "/dev/projects": "My Projects",
  "/dev/velocity": "My Velocity",
  "/dev/notifications": "Channels",
  "/stakeholder": "Project Overview",
  "/stakeholder/delivery": "Delivery Predictability",
  "/stakeholder/epics": "Epics & Milestones",
  "/stakeholder/health": "Team Health",
  "/stakeholder/export": "Export Dashboard",
  "/settings": "Settings",
  "/settings/profile": "Profile Settings",
  "/settings/connections": "Tool Connections",
  "/settings/team": "Team Management",
  "/settings/notifications": "Notification Preferences",
  "/onboarding": "Setup Wizard",
  "/dashboard": "Dashboard",
};

function getPageTitle(pathname: string): string {
  // Exact match first
  if (PAGE_TITLES[pathname]) return PAGE_TITLES[pathname];
  // Dynamic route patterns
  if (pathname.startsWith("/po/retro/")) return "Retrospective Detail";
  return "Dashboard";
}

/* -------------------------------------------------------------------------- */
/*  USER DROPDOWN                                                              */
/* -------------------------------------------------------------------------- */

function UserDropdown() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const router = useRouter();
  const { appUser, role, loading, signOut } = useAuth();
  // Hotfix 89 - same auth-flash fix as sidebar. ``role`` falls back to
  // "product_owner" while ``appUser`` is still loading, so on hard
  // refresh the topbar badge would show "Product Owner" briefly for
  // every user. Gate role-dependent text on ``authReady`` so devs /
  // stakeholders never glimpse the wrong label.
  const authReady = !loading && !!appUser;

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleSignOut = async () => {
    await signOut();
    router.push("/login");
  };

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className={cn(
          "flex items-center gap-2 rounded-xl px-2 py-1.5",
          "hover:bg-[var(--bg-surface-raised)]",
          "transition-colors duration-200 cursor-pointer"
        )}
      >
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[var(--color-brand-secondary)]/20 text-sm font-semibold text-[var(--color-brand-secondary)]">
          {appUser?.full_name?.charAt(0)?.toUpperCase() ?? "U"}
        </div>
        <div className="hidden sm:block text-left">
          <p className="text-sm font-medium text-[var(--text-primary)] leading-tight">
            {appUser?.full_name ?? "User"}
          </p>
          <p className="text-xs text-[var(--text-secondary)] leading-tight">
            {authReady ? ROLE_LABELS[role] : ""}
          </p>
        </div>
        <ChevronDown
          size={14}
          className={cn(
            "text-[var(--text-secondary)] transition-transform duration-200 hidden sm:block",
            open && "rotate-180"
          )}
        />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.95 }}
            transition={{ duration: 0.15 }}
            className="absolute right-0 top-full mt-2 w-56 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]/95 backdrop-blur-xl shadow-xl z-50"
          >
            {/* User info */}
            <div className="px-4 py-3 border-b border-[var(--border-subtle)]">
              <p className="text-sm font-medium text-[var(--text-primary)]">
                {appUser?.full_name ?? "User"}
              </p>
              <p className="text-xs text-[var(--text-secondary)] truncate">
                {appUser?.email ?? ""}
              </p>
            </div>

            {/* Menu items */}
            <div className="py-1">
              <button
                onClick={() => {
                  setOpen(false);
                  router.push("/settings/profile");
                }}
                className="flex w-full items-center gap-3 px-4 py-2.5 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-surface-raised)] transition-colors cursor-pointer"
              >
                <User size={16} />
                Profile
              </button>
              <button
                onClick={() => {
                  setOpen(false);
                  router.push("/settings");
                }}
                className="flex w-full items-center gap-3 px-4 py-2.5 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-surface-raised)] transition-colors cursor-pointer"
              >
                <Settings size={16} />
                Settings
              </button>
            </div>

            {/* Sign out */}
            <div className="border-t border-[var(--border-subtle)] py-1">
              <button
                onClick={handleSignOut}
                className="flex w-full items-center gap-3 px-4 py-2.5 text-sm text-[var(--color-rag-red)] hover:bg-[var(--color-rag-red)]/5 transition-colors cursor-pointer"
              >
                <LogOut size={16} />
                Sign Out
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  TOPBAR                                                                     */
/* -------------------------------------------------------------------------- */

interface AppTopbarProps {
  onMenuClick: () => void;
}

export function AppTopbar({ onMenuClick }: AppTopbarProps) {
  const pathname = usePathname();
  const router = useRouter();
  const pageTitle = getPageTitle(pathname);
  const { role } = useAuth();
  const { hasAnyConnection, openModal } = useIntegrations();

  // Route detection
  const isStakeholderRoute = pathname.startsWith("/stakeholder");
  const isAppRoute = pathname.startsWith("/po") || pathname.startsWith("/dev") || isStakeholderRoute || pathname === "/dashboard";
  const showConnectTools = isAppRoute && !isStakeholderRoute; // stakeholders don't connect tools

  const hasConnections = hasAnyConnection;

  return (
    <header
      className={cn(
        "flex items-center justify-between h-14 px-4 sm:px-6",
        "bg-[var(--bg-surface)]/80 backdrop-blur-xl",
        "border-b border-[var(--border-subtle)]",
        "sticky top-0 z-30"
      )}
    >
      {/* Left: hamburger + page title */}
      <div className="flex items-center gap-3">
        <button
          onClick={onMenuClick}
          className={cn(
            "flex h-9 w-9 items-center justify-center rounded-xl lg:hidden",
            "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
            "hover:bg-[var(--bg-surface-raised)]",
            "transition-colors duration-200 cursor-pointer"
          )}
          aria-label="Toggle sidebar"
        >
          <Menu size={20} />
        </button>
        <h1 className="text-base font-semibold text-[var(--text-primary)]">
          {pageTitle}
        </h1>

        {/* Project selector - stakeholder uses assignment-based selector */}
        {isStakeholderRoute && <StakeholderProjectSelector />}
        {isAppRoute && !isStakeholderRoute && <ProjectSelector />}
      </div>

      {/* Right: notes + connect tools + notifications + user */}
      <div className="flex items-center gap-2">
        {/* Smart Notes - PO + dev only, not stakeholders */}
        {isAppRoute && !isStakeholderRoute && <NotesButton />}

        {/* Connect Tools button - PO routes only, positioned near notifications */}
        {showConnectTools && (
          <button
            onClick={openModal}
            data-onboarding="connect-tools-btn"
            className={cn(
              "relative flex items-center gap-1.5 rounded-lg px-3.5 py-1.5",
              "border border-[var(--color-brand-secondary)]/40",
              "text-[13px] font-medium text-[var(--color-brand-secondary)]",
              "hover:bg-[var(--color-brand-secondary)]/10",
              "transition-all duration-200 cursor-pointer"
            )}
          >
            <Plug size={14} />
            <span className="hidden sm:inline">Connect Tools</span>
            {/* Green dot badge when connected */}
            {hasConnections && (
              <span className="absolute -top-1 -right-1 h-2.5 w-2.5 rounded-full bg-[var(--color-rag-green)] border-2 border-[var(--bg-surface)]" />
            )}
          </button>
        )}

        {/* Help / Onboarding - opens Settings → Help where the user can
            replay the tour or reset page hints. Soft nav (router.push)
            so we don't re-download the entire app on click. */}
        {isAppRoute && (
          <button
            onClick={() => router.push("/settings/help")}
            className={cn(
              "flex h-9 w-9 items-center justify-center rounded-xl",
              "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
              "hover:bg-[var(--bg-surface-raised)]",
              "transition-colors duration-200 cursor-pointer"
            )}
            aria-label="Help and onboarding"
            title="Help & Onboarding"
            data-onboarding="help-button"
          >
            <HelpCircle size={18} />
          </button>
        )}

        {/* Notifications */}
        <NotificationBell />

        {/* User dropdown */}
        <UserDropdown />
      </div>
    </header>
  );
}
