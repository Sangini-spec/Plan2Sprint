"use client";

import { ResponsiveContainer } from "recharts";
import { cn } from "@/lib/utils";

interface ChartWrapperProps {
  children: React.ReactNode;
  height?: number;
  className?: string;
}

/**
 * Theme-aware container for Recharts charts.
 * Uses CSS custom properties for consistent theming.
 */
export function ChartWrapper({
  children,
  height = 300,
  className,
}: ChartWrapperProps) {
  return (
    <div className={cn("w-full", className)} style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        {children as React.ReactElement}
      </ResponsiveContainer>
    </div>
  );
}

/**
 * Chart color tokens derived from CSS custom properties.
 * Use these in Recharts components for theme-aware colors.
 */
export const chartColors = {
  brand: {
    primary: "var(--color-brand-primary)",
    secondary: "var(--color-brand-secondary)",
    accent: "var(--color-brand-accent)",
  },
  rag: {
    green: "var(--color-rag-green)",
    amber: "var(--color-rag-amber)",
    red: "var(--color-rag-red)",
  },
  text: {
    primary: "var(--text-primary)",
    secondary: "var(--text-secondary)",
  },
  border: "var(--border-subtle)",
  surface: "var(--bg-surface-raised)",
} as const;
