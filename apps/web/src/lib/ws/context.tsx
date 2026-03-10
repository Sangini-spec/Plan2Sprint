"use client";

/**
 * WebSocket real-time context.
 *
 * Provides a persistent WebSocket connection to the Plan2Sprint API.
 * Components subscribe to event types via `useRealtimeEvent()` and
 * automatically re-render when matching events arrive.
 *
 * Features:
 *  - Auto-reconnect with exponential backoff (1s, 2s, 4s, 8s, max 30s)
 *  - Heartbeat monitoring (disconnects if no heartbeat for 45s)
 *  - Event bus: components subscribe to specific event types
 *  - Connection status tracking (connecting, connected, disconnected)
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ConnectionStatus = "connecting" | "connected" | "disconnected";

export interface RealtimeEvent {
  type: string;
  data?: Record<string, unknown>;
  ts?: string;
}

type EventHandler = (event: RealtimeEvent) => void;

interface WebSocketContextType {
  /** Current connection status */
  status: ConnectionStatus;
  /** Subscribe to events of a specific type. Returns unsubscribe function. */
  subscribe: (eventType: string, handler: EventHandler) => () => void;
  /** Subscribe to ALL events. Returns unsubscribe function. */
  subscribeAll: (handler: EventHandler) => () => void;
  /** Latest event received (any type) */
  lastEvent: RealtimeEvent | null;
}

const WebSocketContext = createContext<WebSocketContextType>({
  status: "disconnected",
  subscribe: () => () => {},
  subscribeAll: () => () => {},
  lastEvent: null,
});

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30000;
const HEARTBEAT_TIMEOUT_MS = 45000; // expect heartbeat every 30s, timeout at 45s

