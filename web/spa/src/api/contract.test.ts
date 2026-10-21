import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { adaptSearch } from './searchAdapter';
import { rawSearchSchema } from './validators';

// Real /v1/search payloads captured through the SPA proxy on 21/10/2026 (src/api/__samples__).
const sample = (name: string) => rawSearchSchema.parse(JSON.parse(readFileSync(join(__dirname, '__samples__', `${name}.json`), 'utf8')));

describe('contract — real backend payloads', () => {
  it('SINGLE: real image ids, reranker scores, no fabricated total', () => {
    const res = adaptSearch(sample('single'), { query: 'Quần thể Tràng An', top_k: 20 });
    expect(res.query_type).toBe('SINGLE');
    expect(res.results.length).toBeGreaterThan(0);
    expect(res.results.every((r) => /^[0-9a-f-]{36}$/.test(r.image_id))).toBe(true);
    expect(res.results[0]!.score_kind).toBe('reranker');
    expect(res.total_results).toBeUndefined();
    expect(res.intents).toHaveLength(0);
  });

  it('golden multi-intent: two intents, Phú Quốc shared — even when the backend labels it single', () => {
    const raw = sample('multi_intent');
    const res = adaptSearch(raw, { query: 'hồ bơi và công viên nước ở Phú Quốc', top_k: 20 });
    expect(res.intents.map((i) => i.text)).toEqual(['hồ bơi', 'công viên nước']);
    expect(res.constraints.locations?.map((l) => l.label)).toEqual(['phú quốc']);
    if (raw.intent_type !== 'multi_intent') expect(res.type_mismatch).toBeDefined();
    const unique = new Set(res.results.map((r) => r.image_id));
    expect(unique.size).toBe(res.results.length);
    const groupSum = res.intents.reduce((s, it) => s + it.images.length, 0);
    expect(groupSum).toBeGreaterThanOrEqual(unique.size);
  });

  it('two-dish multi-intent groups by entity-name evidence', () => {
    const res = adaptSearch(sample('multi_food'), { query: 'Phở bò và Bánh cuốn', top_k: 20 });
    expect(res.query_type).toBe('MULTI_INTENT');
    expect(res.constraints.locations).toEqual([]);
    expect(res.intents.every((i) => i.evidence === 'entity_name' && i.images.length > 0)).toBe(true);
  });

  it('MULTI_HOP with an unlinked seed stays unverified with no images', () => {
    const res = adaptSearch(sample('multi_hop'), { query: 'ảnh con trai chủ tịch Phạm Nhật Vượng', top_k: 20 });
    expect(res.query_type).toBe('MULTI_HOP');
    expect(res.hop_status).toBe('seed_not_linked');
    expect(res.status).toBe('unverified');
    expect(res.results).toHaveLength(0);
    expect(res.trace.every((s) => s.status !== 'ok')).toBe(true);
  });

  it('MULTI_HOP resolved: labelled facts with quotes, sources, images on the retrieval step', () => {
    const res = adaptSearch(sample('multi_hop_resolved'), { query: 'lăng của mẹ vua Minh Mạng', top_k: 20 });
    expect(res.status).toBe('ok');
    expect(res.trace.map((s) => s.kind)).toEqual(['entity_linking', 'relation_lookup', 'relation_lookup', 'catalog_mapping', 'retrieval']);
    expect(res.trace[0]!.output_summary).toContain('Minh Mạng');
    const parent = res.trace[1]!.facts!;
    // Two edges, one relation: grouped into one fact with every source kept.
    expect(parent).toHaveLength(1);
    expect(parent[0]!.object).toBe('Minh Mạng');
    expect(parent[0]!.sources.every((s) => s.url && s.quote)).toBe(true);
    expect(res.trace.flatMap((s) => s.facts ?? []).every((f) => !f.subject.includes(':') && !f.object.includes(':'))).toBe(true);
    expect(res.results.length).toBeGreaterThan(0);
    expect(res.results[0]!.producer_step_ids).toEqual([res.trace[4]!.id]);
  });

  it('MULTI_HOP catalog-name evidence has no URL but keeps the catalog entity id', () => {
    const res = adaptSearch(sample('multi_hop_child_tomb'), { query: 'lăng của con trai vua Gia Long', top_k: 20 });
    const place = res.trace.find((s) => s.relation?.startsWith('an táng'))!;
    const catalog = place.facts!.flatMap((f) => f.sources).filter((s) => s.type === 'catalog_name');
    expect(catalog.length).toBeGreaterThan(0);
    expect(catalog.every((s) => s.url === undefined && s.catalog_entity_id)).toBe(true);
  });

  it('MULTI_HOP target_not_in_catalog: verified people, no substitute images', () => {
    const res = adaptSearch(sample('multi_hop_target_not_in_catalog'), { query: 'vợ vua Khải Định', top_k: 20 });
    expect(res.status).toBe('unverified');
    expect(res.results).toHaveLength(0);
    expect(res.hop!.targets.map((t) => t.label)).toContain('Trương Như Thị Tịnh');
    expect(res.trace[1]!.status).toBe('ok');
    expect(res.trace.at(-1)!.kind).toBe('catalog_mapping');
    expect(res.trace.at(-1)!.status).toBe('unverified');
  });

  it('SET_QUERY is kept as its own backend label', () => {
    expect(adaptSearch(sample('set_query'), { query: 'các chợ truyền thống', top_k: 20 }).query_type).toBe('SET_QUERY');
  });
});
