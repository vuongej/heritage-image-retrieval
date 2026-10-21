import { request } from './backendClient';
import { rawSearchSchema, type RawHit, type RawResolution, type RawSearch } from './validators';
import type {
  HopFact,
  HopSource,
  HopSourceType,
  HopSummary,
  ImageResult,
  IntentGroup,
  LocationConstraint,
  QueryType,
  RunStatus,
  ScoreKind,
  SearchParams,
  SearchResponse,
  StageTiming,
  TraceStep,
} from '@/types/search';
import { hostOf, safeHttpUrl } from '@/lib/url';

// Every mapping from the real /v1/search payload (docs/backend-inventory.md §4) lives here,
// so components never read backend field names directly.

const INTENT: Record<string, QueryType> = {
  single: 'SINGLE',
  multi_intent: 'MULTI_INTENT',
  multi_hop: 'MULTI_HOP',
  set_query: 'SET_QUERY',
};

const STAGE_LABELS: Record<string, string> = {
  cache_lookup: 'Tra cache kết quả',
  catalog: 'Nạp catalog tên',
  parse: 'Parse (rule)',
  embed_query: 'Embed truy vấn',
  embed_visual: 'Embed thị giác',
  dense: 'Tìm vector Qdrant',
  retrieve: 'FTS5 + khớp tên + RRF',
  llm_wait: 'Chờ LLM parse',
  hop_resolve: 'Giải quan hệ KG',
  metadata_filter: 'Lọc metadata',
  rerank: 'Rerank',
};

export const HOP_STATUS_TEXT: Record<string, string> = {
  resolved: 'Đã xác minh toàn bộ chuỗi quan hệ.',
  seed_not_linked: 'Không xác định được thực thể xuất phát trong KG (kể cả qua tra cứu trực tuyến).',
  no_evidence: 'Có thực thể xuất phát nhưng thiếu cạnh quan hệ có nguồn kiểm chứng.',
  target_not_in_catalog: 'Chuỗi quan hệ đã xác minh, nhưng đích là người không có ảnh trong catalog.',
  pending_online_lookup: 'Đang tra cứu nguồn trực tuyến cho bước còn thiếu — hỏi lại sau vài giây.',
  unsupported_relation: 'Quan hệ trong truy vấn chưa được hỗ trợ.',
};

const DEGRADED = ['embedding_failed', 'rerank_failed', 'llm_rerank_failed', 'sub_query_no_coverage'];

export function stageLabel(key: string): string {
  const llm = key.endsWith('_llm');
  const base = llm ? key.slice(0, -4) : key;
  const label = STAGE_LABELS[base] ?? base;
  return llm ? `${label} (theo LLM)` : label;
}

export function describeWarning(w: string): string {
  if (w.startsWith('embedding_failed')) return 'Endpoint embedding lỗi — bỏ nhánh vector, kết quả chỉ từ FTS5 + khớp tên.';
  if (w.startsWith('llm_rerank_failed') || w.startsWith('rerank_failed'))
    return 'Rerank lỗi — dùng độ tương đồng embedding hoặc thứ tự hợp nhất thay thế.';
  if (w.startsWith('no_relevant_results'))
    return 'Không có ảnh nào đủ liên quan: mọi ứng viên đều dưới ngưỡng điểm liên quan và không khớp tên thực thể nào.';
  if (w.startsWith('llm_parse_failed')) return 'LLM parse lỗi — dùng kết quả rule parser.';
  const cov = /^sub_query_no_coverage: (\w+) \((.*)\)$/.exec(w);
  if (cov) return `Ý định “${cov[2]}” không có ảnh có bằng chứng thuộc ý định này.`;
  if (w.startsWith('filter ') && w.includes('ignored')) return 'Bộ lọc kích thước bị bỏ qua: catalog chưa có kích thước ảnh.';
  if (w.startsWith('size filter')) return 'Một số ứng viên chưa biết kích thước ảnh (xem chi tiết).';
  const hop = /^multi_hop (\w+)/.exec(w);
  if (hop) return HOP_STATUS_TEXT[hop[1]!] ?? HOP_STATUS_TEXT.no_evidence!;
  const k = /^top_k=(\d+) < (\d+) sub-queries/.exec(w);
  if (k) return `Số kết quả yêu cầu (${k[1]}) nhỏ hơn số ý định (${k[2]}).`;
  return w;
}

/**
 * The parser appends a shared place to every sub-query ("hồ bơi ở phú quốc"). When ALL sub-queries
 * end with the same "ở/tại …" phrase, expose it as a shared constraint (flagged `derived`).
 */