function getWsUrl(): string {
  // Build WebSocket URL from current page location
  if (typeof window === "undefined") return "";

  // In dev, API runs on port 8000
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const apiHost =
    process.env.NEXT_PUBLIC_API_URL?.replace(/^https?:\/\//, "") ||
    `${window.location.hostname}:8000`;

  return `${protocol}//${apiHost}/api/ws`;
}

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function WebSocketProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<ConnectionStatus>("disconnected");
  const [lastEvent, setLastEvent] = useState<RealtimeEvent | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heartbeatTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Event bus: eventType -> Set of handlers
  const handlersRef = useRef<Map<string, Set<EventHandler>>>(new Map());
  // Catch-all handlers
  const allHandlersRef = useRef<Set<EventHandler>>(new Set());

  // ------------------------------------------------------------------
  // Subscribe / unsubscribe
  // ------------------------------------------------------------------

  const subscribe = useCallback(
    (eventType: string, handler: EventHandler): (() => void) => {
      if (!handlersRef.current.has(eventType)) {
        handlersRef.current.set(eventType, new Set());
      }
      handlersRef.current.get(eventType)!.add(handler);

      return () => {
        handlersRef.current.get(eventType)?.delete(handler);
      };
    },
    []
  );

  const subscribeAll = useCallback(
    (handler: EventHandler): (() => void) => {
      allHandlersRef.current.add(handler);
      return () => {
        allHandlersRef.current.delete(handler);
      };
    },
    []
  );

  // ------------------------------------------------------------------
  // Dispatch event to subscribers
  // ------------------------------------------------------------------

  const dispatch = useCallback((event: RealtimeEvent) => {
    // Skip internal messages
    if (event.type === "heartbeat" || event.type === "pong") return;

    setLastEvent(event);

    // Notify type-specific handlers
    const handlers = handlersRef.current.get(event.type);
    if (handlers) {
      handlers.forEach((h) => {
        try {
          h(event);
        } catch (e) {
          console.error("[WS] Handler error:", e);
        }
      });
    }

    // Notify catch-all handlers
    allHandlersRef.current.forEach((h) => {
      try {
        h(event);
      } catch (e) {
        console.error("[WS] Handler error:", e);
      }
    });
  }, []);

  // ------------------------------------------------------------------
  // Heartbeat monitoring
  // ------------------------------------------------------------------

  const resetHeartbeatTimer = useCallback(() => {
    if (heartbeatTimerRef.current) {
      clearTimeout(heartbeatTimerRef.current);
    }
    heartbeatTimerRef.current = setTimeout(() => {
      console.warn("[WS] No heartbeat received — closing connection");
      wsRef.current?.close();
    }, HEARTBEAT_TIMEOUT_MS);
  }, []);

  // ------------------------------------------------------------------
  // Connection management
  // ------------------------------------------------------------------

  const connect = useCallback(() => {
    const url = getWsUrl();
    if (!url) return;

    // Get auth token from Supabase session or demo mode
    let tokenParam = "";
    try {
      const stored = localStorage.getItem("plan2sprint_demo_user");
      if (stored) {
        // Demo mode — no token needed (server accepts without)
        tokenParam = "";
      } else {
        // Try to get Supabase token from cookie/storage
        // Supabase stores session in localStorage as sb-<ref>-auth-token
        const keys = Object.keys(localStorage);
        const sbKey = keys.find((k) => k.startsWith("sb-") && k.endsWith("-auth-token"));
        if (sbKey) {
          try {
            const session = JSON.parse(localStorage.getItem(sbKey) || "{}");
            const accessToken = session?.access_token;
            if (accessToken) {
              tokenParam = `?token=${encodeURIComponent(accessToken)}`;
            }
          } catch {
            // fallback to no token
          }
        }
      }
    } catch {
      // localStorage not available
    }

    setStatus("connecting");

    const ws = new WebSocket(`${url}${tokenParam}`);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log("[WS] Connected");
      setStatus("connected");
      reconnectAttemptRef.current = 0;
      resetHeartbeatTimer();
    };

    ws.onmessage = (event) => {
      try {
        const parsed: RealtimeEvent = JSON.parse(event.data);

        // Reset heartbeat on any message
        resetHeartbeatTimer();

        // Dispatch to subscribers
        dispatch(parsed);
      } catch {
        console.warn("[WS] Failed to parse message:", event.data);
      }
    };

    ws.onclose = (event) => {
      console.log("[WS] Disconnected:", event.code, event.reason);
      setStatus("disconnected");
      wsRef.current = null;

      if (heartbeatTimerRef.current) {
        clearTimeout(heartbeatTimerRef.current);
      }

      // Don't reconnect if closed with 4001 (auth failure)
      if (event.code === 4001) {
        console.error("[WS] Authentication failed — not reconnecting");
        return;
      }

      // Exponential backoff reconnect
      const delay = Math.min(
        RECONNECT_BASE_MS * Math.pow(2, reconnectAttemptRef.current),
        RECONNECT_MAX_MS
      );
      reconnectAttemptRef.current += 1;

      console.log(`[WS] Reconnecting in ${delay}ms (attempt ${reconnectAttemptRef.current})`);
      reconnectTimerRef.current = setTimeout(connect, delay);
    };

    ws.onerror = () => {
      // onclose will fire after this — reconnect logic handled there
    };
  }, [dispatch, resetHeartbeatTimer]);

  // ------------------------------------------------------------------
  // Mount / unmount
  // ------------------------------------------------------------------

  useEffect(() => {
    connect();

    return () => {
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
      if (heartbeatTimerRef.current) {
        clearTimeout(heartbeatTimerRef.current);
      }
      wsRef.current?.close();
    };
  }, [connect]);

  // Memoize context value to prevent child re-renders on every WS message
  const value = useMemo(
    () => ({ status, subscribe, subscribeAll, lastEvent }),
    [status, subscribe, subscribeAll, lastEvent]
  );

  return (
    <WebSocketContext.Provider value={value}>
      {children}
    </WebSocketContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

/** Access the raw WebSocket context. */
export function useWebSocket() {
  return useContext(WebSocketContext);
}

/**
 * Subscribe to a specific real-time event type.
 *
 * @param eventType - The event type to listen for (e.g., "sync_complete")
 * @param handler - Callback fired when the event arrives
 *
 * @example
 * ```tsx
 * useRealtimeEvent("sync_complete", (event) => {
 *   console.log("Sync done!", event.data);
 *   refetchDashboard();
 * });
 * ```
 */
export function useRealtimeEvent(
  eventType: string,
  handler: EventHandler
) {
  const { subscribe } = useWebSocket();
  const handlerRef = useRef(handler);
  handlerRef.current = handler;

  useEffect(() => {
    const unsubscribe = subscribe(eventType, (event) => {
      handlerRef.current(event);
    });
    return unsubscribe;
  }, [eventType, subscribe]);
}

/**
 * Subscribe to ANY real-time event.
 *
 * @example
 * ```tsx
 * useRealtimeAll((event) => {
 *   showToast(`Real-time: ${event.type}`);
 * });
 * ```
 */
export function useRealtimeAll(handler: EventHandler) {
  const { subscribeAll } = useWebSocket();
  const handlerRef = useRef(handler);
  handlerRef.current = handler;

  useEffect(() => {
    const unsubscribe = subscribeAll((event) => {
      handlerRef.current(event);
    });
    return unsubscribe;
  }, [subscribeAll]);
}

/**
 * Auto-refresh hook — triggers a callback whenever specific event types arrive.
 * Useful for dashboard panels that should refetch data on real-time events.
 *
 * Performance features:
 *  - Debounce: rapid events within 2s collapse into a single refresh
 *  - Minimum interval: at most one auto-refresh per 60s to prevent idle churn
 *
 * @example
 * ```tsx
 * const refreshKey = useAutoRefresh(["sync_complete", "writeback_success"]);
 * // Use refreshKey in your useEffect dependency to trigger re-fetch
 * ```
 */
const AUTO_REFRESH_DEBOUNCE_MS = 2000; // collapse rapid events
const AUTO_REFRESH_MIN_INTERVAL_MS = 60000; // max once per 60s

export function useAutoRefresh(eventTypes: string[]): number {
  const [refreshKey, setRefreshKey] = useState(0);
  const { subscribe } = useWebSocket();
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastRefreshRef = useRef<number>(0);

  useEffect(() => {
    const unsubscribers = eventTypes.map((type) =>
      subscribe(type, () => {
        // Clear any pending debounce
        if (debounceRef.current) clearTimeout(debounceRef.current);

        debounceRef.current = setTimeout(() => {
          const now = Date.now();
          const elapsed = now - lastRefreshRef.current;

          if (elapsed >= AUTO_REFRESH_MIN_INTERVAL_MS) {
            // Enough time has passed — refresh immediately
            lastRefreshRef.current = now;
            setRefreshKey((k) => k + 1);
          }
          // Otherwise skip — too soon since last refresh
        }, AUTO_REFRESH_DEBOUNCE_MS);
      })
    );

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      unsubscribers.forEach((unsub) => unsub());
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [subscribe, ...eventTypes]);

  return refreshKey;
}
