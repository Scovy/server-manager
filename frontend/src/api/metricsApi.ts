/**
 * API client functions for metrics endpoints.
 *
 * All functions use the native fetch API so they can be used inside
 * TanStack Query hooks or standalone async calls.
 *
 * Endpoints consumed:
 *     GET  /api/metrics/history  — historical snapshots
 *     GET  /api/metrics/alerts   — alert threshold configuration
 *     PUT  /api/metrics/alerts   — update thresholds
 */

import { authenticatedFetch } from './authApi';
import type { AlertConfig, HistoryPoint } from '../types/metrics';

const BASE = '/api';

/**
 * Fetch historical metrics from the database.
 *
 * The backend stores a sample every 60 s and returns the latest `limit`
 * rows sorted ascending (newer backends tag them as UTC; the caller
 * normalizes legacy naive timestamps as UTC as well).
 *
 * @param from - Optional ISO 8601 start timestamp.
 * @param to   - Optional ISO 8601 end timestamp.
 * @param limit - Maximum rows to return (default 500).
 * @returns Array of HistoryPoint sorted ascending.
 */
export async function fetchMetricsHistory(params?: {
  from?: string;
  to?: string;
  limit?: number;
}): Promise<HistoryPoint[]> {
  const url = new URL(`${BASE}/metrics/history`, window.location.origin);
  if (params?.from) url.searchParams.set('from', params.from);
  if (params?.to) url.searchParams.set('to', params.to);
  if (params?.limit) url.searchParams.set('limit', String(params.limit));

  const res = await authenticatedFetch(url.toString());
  if (!res.ok) throw new Error(`Failed to fetch metrics history: ${res.statusText}`);
  return res.json() as Promise<HistoryPoint[]>;
}

/**
 * Fetch the current alert threshold configuration.
 *
 * @returns AlertConfig with threshold percentages and optional webhook URL.
 */
export async function fetchAlertConfig(): Promise<AlertConfig> {
  const res = await authenticatedFetch(`${BASE}/metrics/alerts`);
  if (!res.ok) throw new Error(`Failed to fetch alert config: ${res.statusText}`);
  return res.json() as Promise<AlertConfig>;
}

/**
 * Update alert threshold configuration.
 *
 * @param config - Partial or full AlertConfig to merge with existing config.
 * @returns The updated AlertConfig as persisted by the backend.
 */
export async function updateAlertConfig(config: Partial<AlertConfig>): Promise<AlertConfig> {
  const res = await authenticatedFetch(`${BASE}/metrics/alerts`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
  if (!res.ok) throw new Error(`Failed to update alert config: ${res.statusText}`);
  return res.json() as Promise<AlertConfig>;
}
