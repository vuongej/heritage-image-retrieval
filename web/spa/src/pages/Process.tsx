import {
  Ban,
  CheckCircle2,
  CircleDashed,
  Download,
  FileSpreadsheet,
  ImageOff,
  Loader2,
  MinusCircle,
  Play,
  Square,
  Upload,
  XCircle,
} from 'lucide-react';
import { useMemo, useRef, useState, type DragEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  resultCsvUrl,
  sampleCsvUrl,
  thumbUrl,
  type ItemFilter,
  type Job,
  type JobItem,
  type JobMetrics,
  type JobSummary,
} from '@/api/processAdapter';
import { Chip } from '@/components/shared/badges';
import { StatCard } from '@/components/shared/StatCard';
import { CapabilityNotice, EmptyState, ErrorState } from '@/components/shared/states';
import { Button, Card, cn, Mono, SectionTitle, Tip } from '@/components/shared/ui';
import { DATA_MODE } from '@/config';
import { useCancelJob, useJob, useJobItems, useJobs, useProcessHealth, useUpload } from '@/hooks/queries';
import { fmtDec, fmtInt, fmtPct } from '@/lib/format';

const BUDGETS = [0, 0.05, 0.1, 0.15, 0.2];
const PAGE = 48;
const ACTIVE = new Set(['queued', 'running']);

const STATUS_TEXT: Record<Job['status'], { label: string; cls: string }> = {
  queued: { label: 'Đang chờ', cls: 'border-slate-300 bg-slate-50 text-slate-700' },
  running: { label: 'Đang chạy', cls: 'border-brand-600/30 bg-brand-50 text-brand-700' },
  done: { label: 'Hoàn tất', cls: 'border-emerald-200 bg-emerald-50 text-emerald-800' },
  failed: { label: 'Lỗi', cls: 'border-red-200 bg-red-50 text-red-800' },
  cancelled: { label: 'Đã hủy', cls: 'border-slate-300 bg-slate-100 text-slate-700' },
  interrupted: { label: 'Bị ngắt', cls: 'border-amber-300 bg-amber-50 text-amber-900' },
};

const STAGE_TEXT: Record<JobItem['stage'], string> = { rule: 'Rule', classifier: 'Classifier', vlm: 'VLM' };

const STAGE_HELP: Record<string, string> = {
  parse: 'Đọc CSV, nhận diện cột (image_url, tên entity, category, mô tả, nhãn verify nếu có).',
  gate: 'Rule trên URL: sai định dạng, host bị chặn, khoảng trắng, trùng URL trong entity.',
  fetch: 'Tải ảnh, giải mã, tạo thumbnail 512 px, loại ảnh < 300×200, ghi sha256. Ảnh đã tải được dùng lại.',
  embed: 'SigLIP2: vector ảnh + vector tên entity + vector mô tả (cùng không gian).',
  classify: 'LightGBM M1b trên vector ảnh + 14 feature (độ giống ảnh cùng entity, tên, mô tả, kích thước, host…), hiệu chỉnh isotonic.',
  route: 'Router chọn ảnh bất định nhất (theo entity) để gửi VLM, trong ngân sách α.',
  vlm: 'VLM chấm theo lô ≤ 8 ảnh cùng entity: đúng chủ thể / partial / sai, watermark, nội dung không an toàn.',
  finalize: 'Gộp quyết định, lý do, chi phí; chấm với nhãn người nếu CSV có cột verify.',
};

function fmtSeconds(s: number | null | undefined) {
  if (s === null || s === undefined || !Number.isFinite(s)) return '—';
  if (s < 1) return `${Math.round(s * 1000)} ms`;
  if (s < 90) return `${fmtDec(s, 1)} s`;
  return `${Math.floor(s / 60)} ph ${Math.round(s % 60)} s`;
}

function StatusChip({ status }: { status: Job['status'] }) {
  const s = STATUS_TEXT[status];
  return <Chip className={s.cls}>{s.label}</Chip>;
}

// ---------------------------------------------------------------- upload

