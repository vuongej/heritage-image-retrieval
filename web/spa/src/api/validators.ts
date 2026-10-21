import { z } from 'zod';

// Runtime validation of the REAL backend payloads (docs/backend-inventory.md §3–4).
// Optional fields stay optional: a missing value is shown as "—", never invented.

const nullableNumber = z.number().nullable().optional();

export const rawHitSchema = z.object({
  image_id: z.string(),
  image_url: z.string(),
  score: z.number(),
  /** Raw cross-encoder probability (0..1) before quality penalties; null when rerank is not calibrated. */
  relevance: z.number().nullable().optional(),
  entity_id: z.string().nullable().optional(),
  entity_slug: z.string().nullable().optional(),
  leaf_label: z.string().nullable().optional(),
  query_type: z.string().nullable().optional(),
  parent_class: z.string().nullable().optional(),
  description: z.string().nullable().optional(),
  matched_subqueries: z.array(z.string()).default([]),
  quality: z
    .object({
      width: nullableNumber,
      height: nullableNumber,
      verify: z.string().nullable().optional(),
      verify_source: z.string().nullable().optional(),
      watermark: z.string().nullable().optional(),
      pixel_checked: z.boolean().optional(),
    })
    .partial()
    .default({}),
});

// KG multi-hop (retrieval/hop.py · docs/multihop-kg.md): every edge carries its own evidence
// (source_type + source URL or "catalog:entity/<id>" + verbatim quote).
const edgeSchema = z.object({
  subject: z.string(),
  subject_label: z.string().nullable().optional(),
  predicate: z.string(),
  object: z.string(),
  object_label: z.string().nullable().optional(),
  object_kind: z.string().nullable().optional(),
  source_type: z.string().nullable().optional(),
  source: z.string().nullable().optional(),
  evidence: z.string().nullable().optional(),
  verifier: z.string().nullable().optional(),
});

const kgNodeSchema = z.object({
  node_id: z.string(),
  kind: z.string().nullable().optional(),
  label: z.string().nullable().optional(),
  gender: z.string().nullable().optional(),
});

export const rawResolutionSchema = z.object({
  status: z.string(),
  seed: z
    .object({
      text: z.string().optional(),
      nodes: z.array(kgNodeSchema).optional(),
      /** Wikidata-era payloads (before b4-verified-kg-multihop). */
      qids: z.array(z.string()).optional(),
    })
    .passthrough()
    .default({}),
  steps: z
    .array(
      z.object({
        phrase: z.string().optional(),
        predicate: z.string(),
        direction: z.string().nullable().optional(),
        gender: z.string().nullable().optional(),
        edges: z.array(edgeSchema).default([]),
      }),
    )
    .default([]),
  target_nodes: z
    .array(
      kgNodeSchema.extend({
        related_places: z.array(z.object({ predicate: z.string(), node: kgNodeSchema })).optional(),
      }),
    )
    .default([]),
  target_qids: z.array(z.string()).default([]),
  mapped_target_entity_ids: z.array(z.string()).default([]),
  evidence_checked: z.boolean().optional(),
  online: z
    .object({ status: z.string().optional(), budget_ms: z.number().optional(), cached: z.boolean().optional() })
    .passthrough()
    .default({}),
});

export const rawSubQuerySchema = z
  .object({
    id: z.string(),
    text: z.string(),
    coverage: z.string().optional(),
    returned: z.number().optional(),
    evidence: z.string().optional(),
    supported_candidates: z.number().optional(),
  })
  .passthrough();

export const rawSearchSchema = z.object({
  request_id: z.string(),
  intent_type: z.string(),
  parser: z.string(),
  hits: z.array(rawHitSchema),
  facets: z
    .object({
      entities: z.record(z.string()).optional(),
      classes: z.record(z.number()).optional(),
      query_types: z.record(z.number()).optional(),
    })
    .passthrough()
    .default({}),
  timings_ms: z.record(z.number()).default({}),
  total_ms: z.number(),
  warnings: z.array(z.string()).default([]),
  sub_queries: z.array(rawSubQuerySchema).default([]),
  parse_confidence: z.string().nullable().optional(),
  pipeline_version: z.string().nullable().optional(),
  resolution: rawResolutionSchema.nullable().optional(),
});

export type RawSearch = z.infer<typeof rawSearchSchema>;
export type RawHit = z.infer<typeof rawHitSchema>;
export type RawResolution = z.infer<typeof rawResolutionSchema>;

export const healthSchema = z
  .object({
    status: z.string(),
    llm_provider: z.string().optional(),
    stage3_vlm_enabled: z.boolean().optional(),
    slo_p95_ms: z.number().optional(),
    version: z.string().optional(),
    backend: z.string().optional(),
    catalog: z.object({ images: z.number(), entities: z.number() }).partial().optional(),
    index_complete: z.boolean().optional(),
    embedding_source: z.string().optional(),
    embedding: z
      .object({ model: z.string().nullable(), dim: z.number().nullable(), backend: z.string().nullable() })
      .partial()
      .optional(),
    visual_index: z.boolean().optional(),
    parse_llm: z.string().nullable().optional(),
    rerank: z.string().nullable().optional(),
    rerank_backend: z.string().nullable().optional(),
  })
  .passthrough();
export type Health = z.infer<typeof healthSchema>;

const collectionSchema = z
  .object({
    available: z.boolean(),
    points: z.number().nullable().optional(),
    indexed_vectors: z.number().nullable().optional(),
    status: z.string().optional(),
    reason: z.string().optional(),
  })
  .passthrough();

export const statsSchema = z.object({
  measured_at: z.string(),
  catalog: z.object({ images: z.number(), entities: z.number() }),
  knowledge_graph: z.record(z.number()).default({}),
  vector_backend: z.string(),
  img_text: collectionSchema,
  img_visual: collectionSchema,
  manifest: z
    .object({
      count: z.number().nullable().optional(),
      indexed_count: z.number().nullable().optional(),
      complete: z.boolean().nullable().optional(),
      model: z.string().nullable().optional(),
      dim: z.number().nullable().optional(),
    })
    .passthrough(),
  visual_enabled: z.boolean(),
  required_images: z.number(),
});
export type Stats = z.infer<typeof statsSchema>;

export const reportListSchema = z.object({
  items: z.array(
    z.object({
      id: z.string(),
      title: z.string(),
      path: z.string(),
      available: z.boolean(),
      modified_at: z.string().optional(),
      bytes: z.number().optional(),
    }),
  ),
});
export type ReportList = z.infer<typeof reportListSchema>;

export const reportEnvelopeSchema = z.object({
  id: z.string(),
  title: z.string(),
  path: z.string(),
  modified_at: z.string().optional(),
  sha256: z.string(),
  data: z.unknown(),
});
export type ReportEnvelope = z.infer<typeof reportEnvelopeSchema>;

export const auditSchema = z.object({
  total: z.number(),
  labelled: z.number(),
  by_stratum: z.record(z.number()).default({}),
  items: z.array(
    z
      .object({
        key: z.string(),
        stratum: z.string(),
        entity: z.string().optional(),
        category: z.string().optional(),
        description: z.string().optional(),
        image_url: z.string().optional(),
        source_url: z.string().optional(),
        thumb: z.string().optional(),
        human: z.string().nullable().optional(),
      })
      .passthrough(),
  ),
});
export type AuditQueue = z.infer<typeof auditSchema>;
