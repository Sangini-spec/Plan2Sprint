"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { Logo } from "@/components/ui/logo";
import { usePathname } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { useTheme } from "next-themes";
import {
  LayoutDashboard,
  Zap,
  MessageSquareText,
  Github,
  HeartPulse,
  RotateCcw,
  ChevronLeft,
  Sun,
  Moon,
  Briefcase,
  BarChart3,
  Milestone,
  FileDown,
  KanbanSquare,
  GitPullRequest,
  TrendingUp,
  Inbox,
  FolderKanban,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth/context";
import { ROLE_LABELS, type UserRole } from "@/lib/types/auth";

/* -------------------------------------------------------------------------- */
/*  NAV ITEMS PER ROLE                                                         */
/* -------------------------------------------------------------------------- */

interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
}

const PO_NAV: NavItem[] = [
  { label: "Dashboard", href: "/po", icon: LayoutDashboard },
  { label: "Projects", href: "/po/projects", icon: FolderKanban },
  { label: "Sprint Planning", href: "/po/planning", icon: Zap },
  { label: "Standups", href: "/po/standups", icon: MessageSquareText },
  { label: "GitHub", href: "/po/github", icon: Github },
  { label: "Team Health", href: "/po/health", icon: HeartPulse },
  { label: "Retrospectives", href: "/po/retro", icon: RotateCcw },
  { label: "Channels", href: "/po/notifications", icon: Inbox },
];

const DEV_NAV: NavItem[] = [
  { label: "My Dashboard", href: "/dev", icon: LayoutDashboard },
  { label: "My Standup", href: "/dev/standup", icon: MessageSquareText },
  { label: "My Sprint", href: "/dev/sprint", icon: KanbanSquare },
  { label: "My GitHub", href: "/dev/github", icon: GitPullRequest },
  { label: "My Projects", href: "/dev/projects", icon: FolderKanban },
  { label: "My Velocity", href: "/dev/velocity", icon: TrendingUp },
  { label: "Channels", href: "/dev/notifications", icon: Inbox },
];

const STAKEHOLDER_NAV: NavItem[] = [
  { label: "Portfolio", href: "/stakeholder", icon: Briefcase },
  { label: "Team Health", href: "/stakeholder/health", icon: HeartPulse },
  { label: "Delivery", href: "/stakeholder/delivery", icon: BarChart3 },
  { label: "Epics", href: "/stakeholder/epics", icon: Milestone },
  { label: "Standup Status", href: "/stakeholder/standups", icon: MessageSquareText },
  { label: "Export", href: "/stakeholder/export", icon: FileDown },
];

function getNavForRole(role: UserRole): NavItem[] {
  switch (role) {
    case "owner":
    case "admin":
    case "product_owner":
    case "engineering_manager":
      return PO_NAV;
    case "developer":
      return DEV_NAV;
    case "stakeholder":
      return STAKEHOLDER_NAV;
    default:
      return PO_NAV;
  }
}

/* -------------------------------------------------------------------------- */
/*  THEME TOGGLE                                                               */
/* -------------------------------------------------------------------------- */

function SidebarThemeToggle({ collapsed }: { collapsed: boolean }) {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) return null;

  const isDark = resolvedTheme === "dark";

  return (
    <button
      onClick={() => setTheme(isDark ? "light" : "dark")}
      className={cn(
        "flex items-center gap-3 rounded-xl px-3 py-2.5 w-full",
        "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
        "hover:bg-[var(--bg-surface-raised)]",
        "transition-all duration-200",
        collapsed && "justify-center px-0"
      )}
      title={isDark ? "Switch to light mode" : "Switch to dark mode"}
    >
      <AnimatePresence mode="wait" initial={false}>
        <motion.span
          key={isDark ? "moon" : "sun"}
          initial={{ y: -6, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: 6, opacity: 0 }}
          transition={{ duration: 0.15 }}
          className="flex h-5 w-5 items-center justify-center shrink-0"
        >
          {isDark ? <Moon size={18} /> : <Sun size={18} />}
        </motion.span>
      </AnimatePresence>
      {!collapsed && (
        <span className="text-sm font-medium">
          {isDark ? "Dark Mode" : "Light Mode"}
        </span>
      )}
    </button>
  );
}

/* -------------------------------------------------------------------------- */
/*  SIDEBAR                                                                    */
/* -------------------------------------------------------------------------- */

interface AppSidebarProps {
  collapsed: boolean;
  onToggle: () => void;
  onMobileClose?: () => void;
}

