/**
 * useMetricsWS — React hook for the /ws/metrics WebSocket stream.
 *
 * Connects to the backend WebSocket and pushes live MetricsSnapshot
 * data every 2 seconds. Maintains a rolling history of the last 60
 * data points for chart rendering.
 *
 * Features:
 *  - Auto-reconnects with exponential backoff (1 s → 2 s → 4 s … max 30 s)
 *  - Exposes `status` so the UI can show a connection indicator
 *  - Cleans up the socket and timers on unmount
 *
 * @example
 * ```tsx
 * const { current, history, status } = useMetricsWS();
 * ```
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { MetricsSnapshot, WSStatus } from '../types/metrics';

export interface ChartPoint {
  time: string;
  cpu: number;
  ram: number;
  disk: number;
  net_sent: number;
  net_recv: number;
}

interface UseMetricsWSResult {
  /** Latest metrics snapshot, or null if not yet received. */
  current: MetricsSnapshot | null;
  /** Rolling 60-point history for chart rendering. */
  history: ChartPoint[];
  /** WebSocket connection status. */
  status: WSStatus;
}

const MAX_HISTORY = 60;
const INITIAL_RETRY_MS = 1_000;
const MAX_RETRY_MS = 30_000;

/** Build the WebSocket URL relative to the current page. */
function buildWsUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}/ws/metrics`;
}

export function useMetricsWS(): UseMetricsWSResult {
  const [current, setCurrent] = useState<MetricsSnapshot | null>(null);
  const [history, setHistory] = useState<ChartPoint[]>([]);
  const [status, setStatus] = useState<WSStatus>('connecting');

  const wsRef = useRef<WebSocket | null>(null);
  const retryMsRef = useRef(INITIAL_RETRY_MS);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const connect = useCallback(() => {
    if (!mountedRef.current) return;

    const url = buildWsUrl();
    setStatus('connecting');

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) return;
      setStatus('connected');
      retryMsRef.current = INITIAL_RETRY_MS; // reset backoff on success
    };

    ws.onmessage = (event: MessageEvent) => {
      if (!mountedRef.current) return;
      try {
        const snapshot = JSON.parse(event.data as string) as MetricsSnapshot;
        setCurrent(snapshot);

        const point: ChartPoint = {
          time: new Date().toLocaleTimeString(),
          cpu: snapshot.cpu_percent,
          ram: snapshot.ram_percent,
          disk: snapshot.disk_percent,
          net_sent: snapshot.net_bytes_sent,
          net_recv: snapshot.net_bytes_recv,
        };

        setHistory((prev) => {
          const next = [...prev, point];
          return next.length > MAX_HISTORY ? next.slice(next.length - MAX_HISTORY) : next;
        });
      } catch {
        // Ignore malformed messages
      }
    };

    ws.onerror = () => {
      // onclose will fire immediately after; let it handle retry
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      setStatus('reconnecting');

      const delay = retryMsRef.current;
      retryMsRef.current = Math.min(delay * 2, MAX_RETRY_MS);

      retryTimerRef.current = setTimeout(() => {
        if (mountedRef.current) connect();
      }, delay);
    };
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    connect();

    return () => {
      mountedRef.current = false;
      if (retryTimerRef.current) clearTimeout(retryTimerRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { current, history, status };
}
