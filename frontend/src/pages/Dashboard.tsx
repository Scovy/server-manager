import './Dashboard.css';

/**
 * Dashboard page — main system overview.
 *
 * Will display real-time system metrics (CPU, RAM, Disk, Network)
 * via WebSocket connection to /ws/metrics in Phase 2.
 */
export default function Dashboard() {
  return (
    <div className="dashboard">
      <div className="dashboard__header">
        <h1 className="dashboard__title">Dashboard</h1>
        <p className="dashboard__subtitle">System overview and real-time metrics</p>
      </div>

      {/* Placeholder metric cards */}
      <div className="dashboard__grid">
        <div className="card dashboard__metric">
          <div className="dashboard__metric-icon">🖥️</div>
          <div className="dashboard__metric-info">
            <span className="dashboard__metric-label">CPU Usage</span>
            <span className="dashboard__metric-value">—</span>
          </div>
          <span className="badge badge-info">Phase 2</span>
        </div>

        <div className="card dashboard__metric">
          <div className="dashboard__metric-icon">🧠</div>
          <div className="dashboard__metric-info">
            <span className="dashboard__metric-label">Memory</span>
            <span className="dashboard__metric-value">—</span>
          </div>
          <span className="badge badge-info">Phase 2</span>
        </div>

        <div className="card dashboard__metric">
          <div className="dashboard__metric-icon">💿</div>
          <div className="dashboard__metric-info">
            <span className="dashboard__metric-label">Disk Usage</span>
            <span className="dashboard__metric-value">—</span>
          </div>
          <span className="badge badge-info">Phase 2</span>
        </div>

        <div className="card dashboard__metric">
          <div className="dashboard__metric-icon">🌐</div>
          <div className="dashboard__metric-info">
            <span className="dashboard__metric-label">Network</span>
            <span className="dashboard__metric-value">—</span>
          </div>
          <span className="badge badge-info">Phase 2</span>
        </div>
      </div>

      {/* Status section */}
      <div className="card dashboard__status">
        <h2>System Status</h2>
        <p className="dashboard__status-msg">
          📡 Real-time metrics will be available after Phase 2 implementation.
          <br />
          The WebSocket connection to <code>/ws/metrics</code> will push updates every 2 seconds.
        </p>
      </div>
    </div>
  );
}
