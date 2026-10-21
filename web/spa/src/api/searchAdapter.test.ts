import { describe, expect, it } from 'vitest';
import { adaptSearch, deriveSharedLocation, describeWarning } from './searchAdapter';
import { rawSearchSchema } from './validators';
import { isBreach, slaGate, slaLevel } from '@/lib/sla';
import { safeApiPath, safeHttpUrl } from '@/lib/url';

const hit = (id: string, subs: string[], extra: Record<string, unknown> = {}) => ({
  image_id: id,
  image_url: `https://img.example.vn/${id}.jpg`,
  score: 0.8,
  entity_id: `e-${id}`,
  leaf_label: `Thực thể ${id}`,
  parent_class: 'Nhóm',
  matched_subqueries: subs,
  quality: { width: null, height: null, verify: 'unknown', watermark: 'unknown', pixel_checked: false },
  ...extra,
});

const base = {
  request_id: 'r1',
  parser: 'rule',
  facets: { entities: {}, classes: { Nhóm: 2 }, query_types: {} },
  timings_ms: { parse: 1, embed_query: 100, dense: 30, retrieve: 120, rerank: 110 },
  total_ms: 400,
  warnings: [],
  parse_confidence: 'high',
  pipeline_version: 'b3',
  resolution: null,
};

const params = { query: 'hồ bơi và công viên nước ở Phú Quốc', top_k: 20 };

describe('deriveSharedLocation', () => {
  it('extracts the shared place without making it an intent', () => {
    expect(deriveSharedLocation(['hồ bơi ở phú quốc', 'công viên nước ở phú quốc'])).toEqual({ suffix: 'ở phú quốc', label: 'phú quốc' });
  });
  it('ignores different locations and single sub-queries', () => {
    expect(deriveSharedLocation(['chùa ở huế', 'biển ở nha trang'])).toBeUndefined();
    expect(deriveSharedLocation(['hồ bơi ở phú quốc'])).toBeUndefined();
    expect(deriveSharedLocation(['phở bò', 'bánh cuốn'])).toBeUndefined();
  });
});

describe('adaptSearch — MULTI_INTENT', () => {
  const raw = rawSearchSchema.parse({
    ...base,
    intent_type: 'multi_intent',
    hits: [hit('a', ['q0']), hit('b', ['q1']), hit('c', ['q0', 'q1'])],
    sub_queries: [
      { id: 'q0', text: 'hồ bơi ở phú quốc', coverage: 'covered', returned: 2, evidence: 'retrieval_rank' },
      { id: 'q1', text: 'công viên nước ở phú quốc', coverage: 'covered', returned: 2, evidence: 'retrieval_rank' },
    ],
  });
  const res = adaptSearch(raw, params);

  it('has two intents and Phú Quốc as a shared derived constraint', () => {
    expect(res.query_type).toBe('MULTI_INTENT');
    expect(res.intents.map((i) => i.text)).toEqual(['hồ bơi', 'công viên nước']);
    expect(res.constraints.locations).toEqual([{ label: 'phú quốc', scope: 'ALL_INTENTS', derived: true }]);
  });
  it('groups by backend matched_subqueries and does not duplicate merged images', () => {
    expect(res.intents[0]!.images.map((i) => i.image_id)).toEqual(['a', 'c']);
    expect(res.intents[1]!.images.map((i) => i.image_id)).toEqual(['b', 'c']);
    expect(new Set(res.results.map((r) => r.image_id)).size).toBe(res.results.length);
    expect(res.results.find((r) => r.image_id === 'c')!.intent_ids).toEqual(['q0', 'q1']);
  });
  it('keeps measured stages and only reports a non-negative unattributed remainder', () => {
    expect(res.timings.total_ms).toBe(400);
    expect(res.timings.unattributed_ms).toBe(39);
    expect(res.timings.cached).toBe(false);
  });
});

