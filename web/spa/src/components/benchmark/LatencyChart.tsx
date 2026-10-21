import { Bar, BarChart, CartesianGrid, Legend, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { SLA_MS } from '@/config';
import { fmtMs } from '@/lib/format';

export interface KindLatency {
  kind: string;
  p50?: number | null;
  p95?: number | null;
}

export function LatencyChart({ rows }: { rows: KindLatency[] }) {
  const max = Math.max(SLA_MS, ...rows.map((r) => r.p95 ?? 0));
  return (
    <figure>
      <div className="h-64 w-full">
        <ResponsiveContainer>
          <BarChart data={rows} margin={{ top: 12, right: 16, bottom: 4, left: 0 }}>
            <CartesianGrid stroke="#E2E8F0" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="kind" tick={{ fontSize: 12 }} />
            <YAxis domain={[0, Math.ceil(max / 500) * 500]} tick={{ fontSize: 12 }} width={52} tickFormatter={(v: number) => `${v}`} />
            <Tooltip formatter={(v: number) => fmtMs(v)} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <ReferenceLine y={SLA_MS} stroke="#B91C1C" strokeDasharray="6 4" label={{ value: 'SLA 3.000 ms', position: 'insideTopRight', fontSize: 11, fill: '#B91C1C' }} />
            <Bar dataKey="p50" name="p50" fill="#818CF8" radius={[3, 3, 0, 0]} isAnimationActive={false} />
            <Bar dataKey="p95" name="p95" fill="#4F46E5" radius={[3, 3, 0, 0]} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="mt-1 text-caption text-muted">p50/p95 theo nhóm truy vấn của báo cáo (ms). Báo cáo không ghi p99/max theo từng nhóm.</figcaption>
    </figure>
  );
}
