/**
 * Homelab Dashboard — Application Root
 *
 * Sets up React Router with the following route structure:
 * - /login — Authentication page (no sidebar)
 * - /dashboard — Main dashboard with system metrics
 * - /containers — Docker container management (placeholder)
 * - /marketplace — App marketplace (placeholder)
 * - /domains — Domain and SSL management (placeholder)
 * - /backup — Backup & Restore (placeholder)
 * - /security — Security & audit log (placeholder)
 * - /settings — Dashboard settings (placeholder)
 */

import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import MainLayout from './layouts/MainLayout';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import Containers from './pages/Containers';

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
      <BrowserRouter>
        <Routes>
          {/* Auth routes — no sidebar */}
          <Route path="/login" element={<Login />} />

          {/* App routes — with sidebar layout */}
          <Route element={<MainLayout />}>
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/containers" element={<Containers />} />
            <Route path="/marketplace" element={<ComingSoon title="Marketplace" />} />
            <Route path="/domains" element={<ComingSoon title="Domains & SSL" />} />
            <Route path="/backup" element={<ComingSoon title="Backup & Restore" />} />
            <Route path="/security" element={<ComingSoon title="Security" />} />
            <Route path="/settings" element={<ComingSoon title="Settings" />} />
          </Route>

          {/* Default redirect */}
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
