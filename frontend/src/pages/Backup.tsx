import { useEffect, useState } from 'react';
import {
  exportConfigBackup,
  exportFullBackup,
  fetchBackups,
  importConfigBackup,
  removeBackup,
} from '../api/backupApi';
import type { BackupItem } from '../types/backup';
import './Backup.css';

function formatBytes(bytes: number): string {
  if (bytes <= 0) return '-';

  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = bytes;
  let unitIndex = 0;

  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }

  const decimals = size >= 100 ? 0 : size >= 10 ? 1 : 2;
  return `${size.toFixed(decimals)} ${units[unitIndex]}`;
}

function formatDate(isoDate: string): string {
  const date = new Date(isoDate);
  if (Number.isNaN(date.getTime())) return isoDate;
  return date.toLocaleString();
}

export default function Backup() {
  const [backups, setBackups] = useState<BackupItem[]>([]);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  async function loadBackups() {
    setLoading(true);
    setError('');
    try {
      const payload = await fetchBackups();
      setBackups(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load backups');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadBackups();
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  async function handleCreateBackup(mode: 'config' | 'full') {
    setExporting(true);
    setError('');
    setMessage('');
    try {
      const payload = mode === 'full' ? await exportFullBackup() : await exportConfigBackup();
      const { blob, filename } = payload;
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = objectUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(objectUrl);

      setMessage(
        mode === 'full'
          ? `Full backup created (including Docker volumes): ${filename}`
          : `Config backup created: ${filename}`,
      );
      await loadBackups();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create backup');
    } finally {
      setExporting(false);
    }
  }

  async function handleDeleteBackup(filename: string) {
    if (!window.confirm(`Delete backup ${filename}?`)) return;

    setError('');
    setMessage('');
    try {
      await removeBackup(filename);
      setMessage(`Backup deleted: ${filename}`);
      await loadBackups();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete backup');
    }
  }

  async function handleRestoreBackup() {
    if (!selectedFile) {
      setError('Choose a backup file first.');
      return;
    }

    const confirmed = window.confirm(
      'Restore configuration from this backup? Existing DB and app config files will be replaced.',
    );
    if (!confirmed) return;

    setRestoring(true);
    setError('');
    setMessage('');
    try {
      const payload = await importConfigBackup(selectedFile);
      setMessage(payload.message);
      setSelectedFile(null);
      await loadBackups();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to restore backup');
    } finally {
      setRestoring(false);
    }
  }

  return (
    <div className="backup-page animate-fade-in">
      <div className="backup-page__header">
        <div>
          <h1 className="backup-page__title">Backup</h1>
          <p className="backup-page__subtitle">
            Create config-only or full snapshots (config + Docker volumes)
          </p>
        </div>
        <div className="backup-page__actions">
          <button className="btn btn-secondary" onClick={() => void loadBackups()} disabled={loading}>
            Refresh
          </button>
          <button
            className="btn btn-primary"
            onClick={() => void handleCreateBackup('config')}
            disabled={exporting}
          >
            {exporting ? 'Creating...' : 'Create Config Backup'}
          </button>
          <button
            className="btn btn-primary"
            onClick={() => void handleCreateBackup('full')}
            disabled={exporting}
          >
            {exporting ? 'Creating...' : 'Create Full Backup'}
          </button>
        </div>
      </div>

      {error ? <div className="backup-page__notice backup-page__notice--error">{error}</div> : null}
      {message ? <div className="backup-page__notice backup-page__notice--success">{message}</div> : null}

      <section className="card backup-card">
        <h2>Restore From File</h2>
        <p className="backup-card__helper">
          Upload a previously exported backup archive (`.tar.gz`) from your local machine.
        </p>
        <div className="backup-restore">
          <input
            className="input"
            type="file"
            accept=".tar.gz,application/gzip"
            onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
          />
          <button
            className="btn btn-danger"
            onClick={() => void handleRestoreBackup()}
            disabled={restoring || !selectedFile}
          >
            {restoring ? 'Restoring...' : 'Restore Backup'}
          </button>
        </div>
      </section>

      <section className="card backup-card">
        <h2>Available Backups</h2>
        <div className="backup-table-wrap">
          <table className="backup-table">
            <thead>
              <tr>
                <th>Filename</th>
                <th>Size</th>
                <th>Updated</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {backups.map((backup) => (
                <tr key={backup.filename}>
                  <td>{backup.filename}</td>
                  <td>{formatBytes(backup.size_bytes)}</td>
                  <td>{formatDate(backup.updated_at)}</td>
                  <td>
                    <button
                      className="btn btn-danger"
                      onClick={() => void handleDeleteBackup(backup.filename)}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!loading && backups.length === 0 ? (
            <p className="backup-empty">No backups found.</p>
          ) : null}
          {loading ? <p className="backup-empty">Loading backups...</p> : null}
        </div>
      </section>
    </div>
  );
}
