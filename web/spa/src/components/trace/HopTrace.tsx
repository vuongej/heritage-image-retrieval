import { ArrowRight, CheckCircle2, ChevronDown, CircleHelp, CircleSlash, CircleX, ExternalLink, Hourglass } from 'lucide-react';
import { useState } from 'react';
import { fmtMs } from '@/lib/format';
import type { Evidence, HopFact, HopSource, HopSourceType, TraceStep } from '@/types/search';
import { cn } from '@/components/shared/ui';

const KIND: Record<TraceStep['kind'], string> = {
  entity_linking: 'Xác định thực thể',
  relation_lookup: 'Tra cứu quan hệ',
  catalog_mapping: 'Ánh xạ sang catalog',
  retrieval: 'Truy xuất ảnh',
  rerank: 'Xếp hạng',
  other: 'Phân tích truy vấn',
};

const STATUS: Record<TraceStep['status'], { Icon: typeof CheckCircle2; cls: string; label: string }> = {
  ok: { Icon: CheckCircle2, cls: 'text-emerald-700 bg-emerald-50 border-emerald-200', label: 'Đã xác minh' },
  unverified: { Icon: CircleHelp, cls: 'text-amber-800 bg-amber-50 border-amber-300', label: 'Chưa xác minh' },
  pending: { Icon: Hourglass, cls: 'text-sky-800 bg-sky-50 border-sky-300', label: 'Đang tra cứu' },
  not_supported: { Icon: CircleSlash, cls: 'text-slate-700 bg-slate-100 border-slate-300', label: 'Chưa hỗ trợ' },
  failed: { Icon: CircleX, cls: 'text-red-700 bg-red-50 border-red-200', label: 'Lỗi' },
};

// kg_edge.source_type — giai đoạn dựng KG (docs/multihop-kg.md).
const SOURCE: Record<HopSourceType, { label: string; hint: string; cls: string }> = {
  catalog_name: { label: 'Tên catalog', hint: 'Chính tên thực thể trong catalog (đã duyệt tay) nêu quan hệ', cls: 'border-emerald-200 bg-emerald-50 text-emerald-800' },
  gemini_doc: { label: 'Tài liệu', hint: 'Gemini trích từ tài liệu; câu trích được kiểm có nguyên văn trong trang nguồn', cls: 'border-indigo-200 bg-indigo-50 text-indigo-800' },
  manual_claim: { label: 'Seed thủ công', hint: 'Khẳng định khai báo tay, đã kiểm bằng nguồn web', cls: 'border-violet-200 bg-violet-50 text-violet-800' },
  online: { label: 'Tra cứu trực tuyến', hint: 'Tìm lúc truy vấn; câu trích được kiểm trong nội dung trang nguồn', cls: 'border-sky-200 bg-sky-50 text-sky-800' },
  other: { label: 'Nguồn khác', hint: 'Loại nguồn không xác định', cls: 'border-slate-200 bg-slate-50 text-slate-700' },
};

const FACTS_SHOWN = 4;

