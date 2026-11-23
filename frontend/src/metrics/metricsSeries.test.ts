/**
 * Unit regressions for the System Overview time-series helpers:
 * timestamp parsing, REST/live merge, exact-hour window, network counter
 * differencing (reset/gap = invalid marker, never bridged, per source),
 * per-source "current" readout, minute bucketing (peak positions, gap
 * nulls, reset markers) and live-vs-REST bucket merging.
 */

import { describe, expect, it } from 'vitest';
import {
  bucketNetworkByMinute,
  bucketValueByMinute,
  formatRate,
  hourWindow,
  inWindow,
  latestRate,
  LIVE_MAX_DT_MS,
  mergeNetworkBuckets,
  mergeSeries,
  parseMetricsTimestamp,
  rateUnit,
  REST_MAX_DT_MS,
  toNetworkRates,
  trimToHour,
} from './metricsSeries';
import type { ChartPoint, NetworkRatePoint, ValuePoint } from './metricsSeries';

const MIN = (n: number) => n * 60_000;

function point(ts: number, over: Partial<ChartPoint> = {}): ChartPoint {
  return { ts, cpu: 10, ram: 20, net_sent: 0, net_recv: 0, ...over };
}

describe('parseMetricsTimestamp', () => {
  it('parses explicit UTC (Z) timestamps', () => {
    expect(parseMetricsTimestamp('2026-11-23T10:30:00.123Z')).toBe(Date.parse('2026-11-23T10:30:00.123Z'));
  });

  it('keeps explicit offsets instead of forcing UTC', () => {
    expect(parseMetricsTimestamp('2026-11-23T12:30:00+02:00')).toBe(Date.parse('2026-11-23T12:30:00+02:00'));
  });

  it('treats legacy naive timestamps as UTC', () => {
    expect(parseMetricsTimestamp('2026-11-23T10:30:00')).toBe(Date.parse('2026-11-23T10:30:00Z'));
  });

  it('resolves DST-ambiguous legacy wall times deterministically', () => {
    // 02:30 occurs twice in Europe on 2026-10-25 (CEST→CET): parsing must
    // not depend on the machine's zone, and merging stays ordered by the
    // resulting absolute epochs.
    const t = parseMetricsTimestamp('2026-10-25T02:30:00')!;
    expect(t).toBe(Date.UTC(2026, 9, 25, 2, 30));
    expect(parseMetricsTimestamp('2026-10-25T01:30:00')!).toBeLessThan(t);
    expect(t).toBeLessThan(parseMetricsTimestamp('2026-10-25T03:30:00')!);
  });

  it('returns null for missing or malformed values', () => {
    expect(parseMetricsTimestamp(undefined)).toBeNull();
    expect(parseMetricsTimestamp(null)).toBeNull();
    expect(parseMetricsTimestamp('not a date')).toBeNull();
  });
});

describe('mergeSeries', () => {
  it('interleaves REST and live samples chronologically regardless of length', () => {
    const rest = [point(MIN(0)), point(MIN(2))];
    const live = [point(MIN(1)), point(MIN(3))]; // live is short: below the old >5 threshold
    const merged = mergeSeries(rest, live);
    expect(merged.map((p) => p.ts)).toEqual([MIN(0), MIN(1), MIN(2), MIN(3)]);
  });

  it('drops duplicate timestamps, preferring the later (live) entry', () => {
    const rest = [point(MIN(1), { cpu: 1 })];
    const live = [point(MIN(1), { cpu: 99 }), point(MIN(2), { cpu: 50 })];
    const merged = mergeSeries(rest, live);
    expect(merged).toHaveLength(2);
    expect(merged[0].cpu).toBe(99);
  });

  it('re-merging a refetch (same REST rows) stays deduplicated', () => {
    const rest = [point(MIN(1)), point(MIN(2)), point(MIN(3))];
    const first = mergeSeries(rest, []);
    const second = mergeSeries(rest, first);
    expect(second.map((p) => p.ts)).toEqual([MIN(1), MIN(2), MIN(3)]);
  });

  it('does not collapse clock-skewed legacy REST samples into live ones', () => {
    // Legacy REST timestamps are backend-UTC while live fallback points
    // use client receive time; only exact equality dedups, so a skew keeps
    // both series intact instead of silently erasing one as a "dupe".
    const rest = [point(1_000_000, { cpu: 1 })];
    const live = [point(1_007_999, { cpu: 2 })];
    const merged = mergeSeries(rest, live);
    expect(merged).toHaveLength(2);
    expect(merged.map((p) => p.cpu)).toEqual([1, 2]);
  });
});

