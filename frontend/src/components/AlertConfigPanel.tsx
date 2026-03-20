/**
 * AlertConfigPanel — Form to configure system alert thresholds.
 *
 * Fetches current config on mount, allows editing CPU/RAM/Disk limits
 * and webhook URL, and saves via PUT /api/metrics/alerts.
 */

import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { fetchAlertConfig, updateAlertConfig } from '../api/metricsApi';
import type { AlertConfig } from '../types/metrics';
import './AlertConfigPanel.css';

export default function AlertConfigPanel() {
  const [expanded, setExpanded] = useState(false);
  const [config, setConfig] = useState<AlertConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  useEffect(() => {
    if (expanded && !config) {
      fetchAlertConfig()
        .then(setConfig)
        .catch((err) => setError(err.message));
    }
  }, [expanded, config]);

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!config) return;

    setSaving(true);
    setError('');
    setSuccess('');

    try {
      const updated = await updateAlertConfig(config);
      setConfig(updated);
      setSuccess('Alert configuration saved successfully.');
      setTimeout(() => setSuccess(''), 3000);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to preserve config.');
    } finally {
      setSaving(false);
    }
  };

  const handleNumChange = (field: keyof AlertConfig, value: string) => {
    const num = parseInt(value, 10);
    if (!isNaN(num) && config) {
      setConfig({ ...config, [field]: Math.max(0, Math.min(100, num)) });
    }
  };

  return (
    <div className="card alert-panel">
      <div className="alert-panel__header" onClick={() => setExpanded(!expanded)}>
        <div className="alert-panel__title-group">
          <span className="alert-panel__icon">🔔</span>
          <h3 className="alert-panel__title">Alert Configuration</h3>
        </div>
        <button
          type="button"
          className="btn btn-secondary alert-panel__toggle"
          aria-expanded={expanded}
        >
          {expanded ? 'Collapse' : 'Configure'}
        </button>
      </div>

      {expanded && (
        <div className="alert-panel__content animate-fade-in">
          {error && <div className="alert-panel__msg error">{error}</div>}
          {success && <div className="alert-panel__msg success">{success}</div>}

          {!config ? (
            <div className="alert-panel__loading">Loading configuration...</div>
          ) : (
            <form onSubmit={handleSubmit} className="alert-panel__form">
              <p className="alert-panel__help">
                Trigger a webhook when a metric exceeds its threshold for an extended period.
              </p>

              <div className="alert-panel__row">
                <div className="alert-panel__field">
                  <label htmlFor="cpu_threshold" className="label">CPU Usage (%)</label>
                  <input
                    id="cpu_threshold"
                    type="number"
                    className="input"
                    min="1"
                    max="100"
                    value={config.cpu_threshold}
                    onChange={(e) => handleNumChange('cpu_threshold', e.target.value)}
                  />
                </div>
                <div className="alert-panel__field">
                  <label htmlFor="ram_threshold" className="label">RAM Usage (%)</label>
                  <input
                    id="ram_threshold"
                    type="number"
                    className="input"
                    min="1"
                    max="100"
                    value={config.ram_threshold}
                    onChange={(e) => handleNumChange('ram_threshold', e.target.value)}
                  />
                </div>
                <div className="alert-panel__field">
                  <label htmlFor="disk_threshold" className="label">Disk Usage (%)</label>
                  <input
                    id="disk_threshold"
                    type="number"
                    className="input"
                    min="1"
                    max="100"
                    value={config.disk_threshold}
                    onChange={(e) => handleNumChange('disk_threshold', e.target.value)}
                  />
                </div>
              </div>

              <div className="alert-panel__field full-width">
                <label htmlFor="webhook_url" className="label">
                  Discord / Generic Webhook URL
                </label>
                <input
                  id="webhook_url"
                  type="url"
                  className="input"
                  placeholder="https://discord.com/api/webhooks/..."
                  value={config.webhook_url}
                  onChange={(e) => setConfig({ ...config, webhook_url: e.target.value })}
                />
              </div>

              <div className="alert-panel__actions">
                <button type="submit" className="btn btn-primary" disabled={saving}>
                  {saving ? 'Saving...' : 'Save Configuration'}
                </button>
              </div>
            </form>
          )}
        </div>
      )}
    </div>
  );
}
