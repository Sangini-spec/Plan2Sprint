import { cn } from "@/lib/utils";
import type { HealthSeverity } from "@/lib/types/models";

interface RagIndicatorProps {
  severity: HealthSeverity;
  label?: string;
  size?: "sm" | "md" | "lg";
  className?: string;
}

const severityLabels: Record<HealthSeverity, string> = {
  GREEN: "On Track",
  AMBER: "At Risk",
  RED: "Critical",
};

const dotColors: Record<HealthSeverity, string> = {
  GREEN: "bg-[var(--color-rag-green)]",
  AMBER: "bg-[var(--color-rag-amber)]",
  RED: "bg-[var(--color-rag-red)]",
};

const textColors: Record<HealthSeverity, string> = {
  GREEN: "text-[var(--color-rag-green)]",
  AMBER: "text-[var(--color-rag-amber)]",
  RED: "text-[var(--color-rag-red)]",
};

const dotSizes = {
  sm: "h-1.5 w-1.5",
  md: "h-2 w-2",
  lg: "h-2.5 w-2.5",
};

const textSizes = {
  sm: "text-xs",
  md: "text-sm",
  lg: "text-base",
};

export function RagIndicator({
  severity,
  label,
  size = "md",
  className,
}: RagIndicatorProps) {
  return (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      <span
        className={cn(
          "rounded-full shrink-0",
          dotColors[severity],
          dotSizes[size],
          severity === "RED" && "animate-pulse"
        )}
      />
      <span
        className={cn(
          "font-medium",
          textColors[severity],
          textSizes[size]
        )}
      >
        {label ?? severityLabels[severity]}
      </span>
    </span>
  );
}
