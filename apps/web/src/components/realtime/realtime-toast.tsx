"use client";

/**
 * Toast notifications for real-time events.
 *
 * Listens to all WebSocket events and shows a small slide-in toast
 * for notable events (sync complete, writeback, health signals).
 * Auto-dismisses after 5 seconds.
 */

import { useState, useCallback, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  RefreshCw,
  ArrowUpDown,
  Undo2,
  AlertTriangle,
  FileText,
  Wifi,
  X,
} from "lucide-react";
import { useRealtimeAll, type RealtimeEvent } from "@/lib/ws/context";

interface Toast {
  id: string;
  icon: React.ReactNode;
  title: string;
  description: string;
  severity: "info" | "success" | "warning";
}

const TOAST_DURATION = 5000;
const MAX_TOASTS = 3;

function eventToToast(event: RealtimeEvent): Toast | null {
  const id = `${event.type}-${Date.now()}`;
  const data = event.data || {};

  switch (event.type) {
    case "connected":
      return {
        id,
        icon: <Wifi size={16} className="text-emerald-500" />,
        title: "Real-time Connected",
        description: "Dashboard updates will appear live",
        severity: "info",
      };

    case "sync_complete":
      return {
        id,
        icon: <RefreshCw size={16} className="text-blue-500" />,
        title: "Sync Complete",
        description: `${(data.sourceTool as string) || "Tool"} data synced - ${
          JSON.stringify(data.synced || {})
            .replace(/[{}\"]/g, "")
            .replace(/,/g, ", ")
        }`,
        severity: "success",
      };

    case "writeback_success":
      return {
        id,
        icon: <ArrowUpDown size={16} className="text-emerald-500" />,
        title: "Write-back Applied",
        description: `${(data.itemTitle as string) || (data.itemId as string) || "Item"} updated in ${(data.tool as string)?.toUpperCase() || "tool"}`,
        severity: "success",
      };

    case "writeback_undo":
      return {
        id,
        icon: <Undo2 size={16} className="text-amber-500" />,
        title: "Write-back Undone",
        description: `Changes to ${(data.itemId as string) || "item"} reverted`,
        severity: "info",
      };

    case "health_signals":
      return {
        id,
        icon: <AlertTriangle size={16} className="text-amber-500" />,
        title: "Health Signals",
        description: `${(data.count as number) || 0} new signal(s) detected`,
        severity: "warning",
      };

    case "standup_generated":
      return {
        id,
        icon: <FileText size={16} className="text-violet-500" />,
        title: "Standups Generated",
        description: `${(data.reportsGenerated as number) || 0} reports ready`,
        severity: "success",
      };

    default:
      return null;
  }
}

const severityBorder: Record<string, string> = {
  info: "border-l-blue-400",
  success: "border-l-emerald-400",
  warning: "border-l-amber-400",
};

export function RealtimeToastContainer() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const timersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
    const timer = timersRef.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timersRef.current.delete(id);
    }
  }, []);

  const addToast = useCallback(
    (toast: Toast) => {
      setToasts((prev) => {
        const next = [...prev, toast];
        // Keep only the latest MAX_TOASTS
        if (next.length > MAX_TOASTS) {
          const removed = next.shift();
          if (removed) removeToast(removed.id);
        }
        return next;
      });

      // Auto-dismiss
      const timer = setTimeout(() => removeToast(toast.id), TOAST_DURATION);
      timersRef.current.set(toast.id, timer);
    },
    [removeToast]
  );

  useRealtimeAll(
    useCallback(
      (event: RealtimeEvent) => {
        const toast = eventToToast(event);
        if (toast) addToast(toast);
      },
      [addToast]
    )
  );

  // Cleanup timers on unmount
  useEffect(() => {
    return () => {
      timersRef.current.forEach((timer) => clearTimeout(timer));
    };
  }, []);

  return (
    <div className="fixed bottom-4 right-4 z-[9999] flex flex-col gap-2 pointer-events-none">
      <AnimatePresence mode="popLayout">
        {toasts.map((toast) => (
          <motion.div
            key={toast.id}
            initial={{ opacity: 0, y: 20, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, x: 80, scale: 0.95 }}
            transition={{ type: "spring", damping: 25, stiffness: 300 }}
            className={`pointer-events-auto flex items-start gap-3 rounded-xl border border-[var(--border-subtle)] border-l-4 ${
              severityBorder[toast.severity]
            } bg-[var(--bg-surface-raised)] px-4 py-3 shadow-lg backdrop-blur-md max-w-sm`}
          >
            <div className="mt-0.5 shrink-0">{toast.icon}</div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-[var(--text-primary)]">
                {toast.title}
              </p>
              <p className="text-xs text-[var(--text-secondary)] line-clamp-2">
                {toast.description}
              </p>
            </div>
            <button
              onClick={() => removeToast(toast.id)}
              className="shrink-0 p-0.5 rounded hover:bg-[var(--bg-surface-sunken)] transition-colors"
            >
              <X size={14} className="text-[var(--text-tertiary)]" />
            </button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
