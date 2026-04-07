import type { MarketplaceTemplate } from '../types/marketplace';

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
