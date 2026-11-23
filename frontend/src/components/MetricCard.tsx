/**
 * MetricCard — displays a single system metric with live value and status color.
 *
 * Color coding:
 *  - green (success) : value < warning threshold
 *  - yellow (warning): value >= warning threshold
 *  - red (danger)    : value >= danger threshold
 */

import type { ReactNode } from 'react';
import './MetricCard.css';

interface MetricCardProps {
  /** Emoji or Unicode icon shown on the left. */
  icon: string;
  /** Card label, e.g. "CPU Usage". */
  label: string;
  /** Primary numeric value to display (percentage or other); null while unavailable. */
  value: number | null;
  /** Unit string appended to the value, e.g. "%" or " GB". */
  unit?: string;
  /** Optional secondary line, e.g. "7.6 / 16 GB". */
  subtitle?: string;
  /** Optional percentage (0–100) rendered as a native <meter> bar. */
  meterPercent?: number | null;
  /** Optional extra line under the subtitle (e.g. status chips). */
  below?: ReactNode;
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
  meterPercent = null,
  below,
  warnThreshold = 70,
  dangerThreshold = 90,
}: MetricCardProps) {
  const statusClass = getStatusClass(value, warnThreshold, dangerThreshold);

  return (
    <article className={`card metric-card ${statusClass}`} role="region" aria-label={label}>
      <div className="metric-card__icon" aria-hidden="true">{icon}</div>
      <div className="metric-card__body">
        <span className="metric-card__label">{label}</span>
        <span className="metric-card__value">
          {value !== null ? (
            <>
              {Number.isInteger(value) ? String(value) : value.toFixed(1)}
              {unit && <span className="metric-card__unit">{unit}</span>}
            </>
          ) : (
            <span className="metric-card__loading">—</span>
          )}
        </span>
        {subtitle && <span className="metric-card__subtitle">{subtitle}</span>}
        {meterPercent !== null && (
          <meter
            className="metric-card__meter"
            min={0}
            max={100}
            low={warnThreshold}
            high={dangerThreshold}
            optimum={0}
            value={meterPercent}
            aria-label={`${label}: ${meterPercent} percent used`}
          />
        )}
        {below && <div className="metric-card__below">{below}</div>}
      </div>
      <div className="metric-card__indicator" aria-hidden="true" />
    </article>
  );
}
