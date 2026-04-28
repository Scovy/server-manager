export interface DockerVolume {
  name: string;
  driver: string;
  mountpoint: string;
  scope: string;
  labels: Record<string, string>;
  created_at: string;
  size_bytes: number;
  ref_count: number;
  in_use: boolean;
  app_hint: string;
  used_by: string[];
}

export interface DockerDisk {
  device: string;
  mountpoint: string;
  fstype: string;
  opts: string;
  total_bytes: number;
  used_bytes: number;
  free_bytes: number;
  percent: number;
}

export interface DockerNetwork {
  id: string;
  name: string;
  driver: string;
  scope: string;
  containers: number;
  labels: Record<string, string>;
  protected: boolean;
}
