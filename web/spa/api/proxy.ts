// Vercel Edge Function: /api/* -> backend FastAPI (Hugging Face Space).
// X-API-Key chỉ nằm trong env của Vercel, không bao giờ vào bundle trình duyệt —
// cùng vai trò với proxy của vite dev/preview (vite.config.ts).
export const config = { runtime: 'edge' };

const ALLOWED = /^(v1|thumbs)(\/|$)/;
const DROP_REQUEST = ['host', 'connection', 'content-length', 'accept-encoding', 'x-api-key', 'cookie'];
// fetch ở edge đã giải nén body; giữ các header này sẽ làm trình duyệt giải nén lần nữa.
const DROP_RESPONSE = ['content-encoding', 'content-length', 'transfer-encoding', 'connection'];

export default async function handler(req: Request): Promise<Response> {
  const backend = process.env.BACKEND_URL;
  if (!backend) return Response.json({ detail: 'BACKEND_URL chưa được cấu hình trên Vercel' }, { status: 500 });

  const url = new URL(req.url);
  const path = url.searchParams.get('__path') ?? '';
  url.searchParams.delete('__path');
  if (!ALLOWED.test(path)) return Response.json({ detail: 'Not found' }, { status: 404 });

  const headers = new Headers(req.headers);
  for (const h of DROP_REQUEST) headers.delete(h);
  const key = process.env.TEST_API_KEY;
  if (key) headers.set('X-API-Key', key);

  const t0 = Date.now();
  let upstream: Response;
  try {
    upstream = await fetch(`${backend.replace(/\/+$/, '')}/${path}${url.search}`, {
      method: req.method,
      headers,
      body: req.method === 'GET' || req.method === 'HEAD' ? undefined : await req.arrayBuffer(),
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
