"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth/context";
import type { UserRole } from "@/lib/types/auth";

interface TabSpec {
  label: string;
  href: string;
  /**
   * If set, the tab is hidden for users in these roles. Stakeholders
   * don't connect tools (the PO does) and don't manage team membership,
   * so we hide those tabs entirely to remove confusion.
   */
  hideFor?: UserRole[];
}

const TABS: TabSpec[] = [
  { label: "Profile", href: "/settings/profile" },
  { label: "General", href: "/settings" },
  { label: "Team", href: "/settings/team", hideFor: ["stakeholder", "developer"] },
  { label: "Connections", href: "/settings/connections", hideFor: ["stakeholder"] },
  { label: "Notifications", href: "/settings/notifications" },
  { label: "Help", href: "/settings/help" },
];

export default function SettingsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const { role } = useAuth();
  const visibleTabs = TABS.filter((t) => !t.hideFor?.includes(role));

  function isActive(href: string) {
    if (href === "/settings") return pathname === "/settings";
    return pathname.startsWith(href);
  }

  return (
    <div className="space-y-6">
      {/* Tab bar */}
      <nav className="flex gap-1 border-b border-[var(--border-subtle)]">
        {visibleTabs.map((tab) => (
          <Link
            key={tab.href}
            href={tab.href}
            className={cn(
              "px-4 py-2.5 text-sm font-medium transition-colors relative",
              isActive(tab.href)
                ? "text-[var(--text-primary)]"
                : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            )}
          >
            {tab.label}
            {isActive(tab.href) && (
              <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-[var(--color-brand-secondary)] rounded-t" />
            )}
          </Link>
        ))}
      </nav>

      {/* Content */}
      {children}
    </div>
  );
}
