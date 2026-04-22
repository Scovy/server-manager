import type { DomainsOverview } from '../types/domains';

const BASE = '/api/domains';

async function handleJson<T>(res: Response, fallback: string): Promise<T> {
  if (!res.ok) {
    const payload = await res.json().catch(() => ({ detail: fallback }));
    throw new Error(payload.detail || fallback);
  }
  return res.json() as Promise<T>;
}

export async function fetchDomainsOverview(liveChecks = false): Promise<DomainsOverview> {
  const params = new URLSearchParams();
  if (liveChecks) {
    params.set('live_checks', 'true');
  }
  const query = params.toString();
  const url = query ? `${BASE}?${query}` : BASE;
  const res = await fetch(url);
  return handleJson<DomainsOverview>(res, 'Failed to fetch domains overview');
}

export async function syncDomainRoutes(): Promise<{ status: string; message: string }> {
  const res = await fetch(`${BASE}/sync`, {
    method: 'POST',
  });
  return handleJson<{ status: string; message: string }>(res, 'Failed to sync domain routes');
}
