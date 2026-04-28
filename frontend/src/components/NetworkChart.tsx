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
import './MetricChart.css';

export interface NetworkChartPoint {
  time: string;
  sent_rate_mb_s: number;
  recv_rate_mb_s: number;
}

interface NetworkChartProps {
  title: string;
  data: NetworkChartPoint[];
}

function formatRate(value: number): string {
  return `${value.toFixed(2)} MB/s`;
}

export default function NetworkChart({ title, data }: NetworkChartProps) {
  return (
    <div className="card metric-chart">
      <h3 className="metric-chart__title">{title}</h3>
      <div className="metric-chart__container">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
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
              domain={[0, 'auto']}
              tickFormatter={(val: unknown) => `${Number(val).toFixed(1)} MB/s`}
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
              labelStyle={{ color: 'var(--color-text-muted)', marginBottom: '4px' }}
            />
            <Legend
              verticalAlign="top"
              align="right"
              wrapperStyle={{ color: 'var(--color-text-muted)', fontSize: '12px' }}
            />
            <Line
              type="monotone"
              dataKey="sent_rate_mb_s"
              name="Network Sent"
              stroke="var(--color-success)"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="recv_rate_mb_s"
              name="Network Received"
              stroke="var(--color-accent)"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
