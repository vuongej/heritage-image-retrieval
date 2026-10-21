import { z } from 'zod';
import { request } from './backendClient';
import {
  auditSchema,
  healthSchema,
  reportEnvelopeSchema,
  reportListSchema,
  statsSchema,
  type AuditQueue,
  type Health,
  type ReportEnvelope,
  type ReportList,
  type Stats,
} from './validators';

// Readers for measured artifacts. Each report keeps its own provenance; nothing is filled in.

export const getHealth = (signal?: AbortSignal) => request('/v1/health', healthSchema, { signal }).then((r) => r.data);
export const getStats = (signal?: AbortSignal) => request('/v1/stats', statsSchema, { signal }).then((r) => r.data);
export const listReports = (signal?: AbortSignal) =>
  request('/v1/reports', reportListSchema, { signal }).then((r) => r.data);
export const getAuditQueue = (signal?: AbortSignal) =>
  request('/v1/verify/audit?limit=24&include_done=true', auditSchema, { signal }).then((r) => r.data);

export type { AuditQueue, Health, ReportList, Stats };

export interface Report<T> {
  meta: Omit<ReportEnvelope, 'data'>;
  data: T;
}

async function getReport<T>(id: string, schema: z.ZodType<T, z.ZodTypeDef, unknown>, signal?: AbortSignal): Promise<Report<T>> {
  const env = (await request(`/v1/reports/${id}`, reportEnvelopeSchema, { signal })).data;
  const parsed = schema.safeParse(env.data);
  if (!parsed.success) {
    throw new Error(`Báo cáo ${env.path} không khớp schema: ${parsed.error.issues[0]?.message ?? ''}`);
  }
  const { data: _data, ...meta } = env;
  return { meta, data: parsed.data };
}

const num = z.number().nullable().optional();
const stageMap = z.record(z.number()).default({});

// ---- reports/v2/latency.json (scripts/eval_latency.py) ----
export const latencyRunSchema = z
  .object({
    requests: z.number(),
    errors: z.number(),
    p50: num,
    p95: num,
    p99: num,
    max: num,
    under_1500ms: num,
    under_3000ms: num,
    warnings_429: num,
    warnings_degraded: num,
    parsers: z.record(z.number()).default({}),
    stage_p50: stageMap,
    stage_p95: stageMap,
    by_kind: z.record(z.object({ p50: num, p95: num }).passthrough()).default({}),
    wall_seconds: num,
    throughput_qps: num,
  })
  .passthrough();
export const latencySchema = z.object({
  environment: z.record(z.unknown()).default({}),
  cache_state: z.string().optional(),
  offered_rpm: num,
  endpoint_rate_limit: z.string().optional(),
  runs: z.record(latencyRunSchema),
});
export type LatencyReport = z.infer<typeof latencySchema>;
export type LatencyRun = z.infer<typeof latencyRunSchema>;
export const getLatency = (s?: AbortSignal) => getReport('latency', latencySchema, s);

// ---- reports/v2/quality/eval.json → summary only ----
export const qualitySchema = z.object({
  summary: z
    .object({
      label_type: z.string().optional(),
      config: z.record(z.unknown()).default({}),
      entity: z.record(z.number()).optional(),
      regression_104: z.record(z.unknown()).optional(),
      set_query: z.record(z.number()).optional(),
      multi_intent: z.record(z.number()).optional(),
      parse_confidence: z.record(z.number()).optional(),
    })
    .passthrough(),
});
export type QualityReport = z.infer<typeof qualitySchema>;
export const getQuality = (s?: AbortSignal) => getReport('quality', qualitySchema, s);

// ---- reports/v2/index_counts.json (scripts/check_index_counts.py) ----
export const indexCountsSchema = z
  .object({
    csv_rows: num,
    csv_valid_rows: num,
    sqlite_images: num,
    qdrant_img_text: num,
    indexed_images: num,
    require: num,
    ok: z.boolean().optional(),
    problems: z.array(z.string()).default([]),
    quarantine: z.array(z.record(z.unknown())).default([]),
  })
  .passthrough();
export type IndexCounts = z.infer<typeof indexCountsSchema>;
export const getIndexCounts = (s?: AbortSignal) => getReport('index_counts', indexCountsSchema, s);

// ---- reports/v2/rerank_ab.json ----
export const rerankAbSchema = z
  .object({
    cases: num,
    label_type: z.string().optional(),
    backends: z.record(
      z
        .object({
          mode: z.string().optional(),
          model: z.string().optional(),
          metrics: z.record(z.record(z.number())).default({}),
          rerank_ms: z.object({ p50: num, p95: num, max: num }).partial().default({}),
        })
        .passthrough(),
    ),
  })
  .passthrough();
export type RerankAb = z.infer<typeof rerankAbSchema>;
export const getRerankAb = (s?: AbortSignal) => getReport('rerank_ab', rerankAbSchema, s);

// ---- reports/verify/report.json (python -m pipeline.verify) ----
const rcPoint = z.object({ alpha: z.number(), coverage: z.number(), acc_keep: z.number() });
const layerEval = z
  .object({
    proxy_rows: num,
    proxy_agreement_all: num,
    risk_coverage: z.object({ points: z.array(rcPoint).default([]), aurc: num }).partial().default({}),
    ece_conf: num,
  })
  .passthrough();
const breakdown = z.array(z.object({ key: z.string(), n: z.number(), yes_rate: num, agreement: num }));
export const verifySchema = z
  .object({
    csv: z.string().optional(),
    seed: num,
    pilot_groups: num,
    target_split: z.string().optional(),
    budget_alpha: num,
    primary_layer: z.string().optional(),
    gate: z
      .object({ source_rows: z.number(), live_rows: z.number(), rejected_rows: z.number(), by_rule: z.record(z.number()) })
      .passthrough(),
    split: z.object({ rows: z.record(z.number()), groups: z.record(z.number()) }).passthrough(),
    pilot_rows: num,
    fetch: z.record(z.number()).default({}),
    embedding: z.record(z.number()).default({}),
    bootstrap: z.object({ labelled: num, yes_rate: num }).partial().default({}),
    head: z.record(z.unknown()).default({}),
    jev: z
      .object({ decided: num, defer_share: num, errors: num, routed_models: z.record(z.number()).default({}) })
      .passthrough()
      .default({}),
    layers_proxy_eval: z.record(layerEval).default({}),
    router: z.object({ alpha: num, budget_images: num, chosen: num, defer_rate_actual: num }).passthrough().default({}),
    vlm: z.record(z.number()).default({}),
    cascade_proxy: z
      .object({ rows: num, agreement_all: num, agreement_keep: num, agreement_routed_vlm: num, routed_share: num })
      .partial()
      .default({}),
    approved_flag_eval: z
      .object({
        rows: num,
        approved: num,
        rejected: num,
        accuracy_vlm_teacher: num,
        accuracy_head: num,
        accuracy_jev: num,
        accuracy_cascade: num,
        measurable: z.string().optional(),
      })
      .partial()
      .default({}),
    human_eval: z.record(z.unknown()).default({}),
    by_category: breakdown.default([]),
    by_host: breakdown.default([]),
    cost: z
      .object({
        deepseek_usd_estimate: num,
        jev_this_run: z.object({ requests: num, usd: num }).partial().default({}),
        cache_note: z.string().optional(),
      })
      .passthrough()
      .default({}),
    seconds: z.record(z.number()).default({}),
    proxy_warning: z.string().optional(),
  })
  .passthrough();
export type VerifyReport = z.infer<typeof verifySchema>;
export const getVerify = (s?: AbortSignal) => getReport('verify', verifySchema, s);
