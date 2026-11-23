import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { formatRate, rateUnit } from '../metrics/metricsSeries';
import './MetricChart.css';

interface NetworkChartProps {
  title: string;
  /** Minute-bucketed per-minute peaks in bytes/s (null = break the line). */
  data: Array<{ ts: number; sent_rate: number | null; recv_rate: number | null }>;
  /** Newest live RX/TX in bytes/s; null => '—', never masked as 0. */
  currentRx: number | null;
  currentTx: number | null;
  /** Fixed X domain [start, end] in epoch ms (hourWindow). */
  xDomain: [number, number];
  /** X tick positions in epoch ms. */
  ticks: number[];
}

function formatMinute(ts: number): string {
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export default function NetworkChart({
  title,
  data,
  currentRx,
  currentTx,
  xDomain,
  ticks,
}: NetworkChartProps) {
  const rx = currentRx === null ? '—' : formatRate(currentRx);
  const tx = currentTx === null ? '—' : formatRate(currentTx);

  // One shared unit for the whole Y axis keeps tick labels narrow on
  // mobile; the tooltip keeps fully formatted per-value units.
  const peak = data.reduce((max, p) => Math.max(max, p.sent_rate ?? 0, p.recv_rate ?? 0), 0);
  const { size, unit } = rateUnit(peak);
  const axisTick = (val: unknown) => {
    const scaled = Number(val) / size;
    const text = scaled === 0 ? '0' : scaled < 10 ? scaled.toFixed(1) : String(Math.round(scaled));
    return `${text} ${unit}`;
  };

  return (
    <article className="card metric-chart">
      <header className="metric-chart__header">
        <h3 className="metric-chart__title">{title}</h3>
        <div className="metric-chart__meta">
          <span
            className="metric-chart__current"
            aria-label={`Current traffic: ${currentRx === null ? 'unavailable' : `${rx} received`}, ${currentTx === null ? 'unavailable' : `${tx} sent`}`}
          >
            <span aria-hidden="true">↓ {rx}</span>
            <span aria-hidden="true">↑ {tx}</span>
          </span>
          <span className="metric-chart__range">Last hour · per-minute peak</span>
        </div>
      </header>
      <div className="metric-chart__container">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
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
              width={56}
              stroke="var(--color-text-muted)"
              fontSize={11}
              tickLine={false}
              axisLine={false}
              domain={[0, 'auto']}
              tickFormatter={axisTick}
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
              formatter={(value: unknown, name) => [
                formatRate(Number(value) || 0),
                String(name ?? ''),
              ]}
              labelFormatter={(ts: unknown) => new Date(Number(ts)).toLocaleTimeString()}
              labelStyle={{ color: 'var(--color-text-muted)', marginBottom: '4px' }}
            />
            <Legend
              verticalAlign="top"
              align="right"
              wrapperStyle={{ color: 'var(--color-text-muted)', fontSize: '12px' }}
            />
            <Line
              type="monotone"
              dataKey="sent_rate"
              name="TX (sent)"
              stroke="var(--color-success)"
              strokeWidth={2}
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="recv_rate"
              name="RX (received)"
              stroke="var(--color-accent)"
              strokeWidth={2}
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </article>
  );
}
