"use client";

import { cn } from "@/lib/utils";
import type { ConnectionStatus } from "@/lib/integrations/types";

const STATUS_CONFIG: Record<ConnectionStatus, { label: string; color: string; dot: string }> = {
  disconnected: {
    label: "Not Connected",
    color: "text-[var(--text-tertiary)]",
    dot: "bg-[var(--text-tertiary)]",
  },
  connecting: {
    label: "Connecting...",
    color: "text-[var(--color-brand-secondary)]",
    dot: "bg-[var(--color-brand-secondary)] animate-pulse",
  },
  connected: {
    label: "Connected",
    color: "text-[var(--color-rag-green)]",
    dot: "bg-[var(--color-rag-green)]",
  },
  syncing: {
    label: "Syncing...",
    color: "text-[var(--color-brand-secondary)]",
    dot: "bg-[var(--color-brand-secondary)] animate-pulse",
  },
  error: {
    label: "Error",
    color: "text-[var(--color-rag-red)]",
    dot: "bg-[var(--color-rag-red)]",
  },
  token_expired: {
    label: "Token Expired",
    color: "text-[var(--color-rag-amber)]",
    dot: "bg-[var(--color-rag-amber)]",
  },
};

interface ConnectionStatusBadgeProps {
  status: ConnectionStatus;
  className?: string;
}

export function ConnectionStatusBadge({ status, className }: ConnectionStatusBadgeProps) {
  const config = STATUS_CONFIG[status];

  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs font-medium", config.color, className)}>
      <span className={cn("h-2 w-2 rounded-full shrink-0", config.dot)} />
      {config.label}
    </span>
  );
}
