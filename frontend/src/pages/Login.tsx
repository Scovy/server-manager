import { useState, type FormEvent } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { login } from '../api/authApi';
import { useAuth } from '../auth/AuthContext';
import './Login.css';

/**
 * Login page — authentication entry point.
 */
export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const { establishSession } = useAuth();

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [totpCode, setTotpCode] = useState('');
  const [twoFactorRequired, setTwoFactorRequired] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const redirectTarget = (
    location.state as { from?: { pathname?: string } } | undefined
  )?.from?.pathname ?? '/dashboard';

  function resetTwoFactorChallenge() {
    if (!twoFactorRequired) return;
    setTwoFactorRequired(false);
    setTotpCode('');
    setNotice('');
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setNotice('');
    setLoading(true);

    try {
      const response = await login({
        username: username.trim(),
        password,
        totp_code: twoFactorRequired ? totpCode.trim() : undefined,
      });

      if (response.status === '2fa_required') {
        setTwoFactorRequired(true);
        setNotice(response.message);
        return;
      }

      establishSession(response);
      navigate(redirectTarget, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Authentication failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login">
      <div className="login__container animate-fade-in">
        {/* Logo */}
        <div className="login__header">
          <div className="login__logo">🏠</div>
          <h1 className="login__title">Homelab Dashboard</h1>
          <p className="login__subtitle">Sign in to manage your server</p>
        </div>

        {/* Form */}
        <form className="login__form" onSubmit={handleSubmit} id="login-form">
          {error && (
            <div className="login__error" role="alert">
              {error}
            </div>
          )}
          {notice && !error ? (
            <div className="login__notice" role="status">
              {notice}
            </div>
          ) : null}

          <div className="login__field">
            <label className="label" htmlFor="username">
              Username
            </label>
            <input
              id="username"
              className="input"
              type="text"
              value={username}
              onChange={(e) => {
                setUsername(e.target.value);
                resetTwoFactorChallenge();
              }}
              placeholder="admin"
              autoComplete="username"
              autoFocus
              required
            />
          </div>

          <div className="login__field">
            <label className="label" htmlFor="password">
              Password
            </label>
            <input
              id="password"
              className="input"
              type="password"
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                resetTwoFactorChallenge();
              }}
              placeholder="••••••••"
              autoComplete="current-password"
              required
            />
          </div>

          {twoFactorRequired ? (
            <div className="login__field">
              <label className="label" htmlFor="totp-code">
                Two-Factor Code
              </label>
              <input
                id="totp-code"
                className="input"
                type="text"
                value={totpCode}
                onChange={(e) => setTotpCode(e.target.value)}
                placeholder="123456"
                autoComplete="one-time-code"
                inputMode="numeric"
                maxLength={8}
                required
              />
            </div>
          ) : null}

          <button
            type="submit"
            className="btn btn-primary login__submit"
            disabled={loading}
            id="login-submit"
          >
            {loading ? (
              <>
                <span className="animate-spin">⟳</span>
                {twoFactorRequired ? 'Verifying...' : 'Signing in...'}
              </>
            ) : (
              twoFactorRequired ? 'Verify 2FA' : 'Sign in'
            )}
          </button>
        </form>

        {/* Footer */}
        <div className="login__footer">
          <span className="badge badge-info">v0.1.0</span>
        </div>
      </div>
    </div>
  );
}
