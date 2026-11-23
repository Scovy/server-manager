/**
 * Dashboard regressions:
 * - REST catch-up: history is re-fetched after every WS reconnect
 * - Container card: running/total + unhealthy/restarting chips, and the
 *   '—'/running-only fallbacks when the backend sends no container_summary
 * - Freshness badge: Fresh vs Stale from the sample's own time, ticking
 *   even while the stream is down
 */

import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const wsState = {
  current: null as import('../types/metrics').MetricsSnapshot | null,
  currentTs: null as number | null,
  history: [] as import('../metrics/metricsSeries').ChartPoint[],
  status: 'connecting' as 'connecting' | 'connected' | 'reconnecting' | 'error',
};

vi.mock('../hooks/useMetricsWS', () => ({
  useMetricsWS: () => wsState,
}));

const fetchHistory = vi.fn();
vi.mock('../api/metricsApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/metricsApi')>()),
  fetchMetricsHistory: (...args: Parameters<typeof fetchHistory>) => fetchHistory(...args),
}));

import Dashboard from '../pages/Dashboard';
import type { ContainerStat, MetricsSnapshot } from '../types/metrics';

function makeSnapshot(overrides: Partial<MetricsSnapshot> = {}): MetricsSnapshot {
  return {
    cpu_percent: 12.5,
    ram_percent: 50,
    ram_used_mb: 8192,
    ram_total_mb: 16384,
    disk_percent: 55.2,
    disk_used_gb: 110.5,
    disk_total_gb: 200,
    net_bytes_sent: 1_000,
    net_bytes_recv: 2_000,
    containers: [] as ContainerStat[],
    ...overrides,
  };
}

/** Mutate the mocked WS state and re-render the same Dashboard instance. */
function mountDashboard() {
  const view = render(<Dashboard />);
  return (next: {
    current?: MetricsSnapshot | null;
    currentTs?: number | null;
    status?: typeof wsState.status;
  }) => {
    Object.assign(wsState, next);
    view.rerender(<Dashboard />);
  };
}

beforeEach(() => {
  fetchHistory.mockReset();
  fetchHistory.mockResolvedValue([]);
  wsState.current = null;
  wsState.currentTs = null;
  wsState.history = [];
  wsState.status = 'connecting';
});

describe('REST catch-up on reconnect', () => {
  it('cold load once, skips the first connect, refetches after later reconnects', async () => {
    const update = mountDashboard();
    await waitFor(() => expect(fetchHistory).toHaveBeenCalledTimes(1)); // cold load

    update({ status: 'connected' }); // first connect: cold load already covers it
    update({ status: 'connected' }); // no transition
    await waitFor(() => expect(fetchHistory).toHaveBeenCalledTimes(1));

    update({ status: 'reconnecting' });
    update({ status: 'connected' });
    await waitFor(() => expect(fetchHistory).toHaveBeenCalledTimes(2));
    expect(fetchHistory).toHaveBeenCalledWith({ limit: 90 });
  });

  it('ignores a stale in-flight response that resolves after the dashboard settled', async () => {
    fetchHistory.mockImplementationOnce(
      () => new Promise((resolve) => setTimeout(() => resolve([]), 25)),
    );
    mountDashboard();
    await new Promise((resolve) => setTimeout(resolve, 40));
    expect(screen.getByText('System Overview')).toBeInTheDocument();
  });
});

describe('Container summary card', () => {
  it('shows running/total with unhealthy and restarting chips', () => {
    const update = mountDashboard();
    update({
      current: makeSnapshot({
        container_summary: { running: 2, total: 5, unhealthy: 1, restarting: 2 },
      }),
      currentTs: Date.now(),
    });

    expect(screen.getByText('2')).toBeInTheDocument(); // count, not a decimal
    expect(screen.getByText('2 of 5 running')).toBeInTheDocument();
    expect(screen.getByText('1 unhealthy')).toBeInTheDocument();
    expect(screen.getByText('2 restarting')).toBeInTheDocument();
  });

  it('falls back to a stats-count label when summary is missing', () => {
    const update = mountDashboard();
    update({
      current: makeSnapshot({
        containers: [
          { id: 'abc123def456', name: 'nginx', status: 'running', cpu_percent: 1, mem_usage_mb: 64, mem_limit_mb: 512 },
        ],
      }),
    });

    expect(screen.getByText('1')).toBeInTheDocument();
    expect(screen.getByText('reporting stats · summary unavailable')).toBeInTheDocument();
  });

  it('shows — (not 0) when no summary and no container stats arrive', () => {
    const update = mountDashboard();
    update({ current: makeSnapshot(), currentTs: Date.now() });
    expect(screen.getByText('summary unavailable')).toBeInTheDocument();
  });
});

