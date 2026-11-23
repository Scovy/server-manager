/**
 * Dashboard page — The main overview with live system metrics.
 *
 * Uses the `useMetricsWS` hook for the live stream and the metrics
 * history REST endpoint for cold load and reconnect catch-up. Both merge
 * chronologically into the exact rolling hour [now − 1 h, now] ("Last
 * hour") which the charts render on a real numeric time axis.
 *
 * - MetricCards for current KPI values (CPU, RAM, disk incl. native
 *   meter, containers incl. unhealthy/restarting chips)
 * - CPU/RAM (%) and network (TX/RX throughput) history charts, each a
 *   per-minute peak series
 * - ContainerStatsTable for running Docker container metrics
 * - AlertConfigPanel to configure threshold webhooks
 * - FreshnessBadge tracking the age of the newest real sample
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useMetricsWS } from '../hooks/useMetricsWS';
import {
  bucketValueByMinute,
  hourWindow,
  inWindow,
  LIVE_MAX_DT_MS,
  latestRate,
  mergeNetworkBuckets,
  mergeSeries,
  parseMetricsTimestamp,
  REST_MAX_DT_MS,
  STALE_AFTER_MS,
  toNetworkRates,
} from '../metrics/metricsSeries';
import type { ChartPoint } from '../metrics/metricsSeries';
import { fetchMetricsHistory } from '../api/metricsApi';
import type { HistoryPoint, MetricsSnapshot, WSStatus } from '../types/metrics';

import MetricCard from '../components/MetricCard';
import MetricChart from '../components/MetricChart';
import NetworkChart from '../components/NetworkChart';
import ContainerStatsTable from '../components/ContainerStatsTable';
import AlertConfigPanel from '../components/AlertConfigPanel';
import FreshnessBadge from '../components/FreshnessBadge';
import { useNow } from '../hooks/useNow';
import './Dashboard.css';

/** 60 s storage cadence — 90 rows comfortably cover the hour window. */
const HISTORY_LIMIT = 90;

function mapHistoryPoint(pt: HistoryPoint): ChartPoint | null {
  const ts = parseMetricsTimestamp(pt.timestamp);
  if (ts === null) return null;
  return {
    ts,
    cpu: pt.cpu_percent,
    ram: pt.ram_percent,
    net_sent: pt.net_bytes_sent,
    net_recv: pt.net_bytes_recv,
  };
}

/** Disk card subtitle. Free space comes from the filesystem's own
 * counter — never computed as total-used (that overstates it by the
 * filesystem reserve). Older backends without the field get used/total. */
function diskSubtitle(snapshot: MetricsSnapshot | null): string {
  const name = 'Backend filesystem (/)';
  if (!snapshot) return name;
  const parts = [name];
  if (snapshot.disk_source) parts.push(snapshot.disk_source);
  if (snapshot.disk_free_gb != null) {
    parts.push(`${snapshot.disk_free_gb.toFixed(0)} GB free`);
  } else {
    parts.push(`${snapshot.disk_used_gb.toFixed(0)} / ${snapshot.disk_total_gb.toFixed(0)} GB`);
  }
  return parts.join(' · ');
}

/** Containers KPI card. `containers` from older backends may list paused
 * or restarting containers too, so a missing summary is never claimed as
 * a running count unless stats actually report. */
function ContainersCard({ snapshot }: { snapshot: MetricsSnapshot | null }) {
  const summary = snapshot?.container_summary ?? null;
  const reporting = snapshot && snapshot.containers.length > 0 && !summary
    ? snapshot.containers.length
    : null;

  let value: number | null;
  let subtitle: string;
  if (summary) {
    value = summary.running;
    subtitle = `${summary.running} of ${summary.total} running`;
  } else if (reporting !== null) {
    value = reporting;
    subtitle = 'reporting stats · summary unavailable';
  } else {
    value = null;
    subtitle = 'summary unavailable';
  }

  const below: ReactNode = summary ? (
    <>
      {summary.unhealthy > 0 && (
        <span className="chip chip--danger">{summary.unhealthy} unhealthy</span>
      )}
      {summary.restarting > 0 && (
        <span className="chip chip--warning">{summary.restarting} restarting</span>
      )}
    </>
  ) : null;

  return (
    <MetricCard
      icon="🐳"
      label="Containers"
      value={value}
      unit=""
      subtitle={subtitle}
      below={below}
    />
  );
}

