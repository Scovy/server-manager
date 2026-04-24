import { useState } from 'react';
import { setupTwoFactor, verifyTwoFactor } from '../api/authApi';
import { useAuth } from '../auth/AuthContext';
import './Security.css';

function formatSecret(secret: string): string {
  return secret.match(/.{1,4}/g)?.join(' ') ?? secret;
}

export default function Security() {
  const { user, establishSession, reloadSession } = useAuth();
  const [setupSecret, setSetupSecret] = useState('');
  const [otpauthUri, setOtpauthUri] = useState('');
  const [code, setCode] = useState('');
  const [loadingSetup, setLoadingSetup] = useState(false);
  const [loadingVerify, setLoadingVerify] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const twoFactorEnabled = Boolean(user?.two_factor_enabled);

  async function handleStartSetup() {
    setLoadingSetup(true);
    setError('');
    setMessage('');

    try {
      const payload = await setupTwoFactor();
      setSetupSecret(payload.secret);
      setOtpauthUri(payload.otpauth_uri);
      setCode('');
      setMessage('Secret generated. Add it to your authenticator app, then enter the 6-digit code.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start 2FA setup.');
    } finally {
      setLoadingSetup(false);
    }
  }

  async function handleCopy(value: string, label: string) {
    setError('');
    try {
      if (!navigator.clipboard?.writeText) {
        throw new Error('Clipboard access is not available in this browser.');
      }
      await navigator.clipboard.writeText(value);
      setMessage(`${label} copied to clipboard.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : `Failed to copy ${label.toLowerCase()}.`);
    }
  }

  async function handleVerify() {
    setLoadingVerify(true);
    setError('');
    setMessage('');

    try {
      const payload = await verifyTwoFactor(code.trim());

      if (payload.access_token && payload.token_type && payload.expires_in && payload.user) {
        establishSession({
          status: 'ok',
          access_token: payload.access_token,
          token_type: payload.token_type,
          expires_in: payload.expires_in,
          user: payload.user,
        });
      } else if (payload.status === 'enabled') {
        await reloadSession();
      }

      setCode('');
      if (payload.status === 'enabled') {
        setMessage('Two-factor authentication is now enabled for your account.');
        setSetupSecret('');
        setOtpauthUri('');
      } else {
        setMessage('Code accepted. Your authenticator is working.');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to verify two-factor code.');
    } finally {
      setLoadingVerify(false);
    }
  }

  return (
    <div className="security-page animate-fade-in">
      <div className="security-page__header">
        <div>
          <h1 className="security-page__title">Security</h1>
          <p className="security-page__subtitle">
            Manage two-factor authentication for your dashboard account.
          </p>
        </div>
        <span className={`badge ${twoFactorEnabled ? 'badge-success' : 'badge-warning'}`}>
          {twoFactorEnabled ? '2FA enabled' : '2FA disabled'}
        </span>
      </div>

      <section className="security-card card">
        <div className="security-card__header">
          <div>
            <h2>Authenticator App</h2>
            <p>
              This project already supports TOTP. Until now, the only way to enable it was by
              calling the backend endpoints directly.
            </p>
          </div>
          {!twoFactorEnabled ? (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void handleStartSetup()}
              disabled={loadingSetup}
            >
              {loadingSetup ? 'Generating...' : setupSecret ? 'Regenerate Secret' : 'Generate Secret'}
            </button>
          ) : null}
        </div>

        {error ? (
          <div className="security-card__notice security-card__notice--error" role="alert">
            {error}
          </div>
        ) : null}

        {message && !error ? (
          <div className="security-card__notice security-card__notice--success" role="status">
            {message}
          </div>
        ) : null}

        <div className="security-card__grid">
          <div className="security-panel">
            <h3>Status</h3>
            <p>
              {twoFactorEnabled
                ? 'Your account will require a TOTP code after the username and password step.'
                : 'Generate a setup secret, add it to your authenticator app, then confirm with a one-time code.'}
            </p>
            <ul className="security-steps">
              <li>Supported apps include Google Authenticator, 1Password, Authy, and similar TOTP apps.</li>
              <li>The shared secret stays pending until you confirm it with a valid 6-digit code.</li>
              <li>There is not yet a disable or backup-code flow in this project.</li>
            </ul>
          </div>

          <div className="security-panel">
            <h3>{twoFactorEnabled ? 'Verify a Code' : 'Complete Setup'}</h3>
            {!twoFactorEnabled && !setupSecret ? (
              <p className="security-panel__empty">
                Generate a secret to begin. You can enter it manually in your authenticator app or
                use the `otpauth://` link on supported devices.
              </p>
            ) : null}

            {!twoFactorEnabled && setupSecret ? (
              <div className="security-setup">
                <div className="security-setup__block">
                  <label className="label" htmlFor="security-secret">
                    TOTP Secret
                  </label>
                  <div className="security-setup__value" id="security-secret">
                    {formatSecret(setupSecret)}
                  </div>
                  <div className="security-setup__actions">
                    <button
                      type="button"
                      className="btn btn-secondary"
                      onClick={() => void handleCopy(setupSecret, 'Secret')}
                    >
                      Copy Secret
                    </button>
                    <button
                      type="button"
                      className="btn btn-secondary"
                      onClick={() => void handleCopy(otpauthUri, 'Setup link')}
                    >
                      Copy Setup Link
                    </button>
                  </div>
                </div>

                <div className="security-setup__block">
                  <span className="label">Setup Link</span>
                  <a className="security-setup__link" href={otpauthUri}>
                    {otpauthUri}
                  </a>
                </div>
              </div>
            ) : null}

            <div className="security-form">
              <div className="security-form__field">
                <label className="label" htmlFor="security-code">
                  Authenticator Code
                </label>
                <input
                  id="security-code"
                  className="input"
                  type="text"
                  value={code}
                  onChange={(event) => setCode(event.target.value)}
                  placeholder="123456"
                  autoComplete="one-time-code"
                  inputMode="numeric"
                  maxLength={8}
                />
              </div>

              <button
                type="button"
                className="btn btn-primary"
                onClick={() => void handleVerify()}
                disabled={loadingVerify || (!twoFactorEnabled && !setupSecret) || !code.trim()}
              >
                {loadingVerify
                  ? twoFactorEnabled
                    ? 'Checking...'
                    : 'Enabling...'
                  : twoFactorEnabled
                    ? 'Verify Code'
                    : 'Enable 2FA'}
              </button>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
