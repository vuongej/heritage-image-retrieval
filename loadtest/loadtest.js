// k6 — SLO: p95 < 1500 ms cho cả 3 loại query.
// docker compose --profile loadtest run --rm k6 run /scripts/loadtest.js --out json=/reports/raw.json
import http from 'k6/http';
import { check } from 'k6';
import { Trend, Rate, Counter } from 'k6/metrics';

const BASE = __ENV.API_BASE || 'http://api:8000';
const KEY = __ENV.TEST_API_KEY || 'gsk_test_dev_only';
const SLO = Number(__ENV.SLO_P95_MS || 1500);

const latencyByType = {
  single: new Trend('latency_single', true),
  multi_intent: new Trend('latency_multi_intent', true),
  multi_hop: new Trend('latency_multi_hop', true),
  set_query: new Trend('latency_set_query', true),
};
const serverLatency = new Trend('server_latency', true);
const errRate = new Rate('errors');
const cacheHits = new Counter('cache_hits');

const QUERIES = {
  single: ['Quần thể Tràng An', 'bãi biển Nha Trang', 'Phố cổ Hội An'],
  multi_intent: ['hồ bơi và công viên nước ở Phú Quốc', 'chùa và bãi biển ở Nha Trang'],
  multi_hop: ['ảnh con trai chủ tịch Phạm Nhật Vượng'],
  set_query: ['những con vật sống trong rừng', 'ảnh con hổ và con mèo'],
};

// PROFILE=smoke: 1 VU mỗi loại query trong 1 phút — dùng trong CI sau mỗi lần deploy, giữ tải
// dưới quota 100 request/phút của endpoint embedding. PROFILE=full (mặc định): kịch bản đầy đủ.
const PROFILE = __ENV.PROFILE || 'full';

const SMOKE_SCENARIOS = {
  single_intent: { executor: 'constant-vus', vus: 1, duration: '1m', exec: 'single', tags: { type: 'single' } },
  multi_intent: { executor: 'constant-vus', vus: 1, duration: '1m', exec: 'multiIntent', tags: { type: 'multi_intent' } },
  multi_hop: { executor: 'constant-vus', vus: 1, duration: '1m', exec: 'multiHop', tags: { type: 'multi_hop' } },
};

const FULL_OPTIONS = {
  scenarios: {
    single_intent: {
      executor: 'constant-vus', vus: 20, duration: '3m',
      exec: 'single', tags: { type: 'single' },
    },
    multi_intent: {
      executor: 'constant-vus', vus: 20, duration: '3m',
      exec: 'multiIntent', tags: { type: 'multi_intent' },
    },
    multi_hop: {
      executor: 'constant-vus', vus: 10, duration: '3m',
      exec: 'multiHop', tags: { type: 'multi_hop' },
    },
    set_query: {
      executor: 'constant-vus', vus: 10, duration: '3m',
      exec: 'setQuery', tags: { type: 'set_query' },
    },
    embed_only: {
      executor: 'constant-vus', vus: 30, duration: '1m',
      exec: 'embedOnly', tags: { type: 'embed' },
    },
    rerank_only: {
      executor: 'constant-vus', vus: 30, duration: '1m',
      exec: 'rerankOnly', tags: { type: 'rerank' },
    },
  },
  thresholds: {
    'http_req_duration{type:single}': [`p(95)<${SLO}`],
    'http_req_duration{type:multi_intent}': [`p(95)<${SLO}`],
    'http_req_duration{type:multi_hop}': [`p(95)<${SLO}`],
    'http_req_duration{type:set_query}': [`p(95)<${SLO}`],
    'http_req_duration{type:embed}': ['p(95)<200'],
    'http_req_duration{type:rerank}': ['p(95)<400'],
    errors: ['rate<0.01'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(50)', 'p(95)', 'p(99)', 'max'],
};

export const options = PROFILE === 'smoke'
  ? {
      scenarios: SMOKE_SCENARIOS,
      thresholds: {
        'http_req_duration{type:single}': [`p(95)<${SLO}`],
        'http_req_duration{type:multi_intent}': [`p(95)<${SLO}`],
        'http_req_duration{type:multi_hop}': [`p(95)<${SLO}`],
        errors: ['rate<0.01'],
      },
      summaryTrendStats: FULL_OPTIONS.summaryTrendStats,
    }
  : FULL_OPTIONS;

function pick(arr) { return arr[Math.floor(Math.random() * arr.length)]; }

function callSearch(query, type) {
  const res = http.post(`${BASE}/v1/search`,
    JSON.stringify({ query, top_k: 10 }),
    { headers: { 'Content-Type': 'application/json', 'X-API-Key': KEY }, tags: { type } });
  const ok = check(res, {
    'status 200': (r) => r.status === 200,
    'has hits': (r) => { try { return JSON.parse(r.body).hits !== undefined; } catch (e) { return false; } },
  });
  errRate.add(!ok);
  latencyByType[type] && latencyByType[type].add(res.timings.duration);
  const st = res.headers['X-Response-Time'];
  if (st) serverLatency.add(Number(st));
  return res;
}

export function single() { callSearch(pick(QUERIES.single), 'single'); }
export function multiIntent() { callSearch(pick(QUERIES.multi_intent), 'multi_intent'); }
export function multiHop() { callSearch(pick(QUERIES.multi_hop), 'multi_hop'); }
export function setQuery() { callSearch(pick(QUERIES.set_query), 'set_query'); }

export function embedOnly() {
  const res = http.post(`${BASE}/v1/embed`,
    JSON.stringify({ texts: ['Quần thể Tràng An'] }),
    { headers: { 'Content-Type': 'application/json', 'X-API-Key': KEY }, tags: { type: 'embed' } });
  errRate.add(res.status !== 200);
}

export function rerankOnly() {
  const res = http.post(`${BASE}/v1/rerank`,
    JSON.stringify({ query: 'Quần thể Tràng An', candidates: [{ image_id: 'a' }, { image_id: 'b' }] }),
    { headers: { 'Content-Type': 'application/json', 'X-API-Key': KEY }, tags: { type: 'rerank' } });
  errRate.add(res.status !== 200);
}

export function handleSummary(data) {
  return { [__ENV.SUMMARY_PATH || '/reports/raw.json']: JSON.stringify(data, null, 2) };
}