describe('Current traffic readout (Network Throughput header)', () => {
  it('shows the newest live pair, never an old DB rate', () => {
    const update = mountDashboard();
    const t = Date.now();
    wsState.history = [
      { ts: t - 2_000, cpu: 1, ram: 1, net_sent: 1_000, net_recv: 2_000 },
      { ts: t - 1_000, cpu: 1, ram: 1, net_sent: 3_048, net_recv: 2_048 },
    ];
    update({ current: makeSnapshot(), currentTs: t - 1_000, status: 'connected' });

    expect(screen.getByText('↑ 2.0 KB/s')).toBeInTheDocument();
    expect(screen.getByText('↓ 48 B/s')).toBeInTheDocument();
  });

  it('renders — when the latest live pair is a counter reset', () => {
    const update = mountDashboard();
    const t = Date.now();
    wsState.history = [
      { ts: t - 2_000, cpu: 1, ram: 1, net_sent: 9_000, net_recv: 9_000 },
      { ts: t - 1_000, cpu: 1, ram: 1, net_sent: 100, net_recv: 200 },
    ];
    update({ current: makeSnapshot(), currentTs: t - 1_000, status: 'connected' });

    expect(screen.getByText('↑ —')).toBeInTheDocument();
    expect(screen.getByText('↓ —')).toBeInTheDocument();
  });

  it('renders — when the stream is stale or disconnected', () => {
    const update = mountDashboard();
    const t = Date.now();
    wsState.history = [
      { ts: t - 65_000, cpu: 1, ram: 1, net_sent: 0, net_recv: 0 },
      { ts: t - 64_000, cpu: 1, ram: 1, net_sent: 64_000, net_recv: 0 },
    ];
    update({ current: makeSnapshot(), currentTs: t - 64_000, status: 'connected' });
    expect(screen.getByText('↑ —')).toBeInTheDocument();

    update({ currentTs: t - 1_000, status: 'reconnecting' }); // fresh ts, dead socket
    expect(screen.getByText('↑ —')).toBeInTheDocument();
  });

  it('renders — before any live samples exist (cold load, REST only)', () => {
    const update = mountDashboard();
    update({ status: 'connected' });
    expect(screen.getByText('↑ —')).toBeInTheDocument();
  });
});

describe('Disk card', () => {
  it('uses the reported free space instead of computing total-used', () => {
    const update = mountDashboard();
    update({
      current: makeSnapshot({
        disk_used_gb: 110.5,
        disk_total_gb: 200,
        disk_free_gb: 45.3, // not 89.5 — FS reserve is not free
        disk_source: 'overlay',
      }),
      currentTs: Date.now(),
    });

    expect(screen.getByText('Backend filesystem (/) · overlay · 45 GB free')).toBeInTheDocument();
  });

  it('on older APIs without disk_free_gb shows used/total instead of a made-up free value', () => {
    const update = mountDashboard();
    update({
      current: makeSnapshot({ disk_used_gb: 110.5, disk_total_gb: 200, disk_free_gb: undefined }),
      currentTs: Date.now(),
    });

    expect(screen.getByText('Backend filesystem (/) · 111 / 200 GB')).toBeInTheDocument();
  });
});

describe('Freshness badge', () => {
  it('reads Fresh from a recent sample and Stale from an old one', () => {
    const update = mountDashboard();
    update({ current: makeSnapshot(), currentTs: Date.now() - 2_000 });
    expect(screen.getByText('Fresh')).toBeInTheDocument();
    expect(screen.getByText(/2 s old/)).toBeInTheDocument();

    update({ currentTs: Date.now() - 65_000 });
    expect(screen.getByText('Stale')).toBeInTheDocument();
    expect(screen.getByText(/65 s old/)).toBeInTheDocument();
  });

  it('keeps increasing the displayed age while the stream is down', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const update = mountDashboard();
      update({ current: makeSnapshot(), currentTs: Date.now() - 2_000 });
      expect(screen.getByText(/2 s old/)).toBeInTheDocument();

      update({ status: 'reconnecting' }); // stream drops — badge keeps ticking
      await vi.advanceTimersByTimeAsync(3_000);
      expect(screen.getByText(/5 s old/)).toBeInTheDocument();
      expect(screen.getByText('Fresh')).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});
