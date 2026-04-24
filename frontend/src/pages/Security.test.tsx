import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Security from './Security';

const authMocks = vi.hoisted(() => ({
  establishSession: vi.fn(),
  reloadSession: vi.fn(),
  signOut: vi.fn(),
  user: {
    id: 7,
    username: 'alice',
    role: 'admin',
    two_factor_enabled: false,
  },
}));

const apiMocks = vi.hoisted(() => ({
  setupTwoFactor: vi.fn(),
  verifyTwoFactor: vi.fn(),
}));

const qrCodeMocks = vi.hoisted(() => ({
  toDataURL: vi.fn(),
}));

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({
    user: authMocks.user,
    loading: false,
    establishSession: authMocks.establishSession,
    signOut: authMocks.signOut,
    reloadSession: authMocks.reloadSession,
  }),
}));

vi.mock('../api/authApi', () => ({
  setupTwoFactor: apiMocks.setupTwoFactor,
  verifyTwoFactor: apiMocks.verifyTwoFactor,
}));

vi.mock('qrcode', () => ({
  default: {
    toDataURL: qrCodeMocks.toDataURL,
  },
}));

describe('Security page', () => {
  beforeEach(() => {
    authMocks.user.two_factor_enabled = false;
    authMocks.establishSession.mockReset();
    authMocks.reloadSession.mockReset();
    apiMocks.setupTwoFactor.mockReset();
    apiMocks.verifyTwoFactor.mockReset();
    qrCodeMocks.toDataURL.mockReset();
    qrCodeMocks.toDataURL.mockResolvedValue('data:image/png;base64,qr');
  });

  it('renders the setup call to action when 2FA is disabled', () => {
    render(<Security />);

    expect(screen.getByText('Security')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /generate secret/i })).toBeInTheDocument();
    expect(screen.getByText(/2fa disabled/i)).toBeInTheDocument();
  });

  it('enables 2FA after generating a secret and verifying a code', async () => {
    apiMocks.setupTwoFactor.mockResolvedValue({
      secret: 'ABCDEFGHIJKLMNOP',
      otpauth_uri: 'otpauth://totp/Homelab:alice?secret=ABCDEFGHIJKLMNOP',
    });
    apiMocks.verifyTwoFactor.mockResolvedValue({
      status: 'enabled',
      two_factor_enabled: true,
      access_token: 'fresh-token',
      token_type: 'bearer',
      expires_in: 900,
      user: {
        id: 7,
        username: 'alice',
        role: 'admin',
        two_factor_enabled: true,
      },
    });

    render(<Security />);

    fireEvent.click(screen.getByRole('button', { name: /generate secret/i }));

    expect(await screen.findByAltText(/qr code for pairing/i)).toHaveAttribute(
      'src',
      'data:image/png;base64,qr',
    );
    expect(await screen.findByText(/abcd efgh ijkl mnop/i)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/authenticator code/i), {
      target: { value: '123456' },
    });
    fireEvent.click(screen.getByRole('button', { name: /enable 2fa/i }));

    await waitFor(() => {
      expect(apiMocks.verifyTwoFactor).toHaveBeenCalledWith('123456');
    });
    expect(authMocks.establishSession).toHaveBeenCalledWith({
      status: 'ok',
      access_token: 'fresh-token',
      token_type: 'bearer',
      expires_in: 900,
      user: {
        id: 7,
        username: 'alice',
        role: 'admin',
        two_factor_enabled: true,
      },
    });
    expect(await screen.findByText(/two-factor authentication is now enabled/i)).toBeInTheDocument();
  });
});
