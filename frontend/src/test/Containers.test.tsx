/**
 * Containers page regressions:
 * - initial loading / backend error / empty-success states are distinct; the
 *   error state never leaks raw backend detail (socket URLs) into the UI
 * - a failed refresh keeps the last good list and marks it stale
 * - a stale in-flight list response cannot clobber a newer one
 * - selecting a container never re-fetches the list; details are bound to
 *   the clicked container
 * - lifecycle notices resolving after a selection switch are dropped
 * - log stream errors surface in the Logs panel, sanitized, not as page errors
 */

import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => {
  class FakeEventSource {
    static instances: FakeEventSource[] = [];
    url = '';
    onmessage: ((event: { data: string }) => void) | null = null;
    constructor(url: URL | string) {
      this.url = url.toString();
      FakeEventSource.instances.push(this);
    }
    addEventListener = vi.fn();
    close = vi.fn();
  }
  return { FakeEventSource };
});

vi.mock('eventsource', () => ({ EventSource: h.FakeEventSource }));
vi.mock('@uiw/react-codemirror', () => ({ default: () => null }));
vi.mock('@codemirror/lang-yaml', () => ({ yaml: () => [] }));
vi.mock('../components/ExecTerminal', () => ({
  default: (props: { containerId: string }) => (
    <div data-testid="exec-terminal-mock">{props.containerId}</div>
  ),
}));
vi.mock('../api/authApi', () => ({ authenticatedFetch: vi.fn() }));
vi.mock('../api/marketplaceApi', () => ({ fetchInstalledApps: vi.fn() }));
vi.mock('../api/containersApi', () => ({
  fetchContainers: vi.fn(),
  fetchContainer: vi.fn(),
  fetchContainerStats: vi.fn(),
  fetchCompose: vi.fn(),
  fetchEnvText: vi.fn(),
  removeContainer: vi.fn(),
  runContainerAction: vi.fn(),
  applyContainerChanges: vi.fn(),
  updateCompose: vi.fn(),
  updateEnvText: vi.fn(),
}));

import {
  fetchCompose,
  fetchContainer,
  fetchContainerStats,
  fetchContainers,
  fetchEnvText,
  runContainerAction,
} from '../api/containersApi';
import { fetchInstalledApps } from '../api/marketplaceApi';
import Containers from '../pages/Containers';
import type { ContainerDetail, ContainerItem, ContainerStats } from '../types/containers';

function makeItem(id: string, name: string, image?: string): ContainerItem {
  return {
    id,
    name,
    status: 'running',
    image: image ?? `${name}:latest`,
    created: '',
    labels: {},
    ports: {},
  };
}

function makeDetail(id: string, name: string): ContainerDetail {
  return {
    ...makeItem(id, name),
    raw: { command: null, entrypoint: null, mounts: [], env_count: 0 },
  };
}

function makeStats(id: string): ContainerStats {
  return {
    id,
    name: id,
    status: 'running',
    cpu_percent: 0.5,
    memory_usage_mb: 12,
    memory_limit_mb: 512,
  };
}

const RAW_DOCKER_ERROR =
  'Docker unavailable: Error while fetching server API version: http+docker://localnpipe/501 Server Error';

beforeEach(() => {
  vi.clearAllMocks();
  h.FakeEventSource.instances.length = 0;
  vi.mocked(fetchInstalledApps).mockResolvedValue([]);
  vi.mocked(fetchContainerStats).mockImplementation(async (id: string) => makeStats(id));
  vi.mocked(fetchCompose).mockResolvedValue({ path: '/opt/compose.yml', content: '' });
  vi.mocked(fetchEnvText).mockResolvedValue({ content: '' });
  vi.mocked(fetchContainer).mockImplementation(async (id: string) => makeDetail(id, id));
});

function listButtons() {
  return screen
    .getAllByRole('button')
    .filter((button) => button.closest('[data-testid="containers-list"]'));
}

