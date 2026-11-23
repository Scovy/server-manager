import type {
  AuthSuccessResponse,
  AuthUser,
  InitialAdminCreateRequest,
  LoginRequest,
  LoginResponse,
  TwoFactorSetupResponse,
  TwoFactorVerifyResponse,
} from '../types/auth';

const BASE = '/api/auth';
const ACCESS_TOKEN_STORAGE_KEY = 'homelab_access_token';
export const SESSION_ENDED = 'homelab:session-ended';
let pendingRefresh: Promise<AuthSuccessResponse | null> | undefined;
let sessionGeneration = 0;

function getErrorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== 'object') return fallback;
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  const message = (payload as { message?: unknown }).message;
  if (typeof message === 'string' && message.trim()) return message;
  return fallback;
}

async function parseJson<T>(res: Response, fallback: string): Promise<T> {
  if (!res.ok) {
    const payload = await res.json().catch(() => ({}));
    throw new Error(getErrorMessage(payload, fallback));
  }
  return res.json() as Promise<T>;
}

function authHeader(): HeadersInit {
  const token = getStoredAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function getStoredAccessToken(): string | null {
  return window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY);
}

export function setStoredAccessToken(token: string): void {
  window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, token);
}

export function clearStoredAccessToken(): void {
  window.localStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY);
}

export async function login(payload: LoginRequest): Promise<LoginResponse> {
  const res = await fetch(`${BASE}/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(payload),
  });
  const data = await parseJson<LoginResponse>(res, 'Failed to sign in.');
  if (data.status === 'ok') {
    setStoredAccessToken(data.access_token);
  }
  return data;
}

export async function createInitialAdmin(payload: InitialAdminCreateRequest): Promise<AuthSuccessResponse> {
  const res = await fetch(`${BASE}/bootstrap`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(payload),
  });
  const data = await parseJson<AuthSuccessResponse>(res, 'Failed to create the initial admin account.');
  setStoredAccessToken(data.access_token);
  return data;
}

export function refreshSession(): Promise<AuthSuccessResponse | null> {
  pendingRefresh ??= requestRefresh(sessionGeneration).finally(() => {
    pendingRefresh = undefined;
  });
  return pendingRefresh;
}

async function requestRefresh(generation: number): Promise<AuthSuccessResponse | null> {
  const res = await fetch(`${BASE}/refresh`, {
    method: 'POST',
    credentials: 'include',
  });

  if (generation !== sessionGeneration) return null;
  if (res.status === 401) {
    clearStoredAccessToken();
    window.dispatchEvent(new Event(SESSION_ENDED));
    return null;
  }

  const data = await parseJson<AuthSuccessResponse>(res, 'Failed to refresh session.');
  if (generation !== sessionGeneration) return null;
  setStoredAccessToken(data.access_token);
  return data;
}

export async function authenticatedFetch(url: string | URL, init: RequestInit = {}): Promise<Response> {
  if (new URL(url, window.location.href).origin !== window.location.origin) {
    throw new Error('Management requests must use the panel origin.');
  }
  const send = (token: string | null) => {
    const headers = new Headers(init.headers);
    if (token) headers.set('Authorization', `Bearer ${token}`);
    return fetch(url, { ...init, headers });
  };
  const token = getStoredAccessToken();
  const response = await send(token);
  if (response.status !== 401 || init.signal?.aborted) return response;

  const current = getStoredAccessToken();
  if (!current) return response;
  const renewed = current !== token ? current : (await refreshSession())?.access_token;
  return renewed ? send(renewed) : response;
}

export async function openAdminSocket(path: string, signal: AbortSignal): Promise<WebSocket> {
  const session = await refreshSession();
  signal.throwIfAborted();
  if (!session) throw new Error('Sign in to connect.');
  const url = new URL(path, window.location.origin);
  if (url.origin !== window.location.origin) throw new Error('Invalid stream origin.');
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return new WebSocket(url, ['homelab.v1', session.access_token]);
}

export async function fetchCurrentUser(): Promise<AuthUser> {
  const res = await fetch(`${BASE}/me`, {
    headers: {
      ...authHeader(),
    },
    credentials: 'include',
  });
  return parseJson<AuthUser>(res, 'Failed to fetch current user.');
}

export async function restoreSession(): Promise<AuthUser | null> {
  const existingToken = getStoredAccessToken();
  if (existingToken) {
    try {
      return await fetchCurrentUser();
    } catch {
      clearStoredAccessToken();
    }
  }

  const refreshed = await refreshSession().catch(() => null);
  return refreshed?.user ?? null;
}

export async function logout(): Promise<void> {
  sessionGeneration++;
  try {
    await fetch(`${BASE}/logout`, {
      method: 'POST',
      credentials: 'include',
    });
  } finally {
    clearStoredAccessToken();
    window.dispatchEvent(new Event(SESSION_ENDED));
  }
}

export async function setupTwoFactor(): Promise<TwoFactorSetupResponse> {
  const res = await authenticatedFetch(`${BASE}/2fa/setup`, {
    method: 'POST',
    credentials: 'include',
  });
  return parseJson<TwoFactorSetupResponse>(res, 'Failed to setup two-factor authentication.');
}

export async function verifyTwoFactor(code: string): Promise<TwoFactorVerifyResponse> {
  const res = await authenticatedFetch(`${BASE}/2fa/verify`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    credentials: 'include',
    body: JSON.stringify({ code }),
  });
  const data = await parseJson<TwoFactorVerifyResponse>(res, 'Failed to verify two-factor code.');
  if (data.access_token) {
    setStoredAccessToken(data.access_token);
  }
  return data;
}
