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
