/**
 * MetricCard — displays a single system metric with live value and status color.
 *
 * Color coding:
 *  - green (success) : value < warning threshold
 *  - yellow (warning): value >= warning threshold
 *  - red (danger)    : value >= danger threshold
 */

import './MetricCard.css';

interface MetricCardProps {
  /** Emoji or Unicode icon shown on the left. */
  icon: string;
  /** Card label, e.g. "CPU Usage". */
  label: string;
  /** Primary numeric value to display (percentage or other). */
  value: number | null;
  /** Unit string appended to the value, e.g. "%" or " GB". */
  unit?: string;
  /** Optional secondary line, e.g. "7.6 / 16 GB". */
  subtitle?: string;
  /** Percentage at which the card turns yellow (default 70). */
  warnThreshold?: number;
  /** Percentage at which the card turns red (default 90). */
  dangerThreshold?: number;
}

function getStatusClass(value: number | null, warn: number, danger: number): string {
  if (value === null) return '';
  if (value >= danger) return 'metric-card--danger';
  if (value >= warn) return 'metric-card--warning';
  return 'metric-card--ok';
}

export default function MetricCard({
  icon,
  label,
  value,
  unit = '%',
  subtitle,
  warnThreshold = 70,
  dangerThreshold = 90,
}: MetricCardProps) {
  const statusClass = getStatusClass(value, warnThreshold, dangerThreshold);

  return (
    <div className={`card metric-card ${statusClass}`} role="region" aria-label={label}>
      <div className="metric-card__icon" aria-hidden="true">{icon}</div>
      <div className="metric-card__body">
        <span className="metric-card__label">{label}</span>
        <span className="metric-card__value">
          {value !== null ? (
            <>
              {typeof value === 'number' ? value.toFixed(1) : value}
              <span className="metric-card__unit">{unit}</span>
            </>
          ) : (
            <span className="metric-card__loading">—</span>
          )}
        </span>
        {subtitle && <span className="metric-card__subtitle">{subtitle}</span>}
      </div>
      <div className="metric-card__indicator" aria-hidden="true" />
    </div>
  );
}
