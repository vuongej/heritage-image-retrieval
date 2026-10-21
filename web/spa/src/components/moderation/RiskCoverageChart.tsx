import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { VerifyReport } from '@/api/metricsAdapter';
import { fmtPct } from '@/lib/format';

const COLORS: Record<string, string> = { head: '#4F46E5', jev: '#0E7490' };

/** Proxy risk–coverage: agreement with the VLM teacher, NOT accuracy against human labels. */
export function RiskCoverageChart({ r }: { r: VerifyReport }) {
  const layers = Object.entries(r.layers_proxy_eval);
  const byCoverage = new Map<number, Record<string, number>>();
  for (const [name, layer] of layers) {
    for (const p of layer.risk_coverage.points ?? []) {
      const row = byCoverage.get(p.coverage) ?? { coverage: p.coverage };
      row[name] = p.acc_keep;
      byCoverage.set(p.coverage, row);
    }
  }
  const data = [...byCoverage.values()].sort((a, b) => a.coverage! - b.coverage!);
  if (!data.length) return <p className="text-muted">Báo cáo không có điểm risk–coverage.</p>;
  return (
    <figure>
      <div className="h-64 w-full">
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
            <CartesianGrid stroke="#E2E8F0" strokeDasharray="3 3" />
            <XAxis dataKey="coverage" type="number" domain={['dataMin', 1]} tickFormatter={(v: number) => fmtPct(v)} tick={{ fontSize: 12 }} />
            <YAxis domain={['auto', 'auto']} tickFormatter={(v: number) => fmtPct(v)} tick={{ fontSize: 12 }} width={56} />
            <Tooltip formatter={(v: number) => fmtPct(v)} labelFormatter={(v: number) => `Coverage ${fmtPct(v)}`} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {layers.map(([name]) => (
              <Line key={name} type="monotone" dataKey={name} name={`${name} (đồng thuận khi giữ)`} stroke={COLORS[name] ?? '#64748B'} strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="mt-1 text-caption text-muted">
        Trục Y = tỉ lệ đồng thuận với nhãn VLM bootstrap trên phần ảnh được giữ (n = {r.cascade_proxy.rows ?? '—'}). Đây là proxy, không phải accuracy.
      </figcaption>
    </figure>
  );
}
