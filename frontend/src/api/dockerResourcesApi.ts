import type { DockerDisk, DockerNetwork, DockerVolume } from '../types/dockerResources';

const BASE = '/api';

async function parseJson<T>(res: Response, fallbackMessage: string): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || fallbackMessage);
  }
  return res.json() as Promise<T>;
}

export async function fetchVolumes(): Promise<DockerVolume[]> {
  const res = await fetch(`${BASE}/volumes`);
  return parseJson<DockerVolume[]>(res, 'Failed to fetch volumes');
}

export async function createVolume(
  name: string,
  labels: Record<string, string> = {},
): Promise<DockerVolume> {
  const res = await fetch(`${BASE}/volumes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, labels }),
  });
  const payload = await parseJson<{ status: string; volume: DockerVolume }>(
    res,
    'Failed to create volume',
  );
  return payload.volume;
}

export async function deleteVolume(name: string): Promise<void> {
  const res = await fetch(`${BASE}/volumes/${encodeURIComponent(name)}`, { method: 'DELETE' });
  await parseJson<{ status: string }>(res, 'Failed to delete volume');
}

export async function fetchNetworks(): Promise<DockerNetwork[]> {
  const res = await fetch(`${BASE}/networks`);
  return parseJson<DockerNetwork[]>(res, 'Failed to fetch networks');
}

export async function fetchDisks(): Promise<DockerDisk[]> {
  const res = await fetch(`${BASE}/disks`);
  return parseJson<DockerDisk[]>(res, 'Failed to fetch disks');
}

export async function deleteNetwork(id: string): Promise<void> {
  const res = await fetch(`${BASE}/networks/${encodeURIComponent(id)}`, { method: 'DELETE' });
  await parseJson<{ status: string }>(res, 'Failed to delete network');
}
