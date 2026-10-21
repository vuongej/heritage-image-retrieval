import { Check, Filter, Link2, Loader2, X } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { describeWarning, HOP_STATUS_TEXT } from '@/api/searchAdapter';
import { ImageGrid } from '@/components/grid/ImageGrid';
import { Lightbox } from '@/components/grid/Lightbox';
import { IntentModeSwitch, MultiIntentSummary, type IntentView } from '@/components/search/IntentChips';
import { LatencyBadge } from '@/components/search/LatencyBadge';
import { SearchBar } from '@/components/search/SearchBar';
import { DataSourceBadge, QueryTypeBadge, RunStatusBadge } from '@/components/shared/badges';
import { CapabilityNotice, EmptyState, ErrorState, SkeletonGrid } from '@/components/shared/states';
import { Button, cn, Mono, Tip } from '@/components/shared/ui';
import { HopTrace } from '@/components/trace/HopTrace';
import { DATA_MODE, MAX_TOP_K, PAGE_STEP } from '@/config';
import { useHealth, useSearch } from '@/hooks/queries';
import { EXAMPLES } from '@/lib/examples';
import { fmtInt, sentenceCase } from '@/lib/format';
import type { ImageResult, IntentGroup, QueryType, SearchResponse } from '@/types/search';

const TYPE_COLOR: Record<QueryType, string> = {
  SINGLE: 'border-blue-200 text-blue-800 hover:bg-blue-50',
  SET_QUERY: 'border-blue-200 text-blue-800 hover:bg-blue-50',
  MULTI_INTENT: 'border-violet-200 text-violet-800 hover:bg-violet-50',
  MULTI_HOP: 'border-cyan-200 text-cyan-900 hover:bg-cyan-50',
};

function Hero({ onSearch }: { onSearch: (q: string) => void }) {
  const health = useHealth();
  const visual = health.data?.visual_index;
  return (
    <div className="mx-auto flex max-w-3xl flex-col items-center gap-5 pb-8 pt-10 text-center md:pt-16">
      <h1 className="text-hero font-semibold leading-tight tracking-tight">Tìm kiếm ảnh theo ý định</h1>
      <p className="max-w-xl text-lead text-muted">
        Gõ một tên thực thể, một mô tả, nhiều ý định cùng lúc, hoặc một câu hỏi quan hệ nhiều bước. Hệ thống tự phân loại truy vấn.
      </p>
      <SearchBar initial="" onSubmit={onSearch} />
      <div className="w-full max-w-[640px] text-left">
        <p className="mb-2 text-caption font-medium uppercase leading-[1.4] tracking-wide text-muted">Thử truy vấn mẫu</p>
        <ul className="flex flex-wrap gap-2">
          {EXAMPLES.map((ex) => (
            <li key={ex.query}>
              <Tip content={`${ex.source}${ex.note ? ` — ${ex.note}` : ''}`}>
                <button
                  type="button"
                  onClick={() => onSearch(ex.query)}
                  className={cn('rounded-full border bg-surface px-3 py-1 text-[13px] transition-colors duration-[120ms]', TYPE_COLOR[ex.type])}
                >
                  {ex.query}
                </button>
              </Tip>
            </li>
          ))}
        </ul>
      </div>
      {visual === false && (
        <CapabilityNotice title="Truy xuất dựa trên metadata văn bản" className="max-w-[640px] text-left">
          Ảnh được tìm qua tên thực thể, nhóm và mô tả (vector văn bản + FTS5 + khớp tên). Tìm theo nội dung pixel (SigLIP2 <Mono>img_visual</Mono>) chưa được bật.
        </CapabilityNotice>
      )}
    </div>
  );
}

function CopyLink() {
  const [done, setDone] = useState(false);
  return (
    <Button
      size="sm"
      variant="ghost"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(window.location.href);
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        } catch {
          setDone(false);
        }
      }}
    >
      {done ? <Check aria-hidden className="size-3.5" /> : <Link2 aria-hidden className="size-3.5" />}
      {done ? 'Đã chép' : 'Chép link'}
    </Button>
  );
}

