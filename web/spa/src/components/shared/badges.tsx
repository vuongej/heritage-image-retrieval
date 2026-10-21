import { CheckCircle2, CircleDashed, CircleHelp, CircleSlash, CircleX, Hourglass, ShieldAlert } from 'lucide-react';
import type { ReactNode } from 'react';
import type { DataProvenance, ModerationStatus, QueryType, RunStatus } from '@/types/search';
import type { GateStatus } from '@/lib/sla';
import { cn, Tip } from './ui';

export function Chip({ className, children, title }: { className?: string; children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className={cn('inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-caption font-medium leading-[1.6]', className)}
    >
      {children}
    </span>
  );
}

const PROVENANCE: Record<DataProvenance, { label: string; cls: string; tip: string }> = {
  ACTUAL: { label: 'ĐO THỰC', cls: 'border-emerald-200 bg-emerald-50 text-emerald-800', tip: 'Số liệu từ backend hoặc file báo cáo của một lần chạy thật.' },
  TARGET: { label: 'MỤC TIÊU', cls: 'border-sky-200 bg-sky-50 text-sky-800', tip: 'Ngưỡng mục tiêu, không phải kết quả đo.' },
  ESTIMATE: { label: 'ƯỚC LƯỢNG', cls: 'border-amber-300 bg-amber-50 text-amber-900', tip: 'Ngoại suy từ số đo + giả định, không phải thực nghiệm.' },
  FIXTURE: { label: 'MINH HỌA', cls: 'border-fuchsia-200 bg-fuchsia-50 text-fuchsia-800', tip: 'Dữ liệu minh họa cho phát triển UI — không phải kết quả đo.' },
};

export function DataSourceBadge({ kind, note }: { kind: DataProvenance; note?: string }) {
  const p = PROVENANCE[kind];
  return (
    <Tip content={note ? `${p.tip} ${note}` : p.tip}>
      <span tabIndex={0} className={cn('inline-flex items-center rounded border px-1.5 py-px font-mono text-[10.5px] font-semibold tracking-wider', p.cls)}>
        {p.label}
      </span>
    </Tip>
  );
}

const QT: Record<QueryType, { label: string; color: string; tip: string }> = {
  SINGLE: { label: 'Đơn ý định', color: 'var(--color-q-single)', tip: 'SINGLE — một đối tượng/ý định.' },
  SET_QUERY: { label: 'Tập hợp', color: 'var(--color-q-single)', tip: 'SET_QUERY — truy vấn theo nhóm/lớp ("các chợ truyền thống"), một nhánh của truy vấn đơn.' },
  MULTI_INTENT: { label: 'Nhiều ý định', color: 'var(--color-q-multi)', tip: 'MULTI_INTENT — nhiều ý định độc lập, có thể chung điều kiện.' },
  MULTI_HOP: { label: 'Nhiều bước', color: 'var(--color-q-hop)', tip: 'MULTI_HOP — thực thể → quan hệ có nguồn → ảnh thực thể đích.' },
};

export function QueryTypeBadge({ type, source }: { type: QueryType; source: 'backend' | 'fixture' }) {
  const q = QT[type];
  return (
    <Tip content={`${q.tip} Nguồn phân loại: ${source === 'backend' ? 'backend' : 'fixture minh họa'}.`}>
      <span
        tabIndex={0}
        className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-caption font-semibold text-white"
        style={{ background: q.color }}
      >
        {q.label}
        <span className="font-mono text-[10.5px] font-medium opacity-85">{type}</span>
      </span>
    </Tip>
  );
}

const RUN: Record<RunStatus, { label: string; cls: string; Icon: typeof CheckCircle2 }> = {
  ok: { label: 'Hoàn tất', cls: 'border-emerald-200 bg-emerald-50 text-emerald-800', Icon: CheckCircle2 },
  partial: { label: 'Một phần', cls: 'border-amber-300 bg-amber-50 text-amber-900', Icon: CircleDashed },
  unverified: { label: 'Chưa xác minh', cls: 'border-amber-300 bg-amber-50 text-amber-900', Icon: CircleHelp },
  pending: { label: 'Đang tra cứu', cls: 'border-sky-300 bg-sky-50 text-sky-900', Icon: Hourglass },
  unsupported: { label: 'Chưa hỗ trợ', cls: 'border-slate-300 bg-slate-100 text-slate-700', Icon: CircleSlash },
  error: { label: 'Lỗi', cls: 'border-red-200 bg-red-50 text-red-800', Icon: CircleX },
};

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const r = RUN[status];
  return (
    <Chip className={r.cls}>
      <r.Icon aria-hidden className="size-3.5" />
      {r.label}
    </Chip>
  );
}

const MOD: Record<ModerationStatus, { label: string; color: string }> = {
  approved: { label: 'Đã duyệt', color: 'var(--color-mod-approved)' },
  review: { label: 'Cần xem lại', color: 'var(--color-mod-review)' },
  rejected: { label: 'Bị loại', color: 'var(--color-mod-rejected)' },
  nsfw: { label: 'Nhạy cảm', color: 'var(--color-mod-nsfw)' },
  quarantined: { label: 'Cách ly', color: 'var(--color-mod-quarantined)' },
  unknown: { label: 'Chưa rõ', color: 'var(--color-mod-quarantined)' },
};

/** Text + dot: status is never conveyed by color alone. */
export function ModerationBadge({ status, source }: { status: ModerationStatus; source?: string }) {
  const m = MOD[status];
  return (
    <span className="inline-flex items-center gap-1.5 text-caption text-text" title={source}>
      <span aria-hidden className="size-2 rounded-full" style={{ background: m.color }} />
      {m.label}
    </span>
  );
}

const GATE: Record<GateStatus, { cls: string; label: string }> = {
  PASS: { cls: 'border-emerald-300 bg-emerald-50 text-emerald-800', label: 'PASS' },
  FAIL: { cls: 'border-red-300 bg-red-50 text-red-800', label: 'FAIL' },
  PARTIAL: { cls: 'border-amber-300 bg-amber-50 text-amber-900', label: 'MỘT PHẦN' },
  NOT_MEASURED: { cls: 'border-slate-300 bg-slate-100 text-slate-700', label: 'CHƯA ĐO' },
  NOT_SUPPORTED: { cls: 'border-slate-300 bg-slate-100 text-slate-700', label: 'CHƯA HỖ TRỢ' },
};

export function GateBadge({ status }: { status: GateStatus }) {
  const g = GATE[status];
  return (
    <span className={cn('inline-flex items-center gap-1 rounded border px-1.5 py-px font-mono text-[11px] font-semibold', g.cls)}>
      {status === 'FAIL' && <ShieldAlert aria-hidden className="size-3" />}
      {g.label}
    </span>
  );
}