export function AppSidebar({ collapsed, onToggle, onMobileClose }: AppSidebarProps) {
  const pathname = usePathname();
  const { appUser, role } = useAuth();
  const navItems = getNavForRole(role);

  // Check if any delivery channel is connected (Slack or Teams)
  const [hasChannelConnected, setHasChannelConnected] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function checkChannels() {
      try {
        const [slackRes, teamsRes] = await Promise.allSettled([
          fetch("/api/integrations/slack/status").then((r) => r.json()),
          fetch("/api/integrations/teams/status").then((r) => r.json()),
        ]);
        if (cancelled) return;
        const slackConnected = slackRes.status === "fulfilled" && slackRes.value?.connected;
        const teamsConnected = teamsRes.status === "fulfilled" && teamsRes.value?.connected;
        setHasChannelConnected(slackConnected || teamsConnected);
      } catch {
        // Ignore — dot just won't show
      }
    }
    checkChannels();
    return () => { cancelled = true; };
  }, []);

  const isActive = (href: string) => {
    if (href === "/po" || href === "/dev" || href === "/stakeholder") {
      return pathname === href;
    }
    return pathname.startsWith(href);
  };

  return (
    <aside
      className={cn(
        "flex h-full flex-col bg-[var(--bg-surface)]/95 backdrop-blur-xl",
        "border-r border-[var(--border-subtle)]",
        "transition-all duration-300 ease-out"
      )}
    >
      {/* Logo + collapse toggle */}
      <div className="flex items-center justify-between px-4 py-4 border-b border-[var(--border-subtle)]">
        <Link href="/" className="flex items-center gap-2 overflow-hidden">
          {collapsed ? (
            <Logo size="sm" iconOnly />
          ) : (
            <Logo size="md" />
          )}
        </Link>
        <button
          onClick={() => {
            onToggle();
            onMobileClose?.();
          }}
          className={cn(
            "flex h-7 w-7 items-center justify-center rounded-lg shrink-0",
            "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
            "hover:bg-[var(--bg-surface-raised)]",
            "transition-colors duration-200",
            "hidden lg:flex"
          )}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          <motion.div animate={{ rotate: collapsed ? 180 : 0 }} transition={{ duration: 0.2 }}>
            <ChevronLeft size={16} />
          </motion.div>
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-3 py-4">
        <ul className="space-y-1">
          {navItems.map((item) => {
            const active = isActive(item.href);
            const isNotifications = item.label === "Notifications";
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  onClick={onMobileClose}
                  className={cn(
                    "flex items-center gap-3 rounded-xl px-3 py-2.5",
                    "text-sm font-medium transition-all duration-200",
                    active
                      ? "bg-[var(--color-brand-secondary)]/10 text-[var(--color-brand-secondary)]"
                      : "text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-surface-raised)]",
                    collapsed && "justify-center px-0"
                  )}
                  title={collapsed ? item.label : undefined}
                >
                  <span className="relative shrink-0">
                    <item.icon
                      size={20}
                      className={cn(
                        active && "text-[var(--color-brand-secondary)]"
                      )}
                    />
                    {isNotifications && hasChannelConnected && (
                      <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-[var(--color-rag-green)] border border-[var(--bg-surface)]" />
                    )}
                  </span>
                  {!collapsed && <span>{item.label}</span>}
                  {active && !collapsed && (
                    <motion.div
                      layoutId="sidebar-active"
                      className="ml-auto h-1.5 w-1.5 rounded-full bg-[var(--color-brand-secondary)]"
                      transition={{ type: "spring", stiffness: 300, damping: 30 }}
                    />
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Bottom section */}
      <div className="border-t border-[var(--border-subtle)] px-3 py-3 space-y-2">
        {/* Theme toggle */}
        <SidebarThemeToggle collapsed={collapsed} />

        {/* User info */}
        <div
          className={cn(
            "flex items-center gap-3 rounded-xl px-3 py-2.5",
            collapsed && "justify-center px-0"
          )}
        >
          {/* Avatar */}
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--color-brand-secondary)]/20 text-sm font-semibold text-[var(--color-brand-secondary)]">
            {appUser?.full_name?.charAt(0)?.toUpperCase() ?? "U"}
          </div>
          {!collapsed && (
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-[var(--text-primary)] truncate">
                {appUser?.full_name ?? "User"}
              </p>
              <p className="text-xs text-[var(--text-secondary)] truncate">
                {ROLE_LABELS[role]}
              </p>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}
