import { afterEach, expect, it, vi } from 'vitest';
import { authenticatedFetch, openAdminSocket, setStoredAccessToken } from './authApi';

afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

it('refreshes once for concurrent 401s and preserves request data on retry', async () => {
  setStoredAccessToken('expired');
  const attempts: string[] = [];
  const fetchMock = vi.fn(async (url: string, init: RequestInit) => {
    if (url === '/api/auth/refresh') return Response.json({ access_token: 'renewed' });
    const headers = new Headers(init.headers);
    attempts.push(headers.get('Authorization')!);
    expect(headers.get('Content-Type')).toBe('application/json');
    expect(init.body).toBe('{"enabled":true}');
    return new Response(null, { status: attempts.at(-1) === 'Bearer renewed' ? 200 : 401 });
  });
  vi.stubGlobal('fetch', fetchMock);
  const init = { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: '{"enabled":true}' };
  const responses = await Promise.all([
    authenticatedFetch('/api/metrics/alerts', init),
    authenticatedFetch('/api/metrics/alerts', init),
  ]);
  expect(responses.map((res) => res.status)).toEqual([200, 200]);
  expect(attempts).toEqual(['Bearer expired', 'Bearer expired', 'Bearer renewed', 'Bearer renewed']);
  expect(fetchMock.mock.calls.filter(([url]) => url === '/api/auth/refresh')).toHaveLength(1);
});

it('stops on a forbidden response', async () => {
  setStoredAccessToken('viewer');
  const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 403 }));
  vi.stubGlobal('fetch', fetchMock);
  expect((await authenticatedFetch('/api/volumes')).status).toBe(403);
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it('opens the stream with the renewed credential outside the URL', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ access_token: 'renewed' })));
  const websocket = vi.fn(class {});
  vi.stubGlobal('WebSocket', websocket);
  await openAdminSocket('/ws/metrics', new AbortController().signal);
  const [url, protocols] = websocket.mock.calls[0] as unknown as [URL, string[]];
  expect(url.pathname).toBe('/ws/metrics');
  expect(url.search).toBe('');
  expect(protocols).toEqual(['homelab.v1', 'renewed']);
});
