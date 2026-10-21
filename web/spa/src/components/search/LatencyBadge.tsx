import { ChevronDown, Timer } from 'lucide-react';
import { useId, useState } from 'react';
import { SLA_MS } from '@/config';
import { fmtInt, fmtMs } from '@/lib/format';
import { slaLevel } from '@/lib/sla';
import type { Timing } from '@/types/search';
import { cn } from '@/components/shared/ui';

const LEVEL = {
  ok: 'text-sla-ok',
  warn: 'text-sla-warn',
  bad: 'text-sla-bad',
  none: 'text-muted',
};

/** Only colors a MEASURED backend number; missing data shows "Chưa có số đo". */
export function LatencyBadge({ timing }: { timing: Timing }) {
  const [open, setOpen] = useState(false);
  const panel = useId();
  const total = timing.total_ms;
  const level = slaLevel(total);
  return (
    <div className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panel}
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-2.5 py-0.5 text-caption hover:bg-slate-50"
      >
        <Timer aria-hidden className="size-3.5 text-muted" />
        {total === undefined ? (
          <span className="text-muted">Chưa có số đo</span>
        ) : (
          <span className="font-mono tabular">
            <span className={cn('font-semibold', LEVEL[level])}>{fmtInt(total)} ms</span>
            <span className="text-muted"> / SLA {fmtInt(SLA_MS)} ms</span>
            {timing.cached && <span className="ml-1 rounded bg-brand-50 px-1 font-sans text-[11px] font-medium text-brand-700">cache</span>}
          </span>
        )}
        <ChevronDown aria-hidden className={cn('size-3.5 text-muted transition-transform duration-[120ms]', open && 'rotate-180')} />
      </button>
      {open && (
        <div
          id={panel}
          role="region"
          aria-label="Phân rã thời gian xử lý"
          className="absolute right-0 z-30 mt-2 w-[min(92vw,360px)] rounded-[var(--radius-card)] border border-border bg-surface p-3 text-caption shadow-lg"
        >
          <p className="mb-2 font-semibold text-text">Thời gian theo stage (backend đo)</p>
          {timing.cached && <p className="mb-2 rounded bg-brand-50 px-2 py-1 text-brand-700">Kết quả lấy từ cache — chỉ có thời gian tra cache.</p>}
          {timing.stages.length === 0 ? (
            <p className="text-muted">Backend không trả phân rã stage.</p>
          ) : (
            <table className="w-full">
              <tbody>
                {timing.stages.map((s) => (
                  <tr key={s.key} className="border-b border-border/70 last:border-0">
                    <td className="py-1 pr-2">{s.label}</td>
                    <td className="py-1 text-right font-mono tabular">{fmtMs(s.ms)}</td>
                  </tr>
                ))}
                {timing.unattributed_ms !== undefined && (
                  <tr>
                    <td className="py-1 pr-2 text-muted">Chưa phân bổ (total − Σ stage)</td>
                    <td className="py-1 text-right font-mono tabular text-muted">{fmtMs(timing.unattributed_ms)}</td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
          <dl className="mt-2 space-y-1 border-t border-border pt-2">
            <div className="flex justify-between gap-2">
              <dt>Backend total_ms</dt>
              <dd className="font-mono tabular">{fmtMs(timing.total_ms)}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt>Middleware (X-Response-Time)</dt>
              <dd className="font-mono tabular">{fmtMs(timing.middleware_ms)}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt>Trình duyệt quan sát (gồm mạng)</dt>
              <dd className="font-mono tabular">{fmtMs(timing.client_observed_ms)}</dd>
            </div>
          </dl>
          <p className="mt-2 text-muted">
            Một lần đo không chứng minh SLA. Xem tỉ lệ vi phạm trên nhiều request ở trang Benchmark.
          </p>
        </div>
      )}
    </div>
  );
}
