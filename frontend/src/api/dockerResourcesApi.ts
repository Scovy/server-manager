import type { DockerNetwork, DockerVolume } from '../types/dockerResources';

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

export async function deleteVolume(name: string): Promise<void> {
  const res = await fetch(`${BASE}/volumes/${encodeURIComponent(name)}`, { method: 'DELETE' });
  await parseJson<{ status: string }>(res, 'Failed to delete volume');
}

export async function fetchNetworks(): Promise<DockerNetwork[]> {
  const res = await fetch(`${BASE}/networks`);
  return parseJson<DockerNetwork[]>(res, 'Failed to fetch networks');
}

export async function deleteNetwork(id: string): Promise<void> {
  const res = await fetch(`${BASE}/networks/${encodeURIComponent(id)}`, { method: 'DELETE' });
  await parseJson<{ status: string }>(res, 'Failed to delete network');
}
