// DATA_MODE=mock ONLY. Every value here is "DỮ LIỆU MINH HỌA — KHÔNG PHẢI KẾT QUẢ ĐO".
// Images are generated SVG placeholders: no real or third-party photos in fixtures.
import type { ImageResult, SearchParams, SearchResponse } from '@/types/search';

const placeholder = (label: string, hue: number) =>
  `data:image/svg+xml;utf8,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300"><rect width="400" height="300" fill="hsl(${hue} 40% 88%)"/><text x="200" y="150" text-anchor="middle" font-family="sans-serif" font-size="20" fill="hsl(${hue} 30% 35%)">${label}</text><text x="200" y="180" text-anchor="middle" font-family="sans-serif" font-size="12" fill="hsl(${hue} 30% 45%)">MINH HỌA</text></svg>`,
  )}`;

function img(i: number, name: string, intent: string, hue: number): ImageResult {
  return {
    image_id: `mock-${intent}-${i}`,
    entity_id: `mock-entity-${intent}`,
    entity_name: name,
    entity_class: 'Nhóm minh họa',
    thumbnail_url: placeholder(name, hue),
    score: undefined,
    score_kind: 'other',
    source_host: 'minh-hoa.local',
    caption: 'Ảnh minh họa sinh tự động — không phải dữ liệu thật.',
    intent_ids: [intent],
    producer_step_ids: [],
    moderation: { status: 'approved', source: 'fixture', labels: [] },
    quality: { verify: 'unknown', watermark: 'unknown', pixel_checked: false },
  };
}

const base = {
  query_type_source: 'fixture' as const,
  parser: 'fixture',
  warnings: [],
  constraints: {},
  intents: [],
  trace: [],
  facets: { classes: [] },
  timings: { stages: [], cached: false },
  provenance: 'FIXTURE' as const,
};

export function mockSearch(params: SearchParams): SearchResponse {
  const q = params.query.toLowerCase();
  if (q.includes(' và ')) {
    const a = Array.from({ length: 4 }, (_, i) => img(i, 'Hồ bơi', 'q0', 200));
    const b = Array.from({ length: 4 }, (_, i) => img(i, 'Công viên nước', 'q1', 160));
    return {
      ...base,
      request_id: 'mock-multi-1',
      query: params.query,
      query_type: 'MULTI_INTENT',
      status: 'ok',
      constraints: { locations: [{ label: 'phú quốc', scope: 'ALL_INTENTS', derived: true }] },
      intents: [
        { id: 'q0', text: 'hồ bơi', backend_text: 'hồ bơi ở phú quốc', images: a, status: 'ok' },
        { id: 'q1', text: 'công viên nước', backend_text: 'công viên nước ở phú quốc', images: b, status: 'ok' },
      ],
      results: [...a, ...b],
      top_k: params.top_k,
    };
  }
  if (q.includes('con trai') || q.includes('con gái')) {
    return {
      ...base,
      request_id: 'mock-hop-1',
      query: params.query,
      query_type: 'MULTI_HOP',
      status: 'unverified',
      hop_status: 'seed_not_linked',
      message: 'Chưa có quan hệ và nguồn xác minh được hệ thống cung cấp',
      trace: [
        {
          id: 'h1',
          step: 1,
          kind: 'relation_lookup',
          status: 'unverified',
          input_summary: 'Tra quan hệ từ truy vấn',
          output_summary: 'Chưa có dữ liệu xác minh',
          evidence: [],
        },
      ],
      results: [],
      top_k: params.top_k,
    };
  }
  const results = Array.from({ length: 8 }, (_, i) => img(i, 'Bãi biển minh họa', 'q0', 30 + i * 20));
  return {
    ...base,
    request_id: 'mock-single-1',
    query: params.query,
    query_type: 'SINGLE',
    status: 'ok',
    results,
    top_k: params.top_k,
  };
}
