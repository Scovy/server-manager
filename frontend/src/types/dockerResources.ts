export interface DockerVolume {
  name: string;
  driver: string;
  mountpoint: string;
  scope: string;
  labels: Record<string, string>;
  ref_count: number;
  in_use: boolean;
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