export function deriveSharedLocation(texts: string[]): { suffix: string; label: string } | undefined {
  if (texts.length < 2) return undefined;
  const words = texts.map((t) => t.trim().split(/\s+/));
  const shortest = Math.min(...words.map((w) => w.length));
  let common = 0;
  while (
    common < shortest - 1 &&
    words.every((w) => w[w.length - 1 - common] === words[0]![words[0]!.length - 1 - common])
  ) {
    common += 1;
  }
  if (!common) return undefined;
  const tail = words[0]!.slice(-common);
  const at = tail.findIndex((w) => w === 'ở' || w === 'tại');
  if (at < 0 || at === tail.length - 1) return undefined;
  const suffix = tail.slice(at).join(' ');
  return { suffix, label: tail.slice(at + 1).join(' ') };
}

function scoreKind(raw: RawSearch): ScoreKind {
  if (raw.resolution) return 'rank';
  if (raw.warnings.some((w) => w.startsWith('rerank_failed') || w.startsWith('llm_rerank_failed'))) return 'other';
  return 'reranker';
}

function mapHit(h: RawHit, kind: ScoreKind, producer: string[]): ImageResult {
  const url = safeHttpUrl(h.image_url);
  const verify = h.quality.verify ?? 'unknown';
  const watermark = h.quality.watermark ?? 'unknown';
  return {
    image_id: h.image_id,
    entity_id: h.entity_id ?? undefined,
    entity_name: h.leaf_label ?? undefined,
    entity_class: h.parent_class ?? undefined,
    thumbnail_url: url,
    original_url: url,
    width: h.quality.width ?? undefined,
    height: h.quality.height ?? undefined,
    score: h.score,
    score_kind: kind,
    relevance: h.relevance ?? undefined,
    source_host: hostOf(h.image_url),
    caption: h.description ?? undefined,
    intent_ids: h.matched_subqueries,
    producer_step_ids: producer,
    moderation: {
      // The catalog only imports CSV rows with flag=approved (storage/local.py::import_approved).
      status: verify === 'no' ? 'review' : 'approved',
      source: verify === 'no' ? `verify=no (${h.quality.verify_source ?? 'không rõ nguồn'})` : 'flag=approved trong CSV',
      labels: watermark === 'yes' ? ['watermark'] : [],
    },
    quality: { verify, watermark, pixel_checked: Boolean(h.quality.pixel_checked) },
  };
}

// KG predicates (retrieval/hop.py) in reading order for the UI.
const PREDICATE_VI: Record<string, string> = {
  PARENT_OF: 'cha/mẹ → con',
  SPOUSE_OF: 'vợ/chồng',
  BURIED_AT: 'an táng tại',
  WORSHIPPED_AT: 'được thờ tại',
  MEMORIAL_AT: 'tưởng niệm tại',
};
const GENDER_VI: Record<string, string> = { male: 'nam', female: 'nữ' };
const PLACE_PREDICATES = new Set(['BURIED_AT', 'WORSHIPPED_AT', 'MEMORIAL_AT']);
const SOURCE_TYPES: HopSourceType[] = ['catalog_name', 'gemini_doc', 'manual_claim', 'online'];

export function predicateLabel(predicate: string): string {
  return PREDICATE_VI[predicate] ?? predicate;
}

type RawEdge = RawResolution['steps'][number]['edges'][number];

function edgeSource(e: RawEdge): HopSource {
  const type = SOURCE_TYPES.find((t) => t === e.source_type) ?? 'other';
  const catalog = /^catalog:entity\/(.+)$/.exec(e.source ?? '');
  return {
    type,
    url: safeHttpUrl(e.source ?? undefined),
    catalog_entity_id: catalog?.[1],
    quote: e.evidence?.trim() || undefined,
    verifier: e.verifier ?? undefined,
  };
}

/** Group edges by (subject, object): one relation may be backed by several independent sources. */
export function groupFacts(edges: RawEdge[]): HopFact[] {
  const facts = new Map<string, HopFact>();
  for (const e of edges) {
    const key = `${e.subject}|${e.object}`;
    let fact = facts.get(key);
    if (!fact) {
      fact = { subject: e.subject_label ?? e.subject, object: e.object_label ?? e.object, object_kind: e.object_kind ?? undefined, sources: [] };
      facts.set(key, fact);
    }
    const src = edgeSource(e);
    if (!fact.sources.some((x) => x.type === src.type && x.url === src.url && x.catalog_entity_id === src.catalog_entity_id)) {
      fact.sources.push(src);
    }
  }
  return [...facts.values()];
}

function seedLabels(res: RawResolution): string[] {
  const nodes = res.seed.nodes ?? [];
  return nodes.length ? nodes.map((n) => n.label ?? n.node_id) : (res.seed.qids ?? []);
}

