/**
 * Homelab Dashboard — Application Root
 *
 * Sets up React Router with the following route structure:
 * - /login — Authentication page (no sidebar)
 * - /dashboard — Main dashboard with system metrics
 * - /containers — Docker container management
 * - /docker-resources — Docker volumes and networks management
 * - /marketplace — App marketplace (placeholder)
 * - /domains — Domain and SSL management (placeholder)
 * - /backup — Backup & Restore (placeholder)
 * - /security — Security & audit log (placeholder)
 * - /settings — Dashboard settings (placeholder)
 */

import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import MainLayout from './layouts/MainLayout';
import { fetchSetupStatus } from './api/setupApi';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import Containers from './pages/Containers';
import DockerResources from './pages/DockerResources';
import Marketplace from './pages/Marketplace';
import Domains from './pages/Domains';
import SetupWizard from './pages/SetupWizard';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 30_000, // 30 seconds
    },
  },
});

/**
 * Placeholder page component for routes not yet implemented.
 */
function ComingSoon({ title }: { title: string }) {
  return (
    <div>
      <h1 style={{ fontSize: 'var(--text-3xl)', fontWeight: 700, marginBottom: 'var(--space-md)' }}>
        {title}
      </h1>
      <div className="card">
        <p style={{ color: 'var(--color-text-secondary)' }}>
          🚧 This page will be implemented in a future phase.
        </p>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppRoutes />
    </QueryClientProvider>
  );
}

function AppRoutes() {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['setup-status'],
    queryFn: fetchSetupStatus,
  });

  if (isLoading) {
    return (
      <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: '1rem' }}>
        <div className="card">Checking setup status...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: '1rem' }}>
        <div className="card" style={{ display: 'grid', gap: '1rem', maxWidth: 520 }}>
          <h1 style={{ fontSize: 'var(--text-2xl)', fontWeight: 700 }}>Setup status unavailable</h1>
          <p style={{ color: 'var(--color-text-secondary)' }}>
            {error instanceof Error ? error.message : 'Could not reach backend setup endpoint.'}
          </p>
          <button className="btn btn-primary" onClick={() => void refetch()}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  const initialized = Boolean(data?.initialized);

  return (
    <BrowserRouter>
      {!initialized ? (
        <Routes>
          <Route path="/setup" element={<SetupWizard onInitialized={async () => {
            await refetch();
          }} />} />
          <Route path="*" element={<Navigate to="/setup" replace />} />
        </Routes>
      ) : (
        <Routes>
          {/* Auth routes — no sidebar */}
          <Route path="/login" element={<Login />} />

          {/* App routes — with sidebar layout */}
          <Route element={<MainLayout />}>
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/containers" element={<Containers />} />
            <Route path="/docker-resources" element={<DockerResources />} />
            <Route path="/marketplace" element={<Marketplace />} />
            <Route path="/domains" element={<Domains />} />
            <Route path="/backup" element={<ComingSoon title="Backup & Restore" />} />
            <Route path="/security" element={<ComingSoon title="Security" />} />
            <Route path="/settings" element={<ComingSoon title="Settings" />} />
          </Route>

          {/* Default redirect */}
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      )}
    </BrowserRouter>
  );
}
