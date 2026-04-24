import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { createInitialAdmin } from '../api/authApi';
import { useAuth } from '../auth/AuthContext';
import './Login.css';

interface CreateAccountProps {
  onCreated: () => Promise<void>;
}

export default function CreateAccount({ onCreated }: CreateAccountProps) {
  const navigate = useNavigate();
  const { establishSession } = useAuth();
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError('');

    if (!username.trim()) {
      setError('Username is required.');
      return;
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters long.');
      return;
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }

    setLoading(true);
    try {
      const response = await createInitialAdmin({
        username: username.trim(),
        password,
      });
      establishSession(response);
      await onCreated();
      navigate('/dashboard', { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create the initial admin account.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login">
      <div className="login__container animate-fade-in">
        <div className="login__header">
          <div className="login__logo">🛠️</div>
          <h1 className="login__title">Create Admin Account</h1>
          <p className="login__subtitle">
            Setup is complete. Create the first administrator account to finish onboarding.
          </p>
        </div>

        <form className="login__form" onSubmit={handleSubmit}>
          {error ? (
            <div className="login__error" role="alert">
              {error}
            </div>
          ) : null}

          <div className="login__field">
            <label className="label" htmlFor="create-account-username">
              Username
            </label>
            <input
              id="create-account-username"
              className="input"
              type="text"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              placeholder="admin"
              autoComplete="username"
              required
            />
          </div>

          <div className="login__field">
            <label className="label" htmlFor="create-account-password">
              Password
            </label>
            <input
              id="create-account-password"
              className="input"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Use a strong password"
              autoComplete="new-password"
              required
            />
          </div>

          <div className="login__field">
            <label className="label" htmlFor="create-account-confirm-password">
              Confirm Password
            </label>
            <input
              id="create-account-confirm-password"
              className="input"
              type="password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              placeholder="Repeat the password"
              autoComplete="new-password"
              required
            />
          </div>

          <button type="submit" className="btn btn-primary login__submit" disabled={loading}>
            {loading ? 'Creating account...' : 'Create Admin Account'}
          </button>
        </form>

        <div className="login__footer">
          <span className="badge badge-info">First-run onboarding</span>
        </div>
      </div>
    </div>
  );
}
