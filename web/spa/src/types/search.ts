// Normalized UI types (SKILL.md §4.1). These are the adapter's OUTPUT, not the backend schema;
// the backend payload is validated in api/validators.ts and mapped in api/searchAdapter.ts.

/** SET_QUERY is a 4th intent the real parser returns ("các chợ truyền thống"). */
export type QueryType = 'SINGLE' | 'MULTI_INTENT' | 'MULTI_HOP' | 'SET_QUERY';
/** 'pending' = multi-hop online evidence lookup still running in the background (retry shortly). */
export type RunStatus = 'ok' | 'partial' | 'unsupported' | 'unverified' | 'pending' | 'error';
export type ModerationStatus = 'approved' | 'review' | 'rejected' | 'nsfw' | 'quarantined' | 'unknown';
export type DataProvenance = 'ACTUAL' | 'TARGET' | 'ESTIMATE' | 'FIXTURE';
/** 'rank' = position-derived value (multi-hop), NOT a relevance score. */
export type ScoreKind = 'reranker' | 'cosine' | 'rank' | 'other';

export interface LocationConstraint {
  label: string;
  scope: 'ALL_INTENTS' | 'INTENT';
  /** true: inferred from identical sub-query suffixes returned by the backend, not a backend field. */
  derived: boolean;
}

export interface QueryConstraints {
  locations?: LocationConstraint[];
  parent_class?: string;
  must_match_all_intents?: boolean;
}

export interface ImageResult {
  image_id: string;
  entity_id?: string;
  entity_name?: string;
  entity_class?: string;
  thumbnail_url?: string;
  original_url?: string;
  width?: number;
  height?: number;
  score?: number;
  score_kind: ScoreKind;
  /** Raw cross-encoder relevance (0..1), the value the backend relevance floor is applied to. */
  relevance?: number;
  source_host?: string;
  caption?: string;
  intent_ids: string[];
  producer_step_ids: string[];
  moderation: { status: ModerationStatus; source: string; labels: string[] };
  quality: { verify: string; watermark: string; pixel_checked: boolean };
}

export interface IntentGroup {
  id: string;
  /** Intent text without the shared constraint. */
  text: string;
  /** Exact sub-query text the backend retrieved with. */
  backend_text: string;
  evidence?: string;
  returned?: number;
  supported_candidates?: number;
  images: ImageResult[];
  status: 'ok' | 'empty' | 'error';
}

export interface Evidence {
  label: string;
  url?: string;
  source_id?: string;
}

/** Where a KG edge came from (kg_edge.source_type): catalog name, Gemini-read document, manual seed, online lookup. */
export type HopSourceType = 'catalog_name' | 'gemini_doc' | 'manual_claim' | 'online' | 'other';

export interface HopSource {
  type: HopSourceType;
  /** Safe http(s) URL; absent for catalog-name evidence. */
  url?: string;
  /** Catalog entity whose own name states the relation ("catalog:entity/<id>"). */
  catalog_entity_id?: string;
  /** Verbatim quote the verifier found in the source. */
  quote?: string;
  verifier?: string;
}

/** One verified relation (subject → object), with every independent source that supports it. */
export interface HopFact {
  subject: string;
  object: string;
  object_kind?: string;
  sources: HopSource[];
}

export interface HopTarget {
  label: string;
  kind?: string;
  /** Verified place edges of a target with no images (target_not_in_catalog), e.g. "an táng tại …". */
  related_places: Array<{ relation: string; label: string }>;
}

/** Normalized resolution summary (raw `resolution`) for the MULTI_HOP page body. */
export interface HopSummary {
  status: string;
  seed_text?: string;
  seed_labels: string[];
  targets: HopTarget[];
  online_status?: string;
  online_budget_ms?: number;
}

export interface TraceStep {
  id: string;
  step: number;
  kind: 'entity_linking' | 'relation_lookup' | 'catalog_mapping' | 'retrieval' | 'rerank' | 'other';
  status: 'ok' | 'unverified' | 'pending' | 'not_supported' | 'failed';
  input_summary: string;
  output_summary?: string;
  entity_ids?: string[];
  relation?: string;
  evidence: Evidence[];
  facts?: HopFact[];
  elapsed_ms?: number;
  image_ids?: string[];
}

export interface StageTiming {
  key: string;
  label: string;
  ms: number;
}

export interface Timing {
  /** Backend `total_ms` (perf_counter from request handling to response build). */
  total_ms?: number;
  /** Middleware `X-Response-Time` header (includes serialization). */
  middleware_ms?: number;
  stages: StageTiming[];
  /** total_ms − Σstages, only when stages are present and sequential. */
  unattributed_ms?: number;
  client_observed_ms?: number;
  cached: boolean;
}

export interface SearchResponse {
  request_id: string;
  query: string;
  query_type: QueryType;
  query_type_source: 'backend' | 'fixture';
  parser: string;
  parse_confidence?: string;
  pipeline_version?: string;
  status: RunStatus;
  message?: string;
  /** Set when the backend label and the retrieval it actually ran disagree. */
  type_mismatch?: string;
  warnings: string[];
  constraints: QueryConstraints;
  intents: IntentGroup[];
  trace: TraceStep[];
  hop_status?: string;
  hop?: HopSummary;
  results: ImageResult[];
  facets: { classes: Array<{ label: string; count: number }> };
  /** Backend returns no total; page size is the requested top_k. */
  total_results?: number;
  top_k: number;
  timings: Timing;
  provenance: DataProvenance;
}

export interface SearchParams {
  query: string;
  top_k: number;
  parent_class?: string;
}
