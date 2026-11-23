import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import CodeMirror from '@uiw/react-codemirror';
import { yaml as yamlLang } from '@codemirror/lang-yaml';
import { parseDocument } from 'yaml';
import { EventSource } from 'eventsource';
import { authenticatedFetch } from '../api/authApi';
import {
  fetchCompose,
  fetchContainer,
  fetchContainers,
  fetchContainerStats,
  fetchEnvText,
  removeContainer,
  runContainerAction,
  applyContainerChanges,
  updateCompose,
  updateEnvText,
} from '../api/containersApi';
import { fetchInstalledApps } from '../api/marketplaceApi';
import type { ContainerDetail, ContainerItem, ContainerStats } from '../types/containers';
import type { InstalledApp } from '../types/marketplace';
import ExecTerminal from '../components/ExecTerminal';
import './Containers.css';

type ContainerAction = 'start' | 'stop' | 'restart' | 'kill';

interface EnvRow {
  id: string;
  key: string;
  value: string;
  isSecret: boolean;
  masked: boolean;
}

const SECRET_KEY_PATTERN = /(pass|secret|token|key|pwd|auth|credential|private)/i;

function createRowId(): string {
  return `${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
}

function isSecretKey(key: string): boolean {
  return SECRET_KEY_PATTERN.test(key.trim());
}

function parseEnvRows(content: string): EnvRow[] {
  return content
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0 && !line.startsWith('#') && line.includes('='))
    .map((line) => {
      const index = line.indexOf('=');
      const key = line.slice(0, index).trim();
      const value = line.slice(index + 1);
      const secret = isSecretKey(key);
      return {
        id: createRowId(),
        key,
        value,
        isSecret: secret,
        masked: secret,
      };
    });
}

function envRowsToText(rows: EnvRow[]): string {
  if (rows.length === 0) {
    return '';
  }
  const lines = rows
    .map((row) => `${row.key.trim()}=${row.value}`)
    .filter((line) => !line.startsWith('='));
  return lines.join('\n') + '\n';
}

function statusBadgeClass(status: string): string {
  if (status === 'running') return 'badge-success';
  if (status === 'paused' || status === 'restarting') return 'badge-warning';
  return 'badge-danger';
}

// Backend errors can embed raw Docker internals (local socket/npipe URLs);
// those never belong in the UI, only in the browser console.
function sanitizeDetail(detail: string): string {
  const withoutUrls = detail
    .replace(/\b(?:https?|http\+docker|unix|docker|ws|tcp):\/\/\S+/gi, '(see server logs)')
    .trim();
  return withoutUrls.length > 140 ? `${withoutUrls.slice(0, 137)}…` : withoutUrls;
}

interface LoadError {
  title: string;
  body: string;
}

// Only the backend's explicit "Docker unavailable" detail claims Docker is
// down; offline/network noise gets the generic title. payload.detail is never
// shown verbatim (it can embed local socket URLs).
function toLoadError(err: unknown): LoadError {
  const raw = err instanceof Error ? err.message : String(err);
  if (/docker unavailable/i.test(raw)) {
    return {
      title: 'Docker unavailable',
      body: 'The server could not reach the Docker daemon. Check that Docker is running on the server, then try again.',
    };
  }
  return {
    title: 'Could not load containers',
    body: 'The request failed before any container data came back. Try again in a moment.',
  };
}

function resolveContainerUrl(
  container: ContainerDetail | null,
  appUrlsByContainer: Record<string, string>,
): string | null {
  if (!container) return null;

  const normalizedName = container.name.startsWith('/') ? container.name.slice(1) : container.name;
  const marketplaceUrl = appUrlsByContainer[normalizedName];
  if (marketplaceUrl) {
    return marketplaceUrl;
  }

  const preferredContainerPorts = [80, 8080, 3000, 8096, 9000, 5000];
  const candidates: Array<{ containerPort: number; hostPort: number; hostIp: string }> = [];
  const ports = container.ports as Record<string, unknown>;

  for (const [containerSpec, binding] of Object.entries(ports)) {
    if (!Array.isArray(binding) || binding.length === 0) continue;

    const [containerPortRaw] = containerSpec.split('/');
    const containerPort = Number(containerPortRaw);
    if (!Number.isInteger(containerPort)) continue;

    for (const item of binding) {
      if (!item || typeof item !== 'object') continue;
      const hostPortRaw = (item as { HostPort?: string }).HostPort;
      const hostIpRaw = (item as { HostIp?: string }).HostIp;
      const hostPort = Number(hostPortRaw);
      if (!Number.isInteger(hostPort)) continue;
      candidates.push({
        containerPort,
        hostPort,
        hostIp: hostIpRaw || '',
      });
    }
  }

  if (candidates.length === 0) return null;

  candidates.sort((a, b) => {
    const aIndex = preferredContainerPorts.indexOf(a.containerPort);
    const bIndex = preferredContainerPorts.indexOf(b.containerPort);
    const aScore = aIndex === -1 ? 999 : aIndex;
    const bScore = bIndex === -1 ? 999 : bIndex;
    if (aScore !== bScore) return aScore - bScore;
    return a.hostPort - b.hostPort;
  });

  const selected = candidates[0];
  const host =
    selected.hostIp && selected.hostIp !== '0.0.0.0' && selected.hostIp !== '::'
      ? selected.hostIp
      : window.location.hostname;

  return `http://${host}:${selected.hostPort}`;
}