function Toolbar({ data, fetching }: { data: SearchResponse; fetching: boolean }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <QueryTypeBadge type={data.query_type} source={data.query_type_source} />
      <RunStatusBadge status={data.status} />
      <span className="text-[13px]">
        <span className="font-semibold tabular">{fmtInt(data.results.length)}</span> ảnh
        <span className="text-muted"> · top_k={data.top_k} · tổng số khớp: chưa xác định</span>
      </span>
      <LatencyBadge timing={data.timings} />
      <DataSourceBadge kind={data.provenance} />
      {fetching && (
        <span role="status" className="inline-flex items-center gap-1 text-caption text-muted">
          <Loader2 aria-hidden className="size-3.5 animate-spin" /> Đang cập nhật…
        </span>
      )}
      <span className="ml-auto flex items-center gap-2">
        <Tip content={`Parser: ${data.parser} · độ tin cậy parse: ${data.parse_confidence ?? '—'} · pipeline ${data.pipeline_version ?? '—'}`}>
          <span tabIndex={0} className="hidden font-mono text-[11px] text-muted md:inline">
            req {data.request_id.slice(0, 8)}
          </span>
        </Tip>
        <CopyLink />
      </span>
    </div>
  );
}

function Warnings({ warnings }: { warnings: string[] }) {
  // multi_hop / no_relevant_results are explained by the page body itself.
  const shown = warnings.filter((w) => !w.startsWith('multi_hop') && !w.startsWith('no_relevant_results'));
  if (!shown.length) return null;
  return (
    <CapabilityNotice tone="warn" title="Backend báo cảnh báo cho truy vấn này">
      <ul className="list-disc space-y-0.5 pl-4">
        {shown.map((w) => (
          <li key={w}>
            {describeWarning(w)} <Mono className="text-[11px] text-amber-800">{w.split(':')[0]}</Mono>
          </li>
        ))}
      </ul>
    </CapabilityNotice>
  );
}

function ClassFacets({ data, active, onPick }: { data: SearchResponse; active?: string; onPick: (c?: string) => void }) {
  if (!active && data.facets.classes.length < 2) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="inline-flex items-center gap-1 text-caption font-medium uppercase leading-[1.4] tracking-wide text-muted">
        <Filter aria-hidden className="size-3.5" /> Lọc theo nhóm (server)
      </span>
      {active ? (
        <button type="button" onClick={() => onPick(undefined)} className="inline-flex max-w-full items-center gap-1 rounded-full bg-brand-600 px-2.5 py-0.5 text-[12.5px] text-white">
          <span className="truncate">{active}</span>
          <X aria-label="Bỏ lọc nhóm" className="size-3.5 shrink-0" />
        </button>
      ) : (
        data.facets.classes.slice(0, 6).map((c) => (
          <Tip key={c.label} content="Gửi lại truy vấn với filters.parent_class — lọc trên toàn index phía server.">
            <button type="button" onClick={() => onPick(c.label)} className="max-w-[280px] truncate rounded-full border border-border bg-surface px-2.5 py-0.5 text-[12.5px] hover:bg-slate-50">
              {c.label} <span className="font-mono text-muted">{c.count}</span>
            </button>
          </Tip>
        ))
      )}
    </div>
  );
}

function LoadMore({ data, onMore }: { data: SearchResponse; onMore: () => void }) {
  if (data.results.length < data.top_k && data.intents.length < 2) return null;
  const atMax = data.top_k >= MAX_TOP_K;
  return (
    <div className="flex flex-col items-center gap-1 pt-2">
      <Button onClick={onMore} disabled={atMax}>
        {atMax ? 'Đã đạt giới hạn 100 kết quả' : `Tải thêm (top_k = ${Math.min(data.top_k + PAGE_STEP, MAX_TOP_K)})`}
      </Button>
      <p className="text-caption text-muted">Backend không có phân trang: “Tải thêm” gọi lại API với top_k lớn hơn (tối đa 100).</p>
    </div>
  );
}

type OpenState = { list: ImageResult[]; index: number } | null;

function IntentSection({ intent, index, labelOf, onOpen }: { intent: IntentGroup; index: number; labelOf: (i: ImageResult) => string[] | undefined; onOpen: (list: ImageResult[], i: number) => void }) {
  const [all, setAll] = useState(false);
  const shown = all ? intent.images : intent.images.slice(0, 8);
  return (
    <section aria-labelledby={`intent-${intent.id}`} className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 id={`intent-${intent.id}`} className="text-h3 font-semibold">
          <span className="mr-1.5 inline-grid size-6 place-items-center rounded-full bg-q-multi align-middle font-mono text-[12px] text-white">{index + 1}</span>
          {sentenceCase(intent.text)}
        </h2>
        <span className="text-caption text-muted">
          Backend truy xuất bằng: <Mono>“{intent.backend_text}”</Mono> · bằng chứng: {intent.evidence === 'entity_name' ? 'khớp tên thực thể' : intent.evidence === 'retrieval_rank' ? 'thứ hạng truy xuất' : '—'}
          {intent.supported_candidates !== undefined && <> · {fmtInt(intent.supported_candidates)} ứng viên có bằng chứng</>}
        </span>
      </div>
      {intent.images.length === 0 ? (
        <EmptyState title={`Không có ảnh có bằng chứng cho “${intent.text}”`}>Các ý định khác vẫn hiển thị bình thường (kết quả một phần).</EmptyState>
      ) : (
        <>
          <ImageGrid images={shown} label={`Ảnh cho ý định ${intent.text}`} onOpen={(i) => onOpen(intent.images, i)} intentLabelOf={labelOf} />
          {intent.images.length > 8 && (
            <Button size="sm" variant="ghost" onClick={() => setAll((v) => !v)}>
              {all ? 'Thu gọn' : `Xem tất cả ${fmtInt(intent.images.length)} ảnh`}
            </Button>
          )}
        </>
      )}
    </section>
  );
}