function fmtSec(ms?: number): string {
  return ms === undefined ? 'vài giây' : `${(ms / 1000).toLocaleString('vi-VN', { maximumFractionDigits: 1 })} s`;
}

export function mapTrace(res: RawResolution, imageIds: string[]): TraceStep[] {
  const steps: TraceStep[] = [];
  const next = () => ({ id: `h${steps.length + 1}`, step: steps.length + 1 });
  const seedText = res.seed.text ?? '';
  const seeds = seedLabels(res);
  if (res.status === 'unsupported_relation') {
    return [
      {
        ...next(),
        kind: 'other',
        status: 'not_supported',
        input_summary: 'Phân tích quan hệ trong truy vấn',
        output_summary: 'Quan hệ này chưa nằm trong danh sách hỗ trợ của retrieval/hop.py',
        evidence: [],
      },
    ];
  }
  steps.push({
    ...next(),
    kind: 'entity_linking',
    status: seeds.length ? 'ok' : 'unverified',
    input_summary: seedText ? `Thực thể xuất phát: “${seedText}”` : 'Thực thể xuất phát',
    output_summary: seeds.length
      ? `Nút KG: ${seeds.join(', ')}`
      : 'Không có trong KG và không tìm được nguồn kiểm chứng — hệ thống không đoán',
    entity_ids: (res.seed.nodes ?? []).map((n) => n.node_id),
    evidence: [],
  });
  res.steps.forEach((s, i) => {
    const facts = groupFacts(s.edges);
    const place = PLACE_PREDICATES.has(s.predicate);
    const last = i === res.steps.length - 1;
    const relation = [predicateLabel(s.predicate), s.gender ? (GENDER_VI[s.gender] ?? s.gender) : undefined].filter(Boolean).join(' · ');
    steps.push({
      ...next(),
      kind: 'relation_lookup',
      status: facts.length ? 'ok' : 'unverified',
      input_summary: place ? `Tìm nơi chốn (${s.phrase ?? s.predicate})` : `Tra quan hệ “${s.phrase ?? s.predicate}”`,
      output_summary: facts.length
        ? `${facts.length} quan hệ đã kiểm chứng · ${s.edges.length} nguồn`
        : last && res.online.status === 'no_evidence'
          ? 'KG và tra cứu trực tuyến đều không có nguồn kiểm chứng được (không có nghĩa là quan hệ không tồn tại)'
          : 'KG không có cạnh đã kiểm chứng cho bước này (không có nghĩa là quan hệ không tồn tại)',
      relation,
      entity_ids: [...new Set(s.edges.map((e) => e.object))],
      evidence: [],
      facts,
    });
  });
  if (res.status === 'pending_online_lookup') {
    steps.push({
      ...next(),
      kind: 'relation_lookup',
      status: 'pending',
      input_summary: 'KG chưa có cạnh — đang tra cứu nguồn trực tuyến',
      output_summary: `Quá thời gian chờ ${fmtSec(res.online.budget_ms)}: tra cứu tiếp tục chạy nền, hỏi lại sau vài giây`,
      evidence: [],
    });
  }
  if (res.status === 'resolved' || res.status === 'target_not_in_catalog') {
    const mapped = res.mapped_target_entity_ids;
    const targets = res.target_nodes.length || res.target_qids.length;
    steps.push({
      ...next(),
      kind: 'catalog_mapping',
      status: mapped.length ? 'ok' : 'unverified',
      input_summary: `Ánh xạ ${targets} nút đích sang catalog`,
      output_summary: mapped.length
        ? `${mapped.length} thực thể có ảnh`
        : 'Đích là người — catalog chỉ có ảnh nơi chốn/hiện vật, không trả ảnh thay thế',
      entity_ids: mapped,
      evidence: [],
    });
  }
  if (res.status === 'resolved') {
    steps.push({
      ...next(),
      kind: 'retrieval',
      status: imageIds.length ? 'ok' : 'unverified',
      input_summary: 'Lấy ảnh của thực thể đích đã xác minh',
      output_summary: `${imageIds.length} ảnh`,
      image_ids: imageIds,
      evidence: [],
    });
  }
  return steps;
}

export function hopSummary(res: RawResolution): HopSummary {
  return {
    status: res.status,
    seed_text: res.seed.text || undefined,
    seed_labels: seedLabels(res),
    targets: res.target_nodes.map((t) => ({
      label: t.label ?? t.node_id,
      kind: t.kind ?? undefined,
      related_places: (t.related_places ?? []).map((r) => ({ relation: predicateLabel(r.predicate), label: r.node.label ?? r.node.node_id })),
    })),
    online_status: res.online.status,
    online_budget_ms: res.online.budget_ms,
  };
}

