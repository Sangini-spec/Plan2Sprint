"use client";

import { TrendingUp, TrendingDown, Minus, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import type { HealthSeverity } from "@/lib/types/models";

interface StatCardProps {
  label: string;
  value: string | number;
  trend?: {
    direction: "up" | "down" | "flat";
    value: string;
  };
  severity?: HealthSeverity;
  icon?: LucideIcon;
  className?: string;
}

const severityColors: Record<HealthSeverity, string> = {
  GREEN: "text-[var(--color-rag-green)]",
  AMBER: "text-[var(--color-rag-amber)]",
  RED: "text-[var(--color-rag-red)]",
};

const severityBg: Record<HealthSeverity, string> = {
  GREEN: "bg-[var(--color-rag-green)]/10",
  AMBER: "bg-[var(--color-rag-amber)]/10",
  RED: "bg-[var(--color-rag-red)]/10",
};

const TrendIcon = {
  up: TrendingUp,
  down: TrendingDown,
  flat: Minus,
};

export function StatCard({
  label,
  value,
  trend,
  severity,
  icon: Icon,
  className,
}: StatCardProps) {
  return (
    <div
      className={cn(
        "rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface-raised)] p-4",
        className
      )}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider">
          {label}
        </span>
        {Icon && (
          <div
            className={cn(
              "flex h-7 w-7 items-center justify-center rounded-lg",
              severity ? severityBg[severity] : "bg-[var(--color-brand-secondary)]/10"
            )}
          >
            <Icon
              className={cn(
                "h-3.5 w-3.5",
                severity
                  ? severityColors[severity]
                  : "text-[var(--color-brand-secondary)]"
              )}
            />
          </div>
        )}
      </div>
      <div className="flex items-end gap-2">
        <span
          className={cn(
            "text-2xl font-bold tabular-nums",
            severity
              ? severityColors[severity]
              : "text-[var(--text-primary)]"
          )}
        >
          {value}
        </span>
        {trend && (
          <span
            className={cn(
              "flex items-center gap-0.5 text-xs font-medium mb-1",
              trend.direction === "up" && "text-[var(--color-rag-green)]",
              trend.direction === "down" && "text-[var(--color-rag-red)]",
              trend.direction === "flat" && "text-[var(--text-secondary)]"
            )}
          >
            {(() => {
              const TIcon = TrendIcon[trend.direction];
              return <TIcon className="h-3 w-3" />;
            })()}
            {trend.value}
          </span>
        )}
      </div>
    </div>
  );
}