describe('trimToHour', () => {
  it('keeps only the last hour of samples', () => {
    const now = MIN(70);
    const points = [
      point(MIN(0)),
      point(MIN(5)),
      point(MIN(9)),
      point(MIN(10) + 30_000),
      point(MIN(70)),
    ];
    const trimmed = trimToHour(points, now);
    expect(trimmed.map((p) => p.ts)).toEqual([MIN(10) + 30_000, MIN(70)]);
  });

  it('enforces a hard cap so a fast stream cannot grow the buffer forever', () => {
    const now = MIN(10);
    const points = Array.from({ length: 6_500 }, (_, i) => point(i));
    const trimmed = trimToHour(points, now);
    expect(trimmed).toHaveLength(6_000);
  });
});

describe('toNetworkRates (per source, tolerance-bound)', () => {
  it('computes throughput only from valid consecutive samples', () => {
    const points = [
      point(0, { net_sent: 1_000, net_recv: 2_000 }),
      point(1_000, { net_sent: 2_000, net_recv: 4_000 }),
    ];
    const rates = toNetworkRates(points, LIVE_MAX_DT_MS);
    expect(rates[0]).toMatchObject({ sent_rate: null, recv_rate: null, invalid: false }); // run head
    expect(rates[1]).toMatchObject({ sent_rate: 1000, recv_rate: 2000, invalid: false });
  });

  it('never bridges a counter reset (host reboot): invalid marker, not a negative spike', () => {
    const points = [
      point(0, { net_sent: 9_000, net_recv: 9_000 }),
      point(1_000, { net_sent: 100, net_recv: 200 }),
    ];
    expect(toNetworkRates(points, LIVE_MAX_DT_MS)[1]).toMatchObject({
      sent_rate: null,
      recv_rate: null,
      invalid: true,
    });
  });

  it('marks oversize spacing as an invalid pair (gap marker)', () => {
    const points = [
      point(0, { net_sent: 0, net_recv: 0 }),
      point(30_000, { net_sent: 500, net_recv: 600 }),
    ];
    // oversize for the live tolerance, in-tolerance for the REST one —
    // each source is always differenced with its own spacing budget
    expect(toNetworkRates(points, LIVE_MAX_DT_MS)[1]).toMatchObject({ invalid: true });
    expect(toNetworkRates(points, REST_MAX_DT_MS)[1].invalid).toBe(false);
    expect(toNetworkRates(points, REST_MAX_DT_MS)[1].sent_rate).toBeCloseTo(500 / 30);
  });

  it('bridges normal 60 s REST spacing when called with the REST tolerance', () => {
    const points = [
      point(0, { net_sent: 6_000, net_recv: 0 }),
      point(60_000, { net_sent: 66_000, net_recv: 60_000 }),
    ];
    const rates = toNetworkRates(points, REST_MAX_DT_MS);
    expect(rates[1].sent_rate).toBe(1000);
    expect(rates[1].recv_rate).toBe(1000);
  });

  it('invalidates the whole pair when only one direction resets', () => {
    const points = [
      point(0, { net_sent: 5_000, net_recv: 5_000 }),
      point(1_000, { net_sent: 6_000, net_recv: 100 }),
    ];
    expect(toNetworkRates(points, LIVE_MAX_DT_MS)[1].invalid).toBe(true);
  });
});

describe('latestRate (current readout, live only)', () => {
  it('returns the newest live pair when valid', () => {
    const points = [
      point(0, { net_sent: 0, net_recv: 0 }),
      point(2_000, { net_sent: 4_096, net_recv: 64 }),
    ];
    expect(latestRate(points, LIVE_MAX_DT_MS)).toEqual({ sent_rate: 2048, recv_rate: 32 });
  });

  it('yields null when the latest pair is a reset — never digs for older pairs', () => {
    const points = [
      point(0, { net_sent: 9_000, net_recv: 9_000 }),
      point(1_000, { net_sent: 100, net_recv: 200 }),
    ];
    expect(latestRate(points, LIVE_MAX_DT_MS)).toBeNull();
  });

  it('yields null on oversize spacing (reconnect with a single fresh sample)', () => {
    const points = [
      point(0, { net_sent: 0, net_recv: 0 }),
      point(30_000, { net_sent: 3_000, net_recv: 0 }),
    ];
    expect(latestRate(points, LIVE_MAX_DT_MS)).toBeNull();
  });

  it('yields null with fewer than two samples', () => {
    expect(latestRate([point(0)], LIVE_MAX_DT_MS)).toBeNull();
    expect(latestRate([], LIVE_MAX_DT_MS)).toBeNull();
  });
});

