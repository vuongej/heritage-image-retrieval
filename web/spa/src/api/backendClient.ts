import type { ZodType, ZodTypeDef } from 'zod';
import { API_BASE, REQUEST_TIMEOUT_MS } from '@/config';

export type ApiErrorKind =
  | 'network'
  | 'timeout'
  | 'auth'
  | 'not_found'
  | 'invalid_request'
  | 'rate_limited'
  | 'unavailable'
  | 'server'
  | 'invalid_payload';

export class ApiError extends Error {
  constructor(
    public kind: ApiErrorKind,
    message: string,
    public status?: number,
    public retryAfterSeconds?: number,
    public detail?: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export interface ApiResult<T> {
  data: T;
  clientObservedMs: number;
  /** Server middleware time from `X-Response-Time`, when the header is exposed. */
  middlewareMs?: number;
}

function kindFor(status: number): ApiErrorKind {
  if (status === 401 || status === 403) return 'auth';
  if (status === 404) return 'not_found';
  if (status === 422 || status === 400) return 'invalid_request';
  if (status === 429) return 'rate_limited';
  if (status === 503) return 'unavailable';
  return 'server';
}

async function readDetail(res: Response): Promise<string | undefined> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === 'string') return body.detail;
    if (Array.isArray(body.detail)) return body.detail.map((d) => d?.msg ?? '').join('; ');
  } catch {
    /* non-JSON error body */
  }
  return undefined;
}

/** Same-origin request through the /api proxy (the proxy attaches X-API-Key server-side). */
export async function request<T>(
  path: string,
  schema: ZodType<T, ZodTypeDef, unknown>,
  init: { method?: 'GET' | 'POST'; body?: unknown; signal?: AbortSignal; timeoutMs?: number } = {},
): Promise<ApiResult<T>> {
  const timeout = new AbortController();
  const timer = setTimeout(() => timeout.abort(), init.timeoutMs ?? REQUEST_TIMEOUT_MS);
  const onAbort = () => timeout.abort();
  init.signal?.addEventListener('abort', onAbort);
  const started = performance.now();
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method: init.method ?? 'GET',
      headers: init.body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
      signal: timeout.signal,
    });
  } catch (err) {
    if (init.signal?.aborted) throw err; // superseded by a newer query: let React Query drop it
    if (timeout.signal.aborted) {
      throw new ApiError('timeout', `Quá thời gian chờ ${(init.timeoutMs ?? REQUEST_TIMEOUT_MS) / 1000}s`);
    }
    throw new ApiError('network', navigator.onLine ? 'Không kết nối được tới backend' : 'Thiết bị đang offline');
  } finally {
    clearTimeout(timer);
    init.signal?.removeEventListener('abort', onAbort);
  }
  const clientObservedMs = Math.round(performance.now() - started);
  if (!res.ok) {
    const detail = await readDetail(res);
    const retry = Number(res.headers.get('Retry-After'));
    throw new ApiError(
      kindFor(res.status),
      `HTTP ${res.status}`,
      res.status,
      Number.isFinite(retry) && retry > 0 ? retry : undefined,
      detail,
    );
  }
  const json: unknown = await res.json();
  const parsed = schema.safeParse(json);
  if (!parsed.success) {
    throw new ApiError(
      'invalid_payload',
      'Phản hồi backend không khớp hợp đồng dữ liệu',
      res.status,
      undefined,
      parsed.error.issues.slice(0, 3).map((i) => `${i.path.join('.')}: ${i.message}`).join('; '),
    );
  }
  const header = Number(res.headers.get('X-Response-Time'));
  return {
    data: parsed.data,
    clientObservedMs,
    middlewareMs: Number.isFinite(header) && res.headers.has('X-Response-Time') ? header : undefined,
  };
}

export const errorCopy: Record<ApiErrorKind, { title: string; hint: string }> = {
  network: { title: 'Không kết nối được backend', hint: 'Kiểm tra API đang chạy ở cổng 8000 và proxy /api.' },
  timeout: { title: 'Quá thời gian chờ', hint: 'Backend chưa trả lời kịp. Thử lại hoặc xem log server.' },
  auth: { title: 'Bị từ chối xác thực', hint: 'Proxy chưa gắn X-API-Key hợp lệ (TEST_API_KEY trong .env).' },
  not_found: { title: 'Không tìm thấy', hint: 'Endpoint hoặc báo cáo chưa tồn tại trên backend.' },
  invalid_request: { title: 'Yêu cầu không hợp lệ', hint: 'Backend từ chối tham số truy vấn.' },
  rate_limited: { title: 'Vượt giới hạn tốc độ (429)', hint: 'Chờ rồi thử lại.' },
  unavailable: { title: 'Dịch vụ tạm không sẵn sàng (503)', hint: 'Một thành phần phụ thuộc đang lỗi — xem log backend.' },
  server: { title: 'Lỗi máy chủ', hint: 'Xem log backend để biết nguyên nhân.' },
  invalid_payload: { title: 'Sai hợp đồng dữ liệu', hint: 'Payload backend khác docs/backend-inventory.md.' },
};
