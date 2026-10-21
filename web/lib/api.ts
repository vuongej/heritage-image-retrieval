const BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000';
const KEY = process.env.NEXT_PUBLIC_TEST_API_KEY || 'gsk_test_dev_only';

export type Hit = {
  image_id: string; image_url: string; score: number;
  entity_id?: string; entity_slug?: string; leaf_label?: string;
  query_type?: string; parent_class?: string;
};

export type SearchResult = {
  request_id: string; intent_type: string; parser: string;
  hits: Hit[]; facets: { entities?: Record<string, string>;
    classes?: Record<string, number>; query_types?: Record<string, number> };
  timings_ms: Record<string, number>; total_ms: number;
};

export async function search(query: string, topK = 10): Promise<SearchResult> {
  const res = await fetch(`${BASE}/v1/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-API-Key': KEY },
    body: JSON.stringify({ query, top_k: topK }),
  });
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}
