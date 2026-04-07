import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import {
  deployMarketplaceTemplate,
  fetchInstalledApps,
  fetchMarketplaceTemplates,
  preflightMarketplaceTemplate,
  removeInstalledApp,
} from '../api/marketplaceApi';
import type { InstalledApp, MarketplaceTemplate } from '../types/marketplace';
import './Marketplace.css';

const categories = ['all', 'dev', 'media', 'monitoring', 'productivity', 'security'];

export default function Marketplace() {
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('all');
  const [deployTemplateId, setDeployTemplateId] = useState<string>('');
  const [deployAppName, setDeployAppName] = useState('');
  const [deployHostPort, setDeployHostPort] = useState<string>('');
  const [deployEnvText, setDeployEnvText] = useState('');
  const [deployMessage, setDeployMessage] = useState('');
  const [deployError, setDeployError] = useState('');
  const [preflightErrors, setPreflightErrors] = useState<string[]>([]);
  const [deploying, setDeploying] = useState(false);
  const [purgeOnRemove, setPurgeOnRemove] = useState(false);
  const [removeMessage, setRemoveMessage] = useState('');
  const [removingAppName, setRemovingAppName] = useState<string>('');
  const nextCategory = category === 'all' ? '' : category;
  const { data: items = [], isLoading, error } = useQuery<MarketplaceTemplate[]>({
    queryKey: ['marketplace', nextCategory, search],
    queryFn: () => fetchMarketplaceTemplates(nextCategory, search),
  });
  const {
    data: installedApps = [],
    isLoading: loadingInstalled,
    refetch: refetchInstalled,
  } = useQuery<InstalledApp[]>({
    queryKey: ['marketplace-installed'],
    queryFn: fetchInstalledApps,
  });

  const countLabel = useMemo(() => `${items.length} template${items.length === 1 ? '' : 's'}`, [items]);

  function envMapToText(env: Record<string, string>): string {
    return Object.entries(env)
      .map(([key, value]) => `${key}=${value}`)
      .join('\n');
  }

  function parseEnvText(text: string): Record<string, string> {
    const result: Record<string, string> = {};
    const lines = text.split(/\r?\n/);
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;
      const index = trimmed.indexOf('=');
      if (index <= 0) {
        throw new Error(`Invalid env line: ${trimmed}`);
      }
      const key = trimmed.slice(0, index).trim();
      const value = trimmed.slice(index + 1);
      result[key] = value;
    }
    return result;
  }

  function startDeploy(template: MarketplaceTemplate) {
    setDeployTemplateId(template.id);
    setDeployAppName(template.id);
    setDeployHostPort(String(template.default_port));
    setDeployEnvText(envMapToText(template.default_env));
    setDeployMessage('');
    setDeployError('');
    setPreflightErrors([]);
  }

  async function submitDeploy(templateId: string) {
    setDeployMessage('');
    setDeployError('');
    setPreflightErrors([]);

    const hostPort = Number(deployHostPort);
    if (!Number.isInteger(hostPort) || hostPort < 1 || hostPort > 65535) {
      setDeployError('Host port must be an integer between 1 and 65535.');
      return;
    }

    try {
      const env = parseEnvText(deployEnvText);
      setDeploying(true);
      const preflight = await preflightMarketplaceTemplate({
        template_id: templateId,
        app_name: deployAppName,
        host_port: hostPort,
      });
      if (!preflight.valid) {
        setPreflightErrors(preflight.errors);
        return;
      }

      const result = await deployMarketplaceTemplate({
        template_id: templateId,
        app_name: deployAppName,
        host_port: hostPort,
        env,
      });
      setDeployMessage(`Deployed ${result.app_name} on port ${result.host_port}.`);
      setDeployTemplateId('');
      await refetchInstalled();
    } catch (err) {
      setDeployError(err instanceof Error ? err.message : 'Deploy failed');
    } finally {
      setDeploying(false);
    }
  }

  async function handleRemove(appName: string) {
    setRemoveMessage('');
    setDeployError('');
    setPreflightErrors([]);
    try {
      setRemovingAppName(appName);
      const result = await removeInstalledApp(appName, purgeOnRemove);
      setRemoveMessage(result.message);
      await refetchInstalled();
    } catch (err) {
      setDeployError(err instanceof Error ? err.message : 'Failed to remove app');
    } finally {
      setRemovingAppName('');
    }
  }

  return (
    <div className="marketplace-page animate-fade-in">
      <div className="marketplace-page__header">
        <div>
          <h1 className="marketplace-page__title">Marketplace</h1>
          <p className="marketplace-page__subtitle">Deploy prebuilt homelab apps with one click.</p>
        </div>
        <span className="badge badge-info">{countLabel}</span>
      </div>

      <div className="marketplace-filters card">
        <input
          className="input"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search templates..."
        />
        <div className="marketplace-filters__chips">
          {categories.map((item) => (
            <button
              key={item}
              className={`btn ${category === item ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setCategory(item)}
            >
              {item}
            </button>
          ))}
        </div>
      </div>

      {error ? (
        <div className="marketplace-page__notice marketplace-page__notice--error">
          {error instanceof Error ? error.message : 'Failed to load marketplace'}
        </div>
      ) : null}
      {deployError ? (
        <div className="marketplace-page__notice marketplace-page__notice--error">{deployError}</div>
      ) : null}
      {deployMessage ? (
        <div className="marketplace-page__notice marketplace-page__notice--success">{deployMessage}</div>
      ) : null}
      {removeMessage ? (
        <div className="marketplace-page__notice marketplace-page__notice--success">{removeMessage}</div>
      ) : null}
      {preflightErrors.length > 0 ? (
        <div className="marketplace-page__notice marketplace-page__notice--error">
          {preflightErrors.join(' ')}
        </div>
      ) : null}
      {isLoading ? <div className="card">Loading templates...</div> : null}

      <section className="card marketplace-installed">
        <div className="marketplace-installed__header">
          <h2>Installed Apps</h2>
          <label className="marketplace-installed__purge">
            <input
              type="checkbox"
              checked={purgeOnRemove}
              onChange={(e) => setPurgeOnRemove(e.target.checked)}
            />
            Purge app files on remove
          </label>
        </div>
        {loadingInstalled ? <p>Loading installed apps...</p> : null}
        {!loadingInstalled && installedApps.length === 0 ? <p>No installed apps yet.</p> : null}
        {!loadingInstalled && installedApps.length > 0 ? (
          <div className="marketplace-installed__list">
            {installedApps.map((app) => (
              <div className="marketplace-installed__item" key={app.id}>
                <div>
                  <h3>{app.app_name}</h3>
                  <p>
                    {app.template_id} on port {app.host_port} ({app.status})
                  </p>
                </div>
                <button
                  className="btn btn-secondary"
                  onClick={() => void handleRemove(app.app_name)}
                  disabled={removingAppName === app.app_name}
                >
                  {removingAppName === app.app_name ? 'Removing...' : 'Remove'}
                </button>
              </div>
            ))}
          </div>
        ) : null}
      </section>

      {!isLoading && items.length === 0 ? (
        <div className="card">No templates match the current filters.</div>
      ) : null}

      <div className="marketplace-grid">
        {items.map((template) => (
          <article className="card marketplace-card" key={template.id}>
            <div className="marketplace-card__top">
              <h2>{template.name}</h2>
              <span className="badge badge-warning">{template.category}</span>
            </div>
            <p className="marketplace-card__description">{template.description}</p>
            <div className="marketplace-card__meta">
              <span>Image: {template.image}</span>
              <span>Default Port: {template.default_port}</span>
            </div>
            <div className="marketplace-card__actions">
              <a className="btn btn-secondary" href={template.homepage} target="_blank" rel="noreferrer">
                Docs
              </a>
              <button className="btn btn-primary" onClick={() => startDeploy(template)}>
                Deploy
              </button>
            </div>

            {deployTemplateId === template.id ? (
              <div className="marketplace-deploy">
                <h3>Deploy {template.name}</h3>
                <label>
                  App Name
                  <input
                    className="input"
                    value={deployAppName}
                    onChange={(e) => setDeployAppName(e.target.value)}
                    placeholder="my-app"
                  />
                </label>
                <label>
                  Host Port
                  <input
                    className="input"
                    type="number"
                    value={deployHostPort}
                    onChange={(e) => setDeployHostPort(e.target.value)}
                    min={1}
                    max={65535}
                  />
                </label>
                <label>
                  Environment (KEY=VALUE)
                  <textarea
                    className="input marketplace-deploy__env"
                    value={deployEnvText}
                    onChange={(e) => setDeployEnvText(e.target.value)}
                  />
                </label>
                <div className="marketplace-deploy__actions">
                  <button
                    className="btn btn-secondary"
                    onClick={() => setDeployTemplateId('')}
                    disabled={deploying}
                  >
                    Cancel
                  </button>
                  <button
                    className="btn btn-primary"
                    onClick={() => void submitDeploy(template.id)}
                    disabled={deploying}
                  >
                    {deploying ? 'Deploying...' : 'Confirm Deploy'}
                  </button>
                </div>
              </div>
            ) : null}
          </article>
        ))}
      </div>
    </div>
  );
}