export default function Dashboard() {
  const { current, currentTs, history: wsHistory, status } = useMetricsWS();
  const [dbHistory, setDbHistory] = useState<ChartPoint[]>([]);

  const loadSeq = useRef(0);
  const loadHistory = useCallback(() => {
    const seq = ++loadSeq.current;
    fetchMetricsHistory({ limit: HISTORY_LIMIT })
      .then((rows) => {
        // a newer request superseded this response — keep the newer history
        if (loadSeq.current !== seq) return;
        setDbHistory(rows.map(mapHistoryPoint).filter((p): p is ChartPoint => p !== null));
      })
      .catch((err) => console.warn('Failed to fetch metrics history:', err));
  }, []);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  // Catch-up only after a lost connection ('reconnecting' → 'connected');
  // the initial connect is already covered by the cold load above.
  const prevStatus = useRef<WSStatus | null>(null);
  useEffect(() => {
    const before = prevStatus.current;
    prevStatus.current = status;
    if (status === 'connected' && before === 'reconnecting') loadHistory();
  }, [status, loadHistory]);

  const now = useNow(1_000);

  // Current traffic: only fresh live samples count — a reset, a stream
  // gap or a stale/disconnected WS yields '—', never an old DB rate.
  const lastLive = useMemo(() => latestRate(wsHistory, LIVE_MAX_DT_MS), [wsHistory]);
  const liveOk = status === 'connected' && currentTs !== null && now - currentTs <= STALE_AFTER_MS;
  const currentRx = liveOk ? lastLive?.recv_rate ?? null : null;
  const currentTx = liveOk ? lastLive?.sent_rate ?? null : null;

  // Exact [now−1h, now] window; boundary rows filtered by real ts.
  const window1h = useMemo(() => hourWindow(now), [now]);
  const restWindow = useMemo(() => inWindow(dbHistory, window1h), [dbHistory, window1h]);
  const liveWindow = useMemo(() => inWindow(wsHistory, window1h), [wsHistory, window1h]);
  const mergedWindow = useMemo(() => mergeSeries(restWindow, liveWindow), [restWindow, liveWindow]);

  const cpuSeries = useMemo(
    () => bucketValueByMinute(mergedWindow.map((p) => ({ ts: p.ts, value: p.cpu })), window1h.bucketStarts),
    [mergedWindow, window1h],
  );
  const ramSeries = useMemo(
    () => bucketValueByMinute(mergedWindow.map((p) => ({ ts: p.ts, value: p.ram })), window1h.bucketStarts),
    [mergedWindow, window1h],
  );

  // Rates per source only — never across a REST/WS boundary. Live wins
  // where it has continuous coverage; REST backfills the rest.
  const liveRates = useMemo(() => toNetworkRates(liveWindow, LIVE_MAX_DT_MS), [liveWindow]);
  const restRates = useMemo(() => toNetworkRates(restWindow, REST_MAX_DT_MS), [restWindow]);
  const networkSeries = useMemo(
    () => mergeNetworkBuckets(liveRates, restRates, window1h.bucketStarts),
    [liveRates, restRates, window1h],
  );

  const xDomain: [number, number] = [window1h.start, window1h.end];
  const ticks = window1h.ticks;

  let badgeClass = 'badge-warning';
  let badgeText = 'Connecting...';
  if (status === 'connected') {
    badgeClass = 'badge-success';
    badgeText = 'Connected';
  } else if (status === 'reconnecting') {
    badgeClass = 'badge-danger';
    badgeText = 'Reconnecting...';
  }

  return (
    <div className="dashboard animate-fade-in">
      {/* ── Header ────────────────────────────────────────────────────────── */}
      <div className="dashboard__header">
        <div>
          <h1 className="dashboard__title">System Overview</h1>
          <p className="dashboard__subtitle">Live metrics and container status · Last hour</p>
        </div>
        <div className="dashboard__status">
          <FreshnessBadge sampleTs={currentTs} />
          <span className={`badge ${badgeClass} status-indicator`}>
            <span className="status-indicator__dot" />
            {badgeText}
          </span>
        </div>
      </div>

      {/* ── KPI Cards ─────────────────────────────────────────────────────── */}
      <div className="dashboard__cards">
        <MetricCard
          icon="🖥️"
          label="CPU Usage"
          value={current?.cpu_percent ?? null}
          warnThreshold={80}
          dangerThreshold={95}
        />
        <MetricCard
          icon="🧠"
          label="Memory"
          value={current?.ram_percent ?? null}
          subtitle={
            current
              ? `${(current.ram_used_mb / 1024).toFixed(1)} / ${(current.ram_total_mb / 1024).toFixed(1)} GB`
              : undefined
          }
          warnThreshold={85}
          dangerThreshold={95}
        />
        <MetricCard
          icon="💾"
          label="Disk Usage"
          value={current?.disk_percent ?? null}
          subtitle={diskSubtitle(current)}
          meterPercent={current?.disk_percent ?? null}
          warnThreshold={85}
          dangerThreshold={95}
        />
        <ContainersCard snapshot={current} />
      </div>

      {/* ── Metric Charts ─────────────────────────────────────────────────── */}
      <div className="dashboard__charts">
        <MetricChart
          title="CPU Usage History"
          data={cpuSeries}
          color="var(--color-info)"
          unit="%"
          xDomain={xDomain}
          ticks={ticks}
        />
        <MetricChart
          title="Memory History"
          data={ramSeries}
          color="var(--color-accent)"
          unit="%"
          xDomain={xDomain}
          ticks={ticks}
        />
        <NetworkChart
          title="Network Throughput"
          data={networkSeries}
          currentRx={currentRx}
          currentTx={currentTx}
          xDomain={xDomain}
          ticks={ticks}
        />
      </div>

      {/* ── Container Stats & Settings ────────────────────────────────────── */}
      <div className="dashboard__bottom">
        <ContainerStatsTable containers={current?.containers || []} />
        <AlertConfigPanel />
      </div>
    </div>
  );
}
