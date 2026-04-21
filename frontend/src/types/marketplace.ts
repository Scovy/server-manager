export interface MarketplaceTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  image: string;
  version: string;
  homepage: string;
  default_port: number;
  container_port: number;
  default_env: Record<string, string>;
}

export interface MarketplaceDeployRequest {
  template_id: string;
  app_name: string;
  host_port: number;
  env: Record<string, string>;
}

export interface MarketplaceDeployResult {
  status: string;
  template_id: string;
  app_name: string;
  host_port: number;
  app_dir: string;
  compose_path: string;
  output: string;
}

export interface MarketplacePreflightRequest {
  template_id: string;
  app_name: string;
  host_port: number;
}

export interface MarketplacePreflightResult {
  valid: boolean;
  errors: string[];
}

export interface InstalledApp {
  id: number;
  template_id: string;
  app_name: string;
  container_name: string;
  host_port: number;
  app_url: string;
  app_dir: string;
  compose_path: string;
  status: string;
  created_at: string;
  updated_at: string;
}
