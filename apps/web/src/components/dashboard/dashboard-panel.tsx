"use client";

import { useState, type ReactNode } from "react";
import { ChevronDown, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

interface DashboardPanelProps {
  title: string;
  icon?: LucideIcon;
  actions?: ReactNode;
  children: ReactNode;
  collapsible?: boolean;
  defaultCollapsed?: boolean;
  className?: string;
  sticky?: boolean; // kept for backwards compat but ignored
  noPadding?: boolean;
  id?: string;
}

export function DashboardPanel({
  title,
  icon: Icon,
  actions,
  children,
  collapsible = false,
  defaultCollapsed = false,
  className,
  noPadding = false,
  id,
}: DashboardPanelProps) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);

  return (
    <section
      id={id}
      className={cn(
        "rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)]",
        className
      )}
    >
      {/* Header */}
      <div
        className={cn(
          "flex items-center justify-between px-5 py-3",
          collapsible && "cursor-pointer select-none",
          !collapsed && !noPadding && "border-b border-[var(--border-subtle)]"
        )}
        onClick={collapsible ? () => setCollapsed(!collapsed) : undefined}
      >
        <div className="flex items-center gap-2.5">
          {Icon && (
            <div className="flex h-6 w-6 items-center justify-center rounded-md bg-[var(--color-brand-secondary)]/10">
              <Icon className="h-3.5 w-3.5 text-[var(--color-brand-secondary)]" />
            </div>
          )}
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">
            {title}
          </h2>
        </div>
        <div className="flex items-center gap-2">
          {actions}
          {collapsible && (
            <div
              className={cn(
                "transition-transform duration-200",
                collapsed && "-rotate-90"
              )}
            >
              <ChevronDown className="h-4 w-4 text-[var(--text-secondary)]" />
            </div>
          )}
        </div>
      </div>

      {/* Content */}
      <div
        className={cn(
          "transition-all duration-200 overflow-hidden",
          collapsed ? "h-0 opacity-0" : "h-auto opacity-100"
        )}
      >
        <div className={cn(!noPadding && "p-5")}>{children}</div>
      </div>
    </section>
  );
}
