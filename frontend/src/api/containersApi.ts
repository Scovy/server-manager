import type {
  ComposeFilePayload,
  ContainerDetail,
  ContainerItem,
  ContainerStats,
  EnvTextPayload,
} from '../types/containers';

const BASE = '/api/containers';

async function handleJson<T>(res: Response, message: string): Promise<T> {
  if (!res.ok) {
    const payload = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(payload.detail || message);
  }
  return res.json() as Promise<T>;
}

export async function fetchContainers(includeStopped: boolean): Promise<ContainerItem[]> {
  const url = `${BASE}?all=${includeStopped ? 'true' : 'false'}`;
  const res = await fetch(url);
  return handleJson<ContainerItem[]>(res, 'Failed to fetch containers');
}

export async function fetchContainer(containerId: string): Promise<ContainerDetail> {
  const res = await fetch(`${BASE}/${containerId}`);
  return handleJson<ContainerDetail>(res, 'Failed to fetch container details');
}

export async function fetchContainerStats(containerId: string): Promise<ContainerStats> {
  const res = await fetch(`${BASE}/${containerId}/stats`);
  return handleJson<ContainerStats>(res, 'Failed to fetch container stats');
}

export async function runContainerAction(
  containerId: string,
  action: 'start' | 'stop' | 'restart' | 'kill',
): Promise<void> {
  const res = await fetch(`${BASE}/${containerId}/${action}`, { method: 'POST' });
  await handleJson<{ status: string }>(res, `Failed to ${action} container`);
}

export async function removeContainer(containerId: string, removeVolumes: boolean): Promise<void> {
  const url = `${BASE}/${containerId}?volumes=${removeVolumes ? 'true' : 'false'}`;
  const res = await fetch(url, { method: 'DELETE' });
  await handleJson<{ status: string }>(res, 'Failed to remove container');
}

export async function fetchCompose(containerId: string): Promise<ComposeFilePayload> {
  const res = await fetch(`${BASE}/${containerId}/compose`);
  return handleJson<ComposeFilePayload>(res, 'Failed to fetch compose file');
}

export async function updateCompose(containerId: string, content: string): Promise<void> {
  const res = await fetch(`${BASE}/${containerId}/compose`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
  await handleJson<{ status: string }>(res, 'Failed to update compose file');
}

export async function fetchEnvText(containerId: string): Promise<EnvTextPayload> {
  const res = await fetch(`${BASE}/${containerId}/env?format=text`);
  return handleJson<EnvTextPayload>(res, 'Failed to fetch env file');
}

export async function updateEnvText(containerId: string, content: string): Promise<void> {
  const res = await fetch(`${BASE}/${containerId}/env`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ env: content }),
  });
  await handleJson<{ status: string }>(res, 'Failed to update env file');
}

export async function applyContainerChanges(containerId: string): Promise<string> {
  const res = await fetch(`${BASE}/${containerId}/apply`, { method: 'POST' });
  const payload = await handleJson<{ status: string; output: string }>(
    res,
    'Failed to apply compose changes',
  );
  return payload.output;
}