describe('Containers list states', () => {
  it('shows a loading state first, without the two empty panels', () => {
    vi.mocked(fetchContainers).mockImplementation(() => new Promise(() => {}));
    render(<Containers />);

    expect(screen.getByTestId('containers-loading')).toBeInTheDocument();
    expect(screen.getByText('Loading containers…')).toBeInTheDocument();
    expect(screen.queryByTestId('containers-list')).not.toBeInTheDocument();
    expect(screen.queryByTestId(/containers-error|containers-stale/)).not.toBeInTheDocument();
  });

  it('first-load failure shows a concise Docker error with Retry, hiding raw backend detail', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    try {
      vi.mocked(fetchContainers).mockRejectedValueOnce(new Error(RAW_DOCKER_ERROR));
      render(<Containers />);

      expect(await screen.findByTestId('containers-error')).toBeInTheDocument();
      expect(screen.getByText('Docker unavailable')).toBeInTheDocument();
      expect(screen.getByText(/could not reach the Docker daemon/i)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
      // Raw internals never reach the UI, and the failure is not dressed up as "no containers".
      expect(screen.queryByText(/No containers found/)).not.toBeInTheDocument();
      expect(screen.queryByTestId('containers-list')).not.toBeInTheDocument();
      // The console gets a fixed log line, never the raw error object.
      expect(console.error).toHaveBeenCalledWith('Failed to load containers');
      expect(document.body.textContent).not.toMatch(/http\+docker/);
      expect(document.body.textContent).not.toMatch(/localnpipe/);

      // Retry resolves to a healthy list.
      vi.mocked(fetchContainers).mockResolvedValueOnce([makeItem('a1', 'nginx')]);
      fireEvent.click(screen.getByTestId('containers-retry'));

      expect(await screen.findByTestId('containers-list')).toBeInTheDocument();
      expect(screen.getByText('nginx')).toBeInTheDocument();
      expect(screen.queryByTestId('containers-error')).not.toBeInTheDocument();
    } finally {
      consoleError.mockRestore();
    }
  });

  it('offline/network failures get the generic title, not a Docker verdict', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    try {
      vi.mocked(fetchContainers).mockRejectedValueOnce(new Error('Failed to fetch'));
      render(<Containers />);

      expect(await screen.findByTestId('containers-error')).toBeInTheDocument();
      expect(screen.getByText('Could not load containers')).toBeInTheDocument();
      expect(screen.queryByText('Docker unavailable')).not.toBeInTheDocument();
      expect(console.error).toHaveBeenCalledWith('Failed to load containers');
    } finally {
      consoleError.mockRestore();
    }
  });

  it('successful empty list shows "No containers found.", not an error', async () => {
    vi.mocked(fetchContainers).mockResolvedValue([]);
    render(<Containers />);

    expect(await screen.findByTestId('containers-empty-list')).toBeInTheDocument();
    expect(screen.getByText('No containers found.')).toBeInTheDocument();
    expect(screen.queryByTestId('containers-error')).not.toBeInTheDocument();
    expect(screen.queryByTestId('containers-stale')).not.toBeInTheDocument();
  });
});

describe('refresh keeps a good list', () => {
  it('a failed refresh keeps the loaded list and marks it stale without raw detail', async () => {
    vi.mocked(fetchContainers)
      .mockResolvedValueOnce([makeItem('a1', 'nginx'), makeItem('b2', 'redis')])
      .mockRejectedValueOnce(
        new Error('Docker unavailable: 501 Server Error http://localhost:2375/v1.41/containers/json'),
      );
    render(<Containers />);
    expect(await screen.findByText('redis')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('containers-refresh'));

    expect(await screen.findByTestId('containers-stale')).toBeInTheDocument();
    expect(screen.getByText(/may be out of date/)).toBeInTheDocument();
    // The last good list is still rendered — no "No containers found" under the banner.
    expect(screen.getByText('nginx')).toBeInTheDocument();
    expect(screen.getByText('redis')).toBeInTheDocument();
    expect(screen.queryByText(/No containers found/)).not.toBeInTheDocument();
    expect(screen.queryByTestId('containers-error')).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/localhost:2375/);
  });

  it('ignores a slower stale list response after a newer request resolved', async () => {
    vi.mocked(fetchContainers)
      .mockImplementationOnce(
        () => new Promise((resolve) => setTimeout(() => resolve([makeItem('o1', 'old-box')]), 40)),
      )
      .mockImplementationOnce(async () => [makeItem('n1', 'new-box')]);
    render(<Containers />);

    // Change the filter before the slow first response lands.
    fireEvent.click(screen.getByLabelText('Include stopped'));

    expect(await screen.findByText('new-box')).toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 60)); // the stale response lands now
    expect(screen.queryByText('old-box')).not.toBeInTheDocument();
    expect(screen.getByText('new-box')).toBeInTheDocument();
  });
});