function UploadCard({ onCreated }: { onCreated: (job: Job) => void }) {
  const health = useProcessHealth();
  const upload = useUpload();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [useVlm, setUseVlm] = useState(true);
  const [budget, setBudget] = useState<number | null>(null);
  const defaultBudget = health.data?.model.router_alpha ?? 0.15;
  const vlmReady = health.data?.vlm_available ?? false;
  const maxMb = health.data?.max_upload_mb ?? 50;

  const pick = (f: File | undefined) => {
    upload.reset();
    if (f) setFile(f);
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDrag(false);
    pick(e.dataTransfer.files[0]);
  };
  const tooBig = file ? file.size > maxMb * 1024 * 1024 : false;
  const notCsv = file ? !file.name.toLowerCase().endsWith('.csv') : false;

  const start = () => {
    if (!file) return;
    upload.mutate(
      { file, useVlm: useVlm && vlmReady, vlmBudget: budget ?? defaultBudget },
      { onSuccess: (job) => onCreated(job) },
    );
  };

  return (
    <Card className="p-4" aria-labelledby="upload-title">
      <SectionTitle id="upload-title">1. Tải lên file CSV</SectionTitle>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
        className={cn(
          'flex flex-col items-center gap-2 rounded-[var(--radius-card)] border-2 border-dashed px-4 py-8 text-center transition-colors',
          drag ? 'border-brand-600 bg-brand-50' : 'border-border bg-slate-50/60',
        )}
      >
        <FileSpreadsheet aria-hidden className="size-8 text-muted" />
        {file ? (
          <p className="text-body">
            <span className="font-semibold">{file.name}</span> · {fmtDec(file.size / 1024 / 1024, 2)} MB
          </p>
        ) : (
          <p className="text-body text-muted">Kéo thả file .csv vào đây, hoặc</p>
        )}
        <input ref={input} type="file" accept=".csv,text/csv" className="sr-only" onChange={(e) => pick(e.target.files?.[0])} aria-label="Chọn file CSV" />
        <Button size="sm" onClick={() => input.current?.click()}>
          <Upload aria-hidden className="size-3.5" />
          {file ? 'Chọn file khác' : 'Chọn file'}
        </Button>
      </div>
      <p className="mt-2 text-caption leading-relaxed text-muted">
        Bắt buộc: <Mono>image_url</Mono> và tên entity (<Mono>canonical_name</Mono> hoặc <Mono>entity_name</Mono>). Nên có:{' '}
        <Mono>entity_id</Mono>, <Mono>category</Mono>/<Mono>leaf_label</Mono>, <Mono>description</Mono>. Có cột <Mono>verify</Mono> (yes/no) thì
        kết quả được chấm với nhãn người. Tối đa {fmtInt(health.data?.max_rows)} dòng, {maxMb} MB.{' '}
        <a href={sampleCsvUrl} download className="font-medium text-brand-700 underline">
          Tải CSV mẫu (307 ảnh có nhãn)
        </a>
      </p>

      <fieldset className="mt-4 space-y-2">
        <legend className="mb-1 text-caption font-medium uppercase tracking-wide text-muted">2. Tuỳ chọn</legend>
        <label className={cn('flex items-center gap-2 text-body', !vlmReady && 'opacity-60')}>
          <input type="checkbox" checked={useVlm && vlmReady} disabled={!vlmReady} onChange={(e) => setUseVlm(e.target.checked)} />
          Gửi ảnh bất định nhất cho VLM
          {!vlmReady && health.data && <span className="text-caption text-muted">(service chưa có DEEPSEEK_API_KEY)</span>}
        </label>
        <div className="flex flex-wrap items-center gap-2 text-body">
          <span id="budget-label">Ngân sách VLM</span>
          <div role="radiogroup" aria-labelledby="budget-label" className="flex flex-wrap gap-1">
            {BUDGETS.map((b) => {
              const active = (budget ?? defaultBudget) === b;
              return (
                <button
                  key={b}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  disabled={!useVlm || !vlmReady}
                  onClick={() => setBudget(b)}
                  className={cn(
                    'rounded-md border px-2.5 py-1 font-mono text-[12.5px] tabular disabled:opacity-50',
                    active ? 'border-brand-600 bg-brand-50 text-brand-700' : 'border-border bg-surface hover:bg-slate-50',
                  )}
                >
                  {fmtPct(b)}
                  {b === defaultBudget && ' ★'}
                </button>
              );
            })}
          </div>
        </div>
        <p className="text-caption text-muted">★ = cấu hình production, chọn trên tập VAL (docs/verify-router-benchmark.md).</p>
      </fieldset>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Button variant="primary" onClick={start} disabled={!file || tooBig || notCsv || upload.isPending || DATA_MODE === 'mock'}>
          {upload.isPending ? <Loader2 aria-hidden className="size-4 animate-spin" /> : <Play aria-hidden className="size-4" />}
          Chạy pipeline xử lý
        </Button>
        {tooBig && <span className="text-caption text-red-700">File vượt {maxMb} MB.</span>}
        {notCsv && <span className="text-caption text-red-700">Chỉ nhận file .csv.</span>}
      </div>
      {upload.isError && (
        <div className="mt-3">
          <ErrorState error={upload.error} />
        </div>
      )}
    </Card>
  );
}

