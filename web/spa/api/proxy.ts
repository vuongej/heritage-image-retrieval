// Vercel Edge Function: /api/* -> backend FastAPI.
// X-API-Key chỉ nằm trong env của Vercel, không bao giờ vào bundle trình duyệt —
// cùng vai trò với proxy của vite dev/preview (vite.config.ts).
export const config = { runtime: 'edge' };

// Proxy này PUBLIC và gắn sẵn API key, nên chỉ cho qua đúng những lời gọi SPA thực sự dùng.
// Không chuyển tiếp: POST /v1/graph (rebuild), /v1/verify/label (ghi nhãn), /v1/ingest,
// /v1/backfill, /v1/embed, /v1/rerank — các endpoint ghi dữ liệu hoặc tốn quota.
const ROUTES: { method: string; path: RegExp; process?: boolean }[] = [
  { method: 'POST', path: /^v1\/search$/ },
  { method: 'GET', path: /^v1\/(health|stats)$/ },
  { method: 'GET', path: /^v1\/reports(\/[\w-]+)?$/ },
  { method: 'GET', path: /^v1\/verify\/audit$/ },
  { method: 'GET', path: /^thumbs\/[\w.-]+$/ },
  // Pipeline A — processing service riêng (PROCESS_URL); upload CSV tối đa MAX_UPLOAD_BYTES.
  { method: 'GET', path: /^v1\/process\/(health|jobs|sample\.csv)$/, process: true },
  { method: 'POST', path: /^v1\/process\/jobs$/, process: true },
  { method: 'GET', path: /^v1\/process\/jobs\/[\w-]+(\/(items|result\.csv))?$/, process: true },
  { method: 'POST', path: /^v1\/process\/jobs\/[\w-]+\/cancel$/, process: true },
  { method: 'GET', path: /^v1\/process\/thumbs\/[0-9a-f]{64}\.jpg$/, process: true },
];
const DROP_REQUEST = ['host', 'connection', 'content-length', 'accept-encoding', 'x-api-key', 'cookie', 'authorization'];
// fetch ở edge đã giải nén body; giữ các header này sẽ làm trình duyệt giải nén lần nữa.
const DROP_RESPONSE = ['content-encoding', 'content-length', 'transfer-encoding', 'connection'];
const MAX_BODY_BYTES = 8 * 1024;
// Giới hạn payload của Vercel Function là 4,5 MB: CSV lớn hơn phải gửi thẳng tới processing service.
const MAX_UPLOAD_BYTES = 4 * 1024 * 1024;

export default async function handler(req: Request): Promise<Response> {
  const backend = process.env.BACKEND_URL;
  if (!backend) return Response.json({ detail: 'BACKEND_URL chưa được cấu hình trên Vercel' }, { status: 500 });

  const url = new URL(req.url);
  const path = url.searchParams.get('__path') ?? '';
  url.searchParams.delete('__path');
  const route = ROUTES.find((r) => r.method === req.method && r.path.test(path));
  if (!route) {
    return Response.json({ detail: 'Not found' }, { status: 404 });
  }
  const target = route.process ? process.env.PROCESS_URL : backend;
  if (!target) {
    return Response.json(
      { detail: 'Pipeline xử lý (processing service) chưa được triển khai trên bản cloud: đặt PROCESS_URL, hoặc chạy bản docker compose (README §2).' },
      { status: 503 },
    );
  }

  let body: ArrayBuffer | undefined;
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    body = await req.arrayBuffer();
    if (body.byteLength > (route.process ? MAX_UPLOAD_BYTES : MAX_BODY_BYTES)) return Response.json({ detail: 'Payload quá lớn' }, { status: 413 });
  }

  const headers = new Headers(req.headers);
  for (const h of DROP_REQUEST) headers.delete(h);
  const key = process.env.TEST_API_KEY;
  if (key) headers.set('X-API-Key', key);
  // Space private: HF chỉ cho qua request có token (quyền read) của chủ Space.
  // Chỉ gửi token này tới Space backend, không bao giờ tới PROCESS_URL (host khác).
  const hfToken = process.env.HF_SPACE_TOKEN;
  if (hfToken && !route.process) headers.set('Authorization', `Bearer ${hfToken}`);

  const t0 = Date.now();
  let upstream: Response;
  try {
    upstream = await fetch(`${target.replace(/\/+$/, '')}/${path}${url.search}`, {
      method: req.method,
      headers,
      body,
      redirect: 'manual',
    });
  } catch {
    return Response.json({ detail: 'Backend không phản hồi (Space có thể đang khởi động lại)' }, { status: 502 });
  }

  const out = new Headers(upstream.headers);
  for (const h of DROP_RESPONSE) out.delete(h);
  out.set('X-Proxy-Upstream-Ms', String(Date.now() - t0));
  return new Response(upstream.body, { status: upstream.status, headers: out });
}
