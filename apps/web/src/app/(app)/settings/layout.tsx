"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import { cn } from "@/lib/utils";

const TABS = [
  { label: "Profile", href: "/settings/profile" },
  { label: "General", href: "/settings" },
  { label: "Team", href: "/settings/team" },
  { label: "Connections", href: "/settings/connections" },
  { label: "Notifications", href: "/settings/notifications" },
];

export default function SettingsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();

  function isActive(href: string) {
    if (href === "/settings") return pathname === "/settings";
    return pathname.startsWith(href);
  }

  return (
    <div className="space-y-6">
      {/* Tab bar */}
      <nav className="flex gap-1 border-b border-[var(--border-subtle)]">
        {TABS.map((tab) => (
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
