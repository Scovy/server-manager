import { useEffect, useState } from 'react';
import {
  createVolume,
  fetchDisks,
  deleteNetwork,
  deleteVolume,
  fetchNetworks,
  fetchVolumes,
} from '../api/dockerResourcesApi';
import type { DockerDisk, DockerNetwork, DockerVolume } from '../types/dockerResources';
import './DockerResources.css';

function formatBytes(bytes: number): string {
  if (bytes <= 0) return '-';

  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = bytes;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }

  const digits = size >= 100 ? 0 : size >= 10 ? 1 : 2;
  return `${size.toFixed(digits)} ${units[index]}`;
}

export default function DockerResources() {
  const [volumes, setVolumes] = useState<DockerVolume[]>([]);
  const [disks, setDisks] = useState<DockerDisk[]>([]);
  const [networks, setNetworks] = useState<DockerNetwork[]>([]);
  const [newVolumeName, setNewVolumeName] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  async function loadResources() {
    try {
      const [volData, diskData, netData] = await Promise.all([
        fetchVolumes(),
        fetchDisks(),
        fetchNetworks(),
      ]);
      setVolumes(volData);
      setDisks(diskData);
      setNetworks(netData);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load docker resources');
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadResources();
    }, 0);

    return () => {
      window.clearTimeout(timer);
    };
  }, []);

  async function onCreateVolume() {
    const candidate = newVolumeName.trim();
    if (!candidate) {
      setError('Volume name is required.');
      return;
    }

    setError('');
    setMessage('');
    try {
      await createVolume(candidate, {
        'com.homelab.managed': 'true',
        'com.homelab.scope': 'storage-panel',
      });
      setMessage(`Volume ${candidate} created.`);
      setNewVolumeName('');
      await loadResources();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create volume');
    }
  }

  async function onDeleteVolume(name: string) {
    if (!window.confirm(`Delete volume ${name}?`)) return;
    setError('');
    setMessage('');
    try {
      await deleteVolume(name);
      setMessage(`Volume ${name} removed.`);
      await loadResources();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete volume');
    }
  }

  async function onDeleteNetwork(id: string, name: string) {
    if (!window.confirm(`Delete network ${name}?`)) return;
    setError('');
    setMessage('');
    try {
      await deleteNetwork(id);
      setMessage(`Network ${name} removed.`);
      await loadResources();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete network');
    }
  }

  return (
    <div className="docker-resources-page animate-fade-in">
      <div className="docker-resources-page__header">
        <div>
          <h1 className="docker-resources-page__title">Storage Panel</h1>
          <p className="docker-resources-page__subtitle">Manage volumes, disks, and related resources</p>
        </div>
        <button className="btn btn-secondary" onClick={() => void loadResources()}>
          Refresh
        </button>
      </div>

      {error && <div className="docker-resources-page__notice docker-resources-page__notice--error">{error}</div>}
      {message && <div className="docker-resources-page__notice docker-resources-page__notice--success">{message}</div>}

      <div className="docker-resources-grid">
        <section className="card docker-resource-card">
          <h2>Volumes</h2>
          <div className="docker-resource-create">
            <input
              className="input"
              value={newVolumeName}
              onChange={(e) => setNewVolumeName(e.target.value)}
              placeholder="Create volume (e.g. media_data)"
            />
            <button className="btn btn-primary" onClick={() => void onCreateVolume()}>
              Create Volume
            </button>
          </div>
          <div className="docker-resource-table-wrap">
            <table className="docker-resource-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Driver</th>
                  <th>References</th>
                  <th>Size</th>
                  <th>Mountpoint</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {volumes.map((volume) => (
                  <tr key={volume.name}>
                    <td>
                      <span
                        className="docker-resource-table__truncate docker-resource-table__truncate--name"
                        title={volume.name}
                      >
                        {volume.name}
                      </span>
                    </td>
                    <td>{volume.driver}</td>
                    <td>{volume.ref_count}</td>
                    <td>{formatBytes(volume.size_bytes)}</td>
                    <td>
                      {volume.mountpoint ? (
                        <span
                          className="docker-resource-table__truncate docker-resource-table__truncate--mountpoint"
                          title={volume.mountpoint}
                        >
                          {volume.mountpoint}
                        </span>
                      ) : (
                        '-'
                      )}
                    </td>
                    <td>
                      <button
                        className="btn btn-danger"
                        onClick={() => void onDeleteVolume(volume.name)}
                        disabled={volume.in_use}
                        title={volume.in_use ? 'Volume is in use' : 'Delete volume'}
                      >
                        {volume.in_use ? 'In Use' : 'Delete'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {volumes.length === 0 && <p className="docker-resource-empty">No volumes found.</p>}
          </div>
        </section>

        <section className="card docker-resource-card">
          <h2>Disks</h2>
          <div className="docker-resource-table-wrap">
            <table className="docker-resource-table">
              <thead>
                <tr>
                  <th>Mountpoint</th>
                  <th>Device</th>
                  <th>Filesystem</th>
                  <th>Used</th>
                  <th>Total</th>
                  <th>Free</th>
                  <th>Usage</th>
                </tr>
              </thead>
              <tbody>
                {disks.map((disk) => (
                  <tr key={`${disk.device}-${disk.mountpoint}`}>
                    <td>
                      <span
                        className="docker-resource-table__truncate docker-resource-table__truncate--mountpoint"
                        title={disk.mountpoint}
                      >
                        {disk.mountpoint}
                      </span>
                    </td>
                    <td>
                      {disk.device ? (
                        <span
                          className="docker-resource-table__truncate docker-resource-table__truncate--device"
                          title={disk.device}
                        >
                          {disk.device}
                        </span>
                      ) : (
                        '-'
                      )}
                    </td>
                    <td>{disk.fstype || '-'}</td>
                    <td>{formatBytes(disk.used_bytes)}</td>
                    <td>{formatBytes(disk.total_bytes)}</td>
                    <td>{formatBytes(disk.free_bytes)}</td>
                    <td>{disk.percent.toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {disks.length === 0 && <p className="docker-resource-empty">No disk partitions found.</p>}
          </div>
        </section>

        <section className="card docker-resource-card">
          <h2>Networks</h2>
          <div className="docker-resource-table-wrap">
            <table className="docker-resource-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Driver</th>
                  <th>Containers</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {networks.map((network) => (
                  <tr key={network.id}>
                    <td>{network.name}</td>
                    <td>{network.driver}</td>
                    <td>{network.containers}</td>
                    <td>
                      <button
                        className="btn btn-danger"
                        onClick={() => void onDeleteNetwork(network.id, network.name)}
                        disabled={network.protected || network.containers > 0}
                        title={
                          network.protected
                            ? 'Protected Docker network'
                            : network.containers > 0
                              ? 'Network has attached containers'
                              : 'Delete network'
                        }
                      >
                        {network.protected ? 'Protected' : network.containers > 0 ? 'In Use' : 'Delete'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {networks.length === 0 && <p className="docker-resource-empty">No networks found.</p>}
          </div>
        </section>
      </div>
    </div>
  );
}