export default function Containers() {
  const [containers, setContainers] = useState<ContainerItem[]>([]);
  const [selectedId, setSelectedId] = useState<string>('');
  const [selected, setSelected] = useState<ContainerDetail | null>(null);
  const [stats, setStats] = useState<ContainerStats | null>(null);
  const [logs, setLogs] = useState<string>('');
  const [logsError, setLogsError] = useState<string>('');
  const [composeText, setComposeText] = useState<string>('');
  const [composePath, setComposePath] = useState<string>('');
  const [envRows, setEnvRows] = useState<EnvRow[]>([]);
  const [includeStopped, setIncludeStopped] = useState<boolean>(true);
  const [appUrlsByContainer, setAppUrlsByContainer] = useState<Record<string, string>>({});
  const [hasLoaded, setHasLoaded] = useState<boolean>(false);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [loadError, setLoadError] = useState<LoadError | null>(null);
  const [detailsLoading, setDetailsLoading] = useState<boolean>(false);
  const [recoveryNotice, setRecoveryNotice] = useState<string>('');
  const [search, setSearch] = useState<string>('');
  const [error, setError] = useState<string>('');
  const [message, setMessage] = useState<string>('');
  const selectedIdRef = useRef<string>('');
  const loadSeqRef = useRef<number>(0);

  const visibleContainers = useMemo(() => {
    const sorted = [...containers].sort((a, b) => a.name.localeCompare(b.name));
    const query = search.trim().toLowerCase();
    if (!query) return sorted;
    return sorted.filter(
      (container) =>
        container.name.toLowerCase().includes(query) ||
        container.image.toLowerCase().includes(query),
    );
  }, [containers, search]);
  const openAppUrl = useMemo(
    () => resolveContainerUrl(selected, appUrlsByContainer),
    [selected, appUrlsByContainer],
  );

  useEffect(() => {
    selectedIdRef.current = selectedId;
  }, [selectedId]);

  // Deliberately independent of selectedId: selecting a container must never
  // re-run the list fetch (that caused reload loops on missing selections).
  const loadContainers = useCallback(async () => {
    const seq = ++loadSeqRef.current;
    setRefreshing(true);
    try {
      const data = await fetchContainers(includeStopped);
      if (seq !== loadSeqRef.current) return; // a newer request already superseded this one
      // Publish the list immediately; the optional app-URL map must not delay it.
      setContainers(data);
      setHasLoaded(true);
      setLoadError(null);
      const preferredId = selectedIdRef.current;
      const preferredExists = preferredId
        ? data.some((container) => container.id === preferredId)
        : false;
      setSelectedId(preferredExists ? preferredId : data[0]?.id || '');

      void fetchInstalledApps()
        .then((installedApps) => {
          if (seq !== loadSeqRef.current) return;
          setAppUrlsByContainer(
            installedApps.reduce<Record<string, string>>((acc, app: InstalledApp) => {
              if (app.app_url) {
                acc[app.container_name] = app.app_url;
                acc[app.app_name] = app.app_url;
              }
              return acc;
            }, {}),
          );
        })
        .catch(() => {
          // Keep the previous app-URL mapping; it is not worth failing over.
        });
    } catch (err) {
      if (seq !== loadSeqRef.current) return;
      // Fixed log line only: raw errors can carry URLs or auth material.
      console.error('Failed to load containers');
      // Keep the last good list; the banner marks it as possibly out of date.
      setLoadError(toLoadError(err));
    } finally {
      if (seq === loadSeqRef.current) setRefreshing(false);
    }
  }, [includeStopped]);

  useEffect(() => {
    void loadContainers();
  }, [loadContainers]);

  useEffect(() => {
    // Drop the previous container's detail state immediately so name/stats/
    // compose/env/logs can never mix two different containers, and clear the
    // notices that belonged to the old selection. The 404-recovery notice uses
    // its own channel (recoveryNotice) so navigation doesn't erase it.
    setSelected(null);
    setStats(null);
    setLogs('');
    setLogsError('');
    setComposeText('');
    setComposePath('');
    setEnvRows([]);
    setMessage('');
    setError('');

    if (!selectedId) {
      setDetailsLoading(false);
      return;
    }

    setDetailsLoading(true);

    let cancelled = false;
    let recoveredMissingContainer = false;

    const loadDetails = async () => {
      try {
        const [containerData, statData] = await Promise.all([
          fetchContainer(selectedId),
          fetchContainerStats(selectedId),
        ]);
        if (cancelled) return;
        setSelected(containerData);
        setStats(statData);

        try {
          const compose = await fetchCompose(selectedId);
          if (!cancelled) {
            setComposePath(compose.path);
            setComposeText(compose.content);
          }
        } catch {
          if (!cancelled) {
            setComposePath('Compose path not available for this container');
            setComposeText('# Compose file not available for this container\n');
          }
        }

        try {
          const envPayload = await fetchEnvText(selectedId);
          if (!cancelled) {
            setEnvRows(parseEnvRows(envPayload.content));
          }
        } catch {
          if (!cancelled) {
            setEnvRows([]);
          }
        }
        if (!cancelled) setDetailsLoading(false);
      } catch (err) {
        if (cancelled) return;
        const detail = err instanceof Error ? err.message : 'Failed to load container details';
        if (/not found|404/i.test(detail)) {
          // One recovery refetch per effect run; if the ID is still listed the
          // panel shows the failed state instead of an eternal spinner.
          recoveredMissingContainer = true;
          setDetailsLoading(false);
          setRecoveryNotice('Selected container was not found. Refreshing the container list.');
          void loadContainers();
        } else {
          setDetailsLoading(false);
          setError(sanitizeDetail(detail));
        }
      }
    };

    void loadDetails();

    const logsUrl = new URL(`/api/containers/${selectedId}/logs?tail=200`, window.location.origin);
    const source = new EventSource(logsUrl, { fetch: authenticatedFetch });
    source.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as { logs?: string; error?: string };
        if (cancelled) return;

        if (typeof payload.error === 'string' && payload.error.length > 0) {
          if (!recoveredMissingContainer && /not found|404/i.test(payload.error)) {
            recoveredMissingContainer = true;
            setRecoveryNotice('Selected container was not found. Refreshing the container list.');
            void loadContainers();
          } else {
            // Log failures stay in the Logs panel; they never take down the list.
            setLogsError(sanitizeDetail(payload.error));
          }
          return;
        }

        if (typeof payload.logs === 'string') {
          const logChunk = payload.logs;
          setLogs((prev) => {
            if (logChunk.length === 0) {
              return prev.length > 0 ? prev : '[no logs yet]';
            }
            const next = prev + logChunk;
            return next.slice(-12000);
          });
        }
      } catch {
        // Ignore malformed SSE payloads.
      }
    };
    source.addEventListener('error', () => {
      if (!cancelled) {
        setLogsError('Logs stream disconnected — reconnecting…');
      }
    });

    const statTimer = window.setInterval(() => {
      void fetchContainerStats(selectedId)
        .then((nextStats) => {
          if (!cancelled) setStats(nextStats);
        })
        .catch((err) => {
          if (cancelled || recoveredMissingContainer) return;
          const detail = err instanceof Error ? err.message : '';
          if (/not found|404/i.test(detail)) {
            recoveredMissingContainer = true;
            setRecoveryNotice('Selected container was not found. Refreshing the container list.');
            void loadContainers();
          }
          // Stats are decorative; transient poll errors keep the last known values.
        });
    }, 3000);

    return () => {
      cancelled = true;
      source.close();
      window.clearInterval(statTimer);
    };
  }, [selectedId, loadContainers]);

  async function onAction(action: ContainerAction) {
    const id = selectedId;
    if (!id) return;
    setMessage('');
    setError('');
    setRecoveryNotice('');
    try {
      await runContainerAction(id, action);
      // The user may have switched containers while the request was in flight;
      // don't drop stale notices onto the new selection.
      if (selectedIdRef.current === id) setMessage(`Action ${action} executed successfully.`);
      await loadContainers();
    } catch (err) {
      if (selectedIdRef.current === id) {
        setError(
          sanitizeDetail(err instanceof Error ? err.message : `Failed to ${action} container`),
        );
      }
    }
  }

  async function onRemove() {
    const id = selectedId;
    if (!id) return;
    const confirmed = window.confirm(
      'Remove this container? You can also remove anonymous volumes in the next step.',
    );
    if (!confirmed) return;

    const removeVolumes = window.confirm('Also remove anonymous volumes?');
    setMessage('');
    setError('');
    setRecoveryNotice('');

    try {
      await removeContainer(id, removeVolumes);
      if (selectedIdRef.current === id) setMessage('Container removed successfully.');
      await loadContainers();
    } catch (err) {
      if (selectedIdRef.current === id) {
        setError(sanitizeDetail(err instanceof Error ? err.message : 'Failed to remove container'));
      }
    }
  }

  async function onSaveCompose() {
    const id = selectedId;
    if (!id) return;
    setMessage('');
    setError('');
    setRecoveryNotice('');
    try {
      const parsed = parseDocument(composeText);
      if (parsed.errors.length > 0) {
        throw new Error(`Invalid YAML: ${parsed.errors[0].message}`);
      }
      await updateCompose(id, composeText);
      if (selectedIdRef.current === id) {
        setMessage('Compose file saved. Click Apply Changes to recreate services.');
      }
    } catch (err) {
      if (selectedIdRef.current === id) {
        setError(sanitizeDetail(err instanceof Error ? err.message : 'Failed to save compose file'));
      }
    }
  }

  async function onSaveEnv() {
    const id = selectedId;
    if (!id) return;
    setMessage('');
    setError('');
    setRecoveryNotice('');
    try {
      const nextEnvText = envRowsToText(envRows);
      await updateEnvText(id, nextEnvText);
      if (selectedIdRef.current === id) {
        setMessage('.env file saved. Click Apply Changes to recreate services.');
      }
    } catch (err) {
      if (selectedIdRef.current === id) {
        setError(sanitizeDetail(err instanceof Error ? err.message : 'Failed to save env file'));
      }
    }
  }

  function updateEnvRow(id: string, field: 'key' | 'value', value: string) {
    setEnvRows((prev) =>
      prev.map((row) => {
        if (row.id !== id) return row;
        const nextKey = field === 'key' ? value : row.key;
        const secret = isSecretKey(nextKey);
        return {
          ...row,
          [field]: value,
          isSecret: secret,
          masked: secret ? row.masked : false,
        };
      }),
    );
  }

  function addEnvRow() {
    setEnvRows((prev) => [
      ...prev,
      {
        id: createRowId(),
        key: '',
        value: '',
        isSecret: false,
        masked: false,
      },
    ]);
  }

  function removeEnvRow(id: string) {
    setEnvRows((prev) => prev.filter((row) => row.id !== id));
  }

  function toggleEnvMask(id: string) {
    setEnvRows((prev) => prev.map((row) => (row.id === id ? { ...row, masked: !row.masked } : row)));
  }

  async function onApplyChanges() {
    const id = selectedId;
    if (!id) return;
    setMessage('');
    setError('');
    setRecoveryNotice('');
    try {
      const output = await applyContainerChanges(id);
      if (selectedIdRef.current === id) setMessage(`Apply completed: ${output}`);
      await loadContainers();
    } catch (err) {
      if (selectedIdRef.current === id) {
        setError(sanitizeDetail(err instanceof Error ? err.message : 'Failed to apply compose changes'));
      }
    }
  }

  return (
    <div className="containers-page animate-fade-in">
      <div className="containers-page__header">
        <div>
          <h1 className="containers-page__title">Container Management</h1>
          <p className="containers-page__subtitle">Lifecycle actions, logs, and compose/env editors</p>
        </div>
        <div className="containers-page__controls">
          <label className="containers-page__toggle" htmlFor="include-stopped">
            <input
              id="include-stopped"
              type="checkbox"
              checked={includeStopped}
              onChange={(e) => setIncludeStopped(e.target.checked)}
            />
            Include stopped
          </label>
          <button
            className="btn btn-secondary"
            onClick={() => void loadContainers()}
            disabled={refreshing}
            data-testid="containers-refresh"
          >
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="containers-page__notice containers-page__notice--error" role="alert">
          {error}
        </div>
      )}
      {message && (
        <div className="containers-page__notice containers-page__notice--success" role="status">
          {message}
        </div>
      )}
      {recoveryNotice && (
        <div className="containers-page__notice containers-page__notice--success" role="status">
          {recoveryNotice}
        </div>
      )}

      {refreshing && hasLoaded && (
        <p className="containers-page__refreshing" role="status" data-testid="containers-refreshing">
          Refreshing…
        </p>
      )}
      {loadError && containers.length > 0 && (
        <div
          className="containers-page__notice containers-page__notice--stale"
          role="alert"
          data-testid="containers-stale"
        >
          <span>Couldn't refresh — the list below may be out of date.</span>
          <button
            className="btn btn-secondary"
            onClick={() => void loadContainers()}
            disabled={refreshing}
          >
            Retry
          </button>
        </div>
      )}

      {!hasLoaded && !loadError ? (
        <div className="card containers-empty" role="status" data-testid="containers-loading">
          <p>Loading containers…</p>
        </div>
      ) : loadError && containers.length === 0 ? (
        <div className="card containers-empty" role="alert" data-testid="containers-error">
          <h2 className="containers-empty__title">{loadError.title}</h2>
          <p>{loadError.body}</p>
          <button
            className="btn btn-primary"
            onClick={() => void loadContainers()}
            disabled={refreshing}
            data-testid="containers-retry"
          >
            Retry
          </button>
        </div>
      ) : (
        <div className="containers-grid">
          <section className="card containers-list">
            <h2>Containers</h2>
            <input
              type="search"
              className="input containers-list__search"
              placeholder="Search by name or image…"
              aria-label="Search containers"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              data-testid="containers-search"
            />
            {visibleContainers.length === 0 ? (
              <p className="containers-list__empty" data-testid="containers-empty-list">
                {search.trim() ? 'No containers match your search.' : 'No containers found.'}
              </p>
            ) : (
              <div className="containers-list__items" data-testid="containers-list">
                {visibleContainers.map((container) => (
                  <button
                    key={container.id}
                    className={`containers-list__item ${selectedId === container.id ? 'is-active' : ''}`}
                    aria-pressed={selectedId === container.id}
                    onClick={() => setSelectedId(container.id)}
                  >
                    <div className="containers-list__row">
                      <strong>{container.name}</strong>
                      <span className={`badge ${statusBadgeClass(container.status)}`}>
                        {container.status}
                      </span>
                    </div>
                    <div className="containers-list__meta">
                      <span title={container.image}>{container.image}</span>
                      <span title={container.id}>{container.id}</span>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </section>

          <section className="card containers-detail" data-testid="containers-detail">
            <h2>Details</h2>
            {/* The id gate makes one frame of "detail A + terminal B" impossible:
                the panel only renders when the payload matches the selection. */}
            {!selected || selected.id !== selectedId ? (
              <p className="containers-list__empty">
                {selectedId
                  ? detailsLoading
                    ? 'Loading container details…'
                    : 'Failed to load container details.'
                  : 'Select a container to manage it.'}
              </p>
            ) : (
            <>
              <div className="containers-detail__stats">
                <div>
                  <span className="label">Name</span>
                  <p>{selected.name}</p>
                </div>
                <div>
                  <span className="label">Status</span>
                  <p>{selected.status}</p>
                </div>
                <div>
                  <span className="label">CPU</span>
                  <p>{stats ? `${stats.cpu_percent.toFixed(2)}%` : '-'}</p>
                </div>
                <div>
                  <span className="label">Memory</span>
                  <p>
                    {stats
                      ? `${stats.memory_usage_mb.toFixed(1)} / ${stats.memory_limit_mb.toFixed(1)} MB`
                      : '-'}
                  </p>
                </div>
              </div>

              <div className="containers-detail__actions">
                <button className="btn btn-primary" onClick={() => void onAction('start')}>Start</button>
                <button className="btn btn-secondary" onClick={() => void onAction('stop')}>Stop</button>
                <button className="btn btn-secondary" onClick={() => void onAction('restart')}>Restart</button>
                <button className="btn btn-secondary" onClick={() => void onAction('kill')}>Kill</button>
                <button className="btn btn-secondary" onClick={() => void onApplyChanges()}>
                  Apply Changes
                </button>
                <button
                  className="btn btn-secondary"
                  onClick={() => openAppUrl && window.open(openAppUrl, '_blank', 'noopener,noreferrer')}
                  disabled={!openAppUrl}
                  title={openAppUrl ? `Open ${openAppUrl}` : 'No exposed host port found'}
                >
                  Open App
                </button>
                <button className="btn btn-danger" onClick={() => void onRemove()}>Remove</button>
              </div>

              <div className="containers-detail__split">
                <div>
                  <h3>Logs</h3>
                  {logsError && (
                    <p className="containers-logs-error" role="status" data-testid="containers-logs-error">
                      {logsError}
                    </p>
                  )}
                  <pre className="containers-terminal">{logs || 'Waiting for logs...'}</pre>
                </div>
                <div>
                  <h3>Compose</h3>
                  <p className="containers-detail__path">{composePath}</p>
                  <CodeMirror
                    className="containers-editor-cm"
                    value={composeText}
                    extensions={[yamlLang()]}
                    theme="dark"
                    minHeight="220px"
                    onChange={(value) => setComposeText(value)}
                  />
                  <button className="btn btn-secondary" onClick={() => void onSaveCompose()}>
                    Save Compose
                  </button>
                </div>
              </div>

              <div>
                <h3>.env</h3>
                <div className="containers-env-table">
                  <div className="containers-env-table__head">
                    <span>Key</span>
                    <span>Value</span>
                    <span>Actions</span>
                  </div>
                  {envRows.length === 0 ? <p className="containers-env-table__empty">No variables found.</p> : null}
                  {envRows.map((row) => (
                    <div className="containers-env-table__row" key={row.id}>
                      <input
                        className="input"
                        value={row.key}
                        onChange={(e) => updateEnvRow(row.id, 'key', e.target.value)}
                        placeholder="ENV_KEY"
                        aria-label="Variable key"
                      />
                      <input
                        className="input"
                        type={row.isSecret && row.masked ? 'password' : 'text'}
                        value={row.value}
                        onChange={(e) => updateEnvRow(row.id, 'value', e.target.value)}
                        placeholder="value"
                        aria-label="Variable value"
                      />
                      <div className="containers-env-table__actions">
                        {row.isSecret ? (
                          <button className="btn btn-secondary" onClick={() => toggleEnvMask(row.id)}>
                            {row.masked ? 'Show' : 'Hide'}
                          </button>
                        ) : null}
                        <button
                          className="btn btn-danger"
                          onClick={() => removeEnvRow(row.id)}
                          aria-label={row.key ? `Remove variable ${row.key}` : 'Remove variable'}
                        >
                          Remove
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
                <button className="btn btn-secondary" onClick={addEnvRow}>
                  Add Variable
                </button>
                <button className="btn btn-secondary" onClick={() => void onSaveEnv()}>
                  Save .env
                </button>
              </div>

              <div>
                <h3>Exec Terminal</h3>
                <ExecTerminal containerId={selectedId} />
              </div>
            </>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
