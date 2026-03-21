export interface ContainerItem {
  id: string;
  name: string;
  status: string;
  image: string;
  created: string;
  labels: Record<string, string>;
  ports: Record<string, unknown>;
}

export interface ContainerDetail extends ContainerItem {
  raw: {
    command: string[] | null;
    entrypoint: string[] | null;
    mounts: Array<Record<string, unknown>>;
    env_count: number;
  };
}

export interface ContainerStats {
  id: string;
  name: string;
  status: string;
  cpu_percent: number;
  memory_usage_mb: number;
  memory_limit_mb: number;
}

export interface ComposeFilePayload {
  path: string;
  content: string;
}

export interface EnvTextPayload {
  content: string;
}
