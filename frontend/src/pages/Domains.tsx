import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { fetchDomainsOverview, syncDomainRoutes } from '../api/domainsApi';
import type { DomainRouteStatus, DomainSslStatus } from '../types/domains';
import './Domains.css';

function getSslBadgeClass(status: DomainSslStatus): string {
  if (status === 'active') return 'badge-success';
  if (status === 'error') return 'badge-danger';
  if (status === 'disabled') return 'badge-info';
  return 'badge-warning';
}

function formatCertCell(route: DomainRouteStatus): string {
  if (!route.cert_expiry) return 'N/A';
  const date = new Date(route.cert_expiry);
  if (Number.isNaN(date.getTime())) return route.cert_expiry;

  const days = route.cert_days_remaining;
  const suffix = typeof days === 'number' ? ` (${days} days)` : '';
  return `${date.toLocaleDateString()}${suffix}`;
}

function formatDnsCell(route: DomainRouteStatus): string {
  if (route.dns_resolves === null) return 'Not checked';
  if (!route.dns_resolves) return 'Unresolved';
  if (route.resolved_ips.length === 0) return 'Resolved';
  return `Resolved: ${route.resolved_ips.join(', ')}`;
}

export default function Domains() {
  const [liveChecks, setLiveChecks] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState('');
  const [syncError, setSyncError] = useState('');

  const {
    data,
    isLoading,
    error,
    isRefetching,
    refetch,
  } = useQuery({
    queryKey: ['domains-overview', liveChecks],
    queryFn: () => fetchDomainsOverview(liveChecks),
  });

  const routes = data?.routes ?? [];
  const activeRoutes = routes.filter((route) => route.ssl_status === 'active').length;

  async function handleSyncRoutes() {
    setSyncError('');
    setSyncMessage('');
    setSyncing(true);
    try {
      const result = await syncDomainRoutes();
      setSyncMessage(result.message);
      await refetch();
    } catch (err) {
      setSyncError(err instanceof Error ? err.message : 'Failed to sync domain routes');
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div className="domains-page animate-fade-in">
      <div className="domains-page__header">
        <div>
          <h1 className="domains-page__title">Domains & SSL</h1>
          <p className="domains-page__subtitle">
            Inspect base domain setup, certificate health, and marketplace routes.
          </p>
        </div>
        <div className="domains-page__actions">
          <button
            className="btn btn-secondary"
            onClick={() => setLiveChecks((value) => !value)}
            disabled={isLoading || isRefetching}
          >
            {liveChecks ? 'Disable Live Checks' : 'Enable Live Checks'}
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => void refetch()}
            disabled={isLoading || isRefetching}
          >
            {isRefetching ? 'Refreshing...' : 'Refresh'}
          </button>
          <button className="btn btn-primary" onClick={() => void handleSyncRoutes()} disabled={syncing}>
            {syncing ? 'Syncing...' : 'Sync Caddy Routes'}
          </button>
        </div>
      </div>

      {error ? (
        <div className="domains-notice domains-notice--error">
          {error instanceof Error ? error.message : 'Failed to load domains'}
        </div>
      ) : null}
      {syncError ? <div className="domains-notice domains-notice--error">{syncError}</div> : null}
      {syncMessage ? <div className="domains-notice domains-notice--success">{syncMessage}</div> : null}

      {isLoading ? <div className="card">Loading domain configuration...</div> : null}

      {!isLoading && data ? (
        <>
          {!data.configured ? (
            <div className="card domains-not-configured">
              <h2>Domain setup not initialized</h2>
              <p>
                Complete first-time setup to configure base domain and HTTPS. Once configured,
                marketplace routes and SSL checks will appear here.
              </p>
            </div>
          ) : null}

          <section className="domains-summary-grid">
            <article className="card domains-summary-card">
              <h3>Base Domain</h3>
              <p className="domains-summary-card__value">{data.domain ?? 'Not configured'}</p>
            </article>

            <article className="card domains-summary-card">
              <h3>HTTPS Mode</h3>
              <p className="domains-summary-card__value">
                {data.https_enabled ? 'Enabled' : 'Disabled'}
              </p>
              <span className={`badge ${data.https_enabled ? 'badge-success' : 'badge-warning'}`}>
                {data.acme_staging ? 'ACME Staging' : 'ACME Production'}
              </span>
            </article>

            <article className="card domains-summary-card">
              <h3>ACME Email</h3>
              <p className="domains-summary-card__value">{data.acme_email ?? 'Not configured'}</p>
            </article>

            <article className="card domains-summary-card">
              <h3>Managed Routes</h3>
              <p className="domains-summary-card__value">{routes.length}</p>
              <p className="domains-summary-card__meta">{activeRoutes} certificates active</p>
            </article>
          </section>

          <section className="card domains-runtime">
            <h2>Caddy Runtime Files</h2>
            <div className="domains-runtime__grid">
              <div>
                <span>generated_globals.caddy</span>
                <span
                  className={`badge ${data.caddy_runtime.generated_globals_exists ? 'badge-success' : 'badge-danger'}`}
                >
                  {data.caddy_runtime.generated_globals_exists ? 'present' : 'missing'}
                </span>
              </div>
              <div>
                <span>generated_site.caddy</span>
                <span
                  className={`badge ${data.caddy_runtime.generated_site_exists ? 'badge-success' : 'badge-danger'}`}
                >
                  {data.caddy_runtime.generated_site_exists ? 'present' : 'missing'}
                </span>
              </div>
              <div>
                <span>marketplace_apps.caddy</span>
                <span
                  className={`badge ${data.caddy_runtime.marketplace_routes_exists ? 'badge-success' : 'badge-warning'}`}
                >
                  {data.caddy_runtime.marketplace_routes_exists ? 'present' : 'missing'}
                </span>
              </div>
              <div>
                <span>Marketplace route entries</span>
                <strong>{data.caddy_runtime.marketplace_route_count}</strong>
              </div>
            </div>
          </section>

          <section className="card domains-routes">
            <div className="domains-routes__header">
              <h2>Domain Routes</h2>
              <span className="badge badge-info">
                {liveChecks ? 'Live checks enabled' : 'Live checks disabled'}
              </span>
            </div>

            {routes.length === 0 ? (
              <p>No domain routes found yet.</p>
            ) : (
              <div className="domains-routes__table-wrap">
                <table className="domains-routes__table">
                  <thead>
                    <tr>
                      <th>Host</th>
                      <th>Source</th>
                      <th>Target</th>
                      <th>SSL</th>
                      <th>DNS</th>
                      <th>Certificate</th>
                      <th>Notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {routes.map((route) => (
                      <tr key={route.host}>
                        <td>
                          <a
                            href={`${data.https_enabled ? 'https' : 'http'}://${route.host}`}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {route.host}
                          </a>
                        </td>
                        <td>
                          <span className={`badge ${route.source === 'dashboard' ? 'badge-info' : 'badge-warning'}`}>
                            {route.source}
                          </span>
                        </td>
                        <td>{route.target}</td>
                        <td>
                          <span className={`badge ${getSslBadgeClass(route.ssl_status)}`}>
                            {route.ssl_status}
                          </span>
                        </td>
                        <td>{formatDnsCell(route)}</td>
                        <td>{formatCertCell(route)}</td>
                        <td className="domains-routes__notes">{route.check_message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}