describe('search', () => {
  it('narrows the list by name and image, with its own empty message', async () => {
    vi.mocked(fetchContainers).mockResolvedValue([
      makeItem('a1', 'nginx'),
      makeItem('b2', 'redis'),
      makeItem('c3', 'myapp', 'ghcr.io/acme/myapp:1'),
    ]);
    render(<Containers />);

    expect(await screen.findByTestId('containers-list')).toBeInTheDocument();
    expect(screen.getByText('nginx')).toBeInTheDocument();
    expect(screen.getByText('redis')).toBeInTheDocument();
    expect(screen.getByText('myapp')).toBeInTheDocument();

    fireEvent.change(screen.getByTestId('containers-search'), { target: { value: 'redis' } });
    expect(screen.getByText('redis')).toBeInTheDocument();
    expect(screen.queryByText('nginx')).not.toBeInTheDocument();
    expect(screen.queryByText('myapp')).not.toBeInTheDocument();

    fireEvent.change(screen.getByTestId('containers-search'), { target: { value: 'ghcr.io' } });
    expect(screen.getByText('myapp')).toBeInTheDocument();
    expect(screen.queryByText('nginx')).not.toBeInTheDocument();

    fireEvent.change(screen.getByTestId('containers-search'), { target: { value: 'zzz' } });
    expect(await screen.findByText('No containers match your search.')).toBeInTheDocument();

    fireEvent.change(screen.getByTestId('containers-search'), { target: { value: '' } });
    expect(await screen.findByText('nginx')).toBeInTheDocument();
    expect(screen.getByText('redis')).toBeInTheDocument();
    expect(screen.getByText('myapp')).toBeInTheDocument();
  });
});

describe('selection', () => {
  it('selecting a container does not re-fetch the list and binds details to the clicked one', async () => {
    vi.mocked(fetchContainers).mockResolvedValue([makeItem('a1', 'nginx'), makeItem('b2', 'redis')]);
    vi.mocked(fetchContainer).mockImplementation(
      async (id: string) => makeDetail(id, id === 'b2' ? 'redis' : 'nginx'),
    );
    render(<Containers />);
    expect(await screen.findByText('redis')).toBeInTheDocument();
    await waitFor(() => expect(fetchContainer).toHaveBeenCalledWith('a1'));
    const listCallsAfterLoad = vi.mocked(fetchContainers).mock.calls.length;

    fireEvent.click(screen.getByRole('button', { name: /redis/ }));

    await waitFor(() => expect(fetchContainer).toHaveBeenCalledWith('b2'));
    // The detail panel shows the clicked container, not the previous one.
    await waitFor(() => {
      within(screen.getByTestId('containers-detail')).getByText('redis');
    });
    expect(screen.getByRole('button', { name: /redis/ })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: /nginx/ })).toHaveAttribute('aria-pressed', 'false');
    // Selecting must not re-run the list fetch.
    expect(vi.mocked(fetchContainers).mock.calls.length).toBe(listCallsAfterLoad);
  });

  it('never renders one container\'s details with another container\'s terminal', async () => {
    vi.mocked(fetchContainers).mockResolvedValue([makeItem('a1', 'nginx'), makeItem('b2', 'redis')]);
    let resolveA1!: (detail: ContainerDetail) => void;
    vi.mocked(fetchContainer).mockImplementation((id: string) => {
      if (id === 'a1') {
        return new Promise<ContainerDetail>((resolve) => {
          resolveA1 = resolve;
        });
      }
      return Promise.resolve(makeDetail('b2', 'redis'));
    });
    render(<Containers />);

    // a1 is auto-selected; its details are still in flight.
    const detail = await screen.findByTestId('containers-detail');
    expect(await screen.findByText('Loading container details…')).toBeInTheDocument();

    // Switch to b2 while a1's payload is still pending.
    fireEvent.click(screen.getByRole('button', { name: /redis/ }));
    expect(await screen.findByTestId('exec-terminal-mock')).toHaveTextContent('b2');

    // a1's response lands after the switch: it must not leak into the panel.
    await act(async () => {
      resolveA1(makeDetail('a1', 'nginx'));
    });
    expect(within(detail).queryByText('nginx')).not.toBeInTheDocument();
    await waitFor(() => {
      within(detail).getByText('redis');
    });
  });

  it('drops a lifecycle success notice that resolves after the user switched containers', async () => {
    vi.mocked(fetchContainers).mockResolvedValue([makeItem('a1', 'nginx'), makeItem('b2', 'redis')]);
    vi.mocked(fetchContainer).mockImplementation(
      async (id: string) => makeDetail(id, id === 'b2' ? 'redis' : 'nginx'),
    );
    let resolveAction!: () => void;
    vi.mocked(runContainerAction).mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          resolveAction = resolve;
        }),
    );
    render(<Containers />);
    // Wait until the auto-selected container's detail panel is interactive.
    await screen.findByRole('button', { name: 'Start' });

    // Start on the auto-selected first container, then switch mid-flight.
    fireEvent.click(screen.getByRole('button', { name: 'Start' }));
    fireEvent.click(screen.getByRole('button', { name: /redis/ }));

    resolveAction();
    await waitFor(() => expect(fetchContainers).toHaveBeenCalledTimes(2)); // post-action refresh ran
    expect(screen.queryByText(/executed successfully/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Action start/i)).not.toBeInTheDocument();
  });
});