function ModelCard() {
  const health = useProcessHealth();
  if (health.isError) return <ErrorState error={health.error} onRetry={() => health.refetch()} context="Processing service (cổng 8100)" />;
  const h = health.data;
  const m = h?.model;
  return (
    <Card className="p-4" aria-labelledby="model-title">
      <SectionTitle id="model-title">Model đang dùng</SectionTitle>
      {!h || !m ? (
        <div className="skeleton h-40 rounded" />
      ) : (
        <div className="space-y-3 text-body">
          <p>
            <span className="font-semibold">{m.name}</span> — {m.description}.
          </p>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[13px]">
            <dt className="text-muted">Encoder</dt>
            <dd className="font-mono text-[12px]">{m.encoder}</dd>
            <dt className="text-muted">Thiết bị</dt>
            <dd>{h.device === 'cuda' ? 'GPU (CUDA)' : h.device === 'cpu' ? 'CPU' : h.device}</dd>
            <dt className="text-muted">Ngưỡng duyệt t</dt>
            <dd className="font-mono tabular">{fmtDec(m.threshold_t, 3)}</dd>
            <dt className="text-muted">Ngân sách VLM</dt>
            <dd className="font-mono tabular">
              {fmtPct(m.router_alpha)} · đọc <Mono>{m.vlm_rule}</Mono>
            </dd>
            <dt className="text-muted">VLM</dt>
            <dd>{h.vlm_available ? 'Sẵn sàng (DeepSeek)' : 'Tắt — thiếu key'}</dd>
            <dt className="text-muted">Hàng đợi</dt>
            <dd>{h.running ? `1 đang chạy, ${h.queue} chờ` : h.queue ? `${h.queue} chờ` : 'Trống'}</dd>
          </dl>
          <div className="rounded-md border border-border bg-slate-50 p-3 text-[13px]">
            <p className="mb-1 font-medium">Đo trên TEST (10.565 ảnh, nhãn người):</p>
            <ul className="space-y-0.5">
              <li>
                AUC <Mono>{fmtDec(m.test_auc, 3)}</Mono>
              </li>
              <li>
                Bắt ảnh xấu (recall no) <Mono>{fmtPct(m.test_with_router_vlm.recall_no)}</Mono> · giữ ảnh tốt (recall yes){' '}
                <Mono>{fmtPct(m.test_with_router_vlm.recall_yes)}</Mono>
              </li>
              <li>
                Độ sạch kho (precision yes) <Mono>{fmtPct(m.test_with_router_vlm.precision_yes)}</Mono> · entity còn ảnh{' '}
                <Mono>{fmtPct(m.test_with_router_vlm.entity_retention)}</Mono>
              </li>
            </ul>
          </div>
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- tiến độ

function StageIcon({ status }: { status: Job['stages'][number]['status'] }) {
  if (status === 'running') return <Loader2 aria-hidden className="size-4 animate-spin text-brand-600" />;
  if (status === 'done') return <CheckCircle2 aria-hidden className="size-4 text-emerald-600" />;
  if (status === 'skipped') return <MinusCircle aria-hidden className="size-4 text-slate-400" />;
  if (status === 'failed' || status === 'interrupted') return <XCircle aria-hidden className="size-4 text-red-600" />;
  if (status === 'cancelled') return <Ban aria-hidden className="size-4 text-slate-500" />;
  return <CircleDashed aria-hidden className="size-4 text-slate-300" />;
}

function Stages({ job }: { job: Job }) {
  return (
    <ol className="divide-y divide-border">
      {job.stages.map((s) => {
        const pct = s.total ? Math.min(1, s.done / s.total) : s.status === 'done' ? 1 : 0;
        return (
          <li key={s.key} className="flex items-center gap-3 py-2">
            <StageIcon status={s.status} />
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-2">
                <Tip content={STAGE_HELP[s.key] ?? s.label}>
                  <span tabIndex={0} className={cn('text-body font-medium', s.status === 'pending' && 'text-muted')}>
                    {s.label}
                  </span>
                </Tip>
                <span className="shrink-0 font-mono text-[12px] tabular text-muted">
                  {s.status === 'skipped' ? 'bỏ qua' : s.total ? `${fmtInt(s.done)}/${fmtInt(s.total)}` : ''}
                  {s.seconds !== null && s.seconds !== undefined && s.status !== 'skipped' ? ` · ${fmtSeconds(s.seconds)}` : ''}
                </span>
              </div>
              {s.status === 'running' && s.total > 0 && (
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100" role="progressbar" aria-valuenow={Math.round(pct * 100)} aria-valuemin={0} aria-valuemax={100} aria-label={s.label}>
                  <div className="h-full rounded-full bg-brand-600 transition-[width] duration-500" style={{ width: `${pct * 100}%` }} />
                </div>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

// ---------------------------------------------------------------- kết quả

function Kpis({ s }: { s: JobSummary }) {
  const t = s.timings;
  const total = Object.values(t).reduce((a, b) => a + b, 0);
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard label="Duyệt" value={fmtInt(s.approved)} unit={`/ ${fmtInt(s.rows)} ảnh`} provenance="ACTUAL">
        Loại <span className="font-semibold">{fmtInt(s.rejected)}</span> ({fmtPct(1 - s.approved_share)}) · entity còn ảnh{' '}
        <span className="font-semibold">
          {fmtInt(s.entities_with_approved)}/{fmtInt(s.entities)}
        </span>
      </StatCard>
      <StatCard label="Gửi VLM" value={fmtInt(s.routed)} unit="ảnh" provenance="ACTUAL" footnote={s.vlm.skipped ? `VLM: ${s.vlm.skipped}` : s.vlm.stopped ? `Dừng: ${s.vlm.stopped}` : undefined}>
        Ngân sách {fmtPct(s.decision.budget)} · {fmtInt(s.vlm.requests)} request · lỗi {fmtInt(s.vlm.errors)}
      </StatCard>
      <StatCard label="Chi phí" value={`$${fmtDec(s.cost_usd, 4)}`} provenance="ACTUAL" footnote="Token VLM thật × đơn giá DeepSeek trong .env; chưa gồm GPU / băng thông.">
        ${fmtDec(s.cost_usd_per_1000, 4)} / 1.000 ảnh
      </StatCard>
      <StatCard label="Thời gian" value={fmtSeconds(total)} provenance="ACTUAL">
        {fmtDec(s.throughput.rows_per_second, 1)} ảnh/s cả luồng · tải {fmtDec(s.throughput.fetch_images_per_second, 1)} ảnh/s · SigLIP2{' '}
        {s.embedding.images_per_second ? `${fmtDec(s.embedding.images_per_second, 0)} ảnh/s (${s.embedding.device})` : 'cache'}
      </StatCard>
    </div>
  );
}

function MetricsCard({ m }: { m: JobMetrics }) {
  const rows: [string, number, string][] = [
    ['Bắt ảnh xấu — Recall no', m.recall_no, 'Trong ảnh người gắn no, bao nhiêu % bị loại'],
    ['Loại có đúng — Precision no', m.precision_no, 'Trong ảnh bị loại, bao nhiêu % người cũng gắn no'],
    ['F1 (lớp no)', m.f1_no, 'Trung bình điều hòa precision/recall lớp no'],
    ['Độ sạch kho — Precision yes', m.precision_yes, 'Trong ảnh được duyệt, bao nhiêu % người cũng duyệt'],
    ['Giữ ảnh tốt — Recall yes', m.recall_yes, 'Trong ảnh người duyệt, bao nhiêu % được giữ'],
    ['Balanced accuracy', m.balanced_accuracy, '(Recall no + Recall yes) / 2 — không bị lệch lớp đánh lừa'],
    ['Accuracy', m.accuracy, 'Tỉ lệ đúng trên mọi ảnh có nhãn'],
    ['Entity retention', m.entity_retention, 'Entity có ảnh tốt vẫn còn ≥ 1 ảnh tốt được duyệt'],
  ];
  const c = m.confusion;
  return (
    <Card className="p-4" aria-labelledby="metrics-title">
      <SectionTitle id="metrics-title" aside={<span className="text-caption text-muted">so với cột verify trong CSV · n = {fmtInt(m.n)}</span>}>
        Chất lượng so với nhãn người
      </SectionTitle>
      <div className="grid gap-6 lg:grid-cols-[1fr_auto]">
        <table className="w-full text-table">
          <tbody>
            {rows.map(([label, v, tip]) => (
              <tr key={label} className="border-b border-border last:border-0">
                <td className="py-1.5">
                  <Tip content={tip}>
                    <span tabIndex={0}>{label}</span>
                  </Tip>
                </td>
                <td className="py-1.5 text-right font-mono tabular">{fmtPct(v)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div>
          <p className="mb-1 text-caption font-medium uppercase tracking-wide text-muted">Ma trận nhầm lẫn</p>
          <table className="text-table">
            <thead>
              <tr className="text-caption text-muted">
                <th />
                <th className="px-3 py-1 font-medium">Máy: loại</th>
                <th className="px-3 py-1 font-medium">Máy: duyệt</th>
              </tr>
            </thead>
            <tbody className="font-mono tabular">
              <tr>
                <th className="pr-3 text-left font-sans text-caption font-medium text-muted">Người: no</th>
                <td className="bg-emerald-50 px-3 py-2 text-center">{fmtInt(c['no→no'])}</td>
                <td className="bg-red-50 px-3 py-2 text-center">{fmtInt(c['no→yes'])}</td>
              </tr>
              <tr>
                <th className="pr-3 text-left font-sans text-caption font-medium text-muted">Người: yes</th>
                <td className="bg-amber-50 px-3 py-2 text-center">{fmtInt(c['yes→no'])}</td>
                <td className="bg-emerald-50 px-3 py-2 text-center">{fmtInt(c['yes→yes'])}</td>
              </tr>
            </tbody>
          </table>
          <p className="mt-1 max-w-[260px] text-caption text-muted">Đỏ: ảnh xấu lọt qua · Vàng: ảnh tốt bị loại oan.</p>
        </div>
      </div>
    </Card>
  );
}

function ReasonBars({ s, onPick, active }: { s: JobSummary; onPick: (reason: string | undefined) => void; active?: string }) {
  const entries = Object.entries(s.by_reason);
  const max = Math.max(1, ...entries.map(([, n]) => n));
  return (
    <Card className="p-4" aria-labelledby="reason-title">
      <SectionTitle id="reason-title">Quyết định theo lý do</SectionTitle>
      <ul className="space-y-1.5">
        {entries.map(([reason, n]) => {
          const yes = reason === 'classifier_yes' || reason === 'vlm_dung';
          return (
            <li key={reason}>
              <button
                type="button"
                onClick={() => onPick(active === reason ? undefined : reason)}
                aria-pressed={active === reason}
                className={cn('grid w-full grid-cols-[minmax(0,14rem)_1fr_auto] items-center gap-3 rounded px-1 py-0.5 text-left hover:bg-slate-50', active === reason && 'bg-brand-50')}
              >
                <span className="truncate text-[13px]">{REASON_LABEL[reason] ?? reason}</span>
                <span className="h-2.5 overflow-hidden rounded-full bg-slate-100">
                  <span className={cn('block h-full rounded-full', yes ? 'bg-emerald-500' : 'bg-red-400')} style={{ width: `${(n / max) * 100}%` }} />
                </span>
                <span className="font-mono text-[12.5px] tabular">{fmtInt(n)}</span>
              </button>
            </li>
          );
        })}
      </ul>
      <p className="mt-2 text-caption text-muted">Bấm một lý do để lọc danh sách ảnh bên dưới.</p>
    </Card>
  );
}

const REASON_LABEL: Record<string, string> = {
  classifier_yes: 'Classifier duyệt',
  classifier_no: 'Classifier loại',
  vlm_dung: 'VLM: đúng chủ thể',
  vlm_partial: 'VLM: partial',
  vlm_sai: 'VLM: sai chủ thể',
  vlm_unsafe: 'VLM: không an toàn',
  vlm_error: 'VLM lỗi (giữ classifier)',
  dead: 'Không tải được ảnh',
  too_small: 'Ảnh < 300×200',
  dup_sha256: 'Trùng nội dung ảnh',
  R6_dup_url: 'Trùng URL',
  R1_invalid: 'URL không hợp lệ',
  R1_blocked: 'Host bị chặn',
  R1_ws: 'URL có khoảng trắng',
};

function ItemCard({ it }: { it: JobItem }) {
  const [broken, setBroken] = useState(false);
  const hasThumb = it.width !== null && it.width !== undefined && !['dead', 'too_small'].includes(it.reason) && !broken;
  const mismatch = it.label && it.label !== it.decision;
  return (
    <article className={cn('flex flex-col overflow-hidden rounded-[var(--radius-card)] border bg-surface', mismatch ? 'border-amber-400' : 'border-border')}>
      <a href={it.image_url} target="_blank" rel="noopener noreferrer" className="relative block aspect-[4/3] bg-slate-100">
        {hasThumb ? (
          <img src={thumbUrl(it.key)} alt={it.entity_name} loading="lazy" onError={() => setBroken(true)} className="size-full object-cover" />
        ) : (
          <span className="flex size-full items-center justify-center text-muted">
            <ImageOff aria-hidden className="size-6" />
          </span>
        )}
        <span
          className={cn(
            'absolute left-2 top-2 rounded px-1.5 py-0.5 text-[11px] font-semibold text-white',
            it.decision === 'yes' ? 'bg-emerald-600' : 'bg-red-600',
          )}
        >
          {it.decision === 'yes' ? 'DUYỆT' : 'LOẠI'}
        </span>
        {it.routed && <span className="absolute right-2 top-2 rounded bg-violet-600 px-1.5 py-0.5 text-[11px] font-semibold text-white">VLM</span>}
      </a>
      <div className="flex flex-1 flex-col gap-1 p-3 text-[13px]">
        <p className="line-clamp-2 font-medium" title={it.entity_name}>
          {it.entity_name}
        </p>
        <p className="text-muted">
          <span className="font-medium text-slate-700">{STAGE_TEXT[it.stage]}</span> · {it.reason_text}
        </p>
        {it.vlm?.evidence && <p className="line-clamp-2 text-caption italic text-muted">“{it.vlm.evidence}”</p>}
        <p className="mt-auto flex flex-wrap gap-x-3 font-mono text-[11.5px] tabular text-muted">
          {it.p_yes !== null && it.p_yes !== undefined && <span>p_yes {fmtDec(it.p_yes, 2)}</span>}
          {it.width && it.height && (
            <span>
              {it.width}×{it.height}
            </span>
          )}
          {it.label && <span className={mismatch ? 'font-semibold text-amber-700' : ''}>người: {it.label}</span>}
        </p>
      </div>
    </article>
  );
}

function Results({ job, reason, setReason }: { job: Job; reason?: string; setReason: (r: string | undefined) => void }) {
  const [filter, setFilter] = useState<Omit<ItemFilter, 'offset' | 'limit' | 'reason'>>({});
  const [offset, setOffset] = useState(0);
  const f = useMemo(() => ({ ...filter, reason, offset, limit: PAGE }), [filter, reason, offset]);
  const items = useJobItems(job.id, f);
  const labelled = job.input.labelled > 0;
  const set = (patch: Partial<typeof filter>) => {
    setFilter((x) => ({ ...x, ...patch }));
    setOffset(0);
  };
  const total = items.data?.total ?? 0;
  return (
    <Card className="p-4" aria-labelledby="items-title">
      <SectionTitle
        id="items-title"
        aside={
          <a
            href={resultCsvUrl(job.id)}
            download
            className="inline-flex h-8 items-center gap-1.5 rounded-[var(--radius-input)] bg-brand-600 px-2.5 text-[13px] font-medium text-white hover:bg-brand-700"
          >
            <Download aria-hidden className="size-3.5" />
            Tải CSV kết quả
          </a>
        }
      >
        Kết quả từng ảnh
      </SectionTitle>
      <div className="mb-3 flex flex-wrap items-center gap-2 text-[13px]">
        <select aria-label="Lọc theo quyết định" className="h-8 rounded-md border border-border bg-surface px-2" value={filter.decision ?? ''} onChange={(e) => set({ decision: (e.target.value || undefined) as ItemFilter['decision'] })}>
          <option value="">Mọi quyết định</option>
          <option value="yes">Duyệt</option>
          <option value="no">Loại</option>
        </select>
        <select aria-label="Lọc theo tầng quyết định" className="h-8 rounded-md border border-border bg-surface px-2" value={filter.stage ?? ''} onChange={(e) => set({ stage: (e.target.value || undefined) as ItemFilter['stage'] })}>
          <option value="">Mọi tầng</option>
          <option value="rule">Rule</option>
          <option value="classifier">Classifier</option>
          <option value="vlm">VLM</option>
        </select>
        <input
          type="search"
          placeholder="Tìm entity / URL"
          aria-label="Tìm theo tên entity hoặc URL"
          className="h-8 w-48 rounded-md border border-border bg-surface px-2"
          onChange={(e) => set({ q: e.target.value.trim() || undefined })}
        />
        {labelled && (
          <label className="flex items-center gap-1.5">
            <input type="checkbox" checked={Boolean(filter.mismatch)} onChange={(e) => set({ mismatch: e.target.checked || undefined })} />
            Chỉ ảnh lệch nhãn người
          </label>
        )}
        {reason && (
          <Button size="sm" variant="ghost" onClick={() => setReason(undefined)}>
            Lý do: {REASON_LABEL[reason] ?? reason} ✕
          </Button>
        )}
        <span className="ml-auto text-muted">{fmtInt(total)} ảnh</span>
      </div>
      {items.isError ? (
        <ErrorState error={items.error} onRetry={() => items.refetch()} />
      ) : !items.data ? (
        <div className="skeleton h-64 rounded" />
      ) : items.data.items.length === 0 ? (
        <EmptyState title="Không có ảnh khớp bộ lọc" />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {items.data.items.map((it) => (
            <ItemCard key={it.line} it={it} />
          ))}
        </div>
      )}
      {total > PAGE && (
        <div className="mt-4 flex items-center justify-center gap-3 text-[13px]">
          <Button size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
            Trước
          </Button>
          <span className="font-mono tabular text-muted">
            {fmtInt(offset + 1)}–{fmtInt(Math.min(total, offset + PAGE))} / {fmtInt(total)}
          </span>
          <Button size="sm" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>
            Sau
          </Button>
        </div>
      )}
    </Card>
  );
}

function JobPanel({ id }: { id: string }) {
  const job = useJob(id);
  const cancel = useCancelJob();
  const [reason, setReason] = useState<string | undefined>();
  if (job.isError) return <ErrorState error={job.error} onRetry={() => job.refetch()} context={`Job ${id}`} />;
  const j = job.data;
  if (!j) return <div className="skeleton h-64 rounded-lg" />;
  return (
    <div className="space-y-4">
      <Card className="p-4" aria-labelledby="job-title">
        <SectionTitle
          id="job-title"
          aside={
            <div className="flex items-center gap-2">
              <StatusChip status={j.status} />
              {ACTIVE.has(j.status) && (
                <Button size="sm" onClick={() => cancel.mutate(j.id)} disabled={cancel.isPending}>
                  <Square aria-hidden className="size-3.5" />
                  Hủy
                </Button>
              )}
            </div>
          }
        >
          3. Tiến độ — <span className="font-normal">{j.filename}</span>
        </SectionTitle>
        <p className="mb-2 text-caption text-muted">
          {fmtInt(j.input.rows)} dòng · {fmtInt(j.input.entities)} entity · {fmtInt(j.input.labelled)} có nhãn người · VLM{' '}
          {!j.options.use_vlm ? 'tắt' : j.options.vlm_budget === null || j.options.vlm_budget === undefined ? 'theo model' : fmtPct(j.options.vlm_budget)} · đã chạy {fmtSeconds(j.elapsed_seconds)}
          {j.status === 'queued' && j.queued_ahead ? ` · ${j.queued_ahead} job xếp trước` : ''}
        </p>
        <Stages job={j} />
        {j.error && (
          <CapabilityNotice tone="warn" title="Job dừng" className="mt-3">
            {j.error}
          </CapabilityNotice>
        )}
      </Card>
      {j.summary && (
        <>
          <Kpis s={j.summary} />
          {j.summary.metrics ? (
            <MetricsCard m={j.summary.metrics} />
          ) : (
            <CapabilityNotice title="Không có nhãn người để chấm">
              CSV không có cột <Mono>verify</Mono> (yes/no) đủ cả hai lớp, nên chỉ có quyết định của máy. Thêm nhãn cho một mẫu để đo recall / precision.
            </CapabilityNotice>
          )}
          <ReasonBars s={j.summary} onPick={setReason} active={reason} />
          <Results job={j} reason={reason} setReason={setReason} />
        </>
      )}
    </div>
  );
}

function History({ current, onPick }: { current?: string; onPick: (id: string) => void }) {
  const jobs = useJobs();
  const items = jobs.data?.items ?? [];
  if (!items.length) return null;
  return (
    <Card className="p-4" aria-labelledby="history-title">
      <SectionTitle id="history-title">Các lần xử lý gần đây</SectionTitle>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-table">
          <thead className="text-left text-caption uppercase tracking-wide text-muted">
            <tr>
              <th className="py-1.5 font-medium">File</th>
              <th className="py-1.5 font-medium">Trạng thái</th>
              <th className="py-1.5 text-right font-medium">Ảnh</th>
              <th className="py-1.5 text-right font-medium">Duyệt / loại</th>
              <th className="py-1.5 text-right font-medium">Thời gian</th>
            </tr>
          </thead>
          <tbody>
            {items.map((j) => (
              <tr key={j.id} className={cn('border-t border-border', j.id === current && 'bg-brand-50')}>
                <td className="py-1.5">
                  <button type="button" onClick={() => onPick(j.id)} className="text-left font-medium text-brand-700 hover:underline">
                    {j.filename}
                  </button>
                  <div className="font-mono text-[11px] text-muted">{new Date(j.created_at * 1000).toLocaleString('vi-VN')}</div>
                </td>
                <td className="py-1.5">
                  <StatusChip status={j.status as Job['status']} />
                </td>
                <td className="py-1.5 text-right font-mono tabular">{fmtInt(j.rows)}</td>
                <td className="py-1.5 text-right font-mono tabular">
                  {j.approved === null || j.approved === undefined ? '—' : `${fmtInt(j.approved)} / ${fmtInt(j.rejected)}`}
                </td>
                <td className="py-1.5 text-right font-mono tabular">{fmtSeconds(j.elapsed_seconds)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

export default function ProcessPage() {
  const [params, setParams] = useSearchParams();
  const jobId = params.get('job') ?? undefined;
  const open = (id: string) => setParams({ job: id });
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-h1 font-semibold tracking-tight">Xử lý dữ liệu ảnh</h1>
        <p className="mt-1 max-w-3xl text-lead text-muted">
          Pipeline A: tải lên CSV ảnh vừa crawl, hệ thống tự lọc và kiểm duyệt — rule → SigLIP2 → LightGBM → router → VLM cho ảnh khó — rồi trả CSV quyết định kèm lý do. Chạy trên
          service riêng, không ảnh hưởng chức năng tìm kiếm.
        </p>
      </header>
      {DATA_MODE === 'mock' && (
        <CapabilityNotice tone="warn" title="Chế độ minh họa">
          Pipeline xử lý chỉ chạy ở chế độ live.
        </CapabilityNotice>
      )}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <UploadCard onCreated={(job) => open(job.id)} />
        <ModelCard />
      </div>
      {jobId && <JobPanel key={jobId} id={jobId} />}
      <History current={jobId} onPick={open} />
    </div>
  );
}
