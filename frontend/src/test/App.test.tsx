/**
 * Tests for the App component — verifies routing and basic rendering.
 */
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Login from '../pages/Login';
import Dashboard from '../pages/Dashboard';

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({
    user: null,
    loading: false,
    establishSession: vi.fn(),
    signOut: vi.fn(),
    reloadSession: vi.fn(),
  }),
}));

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});

function renderWithProviders(ui: React.ReactElement, { route = '/' } = {}) {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Login Page', () => {
  it('renders login form with username and password fields', () => {
    renderWithProviders(<Login />);

    expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
  });

  it('renders the Homelab Dashboard title', () => {
    renderWithProviders(<Login />);

    expect(screen.getByText('Homelab Dashboard')).toBeInTheDocument();
  });

  it('has correct form element IDs for testing', () => {
    renderWithProviders(<Login />);

    expect(document.getElementById('username')).toBeInTheDocument();
    expect(document.getElementById('password')).toBeInTheDocument();
    expect(document.getElementById('login-submit')).toBeInTheDocument();
    expect(document.getElementById('login-form')).toBeInTheDocument();
  });
});

describe('Dashboard Page', () => {
  it('renders dashboard title', () => {
    renderWithProviders(<Dashboard />);

    expect(screen.getByText('System Overview')).toBeInTheDocument();
  });

  it('shows KPI cards and the explicit hour window', () => {
    renderWithProviders(<Dashboard />);

    expect(screen.getByText('CPU Usage')).toBeInTheDocument();
    expect(screen.getByText('Memory')).toBeInTheDocument();
    expect(screen.getByText('Disk Usage')).toBeInTheDocument();
    expect(screen.getByText('Containers')).toBeInTheDocument();
    expect(screen.getByText(/Backend filesystem/)).toBeInTheDocument();
    expect(screen.getAllByText(/Last hour/).length).toBeGreaterThan(0);
    expect(screen.getByText('No data yet')).toBeInTheDocument();
  });

  it('shows CPU, RAM and network charts but no disk history', () => {
    renderWithProviders(<Dashboard />);

    expect(screen.getByText('CPU Usage History')).toBeInTheDocument();
    expect(screen.getByText('Memory History')).toBeInTheDocument();
    expect(screen.getByText('Network Throughput')).toBeInTheDocument();
    expect(screen.queryByText('Disk Space History')).not.toBeInTheDocument();
  });
});
