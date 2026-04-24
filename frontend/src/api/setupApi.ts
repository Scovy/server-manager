import type {
  SetupInitializeResult,
  SetupPreflightResult,
  SetupRequest,
  SetupStatus,
} from '../types/setup';

const BASE = '/api/setup';

async function handleJson<T>(res: Response, fallback: string): Promise<T> {
  if (!res.ok) {
    const payload = await res.json().catch(() => ({ detail: fallback }));
    const detail = payload?.detail;
    let message = fallback;
    if (typeof detail === 'string') {
      message = detail;
    } else if (detail && typeof detail === 'object') {
      const preflight = (detail as { preflight?: { errors?: Array<{ message?: string }> } }).preflight;
      const errors = preflight?.errors?.map((item) => item.message).filter(Boolean) ?? [];
      if (errors.length > 0) {
        message = errors.join(' ');
      } else {
        const maybeMessage = (detail as { message?: string }).message;
        if (maybeMessage) message = maybeMessage;
      }
    }
    throw new Error(message);
  }
  return res.json() as Promise<T>;
}

export async function fetchSetupStatus(): Promise<SetupStatus> {
  const res = await fetch(`${BASE}/status`);
  if (!res.ok) {
    return handleJson<SetupStatus>(res, 'Failed to fetch setup status');
  }

  const text = await res.text();
  if (!text.trim()) {
    return { initialized: false, needs_admin_setup: false };
  }

  try {
    const payload = JSON.parse(text) as Partial<SetupStatus>;
    return {
      initialized: Boolean(payload.initialized),
      needs_admin_setup: Boolean(payload.needs_admin_setup),
    };
  } catch {
    return { initialized: false, needs_admin_setup: false };
  }
}

export async function preflightSetup(payload: SetupRequest): Promise<SetupPreflightResult> {
  const res = await fetch(`${BASE}/preflight`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return handleJson<SetupPreflightResult>(res, 'Failed to run setup preflight');
}

export async function initializeSetup(payload: SetupRequest): Promise<SetupInitializeResult> {
  const res = await fetch(`${BASE}/initialize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return handleJson<SetupInitializeResult>(res, 'Failed to initialize setup');
}
