/**
 * Dashboard page — The main overview with live system metrics.
 *
 * Uses the `useMetricsWS` hook to connect to the backend and displays:
 * - 4 MetricCard components for current KPI values
 * - 4 MetricChart AreaCharts for the rolling history buffer
 * - ContainerStatsTable for running Docker container metrics
 * - AlertConfigPanel to configure threshold webhooks
 */

import { useEffect, useState } from 'react';
import { useMetricsWS } from '../hooks/useMetricsWS';
import { fetchMetricsHistory } from '../api/metricsApi';
import type { HistoryPoint } from '../types/metrics';

import MetricCard from '../components/MetricCard';
import MetricChart from '../components/MetricChart';
import ContainerStatsTable from '../components/ContainerStatsTable';
import AlertConfigPanel from '../components/AlertConfigPanel';
import './Dashboard.css';

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
    ...dbHistory.map((pt) => ({
      time: new Date(pt.timestamp).toLocaleTimeString(),
      cpu: pt.cpu_percent,
      ram: pt.ram_percent,
      disk: pt.disk_percent,
      net_sent: pt.net_bytes_sent,
      net_recv: pt.net_bytes_recv,
    })),
    ...wsHistory,
  ].slice(-60);

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
        <MetricCard
          icon="🌐"
          label="Network (Sent)"
          value={current ? current.net_bytes_sent / (1024 * 1024) : null}
          unit=" MB"
          warnThreshold={999999} // Never red
          dangerThreshold={999999}
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
          dataKey="ram"
          color="var(--color-accent)"
          unit="%"
          yMax={100}
        />
        <MetricChart
          title="Disk Space History"
          data={chartData}
          dataKey="disk"
          color="var(--color-warning)"
          unit="%"
          yMax={100}
        />
        <MetricChart
          title="Network Sent"
          data={chartData.map(d => ({ ...d, net_mb: d.net_sent / (1024 * 1024) }))}
          dataKey="net_mb"
          color="var(--color-success)"
          unit=" MB"
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
