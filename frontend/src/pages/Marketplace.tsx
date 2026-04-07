import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { fetchMarketplaceTemplates } from '../api/marketplaceApi';
import type { MarketplaceTemplate } from '../types/marketplace';
import './Marketplace.css';

const categories = ['all', 'dev', 'media', 'monitoring', 'productivity', 'security'];

export default function Marketplace() {
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('all');
  const nextCategory = category === 'all' ? '' : category;
  const { data: items = [], isLoading, error } = useQuery<MarketplaceTemplate[]>({
    queryKey: ['marketplace', nextCategory, search],
    queryFn: () => fetchMarketplaceTemplates(nextCategory, search),
  });

  const countLabel = useMemo(() => `${items.length} template${items.length === 1 ? '' : 's'}`, [items]);

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
      {isLoading ? <div className="card">Loading templates...</div> : null}

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
              <button className="btn btn-primary" disabled>
                Deploy (next)
              </button>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
