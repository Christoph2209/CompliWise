// Generic cache for GET-style API calls, keyed by an arbitrary string.
// Used by pages that fetch the same underlying data (e.g. the schedule for
// a given run) so navigating between them doesn't refire the same request.

type CacheEntry<T> = { data: T; fetchedAt: number };

const DEFAULT_STALE_MS = 60_000;

const cache = new Map<string, CacheEntry<any>>();
const inFlight = new Map<string, Promise<any>>();

export async function cachedFetch<T>(
  key: string,
  fetcher: () => Promise<T>,
  options: { force?: boolean; staleMs?: number } = {}
): Promise<T> {
  const { force = false, staleMs = DEFAULT_STALE_MS } = options;

  const entry = cache.get(key);
  const isStale = !entry || Date.now() - entry.fetchedAt > staleMs;

  if (!force && entry && !isStale) {
    return entry.data as T;
  }

  const existing = inFlight.get(key);
  if (existing) return existing as Promise<T>;

  const promise = (async () => {
    const data = await fetcher();
    cache.set(key, { data, fetchedAt: Date.now() });
    inFlight.delete(key);
    return data;
  })();

  inFlight.set(key, promise);
  return promise;
}

// Call after any mutation that changes what a cached key would return, so
// the next cachedFetch() for that key hits the network instead of serving
// stale data. Omit the key to clear everything.
export function invalidateCache(key?: string) {
  if (key) {
    cache.delete(key);
  } else {
    cache.clear();
  }
}