function runStatus(raw: RawSearch, type: QueryType): RunStatus {
  if (type === 'MULTI_HOP') {
    const status = raw.resolution?.status;
    if (!status || status === 'unsupported_relation') return 'unsupported';
    if (status === 'pending_online_lookup') return 'pending';
    if (status !== 'resolved') return 'unverified';
    return raw.hits.length ? 'ok' : 'partial';
  }
  return raw.warnings.some((w) => DEGRADED.some((p) => w.startsWith(p))) ? 'partial' : 'ok';
}

export function adaptSearch(
  raw: RawSearch,
  params: SearchParams,
  observed: { clientObservedMs?: number; middlewareMs?: number } = {},
): SearchResponse {
  const type = INTENT[raw.intent_type] ?? 'SINGLE';
  const kind = scoreKind(raw);
  const traceIds = raw.resolution ? mapTrace(raw.resolution, raw.hits.map((h) => h.image_id)) : [];
  const retrievalStep = traceIds.find((s) => s.kind === 'retrieval')?.id;
  const results = raw.hits.map((h) => mapHit(h, kind, retrievalStep ? [retrievalStep] : []));

  const subTexts = raw.sub_queries.map((s) => s.text);
  // Group whenever the backend actually retrieved per sub-query, even if its label says otherwise
  // (an LLM parse can return intent_type "single" with two sub-queries).
  const grouped = type === 'MULTI_INTENT' || (type !== 'MULTI_HOP' && raw.sub_queries.length > 1);
  const shared = grouped ? deriveSharedLocation(subTexts) : undefined;
  const locations: LocationConstraint[] = shared ? [{ label: shared.label, scope: 'ALL_INTENTS', derived: true }] : [];

  const intents: IntentGroup[] =
    grouped
      ? raw.sub_queries.map((s) => {
          const images = results.filter((r) => r.intent_ids.includes(s.id));
          const text = shared && s.text.endsWith(shared.suffix) ? s.text.slice(0, -shared.suffix.length).trim() : s.text;
          return {
            id: s.id,
            text: text || s.text,
            backend_text: s.text,
            evidence: s.evidence,
            returned: s.returned,
            supported_candidates: s.supported_candidates,
            images,
            status: images.length ? 'ok' : 'empty',
          };
        })
      : [];

  const stages: StageTiming[] = Object.entries(raw.timings_ms).map(([key, ms]) => ({ key, label: stageLabel(key), ms }));
  const cached = 'cache_lookup' in raw.timings_ms;
  const staged = stages.reduce((sum, s) => sum + s.ms, 0);
  const unattributed = stages.length && !cached ? raw.total_ms - staged : undefined;

  return {
    request_id: raw.request_id,
    query: params.query,
    query_type: type,
    query_type_source: 'backend',
    parser: raw.parser,
    parse_confidence: raw.parse_confidence ?? undefined,
    pipeline_version: raw.pipeline_version ?? undefined,
    status: runStatus(raw, type),
    type_mismatch: grouped && type !== 'MULTI_INTENT' ? `Backend gắn nhãn ${raw.intent_type} nhưng đã truy xuất theo ${raw.sub_queries.length} sub-query (parser: ${raw.parser}).` : undefined,
    warnings: raw.warnings,
    constraints: { locations, parent_class: params.parent_class, must_match_all_intents: undefined },
    intents,
    trace: traceIds,
    hop_status: raw.resolution?.status,
    hop: raw.resolution ? hopSummary(raw.resolution) : undefined,
    results,
    facets: {
      classes: Object.entries(raw.facets.classes ?? {})
        .map(([label, count]) => ({ label, count }))
        .sort((a, b) => b.count - a.count),
    },
    total_results: undefined,
    top_k: params.top_k,
    timings: {
      total_ms: raw.total_ms,
      middleware_ms: observed.middlewareMs,
      stages,
      unattributed_ms: unattributed !== undefined && unattributed >= 0 ? unattributed : undefined,
      client_observed_ms: observed.clientObservedMs,
      cached,
    },
    provenance: 'ACTUAL',
  };
}

export async function searchImages(params: SearchParams, signal?: AbortSignal): Promise<SearchResponse> {
  const body: Record<string, unknown> = { query: params.query, top_k: params.top_k };
  if (params.parent_class) body.filters = { parent_class: params.parent_class };
  const res = await request('/v1/search', rawSearchSchema, { method: 'POST', body, signal });
  return adaptSearch(res.data, params, { clientObservedMs: res.clientObservedMs, middlewareMs: res.middlewareMs });
}
