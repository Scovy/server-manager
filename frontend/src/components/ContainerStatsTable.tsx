/**
 * ContainerStatsTable — Displays memory and CPU usage for running containers.
 *
 * Uses the ContainerStat interface from the WebSocket stream.
 */

import type { ContainerStat } from '../types/metrics';
import './ContainerStatsTable.css';

interface ContainerStatsTableProps {
  containers: ContainerStat[];
}

export default function ContainerStatsTable({ containers }: ContainerStatsTableProps) {
  if (containers.length === 0) {
    return (
      <div className="card container-stats-empty">
        <p>No container stats available.</p>
        <p className="container-stats-sub">Is Docker Engine running and accessible?</p>
      </div>
    );
  }

  // Sort by highest CPU usage first
  const sorted = [...containers].sort((a, b) => b.cpu_percent - a.cpu_percent);

  return (
    <div className="card container-stats">
      <h3 className="container-stats__title">Docker Containers</h3>
      <div className="container-stats__table-wrap">
        <table className="container-stats__table">
          <thead>
            <tr>
              <th>Status</th>
              <th>Name</th>
              <th className="text-right">CPU %</th>
              <th className="text-right">Memory</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((c) => (
              <tr key={c.id}>
                <td>
                  <span
                    className={`status-dot status-dot--${c.status === 'running' ? 'ok' : 'stopped'}`}
                    title={c.status}
                  />
                </td>
                <td className="font-mono">{c.name}</td>
                <td className="text-right tabular-nums">
                  {c.cpu_percent.toFixed(1)}%
                </td>
                <td className="text-right tabular-nums text-muted">
                  {c.mem_usage_mb.toFixed(0)} MB
                  {c.mem_limit_mb > 0 && ` / ${c.mem_limit_mb.toFixed(0)} MB`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
