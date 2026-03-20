import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import './Login.css';

/**
 * Login page — authentication entry point.
 *
 * Currently a UI shell without API wiring.
 * Will be connected to POST /api/auth/login in the auth implementation phase.
 */
export default function Login() {
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    // TODO: Replace with actual API call to POST /api/auth/login
    try {
      // Simulate auth for now
      if (username && password) {
        // Will be replaced with real JWT auth
        navigate('/dashboard');
      } else {
        setError('Please enter username and password');
      }
    } catch {
      setError('Authentication failed. Please try again.');
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

          <div className="login__field">
            <label className="label" htmlFor="username">
              Username
            </label>
            <input
              id="username"
              className="input"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
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
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete="current-password"
              required
            />
          </div>

          <button
            type="submit"
            className="btn btn-primary login__submit"
            disabled={loading}
            id="login-submit"
          >
            {loading ? (
              <>
                <span className="animate-spin">⟳</span>
                Signing in...
              </>
            ) : (
              'Sign in'
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