describe('hourWindow + inWindow', () => {
  it('spans exactly one hour up to now', () => {
    const now = 26 * 3_600_000 + MIN(70) + 30_000;
    const w = hourWindow(now);
    expect(w.end).toBe(now);
    expect(w.start).toBe(now - 3_600_000);
    expect(w.bucketStarts).toHaveLength(61); // 60 full minutes + the partial one
    expect(w.bucketStarts[0]).toBeLessThanOrEqual(w.start);
    expect(w.bucketStarts.at(-1)!).toBeLessThanOrEqual(w.end);
  });

  it('puts ticks on wall-clock 10-minute boundaries inside the window', () => {
    const w = hourWindow(MIN(70) + 30_000);
    expect(w.ticks.length).toBeGreaterThanOrEqual(5);
    for (const t of w.ticks) {
      expect(t % (10 * MIN(1))).toBe(0);
      expect(t).toBeGreaterThan(w.start);
      expect(t).toBeLessThanOrEqual(w.end);
    }
  });

  it('filters boundary records by their real ts, not by bucket', () => {
    const now = MIN(70) + 30_000;
    const w = hourWindow(now);
    const points = [point(w.start - 1), point(w.start), point(w.end), point(w.end + 1)];
    expect(inWindow(points, w).map((p) => p.ts)).toEqual([w.start, w.end]);
  });
});

describe('minute buckets (CPU/RAM)', () => {
  it('keeps the peak sample per minute (short spikes survive) at its own real ts', () => {
    const buckets = hourWindow(MIN(10)).bucketStarts;
    const spikeTs = MIN(3) + 20_000;
    const samples: ValuePoint[] = [
      { ts: MIN(3) + 5_000, value: 10 },
      { ts: spikeTs, value: 95 }, // 0.8 s spike mid-minute
      { ts: MIN(3) + 40_000, value: 12 },
      { ts: MIN(4) + 10_000, value: 30 },
    ];
    const bucketed = bucketValueByMinute(samples, buckets);
    // the spike is not averaged away nor moved to the bucket boundary
    const b3 = bucketed.find((b) => b.ts === spikeTs)!;
    expect(b3.value).toBe(95);
    expect(bucketed.find((b) => b.ts === MIN(4) + 10_000)?.value).toBe(30);
    expect(bucketed.find((b) => b.ts === MIN(5))).toEqual({ ts: MIN(5), value: null });
  });

  it('emits a null entry for minutes without samples (chart line break)', () => {
    const { bucketStarts } = hourWindow(MIN(10));
    const samples: ValuePoint[] = [{ ts: MIN(0) + 5_000, value: 5 }, { ts: MIN(2) + 5_000, value: 7 }];
    const bucketed = bucketValueByMinute(samples, bucketStarts);
    expect(bucketed).toHaveLength(61);

    // Entries align 1:1 with bucketStarts, so gaps are addressable by minute.
    const byMinute = new Map(bucketed.map((entry, i) => [bucketStarts[i], entry]));
    expect(byMinute.get(MIN(1))).toEqual({ ts: MIN(1), value: null });
    expect(byMinute.get(MIN(0))).toEqual({ ts: MIN(0) + 5_000, value: 5 });
    expect(byMinute.get(MIN(2))).toEqual({ ts: MIN(2) + 5_000, value: 7 });
  });
});

