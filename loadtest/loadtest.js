// k6 — load test /v1/search cho 3 loại truy vấn, reproducible (README §5, docs/performance-benchmark.vi.md).
//
//   docker compose --profile loadtest run --rm k6          (qua web proxy, PROFILE=standard)
//   k6 run loadtest/loadtest.js -e API_BASE=https://<domain>/api -e PROFILE=smoke
//
// Truy vấn lấy từ bộ test case (loadtest/queries.json <- evals/testcases/cases.jsonl).
// Endpoint embedding + rerank bị giới hạn 100 request/phút/key, mỗi truy vấn chưa cache tốn
// 1 + số ý request, nên hai pha được đo riêng:
//   cold  mỗi truy vấn đúng 1 lần, nhịp 20 truy vấn/phút (trong hạn mức) -> latency lạnh
//   warm  tải cao, truy vấn lặp lại (cache /v1/search)                  -> throughput phục vụ
// PROFILE: smoke (CI, ~1 phút) | standard (mặc định) | stress (vượt hạn mức, xem suy giảm)
//          capacity (trần throughput phục vụ, truy vấn có cache; RATE req/s, mặc định 150)
import http from 'k6/http';
import { check } from 'k6';
import exec from 'k6/execution';
import { Rate, Trend } from 'k6/metrics';

const BASE = __ENV.API_BASE || 'http://web/api';
const KEY = __ENV.TEST_API_KEY || '';
const SLO = Number(__ENV.SLO_P95_MS || 3000);
const PROFILE = __ENV.PROFILE || 'standard';
const QUERIES = JSON.parse(open('./queries.json'));
const TYPES = ['single', 'multi_intent', 'multi_hop'];
// Danh sách phẳng, xen kẽ 3 loại để mọi khoảng thời gian đều có đủ loại.
const FLAT = [];
for (let i = 0; FLAT.length < TYPES.reduce((n, t) => n + QUERIES[t].length, 0); i++) {
  for (const t of TYPES) if (i < QUERIES[t].length) FLAT.push({ type: t, query: QUERIES[t][i] });
}

const errors = new Rate('errors');
const degraded = new Rate('degraded');
const serverMs = new Trend('server_ms', true);

const COLD = { executor: 'constant-arrival-rate', rate: 20, timeUnit: '1m', preAllocatedVUs: 4,
  duration: `${Math.ceil(FLAT.length / 20)}m`, exec: 'cold', tags: { phase: 'cold' } };
const PROFILES = {
  smoke: { cold: { ...COLD, duration: '1m' } },
  standard: {
    cold: COLD,
    warm: { executor: 'constant-arrival-rate', rate: 20, timeUnit: '1s', duration: '1m',
      preAllocatedVUs: 20, maxVUs: 60, exec: 'warm', startTime: COLD.duration, tags: { phase: 'warm' } },
  },
  capacity: {
    warm: { executor: 'constant-arrival-rate', rate: Number(__ENV.RATE || 150), timeUnit: '1s', duration: '1m',
      preAllocatedVUs: 50, maxVUs: 300, exec: 'warm', tags: { phase: 'warm' } },
  },
  stress: {
    burst: { executor: 'constant-arrival-rate', rate: 5, timeUnit: '1s', duration: '2m',
      preAllocatedVUs: 20, maxVUs: 60, exec: 'burst', tags: { phase: 'burst' } },
  },
};
const scenarios = PROFILES[PROFILE] || PROFILES.standard;

// Ngưỡng trên từng (pha, loại) — đồng thời buộc k6 xuất số liệu riêng cho từng nhóm trong summary.
const thresholds = { errors: ['rate<0.01'] };
for (const phase of Object.keys(scenarios)) {
  for (const t of TYPES) thresholds[`http_req_duration{phase:${phase},type:${t}}`] = [`p(95)<${SLO}`];
}

export const options = {
  scenarios,
  thresholds,
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max', 'count'],
};

function search(item, phase, fresh = false) {
  const res = http.post(`${BASE}/v1/search`, JSON.stringify({ query: item.query, top_k: 10 }), {
    headers: {
      'Content-Type': 'application/json',
      ...(KEY ? { 'X-API-Key': KEY } : {}),
      // cold: bỏ qua cache kết quả của API để đo đúng độ trễ lạnh
      ...(fresh ? { 'Cache-Control': 'no-cache' } : {}),
    },
    tags: { type: item.type, phase },
    timeout: '30s',
  });
  let body = null;
  try { body = JSON.parse(res.body); } catch (e) { /* lỗi được tính bên dưới */ }
  const ok = check(res, { 'status 200': (r) => r.status === 200, 'có trường hits': () => Boolean(body && body.hits) });
  errors.add(!ok);
  if (body && body.warnings) {
    degraded.add(body.warnings.some((w) => w.startsWith('embedding_') || w.startsWith('rerank_')), { phase });
  }
  const st = Number(res.headers['X-Response-Time']);
  if (Number.isFinite(st)) serverMs.add(st, { phase, type: item.type });
}

export function cold() {
  const i = exec.scenario.iterationInTest;
  if (i < FLAT.length) search(FLAT[i], 'cold', true);
}
export function warm() { search(FLAT[Math.floor(Math.random() * FLAT.length)], 'warm'); }
export function burst() { search(FLAT[exec.scenario.iterationInTest % FLAT.length], 'burst', true); }

export function handleSummary(data) {
  return { [__ENV.SUMMARY_PATH || 'reports/loadtest/raw.json']: JSON.stringify(data, null, 2) };
}
