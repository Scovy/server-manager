/**
 * Pure helpers for the System Overview time series.
 *
 * Raw samples come from two sources: the REST history endpoint (stored by
 * the backend every 60 s) and the live WebSocket stream (~0.8 s). Rates are
 * only ever computed inside one source's continuous run — never across a
 * REST/WS boundary. The exact rolling hour is [now − 1 h, now]; boundary
 * records are filtered by their real ts before charting.
 *
 * Chart series are per-minute PEAKS: CPU/RAM keep the peak sample at its
 * own real ts; network peaks sit on a uniform minute-bucket axis (the UI
 * labels all three charts "per-minute peak"). Minutes without data — and
 * minutes containing an invalidated pair (counter reset / oversize gap) —
 * stay null so charts break the line instead of bridging.
 */

export const HOUR_MS = 3_600_000;
export const MINUTE_MS = 60_000;

/** Max spacing between live WS samples still treated as one continuous
 * segment (covers reconnect backoffs of a few seconds). */
export const LIVE_MAX_DT_MS = 10_000;
/** Max spacing between stored 60 s REST samples still bridged. */
export const REST_MAX_DT_MS = 90_000;
/** No usable sample for this long ⇒ stale (drives the FreshnessBadge and
 * gates the "current traffic" readout). */
export const STALE_AFTER_MS = 10_000;

/** Hard cap on buffered samples (~1 h at the 0.8 s WS cadence). */
export const MAX_RAW_POINTS = 6_000;

/** One raw sample shared by both data sources. */
export interface ChartPoint {
  /** Effective sample time in epoch ms (backend timestamp, receipt-time fallback). */
  ts: number;
  /** CPU usage percent. */
  cpu: number;
  /** RAM usage percent. */
  ram: number;
  /** Cumulative bytes sent since boot. */
  net_sent: number;
  /** Cumulative bytes received since boot. */
  net_recv: number;
}

/** Chart-ready single-metric sample; null value = no data (line break). */
export interface ValuePoint {
  ts: number;
  value: number | null;
}

/** Throughput point derived from one consecutive counter pair. */
export interface NetworkRatePoint {
  ts: number;
  sent_rate: number | null;
  recv_rate: number | null;
  /** True when the pair behind this point was invalidated (counter reset
   * or spacing above tolerance) — an explicit line-break marker. */
  invalid: boolean;
}

/** Per-minute network summary. */
export interface NetworkMinutePoint {
  /** Uniform minute-bucket start — values are per-minute peaks. */
  ts: number;
  sent_rate: number | null;
  recv_rate: number | null;
  invalid: boolean;
  /** True when the minute contained at least one computable pair. */
  has: boolean;
}

/**
 * Parse a backend timestamp into epoch ms.
 *
 * ISO strings with an explicit zone (…Z or offset) are parsed as-is.
 * Legacy naive strings (older backends) are interpreted as UTC — the
 * storage layer writes naive `datetime.utcnow()` values — which also
 * makes DST-ambiguous wall times deterministic.
 */
export function parseMetricsTimestamp(raw?: string | null): number | null {
  if (!raw) return null;
  const iso = /[Zz]$|[+-]\d{2}:?\d{2}$/.test(raw) ? raw : `${raw}Z`;
  const ts = Date.parse(iso);
  return Number.isNaN(ts) ? null : ts;
}

/**
 * Chronologically merge REST history with the live buffer, dropping
 * duplicate timestamps (the later entry — live — wins). Only exact
 * equality dedups, so clock-skewed legacy samples never erase each other.
 */
export function mergeSeries(rest: ChartPoint[], live: ChartPoint[]): ChartPoint[] {
  const all = [...rest, ...live].sort((a, b) => a.ts - b.ts);
  const out: ChartPoint[] = [];
  for (const point of all) {
    const prev = out[out.length - 1];
    if (prev && prev.ts === point.ts) out[out.length - 1] = point;
    else out.push(point);
  }
  return out;
}

/**
 * Rolling trim: keep only samples from the last hour (plus a hard cap so a
 * misbehaving backend cannot grow the buffer without bound).
 * Expects `points` sorted ascending, which the append-only buffer is.
 */
export function trimToHour(points: ChartPoint[], now: number, hourMs = HOUR_MS): ChartPoint[] {
  const cutoff = now - hourMs;
  let start = 0;
  while (start < points.length && points[start].ts < cutoff) start += 1;
  const windowed = start > 0 ? points.slice(start) : points;
  if (windowed.length <= MAX_RAW_POINTS) return windowed;
  return windowed.slice(windowed.length - MAX_RAW_POINTS);
}

