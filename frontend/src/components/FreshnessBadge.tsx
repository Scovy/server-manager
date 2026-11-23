/**
 * FreshnessBadge — shows whether the latest metric sample is fresh or
 * stale, plus its age measured from the sample's own time.
 *
 * The age ticker updates every second even while the stream is down, but
 * it is aria-hidden so screen readers only hear the Fresh/Stale state
 * change (role="status"), not a per-second announcement.
 */

import { useNow } from '../hooks/useNow';
import { STALE_AFTER_MS } from '../metrics/metricsSeries';
import '../pages/Dashboard.css';

function formatAge(ageMs: number): string {
  const seconds = Math.round(ageMs / 1000);
  if (seconds < 90) return `${seconds} s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `${minutes} min`;
  return `${(minutes / 60).toFixed(1)} h`;
}

export default function FreshnessBadge({ sampleTs }: { sampleTs: number | null }) {
  const now = useNow(1_000);

  if (sampleTs === null) {
    return (
      <span className="badge badge-warning status-indicator" role="status">
        <span className="status-indicator__dot" />
        No data yet
      </span>
    );
  }

  const age = Math.max(0, now - sampleTs);
  const fresh = age <= STALE_AFTER_MS;

  return (
    <span className="status-indicator-wrap">
      <span className={`badge status-indicator ${fresh ? 'badge-success' : 'badge-danger'}`} role="status">
        <span className="status-indicator__dot" />
        {fresh ? 'Fresh' : 'Stale'}
      </span>
      <span className="status-indicator__age" aria-hidden="true">
        {formatAge(age)} old
      </span>
    </span>
  );
}
