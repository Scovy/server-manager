/**
 * MetricChart — Renders an AreaChart for a single metric over the fixed
 * one-hour window. X axis is the real numeric sample time (epoch ms),
 * with derived tick labels; missing minute buckets arrive as null values
 * and break the line instead of bridging gaps.
 */

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { ValuePoint } from '../metrics/metricsSeries';
import './MetricChart.css';

interface MetricChartProps {
  /** Chart title. */
  title: string;
  /** Minute-bucketed samples (null value = no data in that minute). */
  data: ValuePoint[];
  /** Primary color for the area fill and line. */
  color: string;
  /** Value unit for axis/tooltip formatting. */
  unit: string;
  /** Fixed X domain [start, end] in epoch ms (hourWindow). */
  xDomain: [number, number];
  /** X tick positions in epoch ms. */
  ticks: number[];
}

function formatMinute(ts: number): string {
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export default function MetricChart({
  title,
  data,
  color,
  unit,
  xDomain,
  ticks,
}: MetricChartProps) {
  // Stable, page-unique gradient id derived from the title
  const gradientId = `grad-${title.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;

  return (
    <article className="card metric-chart">
      <header className="metric-chart__header">
        <h3 className="metric-chart__title">{title}</h3>
        <span className="metric-chart__range">Last hour · per-minute peak</span>
      </header>
      <div className="metric-chart__container">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
            <defs>
              <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={color} stopOpacity={0.3} />
                <stop offset="95%" stopColor={color} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" vertical={false} />
            <XAxis
              dataKey="ts"
              type="number"
              domain={xDomain}
              ticks={ticks}
              tickFormatter={formatMinute}
              // Fixed window: overflow skews/clock drift clip instead of expanding the domain
              allowDataOverflow
              stroke="var(--color-text-muted)"
              fontSize={11}
              tickLine={false}
              axisLine={false}
              tickMargin={8}
            />
            <YAxis
              stroke="var(--color-text-muted)"
              fontSize={11}
              tickLine={false}
              axisLine={false}
              tickFormatter={(val: unknown) => `${Number(val)}${unit}`}
              domain={[0, 100]}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: 'var(--color-bg-card)',
                borderColor: 'var(--color-border)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--color-text-primary)',
                boxShadow: 'var(--shadow-md)',
              }}
              itemStyle={{ color: 'var(--color-text-primary)', fontWeight: 600 }}
              formatter={(value: unknown) => [`${(Number(value) || 0).toFixed(1)}${unit}`, title]}
              labelFormatter={(ts: unknown) => new Date(Number(ts)).toLocaleTimeString()}
              labelStyle={{ color: 'var(--color-text-muted)', marginBottom: '4px' }}
            />
            <Area
              type="monotone"
              dataKey="value"
              stroke={color}
              strokeWidth={2}
              fillOpacity={1}
              fill={`url(#${gradientId})`}
              connectNulls={false}
              isAnimationActive={false} // Disable to prevent jerky re-renders on rapid WS updates
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </article>
  );
}