function ratePair(a: ChartPoint, b: ChartPoint, maxDtMs: number): NetworkRatePoint {
  const dtMs = b.ts - a.ts;
  const sentDelta = b.net_sent - a.net_sent;
  const recvDelta = b.net_recv - a.net_recv;
  if (dtMs <= 0 || dtMs > maxDtMs || sentDelta < 0 || recvDelta < 0) {
    return { ts: b.ts, sent_rate: null, recv_rate: null, invalid: true };
  }
  return {
    ts: b.ts,
    sent_rate: (sentDelta * 1000) / dtMs,
    recv_rate: (recvDelta * 1000) / dtMs,
    invalid: false,
  };
}

/**
 * Throughput from consecutive cumulative counters, computed only inside
 * one source's continuous run (spacing ≤ maxDtMs): a counter reset or an
 * oversize gap invalidates that pair (null rates + invalid marker)
 * instead of bridging it. The first sample has no pair: null without the
 * marker. Call once per source — never mix REST and WS here.
 */
export function toNetworkRates(points: ChartPoint[], maxDtMs: number): NetworkRatePoint[] {
  if (points.length === 0) return [];
  const rates: NetworkRatePoint[] = [
    { ts: points[0].ts, sent_rate: null, recv_rate: null, invalid: false },
  ];
  for (let i = 1; i < points.length; i++) {
    rates.push(ratePair(points[i - 1], points[i], maxDtMs));
  }
  return rates;
}

/**
 * Newest computable live pair — the "current traffic" readout. Anything
 * that makes the *latest* pair unusable (reset, oversize spacing, fewer
 * than two samples) yields null; callers render '—' instead of masking
 * it as 0 and gate it on WS freshness anyway.
 */
export function latestRate(
  points: ChartPoint[],
  maxDtMs: number,
): { sent_rate: number; recv_rate: number } | null {
  if (points.length < 2) return null;
  const last = ratePair(points[points.length - 2], points[points.length - 1], maxDtMs);
  if (last.invalid) return null;
  return { sent_rate: last.sent_rate!, recv_rate: last.recv_rate! };
}

/**
 * The exact rolling hour: [now − hourMs, now]. Minute buckets cover the
 * window (61 starts); ticks sit on wall-clock 10-minute boundaries inside
 * it so they stay put between 1 s clock ticks. Charts clip overflowing
 * samples with allowDataOverflow (fixed window), so callers filter rows
 * by real ts first — see `inWindow`.
 */
export interface HourWindow {
  start: number;
  end: number;
  bucketStarts: number[];
  ticks: number[];
}

export function hourWindow(now: number, hourMs = HOUR_MS): HourWindow {
  const start = now - hourMs;
  const end = now;
  const firstBucket = Math.floor(start / MINUTE_MS) * MINUTE_MS;
  const lastBucket = Math.floor(end / MINUTE_MS) * MINUTE_MS;
  const bucketStarts: number[] = [];
  for (let t = firstBucket; t <= lastBucket; t += MINUTE_MS) bucketStarts.push(t);

  const tickStep = 10 * MINUTE_MS;
  const ticks: number[] = [];
  for (let t = Math.ceil(start / tickStep) * tickStep; t <= end; t += tickStep) ticks.push(t);

  return { start, end, bucketStarts, ticks };
}

/** Boundary filter by real sample ts, not by bucket. */
export function inWindow<T extends { ts: number }>(points: T[], window: HourWindow): T[] {
  return points.filter((p) => p.ts >= window.start && p.ts <= window.end);
}

function minuteBucket(ts: number): number {
  return Math.floor(ts / MINUTE_MS) * MINUTE_MS;
}

/**
 * One entry per minute bucket for a single-metric series, keeping the
 * PEAK sample at its own real ts (short spikes survive, and the point
 * stays inside the fixed domain). Minutes without samples become null
 * fillers — charts break the line there.
 */
export function bucketValueByMinute(samples: ValuePoint[], bucketStarts: number[]): ValuePoint[] {
  const peaks = new Map<number, { ts: number; value: number }>();
  for (const sample of samples) {
    if (sample.value === null) continue;
    const bucket = minuteBucket(sample.ts);
    const current = peaks.get(bucket);
    if (!current || sample.value > current.value) {
      peaks.set(bucket, { ts: sample.ts, value: sample.value });
    }
  }
  return bucketStarts.map((start) => {
    const peak = peaks.get(start);
    return peak ? { ts: peak.ts, value: peak.value } : { ts: start, value: null };
  });
}

