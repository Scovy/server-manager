import { useEffect, useMemo, useState } from 'react';
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
import type { ContainerDetail, ContainerItem, ContainerStats } from '../types/containers';
import ExecTerminal from '../components/ExecTerminal';
import './Containers.css';

type ContainerAction = 'start' | 'stop' | 'restart' | 'kill';

function statusBadgeClass(status: string): string {
  if (status === 'running') return 'badge-success';
  if (status === 'paused' || status === 'restarting') return 'badge-warning';
  return 'badge-danger';
}

export default function Containers() {
  const [containers, setContainers] = useState<ContainerItem[]>([]);
  const [selectedId, setSelectedId] = useState<string>('');
  const [selected, setSelected] = useState<ContainerDetail | null>(null);
  const [stats, setStats] = useState<ContainerStats | null>(null);
  const [logs, setLogs] = useState<string>('');
  const [composeText, setComposeText] = useState<string>('');
  const [composePath, setComposePath] = useState<string>('');
  const [envText, setEnvText] = useState<string>('');
  const [includeStopped, setIncludeStopped] = useState<boolean>(true);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string>('');
  const [message, setMessage] = useState<string>('');

  const sortedContainers = useMemo(
    () => [...containers].sort((a, b) => a.name.localeCompare(b.name)),
    [containers],
  );

  async function loadContainers(nextSelectedId?: string) {
    setLoading(true);
    setError('');
    try {
      const data = await fetchContainers(includeStopped);
      setContainers(data);
      const nextId = nextSelectedId || selectedId || data[0]?.id || '';
      setSelectedId(nextId);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load containers');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadContainers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [includeStopped]);

  useEffect(() => {
    if (!selectedId) {
      setSelected(null);
      setStats(null);
      setLogs('');
      setComposeText('');
      setComposePath('');
      setEnvText('');
      return;
    }

    let cancelled = false;
    setError('');

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
          if (!cancelled) setEnvText(envPayload.content);
        } catch {
          if (!cancelled) setEnvText('# .env file not available for this container\n');
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load container details');
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
        .catch(() => {
          // Ignore transient stats failures.
        });
    }, 3000);

    return () => {
      cancelled = true;
      source.close();
      window.clearInterval(statTimer);
    };
  }, [selectedId]);

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
      await updateEnvText(selectedId, envText);
      setMessage('.env file saved. Click Apply Changes to recreate services.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save env file');
    }
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
                  <textarea
                    className="input containers-editor"
                    value={composeText}
                    onChange={(e) => setComposeText(e.target.value)}
                  />
                  <button className="btn btn-secondary" onClick={() => void onSaveCompose()}>
                    Save Compose
                  </button>
                </div>
              </div>

              <div>
                <h3>.env</h3>
                <textarea
                  className="input containers-editor"
                  value={envText}
                  onChange={(e) => setEnvText(e.target.value)}
                />
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
