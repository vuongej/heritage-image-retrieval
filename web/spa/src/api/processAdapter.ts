import { z } from 'zod';
import { API_BASE } from '@/config';
import { ApiError, request } from './backendClient';

// Pipeline A — processing service riêng (processing/main.py, cổng 8100), proxy /api/v1/process/*.

const num = z.number().nullable().optional();

export const stageSchema = z.object({
  key: z.string(),
  label: z.string(),
  status: z.enum(['pending', 'running', 'done', 'skipped', 'failed', 'cancelled', 'interrupted']),
  done: z.number(),
  total: z.number(),
  seconds: num,
});

export const metricsSchema = z.object({
  n: z.number(),
  accuracy: z.number(),
  recall_no: z.number(),
  precision_no: z.number(),
  f1_no: z.number(),
  precision_yes: z.number(),
  recall_yes: z.number(),
  balanced_accuracy: z.number(),
  entity_retention: z.number(),
  confusion: z.record(z.number()),
});

const modelSchema = z.object({
  name: z.string(),
  description: z.string(),
  encoder: z.string(),
  created: z.string(),
  threshold_t: z.number(),
  router_alpha: z.number(),
  vlm_rule: z.string(),
  test_auc: z.number(),
  test_head_only: z.record(z.number()),
  test_with_router_vlm: z.record(z.number()),
});

export const summarySchema = z.object({
  rows: z.number(),
  approved: z.number(),
  rejected: z.number(),
  approved_share: z.number(),
  entities: z.number(),
  entities_with_approved: z.number(),
  by_stage: z.record(z.number()),
  by_reason: z.record(z.number()),
  routed: z.number(),
  decision: z.object({ threshold: z.number(), budget: z.number(), use_vlm: z.boolean(), vlm_rule: z.string() }),
  embedding: z
    .object({ encoded_images: num, cached_images: num, device: z.string().optional(), images_per_second: num })
    .partial()
    .default({}),
  vlm: z
    .object({
      images: num,
      judged: num,
      requests: num,
      errors: num,
      usd: num,
      seconds: num,
      images_per_second: num,
      latency_ms_p95: num,
      skipped: z.string().nullable().optional(),
      stopped: z.string().nullable().optional(),
    })
    .partial()
    .default({}),
  cost_usd: z.number(),
  cost_usd_per_1000: z.number(),
  throughput: z.object({ rows_per_second: num, fetch_images_per_second: num }),
  metrics: metricsSchema.nullable(),
  timings: z.record(z.number()).default({}),
  model: modelSchema,
});

export const jobSchema = z.object({
  id: z.string(),
  filename: z.string(),
  status: z.enum(['queued', 'running', 'done', 'failed', 'cancelled', 'interrupted']),
  created_at: z.number(),
  started_at: num,
  finished_at: num,
  elapsed_seconds: num,
  options: z.object({ use_vlm: z.boolean(), vlm_budget: num, threshold: num }),
  input: z.object({
    rows: z.number(),
    columns: z.array(z.string()),
    mapping: z.record(z.string()),
    entities: z.number(),
    labelled: z.number(),
  }),
  stages: z.array(stageSchema),
  summary: summarySchema.nullable(),
  error: z.string().nullable(),
  queued_ahead: z.number().optional(),
});

export const jobListSchema = z.object({
  items: z.array(
    z.object({
      id: z.string(),
      filename: z.string(),
      status: z.string(),
      created_at: z.number(),
      elapsed_seconds: num,
      rows: z.number(),
      approved: num,
      rejected: num,
    }),
  ),
});

export const itemSchema = z.object({
  line: z.number(),
  key: z.string(),
  entity_id: z.string(),
  entity_name: z.string(),
  category: z.string(),
  image_url: z.string(),
  label: z.string(),
  width: num,
  height: num,
  fetch_ms: num,
  p_yes: num,
  routed: z.boolean(),
  decision: z.enum(['yes', 'no']),
  stage: z.enum(['rule', 'classifier', 'vlm']),
  reason: z.string(),
  reason_text: z.string(),
  vlm: z
    .object({ subject: z.string(), watermark: z.boolean(), unsafe: z.boolean(), evidence: z.string().nullable().optional() })
    .partial()
    .nullable(),
});

