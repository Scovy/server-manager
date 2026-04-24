import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import CreateAccount from './CreateAccount';

const authMocks = vi.hoisted(() => ({
  establishSession: vi.fn(),
  reloadSession: vi.fn(),
  signOut: vi.fn(),
}));

const apiMocks = vi.hoisted(() => ({
  createInitialAdmin: vi.fn(),
}));

const navigateMock = vi.hoisted(() => vi.fn());

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({
    user: null,
    loading: false,
    establishSession: authMocks.establishSession,
    signOut: authMocks.signOut,
    reloadSession: authMocks.reloadSession,
  }),
}));

vi.mock('../api/authApi', () => ({
  createInitialAdmin: apiMocks.createInitialAdmin,
}));

describe('CreateAccount page', () => {
  beforeEach(() => {
    authMocks.establishSession.mockReset();
    apiMocks.createInitialAdmin.mockReset();
    navigateMock.mockReset();
  });

  it('validates password confirmation before submitting', async () => {
    render(<CreateAccount onCreated={vi.fn().mockResolvedValue(undefined)} />);

    fireEvent.change(screen.getByLabelText(/^username$/i), { target: { value: 'admin' } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: 'password123' } });
    fireEvent.change(screen.getByLabelText(/confirm password/i), { target: { value: 'different123' } });
    fireEvent.click(screen.getByRole('button', { name: /create admin account/i }));

    expect(await screen.findByText(/passwords do not match/i)).toBeInTheDocument();
    expect(apiMocks.createInitialAdmin).not.toHaveBeenCalled();
  });

  it('creates the first admin account and navigates to the dashboard', async () => {
    const onCreated = vi.fn().mockResolvedValue(undefined);
    apiMocks.createInitialAdmin.mockResolvedValue({
      status: 'ok',
      access_token: 'token-123',
      token_type: 'bearer',
      expires_in: 900,
      user: {
        id: 1,
        username: 'admin',
        role: 'admin',
        two_factor_enabled: false,
      },
      bootstrap_created: true,
    });

    render(<CreateAccount onCreated={onCreated} />);

    fireEvent.change(screen.getByLabelText(/^username$/i), { target: { value: 'admin' } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: 'password123' } });
    fireEvent.change(screen.getByLabelText(/confirm password/i), { target: { value: 'password123' } });
    fireEvent.click(screen.getByRole('button', { name: /create admin account/i }));

    await waitFor(() => {
      expect(apiMocks.createInitialAdmin).toHaveBeenCalledWith({
        username: 'admin',
        password: 'password123',
      });
    });
    expect(authMocks.establishSession).toHaveBeenCalled();
    expect(onCreated).toHaveBeenCalled();
    expect(navigateMock).toHaveBeenCalledWith('/dashboard', { replace: true });
  });
});
