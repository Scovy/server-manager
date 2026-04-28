/**
 * useMetricsWS — React hook for the /ws/metrics WebSocket stream.
 *
 * Connects to the backend WebSocket and pushes live MetricsSnapshot
 * data. Maintains a rolling history of the last 60 data points for
 * chart rendering.
 *
 * Features:
 *  - Auto-reconnects with exponential backoff (1 s → 2 s → 4 s … max 30 s)
 *  - Shares one socket across subscribers to avoid reconnect delays on route switches
 *  - Keeps the socket alive briefly after unmount so returning to Dashboard is instant
 *  - Exposes `status` so the UI can show a connection indicator
 *
 * @example
 * ```tsx
 * const { current, history, status } = useMetricsWS();
 * ```
 */

import { useEffect, useState } from 'react';
import type { MetricsSnapshot, WSStatus } from '../types/metrics';

export interface ChartPoint {
  ts: number;
  time: string;
  cpu: number;
  ram: number;
  ram_used_gb: number;
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
const IDLE_CLOSE_DELAY_MS = 60_000;

type MetricsState = UseMetricsWSResult;
type Listener = (state: MetricsState) => void;

const listeners = new Set<Listener>();
let ws: WebSocket | null = null;
let retryMs = INITIAL_RETRY_MS;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let idleCloseTimer: ReturnType<typeof setTimeout> | null = null;

let sharedCurrent: MetricsSnapshot | null = null;
let sharedHistory: ChartPoint[] = [];
let sharedStatus: WSStatus = 'connecting';

/** Build the WebSocket URL relative to the current page. */
function buildWsUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}/ws/metrics`;
}

function getState(): MetricsState {
  return {
    current: sharedCurrent,
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

function connectSocket(): void {
  clearIdleCloseTimer();
  clearReconnectTimer();

  if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) return;
  if (listeners.size === 0) return;

  const nextSocket = new WebSocket(buildWsUrl());
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
      const now = Date.now();

      const point: ChartPoint = {
        ts: now,
        time: new Date(now).toLocaleTimeString(),
        cpu: snapshot.cpu_percent,
        ram: snapshot.ram_percent,
        ram_used_gb: snapshot.ram_used_mb / 1024,
        disk: snapshot.disk_percent,
        net_sent: snapshot.net_bytes_sent,
        net_recv: snapshot.net_bytes_recv,
      };

      const nextHistory = [...sharedHistory, point];
      sharedHistory = nextHistory.length > MAX_HISTORY
        ? nextHistory.slice(nextHistory.length - MAX_HISTORY)
        : nextHistory;

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
