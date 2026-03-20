/**
 * MetricChart — Renders an AreaChart for system metrics history.
 *
 * Built with Recharts. Automatically resizes to fit its container.
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
import type { ChartPoint } from '../hooks/useMetricsWS';
import './MetricChart.css';

interface MetricChartProps {
  /** Chart title. */
  title: string;
  /** Array of history points (from WebSocket or API). */
  data: ChartPoint[];
  /** Key in ChartPoint to plot on the Y axis. */
  dataKey: keyof ChartPoint;
  /** Primary color for the area fill and line. */
  color: string;
  /** Value unit for tooltip formatting. */
  unit?: string;
  /** Max Y-axis value. Defaults to 'auto'. Set to 100 for percentage charts. */
  yMax?: number | 'auto';
}

export default function MetricChart({
  title,
  data,
  dataKey,
  color,
  unit = '',
  yMax = 'auto',
}: MetricChartProps) {
  // Generate a unique ID for the stable gradient definition
  const gradientId = `color-${dataKey as string}`;

  return (
    <div className="card metric-chart">
      <h3 className="metric-chart__title">{title}</h3>
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
              dataKey="time"
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
              tickFormatter={(val: number) => `${val}${unit}`}
              domain={[0, yMax]}
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
              formatter={(value: number) => [`${value.toFixed(1)}${unit}`, title]}
              labelStyle={{ color: 'var(--color-text-muted)', marginBottom: '4px' }}
            />
            <Area
              type="monotone"
              dataKey={dataKey}
              stroke={color}
              strokeWidth={2}
              fillOpacity={1}
              fill={`url(#${gradientId})`}
              isAnimationActive={false} // Disable to prevent jerky re-renders on rapid WS updates
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
