import { useCallback, useEffect, useMemo, useState } from 'react';
import CodeMirror from '@uiw/react-codemirror';
import { yaml as yamlLang } from '@codemirror/lang-yaml';
import { parseDocument } from 'yaml';
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
  const [composeText, setComposeText] = useState<string>('');
  const [composePath, setComposePath] = useState<string>('');
  const [envRows, setEnvRows] = useState<EnvRow[]>([]);
  const [includeStopped, setIncludeStopped] = useState<boolean>(true);
  const [appUrlsByContainer, setAppUrlsByContainer] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string>('');
  const [message, setMessage] = useState<string>('');

  const sortedContainers = useMemo(
    () => [...containers].sort((a, b) => a.name.localeCompare(b.name)),
    [containers],
  );
  const openAppUrl = useMemo(
    () => resolveContainerUrl(selected, appUrlsByContainer),
    [selected, appUrlsByContainer],
  );

  const loadContainers = useCallback(async (nextSelectedId?: string) => {
    setLoading(true);
    setError('');
    try {
      const data = await fetchContainers(includeStopped);
      setContainers(data);
      try {
        const installedApps = await fetchInstalledApps();
        const nextMap = installedApps.reduce<Record<string, string>>((acc, app: InstalledApp) => {
          if (app.app_url) {
            acc[app.container_name] = app.app_url;
            acc[app.app_name] = app.app_url;
          }
          return acc;
        }, {});
        setAppUrlsByContainer(nextMap);
      } catch {
        setAppUrlsByContainer({});
      }
      const preferredId = nextSelectedId || selectedId;
      const preferredExists = preferredId
        ? data.some((container) => container.id === preferredId)
        : false;
      const nextId = preferredExists ? preferredId : data[0]?.id || '';
      setSelectedId(nextId);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load containers');
    } finally {
      setLoading(false);
    }
  }, [includeStopped, selectedId]);

  useEffect(() => {
    void loadContainers();
  }, [loadContainers]);

  useEffect(() => {
    if (!selectedId) {
      setSelected(null);
      setStats(null);
      setLogs('');
      setComposeText('');
      setComposePath('');
      setEnvRows([]);
      return;
    }

    let cancelled = false;
    let recoveredMissingContainer = false;
    setError('');
    setMessage('');
    setLogs('');

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
      } catch (err) {
        if (!cancelled) {
          const detail = err instanceof Error ? err.message : 'Failed to load container details';
          setError(detail);
          if (/not found|404/i.test(detail)) {
            recoveredMissingContainer = true;
            setMessage('Previously selected container no longer exists. Switched to an available one.');
            void loadContainers('');
          }
        }
      }
    };

    void loadDetails();

    const source = new EventSource(`/api/containers/${selectedId}/logs?tail=200`);
    source.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as { logs?: string; error?: string };
        if (cancelled) return;

        if (typeof payload.error === 'string' && payload.error.length > 0) {
          setError(payload.error);
          if (!recoveredMissingContainer && /not found|404/i.test(payload.error)) {
            recoveredMissingContainer = true;
            setMessage('Selected container disappeared. Switched to an available one.');
            void loadContainers('');
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
        setMessage('Logs stream disconnected, retrying...');
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
            setMessage('Selected container disappeared. Switched to an available one.');
            void loadContainers('');
          }
        });
    }, 3000);

    return () => {
      cancelled = true;
      source.close();
      window.clearInterval(statTimer);
    };
  }, [selectedId, loadContainers]);

  async function onAction(action: ContainerAction) {
    if (!selectedId) return;
    setMessage('');
    setError('');
    try {
      await runContainerAction(selectedId, action);
      setMessage(`Action ${action} executed successfully.`);
      await loadContainers(selectedId);
    } catch (err) {
      setError(err instanceof Error ? err.message : `Failed to ${action} container`);
    }
  }

  async function onRemove() {
    if (!selectedId) return;
    const confirmed = window.confirm(
      'Remove this container? You can also remove anonymous volumes in the next step.',
    );
    if (!confirmed) return;

    const removeVolumes = window.confirm('Also remove anonymous volumes?');
    setMessage('');
    setError('');

    try {
      await removeContainer(selectedId, removeVolumes);
      setMessage('Container removed successfully.');
      await loadContainers('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to remove container');
    }
  }

  async function onSaveCompose() {
    if (!selectedId) return;
    setMessage('');
    setError('');
    try {
      const parsed = parseDocument(composeText);
      if (parsed.errors.length > 0) {
        throw new Error(`Invalid YAML: ${parsed.errors[0].message}`);
      }
      await updateCompose(selectedId, composeText);
      setMessage('Compose file saved. Click Apply Changes to recreate services.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save compose file');
    }
  }

  async function onSaveEnv() {
    if (!selectedId) return;
    setMessage('');
    setError('');
    try {
      const nextEnvText = envRowsToText(envRows);
      await updateEnvText(selectedId, nextEnvText);
      setMessage('.env file saved. Click Apply Changes to recreate services.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save env file');
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
    if (!selectedId) return;
    setMessage('');
    setError('');
    try {
      const output = await applyContainerChanges(selectedId);
      setMessage(`Apply completed: ${output}`);
      await loadContainers(selectedId);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to apply compose changes');
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
          <button className="btn btn-secondary" onClick={() => void loadContainers(selectedId)}>
            Refresh
          </button>
        </div>
      </div>

      {error && <div className="containers-page__notice containers-page__notice--error">{error}</div>}
      {message && <div className="containers-page__notice containers-page__notice--success">{message}</div>}

      <div className="containers-grid">
        <section className="card containers-list">
          <h2>Containers</h2>
          {loading ? <p>Loading containers...</p> : null}
          {!loading && sortedContainers.length === 0 ? <p>No containers found.</p> : null}

          <div className="containers-list__items">
            {sortedContainers.map((container) => (
              <button
                key={container.id}
                className={`containers-list__item ${selectedId === container.id ? 'is-active' : ''}`}
                onClick={() => setSelectedId(container.id)}
              >
                <div className="containers-list__row">
                  <strong>{container.name}</strong>
                  <span className={`badge ${statusBadgeClass(container.status)}`}>{container.status}</span>
                </div>
                <div className="containers-list__meta">
                  <span>{container.image}</span>
                  <span>{container.id}</span>
                </div>
              </button>
            ))}
          </div>
        </section>

        <section className="card containers-detail">
          <h2>Details</h2>
          {!selected ? (
            <p>Select a container to manage it.</p>
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
                      />
                      <input
                        className="input"
                        type={row.isSecret && row.masked ? 'password' : 'text'}
                        value={row.value}
                        onChange={(e) => updateEnvRow(row.id, 'value', e.target.value)}
                        placeholder="value"
                      />
                      <div className="containers-env-table__actions">
                        {row.isSecret ? (
                          <button className="btn btn-secondary" onClick={() => toggleEnvMask(row.id)}>
                            {row.masked ? 'Show' : 'Hide'}
                          </button>
                        ) : null}
                        <button className="btn btn-danger" onClick={() => removeEnvRow(row.id)}>
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
    </div>
  );
}
