import { useEffect, useState } from 'react';
import {
  deleteNetwork,
  deleteVolume,
  fetchNetworks,
  fetchVolumes,
} from '../api/dockerResourcesApi';
import type { DockerNetwork, DockerVolume } from '../types/dockerResources';
import './DockerResources.css';

export default function DockerResources() {
  const [volumes, setVolumes] = useState<DockerVolume[]>([]);
  const [networks, setNetworks] = useState<DockerNetwork[]>([]);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  async function loadResources() {
    try {
      const [volData, netData] = await Promise.all([fetchVolumes(), fetchNetworks()]);
      setVolumes(volData);
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
          <h1 className="docker-resources-page__title">Docker Resources</h1>
          <p className="docker-resources-page__subtitle">Manage volumes and networks</p>
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
          <div className="docker-resource-table-wrap">
            <table className="docker-resource-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Driver</th>
                  <th>Scope</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {volumes.map((volume) => (
                  <tr key={volume.name}>
                    <td>{volume.name}</td>
                    <td>{volume.driver}</td>
                    <td>{volume.scope}</td>
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