describe('detail 404 recovery', () => {
  it('keeps a listed-but-missing ID at one list refetch, no eternal loading, neutral notice', async () => {
    vi.mocked(fetchContainers).mockResolvedValue([makeItem('a1', 'nginx'), makeItem('b2', 'redis')]);
    vi.mocked(fetchContainer).mockImplementation(async () => {
      throw new Error('Container not found');
    });
    render(<Containers />);

    // Initial load + exactly one recovery refetch — the list still contains a1,
    // so the selection does not change and the effect must not loop.
    await waitFor(() => expect(fetchContainers).toHaveBeenCalledTimes(2));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(fetchContainers).toHaveBeenCalledTimes(2);

    // Neutral notice (it may or may not switch the selection).
    expect(
      screen.getByText('Selected container was not found. Refreshing the container list.'),
    ).toBeInTheDocument();
    // The panel shows the failed state, not an eternal "Loading container details…".
    expect(
      within(screen.getByTestId('containers-detail')).getByText('Failed to load container details.'),
    ).toBeInTheDocument();
    expect(
      within(screen.getByTestId('containers-detail')).queryByText('Loading container details…'),
    ).not.toBeInTheDocument();
    // The list itself stays untouched.
    expect(screen.getByText('nginx')).toBeInTheDocument();
  });
});

describe('log stream errors', () => {
  it('surface sanitized in the Logs panel, not as a page-level error', async () => {
    vi.mocked(fetchContainers).mockResolvedValue([makeItem('a1', 'nginx')]);
    render(<Containers />);

    expect(await screen.findByText('Logs')).toBeInTheDocument();
    const sse = h.FakeEventSource.instances.at(-1);
    expect(sse).toBeDefined();
    await act(async () => {
      sse!.onmessage?.({
        data: JSON.stringify({ error: 'Docker logs failed: http+docker://localnpipe/boom' }),
      });
    });

    expect(await screen.findByTestId('containers-logs-error')).toHaveTextContent(
      '(see server logs)',
    );
    expect(document.body.textContent).not.toMatch(/localnpipe/);
    // List stays populated; the page-level error notice stayed empty.
    expect(screen.getByText('nginx')).toBeInTheDocument();
    expect(screen.queryByText(/No containers found/)).not.toBeInTheDocument();
    expect(listButtons().length).toBe(1);
  });
});
