import type {
  MarketplaceDeployRequest,
  MarketplaceDeployResult,
  MarketplacePreflightRequest,
  MarketplacePreflightResult,
  MarketplaceTemplate,
  InstalledApp,
} from '../types/marketplace';

const BASE = '/api/marketplace';

async function handleJson<T>(res: Response, message: string): Promise<T> {
  if (!res.ok) {
    const payload = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(payload.detail || message);
  }
  return res.json() as Promise<T>;
}

export async function fetchMarketplaceTemplates(
  category: string,
  search: string,
): Promise<MarketplaceTemplate[]> {
  const params = new URLSearchParams();
  if (category.trim()) params.set('category', category.trim());
  if (search.trim()) params.set('search', search.trim());

  const query = params.toString();
  const url = query ? `${BASE}?${query}` : BASE;
  const res = await fetch(url);
  return handleJson<MarketplaceTemplate[]>(res, 'Failed to fetch marketplace templates');
}

export async function fetchMarketplaceTemplate(templateId: string): Promise<MarketplaceTemplate> {
  const res = await fetch(`${BASE}/${templateId}`);
  return handleJson<MarketplaceTemplate>(res, 'Failed to fetch marketplace template');
}

export async function deployMarketplaceTemplate(
  payload: MarketplaceDeployRequest,
): Promise<MarketplaceDeployResult> {
  const res = await fetch(`${BASE}/deploy`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return handleJson<MarketplaceDeployResult>(res, 'Failed to deploy marketplace template');
}

export async function preflightMarketplaceTemplate(
  payload: MarketplacePreflightRequest,
): Promise<MarketplacePreflightResult> {
  const res = await fetch(`${BASE}/preflight`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return handleJson<MarketplacePreflightResult>(res, 'Failed to validate deployment');
}

export async function fetchInstalledApps(): Promise<InstalledApp[]> {
  const res = await fetch(`${BASE}/installed`);
  return handleJson<InstalledApp[]>(res, 'Failed to fetch installed apps');
}

export async function removeInstalledApp(appName: string, purgeFiles = false): Promise<{ status: string; message: string }> {
  const params = new URLSearchParams();
  if (purgeFiles) params.set('purge_files', 'true');
  const suffix = params.toString() ? `?${params.toString()}` : '';
  const res = await fetch(`${BASE}/installed/${encodeURIComponent(appName)}${suffix}`, {
    method: 'DELETE',
  });
  return handleJson<{ status: string; message: string }>(res, 'Failed to remove installed app');
}
