export type DomainRouteSource = 'dashboard' | 'marketplace';

export type DomainSslStatus = 'disabled' | 'local' | 'active' | 'pending' | 'error';

export interface DomainRouteStatus {
  host: string;
  source: DomainRouteSource;
  target: string;
  app_name: string | null;
  dns_resolves: boolean | null;
  resolved_ips: string[];
  ssl_status: DomainSslStatus;
  cert_expiry: string | null;
  cert_days_remaining: number | null;
  cert_issuer: string | null;
  cert_subject: string | null;
  check_message: string;
}

export interface CaddyRuntimeStatus {
  generated_globals_exists: boolean;
  generated_site_exists: boolean;
  marketplace_routes_exists: boolean;
  marketplace_route_count: number;
}

export interface DomainsOverview {
  configured: boolean;
  domain: string | null;
  https_enabled: boolean;
  acme_email: string | null;
  acme_staging: boolean;
  routes: DomainRouteStatus[];
  caddy_runtime: CaddyRuntimeStatus;
}