describe('adaptSearch — states', () => {
  it('marks a partial result when an intent has no coverage', () => {
    const raw = rawSearchSchema.parse({ ...base, intent_type: 'multi_intent', hits: [hit('a', ['q0'])], sub_queries: [{ id: 'q0', text: 'a' }, { id: 'q1', text: 'b' }], warnings: ['sub_query_no_coverage: q1 (b)'] });
    const res = adaptSearch(raw, params);
    expect(res.status).toBe('partial');
    expect(res.intents[1]!.status).toBe('empty');
    expect(describeWarning(raw.warnings[0]!)).toContain('“b”');
  });

  it('never fabricates a multi-hop result when the seed is not linked', () => {
    const raw = rawSearchSchema.parse({
      ...base,
      intent_type: 'multi_hop',
      hits: [],
      sub_queries: [],
      warnings: ['multi_hop seed_not_linked: no verified relation chain'],
      resolution: { status: 'seed_not_linked', seed: { text: 'phạm nhật vượng', nodes: [] }, steps: [], target_nodes: [], mapped_target_entity_ids: [] },
    });
    const res = adaptSearch(raw, { query: 'ảnh con trai chủ tịch Phạm Nhật Vượng', top_k: 20 });
    expect(res.status).toBe('unverified');
    expect(res.results).toHaveLength(0);
    expect(res.trace).toHaveLength(1);
    expect(res.trace[0]!.status).toBe('unverified');
    expect(res.trace.some((s) => s.status === 'ok')).toBe(false);
  });

  it('links images to the retrieval step only for a resolved chain with sources', () => {
    const raw = rawSearchSchema.parse({
      ...base,
      intent_type: 'multi_hop',
      hits: [hit('t1', ['q0'], { score: 1 })],
      sub_queries: [{ id: 'q0', text: 'x', evidence: 'verified_relation_chain' }],
      resolution: {
        status: 'resolved',
        seed: { text: 'gia long', nodes: [{ node_id: 'person:gia-long', kind: 'person', label: 'Gia Long', gender: 'male' }] },
        steps: [
          {
            phrase: 'con trai',
            predicate: 'PARENT_OF',
            direction: 'forward',
            gender: 'male',
            edges: [
              { subject: 'person:gia-long', subject_label: 'Gia Long', predicate: 'PARENT_OF', object: 'person:minh-mang', object_label: 'Minh Mạng', source_type: 'gemini_doc', source: 'https://vi.wikipedia.org/wiki/Minh_M%E1%BA%A1ng', evidence: 'Minh Mạng là con trai thứ tư của vua Gia Long.' },
              { subject: 'person:gia-long', subject_label: 'Gia Long', predicate: 'PARENT_OF', object: 'person:minh-mang', object_label: 'Minh Mạng', source_type: 'manual_claim', source: 'javascript:alert(1)', evidence: 'x' },
            ],
          },
        ],
        target_nodes: [{ node_id: 'person:minh-mang', kind: 'person', label: 'Minh Mạng', gender: 'male' }],
        mapped_target_entity_ids: ['e-t1'],
      },
    });
    const res = adaptSearch(raw, { query: 'lăng con vua gia long', top_k: 20 });
    expect(res.status).toBe('ok');
    expect(res.trace.map((s) => s.kind)).toEqual(['entity_linking', 'relation_lookup', 'catalog_mapping', 'retrieval']);
    expect(res.trace[1]!.relation).toBe('cha/mẹ → con · nam');
    const fact = res.trace[1]!.facts![0]!;
    expect(fact).toMatchObject({ subject: 'Gia Long', object: 'Minh Mạng' });
    expect(fact.sources[0]).toMatchObject({ type: 'gemini_doc', url: 'https://vi.wikipedia.org/wiki/Minh_M%E1%BA%A1ng' });
    expect(fact.sources[1]!.url).toBeUndefined();
    expect(res.results[0]!.score_kind).toBe('rank');
    expect(res.results[0]!.producer_step_ids).toEqual([res.trace[3]!.id]);
  });

  it('keeps a pending online lookup distinct from "no evidence"', () => {
    const raw = rawSearchSchema.parse({
      ...base,
      intent_type: 'multi_hop',
      hits: [],
      sub_queries: [],
      warnings: ['multi_hop pending_online_lookup: KG has no verified edge yet'],
      resolution: {
        status: 'pending_online_lookup',
        seed: { text: 'x', nodes: [{ node_id: 'person:x', label: 'X' }] },
        steps: [],
        online: { status: 'pending', budget_ms: 2500 },
      },
    });
    const res = adaptSearch(raw, params);
    expect(res.status).toBe('pending');
    expect(res.trace.at(-1)!.status).toBe('pending');
    expect(res.results).toHaveLength(0);
    expect(describeWarning(raw.warnings[0]!)).toContain('trực tuyến');
  });

  it('labels unsupported relations', () => {
    const raw = rawSearchSchema.parse({ ...base, intent_type: 'multi_hop', hits: [], sub_queries: [], resolution: { status: 'unsupported_relation', seed: { text: 'x' } } });
    expect(adaptSearch(raw, params).status).toBe('unsupported');
  });

  it('keeps an empty answer empty when nothing reaches the relevance floor', () => {
    const raw = rawSearchSchema.parse({ ...base, intent_type: 'single', hits: [], sub_queries: [{ id: 'q0', text: 'iphone 15' }], warnings: ['no_relevant_results: no candidate reached relevance 0.1'] });
    const res = adaptSearch(raw, params);
    expect(res.results).toHaveLength(0);
    expect(describeWarning(raw.warnings[0]!)).toContain('đủ liên quan');
  });

  it('passes the raw cross-encoder relevance through', () => {
    const raw = rawSearchSchema.parse({ ...base, intent_type: 'single', hits: [hit('a', ['q0'], { score: 0.7, relevance: 0.95 })], sub_queries: [] });
    expect(adaptSearch(raw, params).results[0]!.relevance).toBe(0.95);
  });

  it('flags cached responses and drops unsafe image URLs', () => {
    const raw = rawSearchSchema.parse({ ...base, intent_type: 'single', timings_ms: { cache_lookup: 3 }, total_ms: 3, hits: [hit('a', ['q0'], { image_url: 'javascript:alert(1)' })], sub_queries: [] });
    const res = adaptSearch(raw, params);
    expect(res.timings.cached).toBe(true);
    expect(res.timings.unattributed_ms).toBeUndefined();
    expect(res.results[0]!.thumbnail_url).toBeUndefined();
  });
});

describe('SLA and URL helpers', () => {
  it('treats exactly 3,000 ms as a breach', () => {
    expect(isBreach(2999)).toBe(false);
    expect(isBreach(3000)).toBe(true);
    expect(slaLevel(3000)).toBe('warn');
    expect(slaLevel(undefined)).toBe('none');
  });
  it('requires measurements and zero breaches for PASS', () => {
    expect(slaGate(0, 1)).toBe('NOT_MEASURED');
    expect(slaGate(244, undefined)).toBe('NOT_MEASURED');
    expect(slaGate(244, 0.9959)).toBe('FAIL');
    expect(slaGate(244, 1)).toBe('PASS');
  });
  it('accepts only http(s) and well-formed thumb paths', () => {
    expect(safeHttpUrl('data:text/html,x')).toBeUndefined();
    expect(safeApiPath('/thumbs/../../.env', '/api')).toBeUndefined();
    expect(safeApiPath(`/thumbs/${'a'.repeat(64)}.jpg`, '/api')).toBe(`/api/thumbs/${'a'.repeat(64)}.jpg`);
  });
});