export function EvidenceLink({ ev }: { ev: Evidence }) {
  return (
    <li className="flex flex-wrap items-center gap-x-2 text-caption">
      <span className="font-medium">{ev.label}</span>
      {ev.url ? (
        <a href={ev.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-brand-700 hover:underline">
          <ExternalLink aria-hidden className="size-3" />
          {new URL(ev.url).hostname}
        </a>
      ) : (
        <span className="text-muted">Chưa có nguồn xác minh</span>
      )}
    </li>
  );
}

function SourceItem({ src }: { src: HopSource }) {
  const meta = SOURCE[src.type];
  return (
    <li className="space-y-0.5">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-caption">
        <span title={meta.hint} className={cn('rounded border px-1.5 text-[11px] font-medium', meta.cls)}>
          {meta.label}
        </span>
        {src.url ? (
          <a href={src.url} target="_blank" rel="noopener noreferrer" className="inline-flex min-w-0 items-center gap-1 text-brand-700 hover:underline">
            <ExternalLink aria-hidden className="size-3 shrink-0" />
            <span className="truncate">{new URL(src.url).hostname}</span>
          </a>
        ) : src.catalog_entity_id ? (
          <span className="font-mono text-[11px] text-muted" title={src.catalog_entity_id}>
            entity {src.catalog_entity_id.slice(0, 8)}
          </span>
        ) : (
          <span className="text-muted">Không có URL nguồn</span>
        )}
      </div>
      {src.quote && src.type !== 'catalog_name' && (
        <blockquote className="line-clamp-3 border-l-2 border-border pl-2 text-[12px] italic text-muted" title={src.quote}>
          “{src.quote}”
        </blockquote>
      )}
    </li>
  );
}

function FactItem({ fact }: { fact: HopFact }) {
  const [all, setAll] = useState(false);
  const sources = all ? fact.sources : fact.sources.slice(0, 2);
  return (
    <li className="rounded-md border border-border bg-surface p-2">
      <p className="flex flex-wrap items-center gap-1 text-[13px] font-medium">
        <span>{fact.subject}</span>
        <ArrowRight aria-hidden className="size-3.5 text-q-hop" />
        <span>{fact.object}</span>
      </p>
      <ul className="mt-1 space-y-1.5">
        {sources.map((s, i) => (
          <SourceItem key={i} src={s} />
        ))}
      </ul>
      {fact.sources.length > 2 && (
        <button type="button" onClick={() => setAll((v) => !v)} className="mt-1 text-caption text-muted hover:text-text">
          {all ? 'Thu gọn nguồn' : `+${fact.sources.length - 2} nguồn khác`}
        </button>
      )}
    </li>
  );
}

function FactList({ facts }: { facts: HopFact[] }) {
  const [all, setAll] = useState(false);
  const shown = all ? facts : facts.slice(0, FACTS_SHOWN);
  return (
    <>
      <ul className="mt-1.5 space-y-1.5">
        {shown.map((f, i) => (
          <FactItem key={i} fact={f} />
        ))}
      </ul>
      {facts.length > FACTS_SHOWN && (
        <button type="button" onClick={() => setAll((v) => !v)} className="mt-1 text-caption font-medium text-q-hop hover:underline">
          {all ? 'Thu gọn' : `Xem thêm ${facts.length - FACTS_SHOWN} quan hệ`}
        </button>
      )}
    </>
  );
}

export function HopTrace({
  steps,
  totalHopMs,
  cached,
  activeStep,
  onSelectStep,
}: {
  steps: TraceStep[];
  totalHopMs?: number;
  /** Whole response served from the search cache: no per-stage timings exist. */
  cached?: boolean;
  activeStep?: string;
  onSelectStep: (id: string | undefined) => void;
}) {
  const [showJson, setShowJson] = useState(false);
  return (
    <section aria-labelledby="hop-title" className="rounded-[var(--radius-card)] border border-border bg-surface p-4">
      <div className="mb-3 flex items-baseline justify-between gap-2">
        <h2 id="hop-title" className="text-[15px] font-semibold">
          Quá trình truy xuất nhiều bước
        </h2>
        <span className="font-mono text-caption text-muted" title="timings_ms.hop_resolve — gồm cả thời gian chờ tra cứu trực tuyến; backend không đo riêng từng bước">
          KG: {cached && totalHopMs === undefined ? 'từ cache' : fmtMs(totalHopMs)}
        </span>
      </div>
      <ol className="relative space-y-3 before:absolute before:bottom-2 before:left-[13px] before:top-2 before:w-px before:bg-border">
        {steps.map((s) => {
          const st = STATUS[s.status];
          const linkable = Boolean(s.image_ids?.length);
          const active = activeStep === s.id;
          return (
            <li key={s.id} className="relative pl-9">
              <span className={cn('absolute left-0 top-0.5 grid size-7 place-items-center rounded-full border bg-surface', st.cls)}>
                <st.Icon aria-hidden className="size-4" />
              </span>
              <div className={cn('rounded-md border p-2.5', active ? 'border-q-hop bg-cyan-50/60' : 'border-transparent')}>
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="font-mono text-caption text-muted">#{s.step}</span>
                  <span className="text-[13.5px] font-semibold">{KIND[s.kind]}</span>
                  <span className={cn('rounded border px-1.5 text-[11px] font-medium', st.cls)}>{st.label}</span>
                  {s.relation && <span className="text-[11.5px] font-medium text-q-hop">{s.relation}</span>}
                </div>
                <p className="mt-1 text-[13px]">{s.input_summary}</p>
                {s.output_summary && <p className="text-[13px] text-muted">→ {s.output_summary}</p>}
                {s.facts && s.facts.length > 0 && <FactList facts={s.facts} />}
                {s.evidence.length > 0 && <ul className="mt-1.5 space-y-1">{s.evidence.map((e, i) => <EvidenceLink key={i} ev={e} />)}</ul>}
                {s.elapsed_ms !== undefined && <p className="mt-1 font-mono text-caption text-muted">{fmtMs(s.elapsed_ms)}</p>}
                {linkable && (
                  <button
                    type="button"
                    aria-pressed={active}
                    onClick={() => onSelectStep(active ? undefined : s.id)}
                    className="mt-1.5 text-caption font-medium text-q-hop hover:underline"
                  >
                    {active ? 'Bỏ đánh dấu ảnh' : `Đánh dấu ${s.image_ids!.length} ảnh của bước này`}
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ol>
      <button
        type="button"
        onClick={() => setShowJson((v) => !v)}
        aria-expanded={showJson}
        className="mt-3 inline-flex items-center gap-1 text-caption text-muted hover:text-text"
      >
        <ChevronDown aria-hidden className={cn('size-3.5 transition-transform', showJson && 'rotate-180')} />
        JSON trace (cho kỹ sư)
      </button>
      {showJson && (
        <pre className="mt-2 max-h-64 overflow-auto rounded bg-slate-950 p-3 font-mono text-[11.5px] leading-relaxed text-slate-100">
          {JSON.stringify(steps, null, 2)}
        </pre>
      )}
    </section>
  );
}
