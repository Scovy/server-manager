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

export async function refreshSession(): Promise<AuthSuccessResponse | null> {
  const res = await fetch(`${BASE}/refresh`, {
    method: 'POST',
    credentials: 'include',
  });

  if (res.status === 401) {
    clearStoredAccessToken();
    return null;
  }

  const data = await parseJson<AuthSuccessResponse>(res, 'Failed to refresh session.');
  setStoredAccessToken(data.access_token);
  return data;
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
  try {
    await fetch(`${BASE}/logout`, {
      method: 'POST',
      credentials: 'include',
    });
  } finally {
    clearStoredAccessToken();
  }
}

export async function setupTwoFactor(): Promise<TwoFactorSetupResponse> {
  const res = await fetch(`${BASE}/2fa/setup`, {
    method: 'POST',
    headers: {
      ...authHeader(),
    },
    credentials: 'include',
  });
  return parseJson<TwoFactorSetupResponse>(res, 'Failed to setup two-factor authentication.');
}

export async function verifyTwoFactor(code: string): Promise<TwoFactorVerifyResponse> {
  const res = await fetch(`${BASE}/2fa/verify`, {
    method: 'POST',
    headers: {
      ...authHeader(),
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
