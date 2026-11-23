/**
 * useMetricsWS — React hook for the /ws/metrics WebSocket stream.
 *
 * Connects to the backend WebSocket and pushes live MetricsSnapshot
 * data. Maintains a rolling raw history of the last hour for chart
 * rendering (trimmed per append; see lib/metricsSeries).
 *
 * Features:
 *  - Auto-reconnects with exponential backoff (1 s → 2 s → 4 s … max 30 s)
 *  - Shares one socket across subscribers to avoid reconnect delays on route switches
 *  - Keeps the socket alive briefly after unmount so returning to Dashboard is instant
 *  - Samples carry the backend's own UTC timestamp with a receipt-time
 *    fallback for older backends that do not send one
 *  - Exposes `status` and the current sample's effective time
 *
 * @example
 * ```tsx
 * const { current, currentTs, history, status } = useMetricsWS();
 * ```
 */

import { useEffect, useState } from 'react';
import { openAdminSocket, SESSION_ENDED } from '../api/authApi';
import { parseMetricsTimestamp, trimToHour } from '../metrics/metricsSeries';
import type { ChartPoint } from '../metrics/metricsSeries';
import type { MetricsSnapshot, WSStatus } from '../types/metrics';

export type { ChartPoint };

interface UseMetricsWSResult {
  /** Latest metrics snapshot, or null if not yet received. */
  current: MetricsSnapshot | null;
  /** Effective sample time (epoch ms) of `current`: the backend timestamp
   * when provided, otherwise the client receive time. Null before the
   * first sample. */
  currentTs: number | null;
  /** Raw rolling one-hour history for chart rendering. */
  history: ChartPoint[];
  /** WebSocket connection status. */
  status: WSStatus;
}

const INITIAL_RETRY_MS = 1_000;
const MAX_RETRY_MS = 30_000;
const IDLE_CLOSE_DELAY_MS = 60_000;

type MetricsState = UseMetricsWSResult;
type Listener = (state: MetricsState) => void;

const listeners = new Set<Listener>();
let ws: WebSocket | null = null;
let connecting: AbortController | null = null;
let retryMs = INITIAL_RETRY_MS;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let idleCloseTimer: ReturnType<typeof setTimeout> | null = null;

let sharedCurrent: MetricsSnapshot | null = null;
let sharedCurrentTs: number | null = null;
let sharedHistory: ChartPoint[] = [];
let sharedStatus: WSStatus = 'connecting';

function getState(): MetricsState {
  return {
    current: sharedCurrent,
    currentTs: sharedCurrentTs,
    history: sharedHistory,
    status: sharedStatus,
  };
}

function notifyListeners(): void {
  const state = getState();
  listeners.forEach((listener) => listener(state));
}

function clearReconnectTimer(): void {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
}

function clearIdleCloseTimer(): void {
  if (idleCloseTimer) {
    clearTimeout(idleCloseTimer);
    idleCloseTimer = null;
  }
}

function closeSocket(): void {
  clearReconnectTimer();
  connecting?.abort();
  connecting = null;
  if (!ws) return;

  ws.onopen = null;
  ws.onmessage = null;
  ws.onerror = null;
  ws.onclose = null;
  ws.close();
  ws = null;
}

function scheduleReconnect(): void {
  if (listeners.size === 0) return;
  clearReconnectTimer();

  const delay = retryMs;
  retryMs = Math.min(delay * 2, MAX_RETRY_MS);
  sharedStatus = 'reconnecting';
  notifyListeners();

  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connectSocket();
  }, delay);
}

async function connectSocket(): Promise<void> {
  clearIdleCloseTimer();
  clearReconnectTimer();

  if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) return;
  if (listeners.size === 0 || connecting) return;

  const controller = new AbortController();
  connecting = controller;
  let nextSocket: WebSocket;
  try {
    nextSocket = await openAdminSocket('/ws/metrics', controller.signal);
  } catch {
    if (!controller.signal.aborted) scheduleReconnect();
    return;
  } finally {
    if (connecting === controller) connecting = null;
  }
  if (controller.signal.aborted) {
    nextSocket.close();
    return;
  }
  ws = nextSocket;
  sharedStatus = sharedCurrent ? 'reconnecting' : 'connecting';
  notifyListeners();

  nextSocket.onopen = () => {
    if (ws !== nextSocket) return;
    retryMs = INITIAL_RETRY_MS;
    sharedStatus = 'connected';
    notifyListeners();
  };

  nextSocket.onmessage = (event: MessageEvent) => {
    if (ws !== nextSocket) return;
    try {
      const snapshot = JSON.parse(event.data as string) as MetricsSnapshot;
      sharedCurrent = snapshot;
      // Older backends send no timestamp — fall back to receipt time.
      const sampleTs = parseMetricsTimestamp(snapshot.timestamp) ?? Date.now();
      sharedCurrentTs = sampleTs;

      const point: ChartPoint = {
        ts: sampleTs,
        cpu: snapshot.cpu_percent,
        ram: snapshot.ram_percent,
        net_sent: snapshot.net_bytes_sent,
        net_recv: snapshot.net_bytes_recv,
      };

      sharedHistory = trimToHour([...sharedHistory, point], sampleTs);

      notifyListeners();
    } catch {
      // Ignore malformed messages
    }
  };

  nextSocket.onerror = () => {
    // onclose will fire immediately after; let it handle retry
  };

  nextSocket.onclose = () => {
    if (ws !== nextSocket) return;
    ws = null;
    scheduleReconnect();
  };
}

function scheduleIdleClose(): void {
  if (listeners.size > 0) return;

  clearIdleCloseTimer();
  idleCloseTimer = setTimeout(() => {
    idleCloseTimer = null;
    if (listeners.size > 0) return;
    closeSocket();
    sharedStatus = 'connecting';
  }, IDLE_CLOSE_DELAY_MS);
}

window.addEventListener(SESSION_ENDED, () => {
  clearIdleCloseTimer();
  closeSocket();
  sharedHistory = [];
  sharedCurrent = null;
  sharedCurrentTs = null;
  sharedStatus = 'connecting';
  notifyListeners();
});

export function useMetricsWS(): UseMetricsWSResult {
  const [state, setState] = useState<MetricsState>(() => getState());

  useEffect(() => {
    const listener: Listener = (nextState) => setState(nextState);
    listeners.add(listener);
    connectSocket();

    return () => {
      listeners.delete(listener);
      scheduleIdleClose();
    };
  }, []);

  return state;
}
