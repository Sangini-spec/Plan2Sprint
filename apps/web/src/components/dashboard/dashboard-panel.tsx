"use client";

import { useState, type ReactNode } from "react";
import { motion, AnimatePresence } from "framer-motion";
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
        "rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)]/80 backdrop-blur-xl shadow-lg shadow-black/5 dark:shadow-black/20",
        className
      )}
    >
      {/* Header */}
      <div
        className={cn(
          "flex items-center justify-between px-6 py-4",
          collapsible && "cursor-pointer select-none",
          !collapsed && !noPadding && "border-b border-[var(--border-subtle)]"
        )}
        onClick={collapsible ? () => setCollapsed(!collapsed) : undefined}
      >
        <div className="flex items-center gap-3">
          {Icon && (
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--color-brand-secondary)]/10">
              <Icon className="h-4 w-4 text-[var(--color-brand-secondary)]" />
            </div>
          )}
          <h2 className="text-base font-semibold text-[var(--text-primary)]">
            {title}
          </h2>
        </div>
        <div className="flex items-center gap-2">
          {actions}
          {collapsible && (
            <motion.div
              animate={{ rotate: collapsed ? -90 : 0 }}
              transition={{ duration: 0.2 }}
            >
              <ChevronDown className="h-4 w-4 text-[var(--text-secondary)]" />
            </motion.div>
          )}
        </div>
      </div>

      {/* Content */}
      <AnimatePresence initial={false}>
        {!collapsed && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: "easeInOut" }}
            className="overflow-hidden"
          >
            <div className={cn(!noPadding && "p-6")}>{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}
