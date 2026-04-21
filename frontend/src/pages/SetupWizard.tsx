import { useMemo, useState } from 'react';
import { initializeSetup, preflightSetup } from '../api/setupApi';
import type { SetupPreflightResult, SetupRequest } from '../types/setup';
import './SetupWizard.css';

interface SetupWizardProps {
  onInitialized: () => Promise<void>;
}

const defaultPreflight: SetupPreflightResult = {
  valid: false,
  errors: [],
  warnings: [],
  checks: [],
};

function isIpOrLocalDomain(value: string): boolean {
  const domain = value.trim().toLowerCase();
  if (!domain) return true;
  if (domain === 'localhost' || domain === '127.0.0.1') return true;
  if (/^\d{1,3}(\.\d{1,3}){3}$/.test(domain)) return true;
  return false;
}

export default function SetupWizard({ onInitialized }: SetupWizardProps) {
  const initialDomain = window.location.hostname || 'localhost';
  const [domain, setDomain] = useState(initialDomain);
  const [acmeEmail, setAcmeEmail] = useState('');
  const [enableHttps, setEnableHttps] = useState(true);
  const [useStaging, setUseStaging] = useState(false);
  const [corsOrigins, setCorsOrigins] = useState('http://localhost:5173,http://localhost:3000');
  const [preflight, setPreflight] = useState<SetupPreflightResult>(defaultPreflight);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [running, setRunning] = useState(false);
  const [saving, setSaving] = useState(false);

  const issuesSummary = useMemo(() => {
    if (!preflight.errors.length && !preflight.warnings.length) return '';
    return `Errors: ${preflight.errors.length}, Warnings: ${preflight.warnings.length}`;
  }, [preflight.errors.length, preflight.warnings.length]);
  const localDomain = isIpOrLocalDomain(domain);

  function buildPayload(): SetupRequest {
    return {
      domain,
      acme_email: acmeEmail,
      enable_https: enableHttps,
      use_staging_acme: useStaging,
      cors_origins: corsOrigins
        .split(',')
        .map((origin) => origin.trim())
        .filter(Boolean),
    };
  }

  async function runPreflight() {
    setError('');
    setMessage('');
    setRunning(true);
    try {
      const result = await preflightSetup(buildPayload());
      setPreflight(result);
      setMessage(result.valid ? 'Preflight passed. You can initialize now.' : 'Preflight found issues.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Preflight failed');
    } finally {
      setRunning(false);
    }
  }

  async function runInitialize() {
    setError('');
    setMessage('');
    setSaving(true);
    try {
      const result = await initializeSetup(buildPayload());
      setPreflight(result.preflight);
      setMessage(result.message);
      await onInitialized();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Initialization failed');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="setup-page animate-fade-in">
      <div className="setup-shell card">
        <div className="setup-header">
          <h1>First Installation Setup</h1>
          <p>Configure domain, HTTPS, and core startup settings.</p>
        </div>

        {error ? <div className="setup-notice setup-notice--error">{error}</div> : null}
        {message ? <div className="setup-notice setup-notice--success">{message}</div> : null}
        {localDomain ? (
          <div className="setup-notice setup-notice--warn">
            Local/IP address detected. HTTPS will use Caddy&apos;s local certificate authority.
            Browser warnings are expected until that local CA is trusted on your client device.
          </div>
        ) : null}

        <div className="setup-grid">
          <label>
            Domain
            <input
              className="input"
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              placeholder="home.example.com"
            />
          </label>

          <label>
            ACME Email
            <input
              className="input"
              value={acmeEmail}
              onChange={(e) => setAcmeEmail(e.target.value)}
              placeholder="admin@example.com"
            />
          </label>

          <label className="setup-checkbox">
            <input
              type="checkbox"
              checked={enableHttps}
              onChange={(e) => setEnableHttps(e.target.checked)}
            />
            Enable HTTPS (recommended)
          </label>

          <label className="setup-checkbox">
            <input
              type="checkbox"
              checked={useStaging}
              onChange={(e) => setUseStaging(e.target.checked)}
              disabled={!enableHttps}
            />
            Use ACME staging (testing only)
          </label>

          <label className="setup-full">
            CORS Origins (comma-separated)
            <textarea
              className="input setup-cors"
              value={corsOrigins}
              onChange={(e) => setCorsOrigins(e.target.value)}
            />
          </label>
        </div>

        <div className="setup-actions">
          <button className="btn btn-secondary" onClick={() => void runPreflight()} disabled={running || saving}>
            {running ? 'Checking...' : 'Run Preflight'}
          </button>
          <button className="btn btn-primary" onClick={() => void runInitialize()} disabled={saving}>
            {saving ? 'Initializing...' : 'Initialize'}
          </button>
        </div>

        <div className="setup-results">
          <div className="setup-results__summary">
            <h2>Preflight Results</h2>
            <span className="badge badge-info">{issuesSummary || 'No checks run yet'}</span>
          </div>

          {preflight.errors.length > 0 ? (
            <div className="setup-results__block setup-results__block--error">
              <h3>Errors</h3>
              <ul>
                {preflight.errors.map((issue) => (
                  <li key={`${issue.code}-${issue.message}`}>{issue.message}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {preflight.warnings.length > 0 ? (
            <div className="setup-results__block setup-results__block--warn">
              <h3>Warnings</h3>
              <ul>
                {preflight.warnings.map((issue) => (
                  <li key={`${issue.code}-${issue.message}`}>{issue.message}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {preflight.checks.length > 0 ? (
            <div className="setup-checks">
              {preflight.checks.map((check) => (
                <div className="setup-checks__item" key={check.name}>
                  <span className={`badge ${check.status === 'pass' ? 'badge-success' : check.status === 'warn' ? 'badge-warning' : 'badge-danger'}`}>
                    {check.status}
                  </span>
                  <span>{check.message}</span>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