function HopTargets({ data, onSearch }: { data: SearchResponse; onSearch: (q: string) => void }) {
  const targets = data.hop?.targets ?? [];
  if (!targets.length) return null;
  const places = targets.flatMap((t) => t.related_places.map((p) => ({ ...p, person: t.label })));
  return (
    <section aria-labelledby="hop-targets" className="space-y-3 rounded-[var(--radius-card)] border border-border bg-surface p-4">
      <h2 id="hop-targets" className="text-[15px] font-semibold">
        Thực thể đích đã xác minh
      </h2>
      <ul className="flex flex-wrap gap-2">
        {targets.map((t) => (
          <li key={t.label} className="rounded-full border border-cyan-200 bg-cyan-50 px-2.5 py-0.5 text-[13px] text-cyan-900">
            {t.label}
          </li>
        ))}
      </ul>
      {places.length > 0 ? (
        <div className="space-y-1.5">
          <p className="text-caption text-muted">Nơi chốn liên quan đã kiểm chứng trong KG — bấm để tìm ảnh nơi đó (truy vấn mới):</p>
          <ul className="flex flex-wrap gap-2">
            {places.map((p) => (
              <li key={`${p.person}-${p.label}`}>
                <button type="button" onClick={() => onSearch(p.label)} className="rounded-full border border-border bg-surface px-2.5 py-0.5 text-[13px] hover:bg-slate-50">
                  {p.person} · {p.relation} <span className="font-medium">{p.label}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="text-caption text-muted">KG chưa có nơi chốn (lăng, mộ, đền thờ) đã kiểm chứng gắn với các thực thể này.</p>
      )}
    </section>
  );
}

function MultiHopBody({
  data,
  onOpen,
  onFallback,
  onSearch,
  onRetry,
  retrying,
}: {
  data: SearchResponse;
  onOpen: (list: ImageResult[], i: number) => void;
  onFallback: (q: string) => void;
  onSearch: (q: string) => void;
  onRetry: () => void;
  retrying: boolean;
}) {
  const [active, setActive] = useState<string>();
  const highlight = useMemo(() => new Set(data.trace.find((s) => s.id === active)?.image_ids ?? []), [data.trace, active]);
  const seed = data.hop?.seed_text;
  const hop = data.timings.stages.find((s) => s.key === 'hop_resolve')?.ms;
  const status = data.hop?.status ?? data.hop_status;
  return (
    <div className="grid gap-5 lg:grid-cols-[360px_minmax(0,1fr)]">
      <div className="lg:sticky lg:top-[132px] lg:max-h-[calc(100vh-150px)] lg:self-start lg:overflow-y-auto">
        <HopTrace steps={data.trace} totalHopMs={hop} cached={data.timings.cached} activeStep={active} onSelectStep={setActive} />
      </div>
      <div className="min-w-0 space-y-4">
        {data.status === 'pending' && (
          <CapabilityNotice tone="info" title="Đang tra cứu nguồn trực tuyến">
            <p>
              KG chưa có cạnh đã kiểm chứng cho một bước, nên hệ thống đang tìm nguồn trên web và chỉ nhận câu trích có nguyên văn trong trang nguồn. Tra cứu chạy
              nền; trang tự hỏi lại sau vài giây.
            </p>
            <Button size="sm" className="mt-2" onClick={onRetry} disabled={retrying}>
              {retrying ? <Loader2 aria-hidden className="size-3.5 animate-spin" /> : null}
              Hỏi lại ngay
            </Button>
          </CapabilityNotice>
        )}
        {data.status === 'unverified' && (
          <CapabilityNotice tone="warn" title={status === 'target_not_in_catalog' ? 'Đã xác minh quan hệ, nhưng không có ảnh của đích' : 'Chưa xác minh được quan hệ'}>
            <p>
              {(status && HOP_STATUS_TEXT[status]) ?? 'Không có chuỗi quan hệ đã xác minh.'} <Mono className="text-[11px]">{status}</Mono>
            </p>
            <p className="mt-1">
              Hệ thống chỉ đi theo cạnh có nguồn kiểm chứng, không trả ảnh “gần đúng” của thực thể khác và không tự đoán tên người hay quan hệ.
            </p>
            {seed && status !== 'target_not_in_catalog' && (
              <Button size="sm" className="mt-2" onClick={() => onFallback(seed)}>
                Tìm kiếm theo từ khóa “{seed}” (không xác minh quan hệ)
              </Button>
            )}
          </CapabilityNotice>
        )}
        {data.status === 'unsupported' && (
          <CapabilityNotice tone="unsupported" title="Hệ thống hiện chưa hỗ trợ truy vấn quan hệ này">
            Quan hệ được hỗ trợ: con / con trai / con gái, cha, mẹ, bố, vợ, chồng; nơi chốn: lăng, mộ, đền thờ, khu tưởng niệm (retrieval/hop.py). Có thể nối
            nhiều bước, ví dụ “lăng của con trai vua Gia Long”.
          </CapabilityNotice>
        )}
        {status === 'target_not_in_catalog' && <HopTargets data={data} onSearch={onSearch} />}
        {data.results.length > 0 && (
          <>
            {data.hop && data.hop.targets.length > 0 && (
              <p className="text-caption text-muted">
                Ảnh của {data.hop.targets.length} thực thể đích:{' '}
                {[...new Set(data.hop.targets.map((t) => t.label))].slice(0, 6).join(' · ')}
                {data.hop.targets.length > 6 ? ' …' : ''}
              </p>
            )}
            <ImageGrid
              images={data.results}
              label="Ảnh của thực thể đích đã xác minh"
              onOpen={(i) => onOpen(data.results, i)}
              highlightIds={active ? highlight : undefined}
            />
          </>
        )}
      </div>
    </div>
  );
}

export function SearchPage() {
  const [params, setParams] = useSearchParams();
  const q = params.get('q')?.trim() ?? '';
  const k = Math.min(MAX_TOP_K, Math.max(PAGE_STEP, Number(params.get('k')) || PAGE_STEP));
  const cls = params.get('cls') ?? undefined;
  const view = (params.get('view') as IntentView) === 'merged' ? 'merged' : 'grouped';
  const fallback = params.get('fallback') === 'keyword';
  const search = useSearch(q ? { query: q, top_k: k, parent_class: cls } : null);
  const [open, setOpen] = useState<OpenState>(null);

  const update = (patch: Record<string, string | undefined>, replace = false) => {
    const next = new URLSearchParams(params);
    for (const [key, v] of Object.entries(patch)) {
      if (v === undefined) next.delete(key);
      else next.set(key, v);
    }
    setParams(next, { replace });
  };
  const runQuery = (query: string, extra: Record<string, string | undefined> = {}) =>
    update({ q: query, k: undefined, cls: undefined, view: undefined, fallback: undefined, ...extra });

  const data = search.data;
  const intentText = useMemo(() => new Map(data?.intents.map((it) => [it.id, sentenceCase(it.text)]) ?? []), [data]);
  const multi = (data?.intents.length ?? 0) > 1;
  const labelOf = (img: ImageResult) => (multi ? img.intent_ids.map((id) => intentText.get(id) ?? id) : undefined);

  const removeIntent = (id: string) => {
    if (!data) return;
    const rest = data.intents.filter((it) => it.id !== id).map((it) => it.text);
    const loc = data.constraints.locations?.[0];
    runQuery(`${rest.join(' và ')}${loc ? ` ở ${loc.label}` : ''}`);
  };

  if (!q) return <Hero onSearch={runQuery} />;

  return (
    <div className="space-y-4">
      <div className={cn('sticky z-30 -mx-4 border-b border-border bg-bg/95 px-4 py-3 backdrop-blur', DATA_MODE === 'mock' ? 'top-[84px]' : 'top-14')}>
        <SearchBar initial={q} onSubmit={(nq) => runQuery(nq)} compact busy={search.isFetching} />
      </div>
      <h1 className="sr-only">Kết quả cho “{q}”</h1>

      {fallback && (
        <CapabilityNotice tone="warn" title="Tìm kiếm theo từ khóa — không xác minh quan hệ">
          Đây là kết quả truy vấn thường cho “{q}”, không phải ảnh của thực thể được suy ra qua quan hệ.
        </CapabilityNotice>
      )}

      {search.isPending && <SkeletonGrid />}
      {search.isError && <ErrorState error={search.error} onRetry={() => search.refetch()} context={`Truy vấn: “${q}”`} />}

      {data && !search.isError && (
        <div className="space-y-4" aria-busy={search.isFetching}>
          <Toolbar data={data} fetching={search.isFetching && !search.isPending} />
          {data.type_mismatch && (
            <CapabilityNotice tone="warn" title="Nhãn loại truy vấn không khớp cách backend truy xuất">
              {data.type_mismatch} Kết quả được nhóm theo sub-query và matched_subqueries mà backend trả về.
            </CapabilityNotice>
          )}
          <Warnings warnings={data.warnings} />
          {data.query_type !== 'MULTI_HOP' && <ClassFacets data={data} active={cls} onPick={(c) => update({ cls: c, k: undefined })} />}

          {data.query_type === 'MULTI_HOP' ? (
            <MultiHopBody
              data={data}
              onOpen={(list, i) => setOpen({ list, index: i })}
              onFallback={(seed) => runQuery(seed, { fallback: 'keyword' })}
              onSearch={(nq) => runQuery(nq)}
              onRetry={() => search.refetch()}
              retrying={search.isFetching}
            />
          ) : data.results.length === 0 ? (
            <EmptyState
              title={
                data.warnings.some((w) => w.startsWith('no_relevant_results'))
                  ? `Không có ảnh đủ liên quan tới “${q}”`
                  : `Không tìm thấy ảnh cho “${q}”`
              }
            >
              {data.warnings.some((w) => w.startsWith('no_relevant_results')) && (
                <p className="mb-1">
                  Kho ảnh chỉ gồm di sản, địa danh, ẩm thực và văn hoá Việt Nam. Hệ thống không trả ảnh “gần nhất” khi không có ảnh nào đạt ngưỡng liên quan của
                  reranker hoặc khớp tên thực thể.
                </p>
              )}
              <p>Thử bỏ bớt từ, viết tên thực thể đầy đủ hoặc thử một truy vấn mẫu:</p>
              <div className="mt-3 flex flex-wrap justify-center gap-2">
                {EXAMPLES.slice(0, 3).map((ex) => (
                  <button key={ex.query} type="button" onClick={() => runQuery(ex.query)} className="rounded-full border border-border bg-surface px-3 py-1 text-[13px] text-text hover:bg-slate-50">
                    {ex.query}
                  </button>
                ))}
              </div>
            </EmptyState>
          ) : multi ? (
            <div className="space-y-5">
              <MultiIntentSummary intents={data.intents} locations={data.constraints.locations ?? []} onRemove={removeIntent} />
              <IntentModeSwitch value={view} onChange={(v) => update({ view: v === 'grouped' ? undefined : v }, true)} />
              {view === 'grouped' ? (
                data.intents.map((it, i) => <IntentSection key={it.id} intent={it} index={i} labelOf={labelOf} onOpen={(list, idx) => setOpen({ list, index: idx })} />)
              ) : (
                <section aria-label="Gộp tất cả kết quả" className="space-y-2">
                  <p className="text-caption text-muted">
                    {fmtInt(data.results.length)} ảnh duy nhất (theo image_id); tổng các nhóm là {fmtInt(data.intents.reduce((s, it) => s + it.images.length, 0))} vì một ảnh có thể khớp nhiều ý định.
                  </p>
                  <ImageGrid images={data.results} label="Tất cả ảnh" onOpen={(i) => setOpen({ list: data.results, index: i })} intentLabelOf={labelOf} />
                </section>
              )}
            </div>
          ) : (
            <ImageGrid images={data.results} label={`Kết quả cho ${q}`} onOpen={(i) => setOpen({ list: data.results, index: i })} />
          )}

          {data.query_type !== 'MULTI_HOP' && data.results.length > 0 && <LoadMore data={data} onMore={() => update({ k: String(Math.min(k + PAGE_STEP, MAX_TOP_K)) })} />}
        </div>
      )}

      <Lightbox
        images={open?.list ?? []}
        index={open?.index ?? null}
        onIndex={(i) => setOpen((o) => (o ? { ...o, index: i } : o))}
        onClose={() => setOpen(null)}
        intentLabelOf={labelOf}
      />
    </div>
  );
}
