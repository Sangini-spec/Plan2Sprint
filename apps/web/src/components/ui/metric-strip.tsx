"use client";

import { cn } from "@/lib/utils";

export interface MetricItem {
  label: string;
  value: string | number;
  /** Optional severity tint for the value */
  severity?: "green" | "amber" | "red";
}

interface MetricStripProps {
  items: MetricItem[];
  className?: string;
}

const severityColor: Record<string, string> = {
  green: "text-[var(--color-rag-green)]",
  amber: "text-[var(--color-rag-amber)]",
  red: "text-[var(--color-rag-red)]",
};

export function MetricStrip({ items, className }: MetricStripProps) {
  return (
    <div
      className={cn(
        "flex items-center divide-x divide-[var(--border-subtle)] overflow-x-auto",
        "bg-[var(--bg-surface-sunken)] border border-[var(--border-subtle)] rounded-lg",
        className
      )}
    >
      {items.map((item) => (
        <div
          key={item.label}
          className="flex items-center gap-2 px-4 py-2 min-w-0 shrink-0"
        >
          <span
            className={cn(
              "text-sm font-semibold tabular-nums whitespace-nowrap",
              item.severity
                ? severityColor[item.severity]
                : "text-[var(--text-primary)]"
            )}
          >
            {item.value}
          </span>
          <span className="text-xs text-[var(--text-secondary)] whitespace-nowrap">
            {item.label}
          </span>
        </div>
      ))}
    </div>
  );
}
