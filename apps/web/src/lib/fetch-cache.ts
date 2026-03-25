/**
 * Lightweight in-memory fetch cache with TTL.
 *
 * Prevents duplicate API calls when:
 *  - Multiple components fetch the same endpoint on mount
 *  - WebSocket-triggered refreshes happen within the cache window
 *  - React re-renders cause unnecessary refetches
 *
 * Only caches GET requests. POST/PUT/DELETE bypass cache.
 */

interface CacheEntry {
  data: unknown;
  timestamp: number;
}

interface CachedResult {
  ok: boolean;
  status: number;
  data: unknown;
}

const cache = new Map<string, CacheEntry>();
const inflight = new Map<string, Promise<CachedResult>>();

const DEFAULT_TTL_MS = 30_000; // 30 seconds

/**
 * Fetch with in-memory caching for GET requests.
 *
 * @param url - The URL to fetch
 * @param options - Standard fetch options (only GET requests are cached)
 * @param ttl - Cache TTL in milliseconds (default: 30s)
 * @returns Parsed JSON response
 */
export async function cachedFetch<T = unknown>(
  url: string,
  options?: RequestInit,
  ttl: number = DEFAULT_TTL_MS
): Promise<{ ok: boolean; status: number; data: T }> {
  const method = (options?.method ?? "GET").toUpperCase();

  // Only cache GET requests
  if (method !== "GET") {
    const res = await fetch(url, options);
    const data = res.ok ? await res.json() : null;
    return { ok: res.ok, status: res.status, data: data as T };
  }

  // Check cache
  const cached = cache.get(url);
  if (cached && Date.now() - cached.timestamp < ttl) {
    return { ok: true, status: 200, data: cached.data as T };
  }

  // Deduplicate inflight requests — if the same URL is already being fetched,
  // reuse the pending *parsed result* promise instead of firing another request.
  // We store the parsed result (not raw Response) so multiple callers can share it
  // without body-stream conflicts.
  let resultPromise = inflight.get(url);
  if (!resultPromise) {
    resultPromise = (async (): Promise<CachedResult> => {
      try {
        const res = await fetch(url, options);
        if (res.ok) {
          const data = await res.json();
          cache.set(url, { data, timestamp: Date.now() });
          return { ok: true, status: res.status, data };
        }
        // Do NOT cache error responses (401, 500, etc.)
        // This prevents stale auth failures from blocking real data
        return { ok: false, status: res.status, data: null };
      } catch {
        return { ok: false, status: 0, data: null };
      } finally {
        inflight.delete(url);
      }
    })();
    inflight.set(url, resultPromise);
  }

  const result = await resultPromise;
  return { ok: result.ok, status: result.status, data: result.data as T };
}

/**
 * Invalidate a specific cache entry or all entries matching a prefix.
 */
export function invalidateCache(urlOrPrefix?: string) {
  if (!urlOrPrefix) {
    cache.clear();
    return;
  }

  for (const key of cache.keys()) {
    if (key === urlOrPrefix || key.startsWith(urlOrPrefix)) {
      cache.delete(key);
    }
  }
}
