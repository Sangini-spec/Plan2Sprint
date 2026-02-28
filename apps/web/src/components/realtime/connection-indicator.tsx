"use client";

/**
 * Small dot indicator showing WebSocket connection status.
 * Green = connected, Yellow = connecting, Gray = disconnected.
 * Placed in the topbar or sidebar.
 */

import { useWebSocket, type ConnectionStatus } from "@/lib/ws/context";

const statusConfig: Record<ConnectionStatus, { color: string; label: string }> = {
  connected: { color: "bg-emerald-500", label: "Real-time connected" },
  connecting: { color: "bg-amber-400 animate-pulse", label: "Connecting..." },
  disconnected: { color: "bg-gray-400", label: "Disconnected" },
};

export function ConnectionIndicator() {
  const { status } = useWebSocket();
  const { color, label } = statusConfig[status];

  return (
    <div className="flex items-center gap-1.5" title={label}>
      <span className={`inline-block h-2 w-2 rounded-full ${color}`} />
      <span className="text-[10px] font-medium text-[var(--text-tertiary)] hidden sm:inline">
        {status === "connected" ? "Live" : status === "connecting" ? "..." : "Offline"}
      </span>
    </div>
  );
}
