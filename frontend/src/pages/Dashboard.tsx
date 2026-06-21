/**
 * Dashboard page — The main overview with live system metrics.
 *
 * Uses the `useMetricsWS` hook to connect to the backend and displays:
 * - 3 MetricCard components for current KPI values
 * - 4 charts for the rolling history buffer
 * - ContainerStatsTable for running Docker container metrics
 * - AlertConfigPanel to configure threshold webhooks
 */

import { useEffect, useState } from 'react';
import { useMetricsWS } from '../hooks/useMetricsWS';
import type { ChartPoint } from '../hooks/useMetricsWS';
import { fetchMetricsHistory } from '../api/metricsApi';
import type { HistoryPoint } from '../types/metrics';

import MetricCard from '../components/MetricCard';
import MetricChart from '../components/MetricChart';
import NetworkChart from '../components/NetworkChart';
import ContainerStatsTable from '../components/ContainerStatsTable';
import AlertConfigPanel from '../components/AlertConfigPanel';
import './Dashboard.css';

const MEGABYTE = 1024 * 1024;

function mapHistoryPoint(pt: HistoryPoint): ChartPoint {
  const ts = new Date(pt.timestamp).getTime();
  return {
    ts,
    time: new Date(ts).toLocaleTimeString(),
    cpu: pt.cpu_percent,
    ram: pt.ram_percent,
    ram_used_gb: pt.ram_used_mb / 1024,
    disk: pt.disk_percent,
    net_sent: pt.net_bytes_sent,
    net_recv: pt.net_bytes_recv,
  };
}

function toNetworkThroughput(points: ChartPoint[]): Array<{
  time: string;
  sent_rate_mb_s: number;
  recv_rate_mb_s: number;
}> {
  return points.map((point, index) => {
    if (index === 0) {
      return { time: point.time, sent_rate_mb_s: 0, recv_rate_mb_s: 0 };
    }

    const prev = points[index - 1];
    const dtSeconds = Math.max((point.ts - prev.ts) / 1000, 1);
    const sentDelta = Math.max(0, point.net_sent - prev.net_sent);
    const recvDelta = Math.max(0, point.net_recv - prev.net_recv);

    return {
      time: point.time,
      sent_rate_mb_s: sentDelta / MEGABYTE / dtSeconds,
      recv_rate_mb_s: recvDelta / MEGABYTE / dtSeconds,
    };
  });
}

export default function Dashboard() {
  const { current, history: wsHistory, status } = useMetricsWS();
  const [dbHistory, setDbHistory] = useState<HistoryPoint[]>([]);

  // Fetch initial history on mount so charts aren't empty while WS populates
  useEffect(() => {
    fetchMetricsHistory({ limit: 60 })
      .then((data) => setDbHistory(data))
      .catch((err) => console.warn('Failed to fetch initial history:', err));
  }, []);

  // Merge DB history with live WS history
  // In a production app you'd deduplicate these based on timestamp,
  // but for the MVP simply concatenating or using WS history if available is fine.
  const chartData = wsHistory.length > 5 ? wsHistory : [
    ...dbHistory.map(mapHistoryPoint),
    ...wsHistory,
  ].slice(-60);
  const networkData = toNetworkThroughput(chartData);

  // Connection badge styling
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
          <p className="dashboard__subtitle">Live metrics and container status</p>
        </div>
        <div className="dashboard__status">
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
            current ? `${current.ram_used_mb} / ${current.ram_total_mb} MB` : undefined
          }
          warnThreshold={85}
          dangerThreshold={95}
        />
        <MetricCard
          icon="💿"
          label="Disk Usage"
          value={current?.disk_percent ?? null}
          subtitle={
            current ? `${current.disk_used_gb.toFixed(0)} / ${current.disk_total_gb.toFixed(0)} GB` : undefined
          }
          warnThreshold={85}
          dangerThreshold={95}
        />
      </div>

      {/* ── Metric Charts ─────────────────────────────────────────────────── */}
      <div className="dashboard__charts">
        <MetricChart
          title="CPU Usage History"
          data={chartData}
          dataKey="cpu"
          color="var(--color-info)"
          unit="%"
          yMax={100}
        />
        <MetricChart
          title="Memory History"
          data={chartData}
          dataKey="ram_used_gb"
          color="var(--color-accent)"
          unit=" GB"
        />
        <MetricChart
          title="Disk Space History"
          data={chartData}
          dataKey="disk"
          color="var(--color-warning)"
          unit="%"
          yMax={100}
        />
        <NetworkChart title="Network Throughput" data={networkData} />
      </div>

      {/* ── Container Stats & Settings ────────────────────────────────────── */}
      <div className="dashboard__bottom">
        <ContainerStatsTable containers={current?.containers || []} />
        <AlertConfigPanel />
      </div>
    </div>
  );
}
