export interface DockerVolume {
  name: string;
  driver: string;
  mountpoint: string;
  scope: string;
  labels: Record<string, string>;
}

export interface DockerNetwork {
  id: string;
  name: string;
  driver: string;
  scope: string;
  containers: number;
  labels: Record<string, string>;
}
