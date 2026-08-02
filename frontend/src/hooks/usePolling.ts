/**
 * Polling hook — fetches data at a regular interval.
 */

import { useState, useEffect, useCallback, useRef } from 'react';

const DEFAULT_INTERVAL = 3000;

export function usePolling<T>(
  fetcher: () => Promise<T>,
  interval: number = DEFAULT_INTERVAL,
  enabled: boolean = true,
): { data: T | null; error: string | null; loading: boolean; refetch: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const mountedRef = useRef(true);

  const doFetch = useCallback(async () => {
    try {
      const result = await fetcher();
      if (mountedRef.current) {
        setData(result);
        setError(null);
      }
    } catch (e) {
      if (mountedRef.current) {
        setError(e instanceof Error ? e.message : 'Unknown error');
      }
    } finally {
      if (mountedRef.current) {
        setLoading(false);
      }
    }
  }, [fetcher]);

  useEffect(() => {
    mountedRef.current = true;
    if (!enabled) return;

    doFetch();
    const id = setInterval(doFetch, interval);

    return () => {
      mountedRef.current = false;
      clearInterval(id);
    };
  }, [doFetch, interval, enabled]);

  return { data, error, loading, refetch: doFetch };
}
