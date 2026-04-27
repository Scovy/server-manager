import type { BackupItem, BackupRestoreResult } from '../types/backup';

const BASE = '/api/backup';

function parseErrorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== 'object') return fallback;
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  return fallback;
}

async function parseJson<T>(res: Response, fallback: string): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(parseErrorMessage(body, fallback));
  }
  return res.json() as Promise<T>;
}

function parseFilenameFromHeader(headerValue: string | null): string | null {
  if (!headerValue) return null;
  const filenameMatch = headerValue.match(/filename="?([^";]+)"?/i);
  return filenameMatch ? filenameMatch[1] : null;
}

export async function exportConfigBackup(): Promise<{ blob: Blob; filename: string }> {
  const res = await fetch(`${BASE}/export?mode=config`, { method: 'POST' });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(parseErrorMessage(body, 'Failed to export backup'));
  }

  const blob = await res.blob();
  const filename =
    parseFilenameFromHeader(res.headers.get('content-disposition')) || 'config-backup.tar.gz';

  return { blob, filename };
}

export async function exportFullBackup(): Promise<{ blob: Blob; filename: string }> {
  const res = await fetch(`${BASE}/export?mode=full`, { method: 'POST' });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(parseErrorMessage(body, 'Failed to export backup'));
  }

  const blob = await res.blob();
  const filename = parseFilenameFromHeader(res.headers.get('content-disposition')) || 'full-backup.tar.gz';

  return { blob, filename };
}

export async function fetchBackups(): Promise<BackupItem[]> {
  const res = await fetch(`${BASE}/list`);
  return parseJson<BackupItem[]>(res, 'Failed to list backups');
}

export async function removeBackup(filename: string): Promise<void> {
  const res = await fetch(`${BASE}/${encodeURIComponent(filename)}`, {
    method: 'DELETE',
  });
  await parseJson<{ status: string }>(res, 'Failed to delete backup');
}

export async function importConfigBackup(file: File): Promise<BackupRestoreResult> {
  const res = await fetch(`${BASE}/import`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/gzip',
      'X-Backup-Filename': file.name,
    },
    body: file,
  });
  return parseJson<BackupRestoreResult>(res, 'Failed to restore backup');
}