export const itemsSchema = z.object({ total: z.number(), offset: z.number(), items: z.array(itemSchema) });

export const processHealthSchema = z.object({
  status: z.string(),
  model: modelSchema,
  encoder: z.string(),
  device: z.string(),
  vlm_available: z.boolean(),
  queue: z.number(),
  running: z.string().nullable(),
  max_rows: z.number(),
  max_upload_mb: z.number(),
});

export type Job = z.infer<typeof jobSchema>;
export type JobSummary = z.infer<typeof summarySchema>;
export type JobItem = z.infer<typeof itemSchema>;
export type JobMetrics = z.infer<typeof metricsSchema>;
export type ProcessHealth = z.infer<typeof processHealthSchema>;
export type JobListItem = z.infer<typeof jobListSchema>['items'][number];

export interface ItemFilter {
  decision?: 'yes' | 'no';
  stage?: 'rule' | 'classifier' | 'vlm';
  reason?: string;
  q?: string;
  mismatch?: boolean;
  offset: number;
  limit: number;
}

export const getProcessHealth = (signal?: AbortSignal) =>
  request('/v1/process/health', processHealthSchema, { signal }).then((r) => r.data);
export const listJobs = (signal?: AbortSignal) => request('/v1/process/jobs?limit=20', jobListSchema, { signal }).then((r) => r.data);
export const getJob = (id: string, signal?: AbortSignal) =>
  request(`/v1/process/jobs/${encodeURIComponent(id)}`, jobSchema, { signal }).then((r) => r.data);
export const cancelJob = (id: string) =>
  request(`/v1/process/jobs/${encodeURIComponent(id)}/cancel`, jobSchema, { method: 'POST' }).then((r) => r.data);

export function getItems(id: string, f: ItemFilter, signal?: AbortSignal) {
  const qs = new URLSearchParams({ offset: String(f.offset), limit: String(f.limit) });
  if (f.decision) qs.set('decision', f.decision);
  if (f.stage) qs.set('stage', f.stage);
  if (f.reason) qs.set('reason', f.reason);
  if (f.q) qs.set('q', f.q);
  if (f.mismatch) qs.set('mismatch', 'true');
  return request(`/v1/process/jobs/${encodeURIComponent(id)}/items?${qs}`, itemsSchema, { signal }).then((r) => r.data);
}

export const thumbUrl = (key: string) => `${API_BASE}/v1/process/thumbs/${key}.jpg`;
export const resultCsvUrl = (id: string) => `${API_BASE}/v1/process/jobs/${encodeURIComponent(id)}/result.csv`;
export const sampleCsvUrl = `${API_BASE}/v1/process/sample.csv`;

export interface UploadOptions {
  useVlm: boolean;
  vlmBudget: number;
}

/** Multipart upload (request() chỉ gửi JSON). Lỗi được quy về ApiError như mọi lời gọi khác. */
export async function uploadCsv(file: File, opts: UploadOptions): Promise<Job> {
  const form = new FormData();
  form.append('file', file);
  form.append('use_vlm', String(opts.useVlm));
  form.append('vlm_budget', String(opts.useVlm ? opts.vlmBudget : 0));
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/v1/process/jobs`, { method: 'POST', body: form });
  } catch {
    throw new ApiError('network', 'Không kết nối được tới processing service');
  }
  if (!res.ok) {
    let detail: string | undefined;
    try {
      const body = (await res.json()) as { detail?: unknown };
      detail = typeof body.detail === 'string' ? body.detail : undefined;
    } catch {
      /* non-JSON */
    }
    const kind = res.status === 413 || res.status === 422 ? 'invalid_request' : res.status === 503 ? 'unavailable' : res.status === 404 ? 'not_found' : 'server';
    throw new ApiError(kind, `HTTP ${res.status}`, res.status, undefined, detail);
  }
  const parsed = jobSchema.safeParse(await res.json());
  if (!parsed.success) throw new ApiError('invalid_payload', 'Phản hồi processing service không khớp hợp đồng', res.status);
  return parsed.data;
}
