import { ArrowDown, ArrowRight, GitBranch } from 'lucide-react';
import type { ReactNode } from 'react';
import { fmtInt, fmtPct } from '@/lib/format';
import type { VerifyReport } from '@/api/metricsAdapter';
import { Mono } from '@/components/shared/ui';

function Stage({ title, input, output, children, tone = 'main' }: { title: string; input?: ReactNode; output?: ReactNode; children?: ReactNode; tone?: 'main' | 'branch' }) {
  return (
    <li
      className={
        tone === 'branch'
          ? 'rounded-[var(--radius-card)] border border-dashed border-amber-400 bg-amber-50/60 p-3'
          : 'rounded-[var(--radius-card)] border border-border bg-surface p-3'
      }
    >
      <p className="text-[13.5px] font-semibold">{title}</p>
      {(input !== undefined || output !== undefined) && (
        <p className="mt-1 flex flex-wrap items-center gap-1 font-mono text-[12.5px] tabular">
          {input !== undefined && <span>{input}</span>}
          {input !== undefined && output !== undefined && <ArrowRight aria-label="thành" className="size-3.5 text-muted" />}
          {output !== undefined && <span className="font-semibold">{output}</span>}
        </p>
      )}
      {children && <div className="mt-1 text-caption leading-relaxed text-muted">{children}</div>}
    </li>
  );
}

const Down = () => (
  <li aria-hidden className="flex justify-center py-0.5 text-slate-400">
    <ArrowDown className="size-4" />
  </li>
);

/** Branch-aware flow: the VLM step is a sampled side branch, not a stage every image passes. */
export function PipelineFlow({ r }: { r: VerifyReport }) {
  const rules = Object.entries(r.gate.by_rule)
    .map(([k, v]) => `${k}: ${fmtInt(v)}`)
    .join(' · ');
  const pilot = r.pilot_rows ?? undefined;
  const fetchOk = r.fetch.ok;
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,340px)]">
      <ol aria-label="Luồng chính" className="space-y-0">
        <Stage title="S0 · Gate theo rule (toàn bộ CSV)" input={`${fmtInt(r.gate.source_rows)} dòng`} output={`${fmtInt(r.gate.live_rows)} sống`}>
          Loại {fmtInt(r.gate.rejected_rows)} dòng theo rule ({rules}). Một dòng có thể vi phạm nhiều rule — không cộng như nhóm loại trừ.
        </Stage>
        <Down />
        <Stage title="S2b · Chia train/val/test theo nhóm thực thể" output={Object.entries(r.split.rows).map(([k, v]) => `${k} ${fmtInt(v)}`).join(' · ')}>
          Chia theo nhóm để tránh rò rỉ thực thể giữa các tập.
        </Stage>
        <Down />
        <Stage title={`Pilot · ${fmtInt(r.pilot_groups)} nhóm thực thể`} output={`${fmtInt(pilot)} dòng`}>
          Chỉ phần pilot đi qua các stage tải ảnh và mô hình bên dưới.
        </Stage>
        <Down />
        <Stage title="S1 · Tải ảnh + khử trùng sha256" input={`${fmtInt(pilot)}`} output={`${fmtInt(fetchOk)} tải được`}>
          {Object.entries(r.fetch)
            .map(([k, v]) => `${k} ${fmtInt(v)}`)
            .join(' · ')}
        </Stage>
        <Down />
        <Stage title="S2–S3 · Embedding SigLIP2 + nhãn bootstrap VLM" output={`${fmtInt(r.bootstrap.labelled)} ảnh có nhãn`}>
          Tỉ lệ yes của nhãn bootstrap: {fmtPct(r.bootstrap.yes_rate)}.
        </Stage>
        <Down />
        <Stage title={`S4 · Head + Jev (tầng quyết định: ${r.primary_layer ?? '—'})`} output={`${fmtInt(r.jev.decided)} quyết định`}>
          Tỉ lệ hoãn (defer) của Jev: {fmtPct(r.jev.defer_share)} · lỗi gọi: {fmtInt(r.jev.errors)}.
        </Stage>
        <Down />
        <Stage title={`Đánh giá trên tập ${r.target_split ?? 'test'}`} output={`${fmtInt(r.cascade_proxy.rows)} ảnh`}>
          Kết quả cascade xuất ra CSV đã verify.
        </Stage>
      </ol>
      <div className="space-y-2">
        <p className="flex items-center gap-1.5 text-caption font-medium uppercase leading-[1.4] tracking-wide text-muted">
          <GitBranch aria-hidden className="size-3.5" /> Nhánh phụ (chỉ một phần ảnh)
        </p>
        <ol className="space-y-2">
          <Stage
            tone="branch"
            title={`T4 · Router chọn ảnh khó (α = ${fmtPct(r.router.alpha)})`}
            output={`${fmtInt(r.router.chosen)} / ngân sách ${fmtInt(r.router.budget_images)}`}
          >
            Tỉ lệ chuyển thực tế {fmtPct(r.router.defer_rate_actual)}. Ảnh còn lại giữ quyết định của tầng chính.
          </Stage>
          <Stage tone="branch" title="T5 · VLM batch (≤ 8 ảnh/lần)">
            {Object.entries(r.vlm).map(([k, v]) => (
              <span key={k} className="mr-2 inline-block">
                <Mono>{k}</Mono> {fmtInt(v)}
              </span>
            ))}
          </Stage>
        </ol>
      </div>
    </div>
  );
}
