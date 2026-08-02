import { useEffect, useRef, useState, useCallback } from 'react';

export interface SSEEvent {
  event: string;
  data: any;
  timestamp: string;
}

export const useSSE = (url: string) => {
  const [isConnected, setIsConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState<SSEEvent | null>(null);
  const retries = useRef(0);
  const eventSourceRef = useRef<EventSource | null>(null);

  const connect = useCallback(() => {
    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.onopen = () => {
      setIsConnected(true);
      retries.current = 0; // Reset retries on successful connection
    };

    es.onmessage = (event) => {
      // Ignore SSE heartbeat comments (starting with :)
      if (event.data.startsWith(':')) return;

      try {
        const parsedEvent: SSEEvent = JSON.parse(event.data);
        setLastEvent(parsedEvent);
      } catch (e) {
        console.error('Failed to parse SSE data', e);
      }
    };

    es.onerror = () => {
      setIsConnected(false);
      es.close();

      // Exponential backoff: 1s, 2s, 4s, 8s, max 30s
      const delay = Math.min(Math.pow(2, retries.current) * 1000, 30000);
      retries.current += 1;

      setTimeout(connect, delay);
    };
  }, [url]);

  useEffect(() => {
    connect();

    return () => {
      eventSourceRef.current?.close();
    };
  }, [connect]);

  return { isConnected, lastEvent };
};