/**
 * Per-minute network summary for one source. Peaks are independent per
 * direction and sit on the uniform bucket axis. A minute containing an
 * invalidated pair (reset/oversize gap) is dropped to null — the break
 * marker must not be swallowed by peaks from the same minute.
 */
export function bucketNetworkByMinute(
  rates: NetworkRatePoint[],
  bucketStarts: number[],
): NetworkMinutePoint[] {
  const buckets = new Map<number, { sent: number; recv: number; invalid: boolean; has: boolean }>();
  for (const r of rates) {
    const bucket = minuteBucket(r.ts);
    let b = buckets.get(bucket);
    if (!b) {
      b = { sent: 0, recv: 0, invalid: false, has: false };
      buckets.set(bucket, b);
    }
    if (r.invalid) {
      b.invalid = true;
      continue;
    }
    if (r.sent_rate === null || r.recv_rate === null) continue; // run head
    b.has = true;
    if (r.sent_rate > b.sent) b.sent = r.sent_rate;
    if (r.recv_rate > b.recv) b.recv = r.recv_rate;
  }

  return bucketStarts.map((start) => {
    const b = buckets.get(start);
    if (!b || (!b.has && !b.invalid)) {
      return { ts: start, sent_rate: null, recv_rate: null, invalid: false, has: false };
    }
    return {
      ts: start,
      sent_rate: b.invalid ? null : b.sent,
      recv_rate: b.invalid ? null : b.recv,
      invalid: b.invalid,
      has: b.has,
    };
  });
}

/**
 * Chart series: live minutes win; stored samples only backfill minutes the
 * live stream does not cover (no mixed REST/WS pairs anywhere). A live
 * reset marker keeps its break even where stored rates exist — both
 * sources watch the same counters, a reset invalidates both.
 */
export function mergeNetworkBuckets(
  liveRates: NetworkRatePoint[],
  restRates: NetworkRatePoint[],
  bucketStarts: number[],
): Array<{ ts: number; sent_rate: number | null; recv_rate: number | null }> {
  const live = bucketNetworkByMinute(liveRates, bucketStarts);
  const rest = bucketNetworkByMinute(restRates, bucketStarts);
  return live.map((l, i) => {
    if (l.invalid) return { ts: l.ts, sent_rate: null, recv_rate: null };
    if (l.has) return { ts: l.ts, sent_rate: l.sent_rate, recv_rate: l.recv_rate };
    const r = rest[i];
    if (r.invalid) return { ts: r.ts, sent_rate: null, recv_rate: null };
    if (r.has) return { ts: r.ts, sent_rate: r.sent_rate, recv_rate: r.recv_rate };
    return { ts: l.ts, sent_rate: null, recv_rate: null };
  });
}

/** Adaptive human-readable rate, e.g. `812 B/s`, `2.4 MB/s`, `1.1 GB/s`. */
export function formatRate(bytesPerSec: number): string {
  if (bytesPerSec < 1024) return `${bytesPerSec < 10 ? bytesPerSec.toFixed(1) : bytesPerSec.toFixed(0)} B/s`;
  const kb = bytesPerSec / 1024;
  if (kb < 1024) return `${kb < 10 ? kb.toFixed(1) : kb.toFixed(0)} KB/s`;
  const mb = kb / 1024;
  if (mb < 1024) return `${mb < 10 ? mb.toFixed(1) : mb.toFixed(0)} MB/s`;
  return `${(mb / 1024).toFixed(1)} GB/s`;
}

/**
 * One shared unit for a whole rate axis, chosen from the largest expected
 * value. Keeps mobile tick labels narrow and predictable width (the
 * tooltip keeps the fully formatted per-value units).
 */
export function rateUnit(bytesPerSec: number): { size: number; unit: string } {
  if (bytesPerSec < 1024) return { size: 1, unit: 'B/s' };
  if (bytesPerSec < 1024 ** 2) return { size: 1024, unit: 'KB/s' };
  if (bytesPerSec < 1024 ** 3) return { size: 1024 ** 2, unit: 'MB/s' };
  return { size: 1024 ** 3, unit: 'GB/s' };
}
