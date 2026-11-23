/**
 * TypeScript types for the metrics system.
 *
 * These interfaces mirror the Pydantic schemas returned by:
 * - `/ws/metrics`         (MetricsSnapshot + ContainerStat[])
 * - `/api/metrics/history` (HistoryPoint[])
 * - `/api/metrics/alerts`  (AlertConfig)
 */

/** Counts derived from `docker ps` at snapshot time. */
export interface ContainerSummary {
  /** Containers currently running. */
  running: number;
  /** All containers regardless of state. */
  total: number;
  /** Containers whose health check reports unhealthy. */
  unhealthy: number;
  /** Containers in a restart loop. */
  restarting: number;
}

/** Resource usage stats for a single running container. */
export interface ContainerStat {
  /** Short container ID (first 12 chars). */
  id: string;
  /** Container name without leading slash. */
  name: string;
  /** Container status: "running" | "exited" | "paused" | … */
  status: string;
  /** CPU usage as a percentage of one core (may exceed 100% on multi-core). */
  cpu_percent: number;
  /** Memory consumed in MB. */
  mem_usage_mb: number;
  /** Memory limit in MB (0 = no limit / host RAM). */
  mem_limit_mb: number;
}

/** Point-in-time snapshot pushed over the WebSocket every 2 seconds. */
export interface MetricsSnapshot {
  cpu_percent: number;
  ram_percent: number;
  /** RAM used in megabytes. */
  ram_used_mb: number;
  /** Total RAM in megabytes. */
  ram_total_mb: number;
  disk_percent: number;
  /** Disk space used in gigabytes. */
  disk_used_gb: number;
  /** Total disk space in gigabytes. */
  disk_total_gb: number;
  /**
   * Free disk space in gigabytes from the filesystem's own `free` counter
   * (less than total-used: part of that is filesystem-level reserve).
   * Older backends don't send it — do not compute it from used/total.
   */
  disk_free_gb?: number | null;
  /**
   * Optional device/filesystem source of the reported usage (e.g. the
   * mount's device name such as "overlay"). Null when unknown.
   */
  disk_source?: string | null;
  /** Cumulative bytes sent since boot. */
  net_bytes_sent: number;
  /** Cumulative bytes received since boot. */
  net_bytes_recv: number;
  /** Per-container stats. Empty if Docker is unavailable. */
  containers: ContainerStat[];
  /**
   * ISO 8601 UTC timestamp (…Z) set by newer backends.
   * Older backends omit it — clients fall back to their own receive time.
   */
  timestamp?: string;
  /**
   * Summary counts from `docker ps`. Null when Docker (or an older
   * backend without the field) cannot provide them.
   */
  container_summary?: ContainerSummary | null;
}

/**
 * A single row from the metrics_history table.
 * Used to populate historical charts on first load.
 */
export interface HistoryPoint {
  id: number;
  /** ISO 8601 timestamp string. */
  timestamp: string;
  cpu_percent: number;
  ram_percent: number;
  ram_used_mb: number;
  disk_percent: number;
  net_bytes_sent: number;
  net_bytes_recv: number;
}

/** Alert threshold configuration stored in the settings table. */
export interface AlertConfig {
  /** CPU usage % that triggers an alert (0–100). */
  cpu_threshold: number;
  /** RAM usage % that triggers an alert (0–100). */
  ram_threshold: number;
  /** Disk usage % that triggers an alert (0–100). */
  disk_threshold: number;
  /** Discord or generic webhook URL. Empty string = alerts disabled. */
  webhook_url: string;
}

/** WebSocket connection status exposed by useMetricsWS. */
export type WSStatus = 'connecting' | 'connected' | 'reconnecting' | 'error';