describe('network minute buckets', () => {
  const buckets = hourWindow(MIN(2)).bucketStarts;

  it('summarizes independent per-direction peaks on a uniform bucket axis', () => {
    const rates: NetworkRatePoint[] = [
      { ts: MIN(1) + 10_000, sent_rate: 100, recv_rate: 400, invalid: false },
      { ts: MIN(1) + 40_000, sent_rate: 900, recv_rate: 50, invalid: false },
    ];
    const bucketed = bucketNetworkByMinute(rates, buckets);
    const b1 = bucketed.find((b) => b.ts === MIN(1))!;
    expect(b1).toMatchObject({ sent_rate: 900, recv_rate: 400, invalid: false, has: true });
  });

  it('drops a whole minute containing a reset to null — the marker is not swallowed by peaks', () => {
    const rates: NetworkRatePoint[] = [
      { ts: MIN(1) + 10_000, sent_rate: 100, recv_rate: 400, invalid: false },
      { ts: MIN(1) + 20_000, sent_rate: null, recv_rate: null, invalid: true }, // reset mid-minute
      { ts: MIN(1) + 30_000, sent_rate: 900, recv_rate: 50, invalid: false },
    ];
    const bucketed = bucketNetworkByMinute(rates, buckets);
    const b1 = bucketed.find((b) => b.ts === MIN(1))!;
    expect(b1.invalid).toBe(true);
    expect(b1.sent_rate).toBeNull();
    expect(b1.recv_rate).toBeNull();
  });

  it('marks minutes without pairs as plain empty (no invalid flag)', () => {
    const bucketed = bucketNetworkByMinute([], buckets);
    expect(bucketed.find((b) => b.ts === MIN(1))).toMatchObject({
      sent_rate: null,
      recv_rate: null,
      invalid: false,
      has: false,
    });
  });
});

describe('mergeNetworkBuckets (live wins, REST backfills)', () => {
  const buckets = hourWindow(MIN(5)).bucketStarts;

  it('prefers live minutes and backfills uncovered minutes from REST', () => {
    const live: NetworkRatePoint[] = [
      { ts: MIN(1) + 10_000, sent_rate: 100, recv_rate: 100, invalid: false },
      { ts: MIN(1) + 11_000, sent_rate: 500, recv_rate: 400, invalid: false },
    ];
    const rest: NetworkRatePoint[] = [
      { ts: MIN(1) + 30_000, sent_rate: 2_000, recv_rate: 2_000, invalid: false }, // covered by live → ignored
      { ts: MIN(2) + 10_000, sent_rate: 300, recv_rate: 200, invalid: false },   // backfill
    ];
    const merged = mergeNetworkBuckets(live, rest, buckets);
    const byMinute = new Map(merged.map((entry, i) => [buckets[i], entry]));
    expect(byMinute.get(MIN(1))).toMatchObject({ sent_rate: 500, recv_rate: 400 });
    expect(byMinute.get(MIN(2))).toMatchObject({ sent_rate: 300, recv_rate: 200 });
    expect(byMinute.get(MIN(3))).toMatchObject({ sent_rate: null, recv_rate: null });
  });

  it('a live reset keeps its break even when stored rates exist for that minute', () => {
    const live: NetworkRatePoint[] = [
      { ts: MIN(1) + 10_000, sent_rate: null, recv_rate: null, invalid: true },
    ];
    const rest: NetworkRatePoint[] = [
      { ts: MIN(1) + 30_000, sent_rate: 900, recv_rate: 900, invalid: false },
    ];
    const merged = mergeNetworkBuckets(live, rest, buckets);
    const byMinute = new Map(merged.map((entry, i) => [buckets[i], entry]));
    expect(byMinute.get(MIN(1))).toMatchObject({ sent_rate: null, recv_rate: null });
  });

  it('backfills a REST-side reset break where live has no coverage', () => {
    const rest: NetworkRatePoint[] = [
      { ts: MIN(1) + 30_000, sent_rate: null, recv_rate: null, invalid: true },
    ];
    const merged = mergeNetworkBuckets([], rest, buckets);
    const byMinute = new Map(merged.map((entry, i) => [buckets[i], entry]));
    expect(byMinute.get(MIN(1))).toMatchObject({ sent_rate: null, recv_rate: null });
  });
});

describe('formatRate', () => {
  it('scales the unit adaptively', () => {
    expect(formatRate(512)).toBe('512 B/s');
    expect(formatRate(2048)).toBe('2.0 KB/s');
    expect(formatRate(2 * 1024 * 1024)).toBe('2.0 MB/s');
    expect(formatRate(3 * 1024 ** 3)).toBe('3.0 GB/s');
  });

  it('rateUnit picks one shared unit for a whole axis from the largest rate', () => {
    expect(rateUnit(0)).toEqual({ size: 1, unit: 'B/s' });
    expect(rateUnit(512)).toEqual({ size: 1, unit: 'B/s' });
    expect(rateUnit(2048)).toEqual({ size: 1024, unit: 'KB/s' });
    expect(rateUnit(2 * 1024 * 1024)).toEqual({ size: 1024 * 1024, unit: 'MB/s' });
    expect(rateUnit(3 * 1024 ** 3)).toEqual({ size: 1024 ** 3, unit: 'GB/s' });
  });
});
