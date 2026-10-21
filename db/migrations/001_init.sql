-- Chạy tự động bởi postgres container (/docker-entrypoint-initdb.d)
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS entities (
  entity_id       uuid PRIMARY KEY,
  entity_stt      int,
  entity_name     text NOT NULL,
  entity_slug     text UNIQUE NOT NULL,
  branch          varchar(4),
  priority        varchar(4),
  score           numeric(4,2),
  leaf_label      text,
  description     text,
  parent_class    text,
  province        text,
  so_anh_pass     int DEFAULT 0,
  duoi_5          boolean DEFAULT false,
  assigned_member text,
  created_at      timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_entities_branch   ON entities(branch);
CREATE INDEX IF NOT EXISTS ix_entities_priority ON entities(priority);
CREATE INDEX IF NOT EXISTS ix_entities_class    ON entities(parent_class);
CREATE INDEX IF NOT EXISTS ix_entities_name_trgm ON entities USING gin (entity_name gin_trgm_ops);

CREATE TABLE IF NOT EXISTS images (
  image_id     uuid PRIMARY KEY,
  image_url    text NOT NULL,
  sha256       varchar(64) UNIQUE,
  phash64      bigint,
  width        int,
  height       int,
  s3_key       text,
  page_url     text,
  page_title   text,
  image_source text,
  query_type   varchar(32),
  nguon        varchar(32),
  crawled_at   timestamptz,
  created_at   timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_images_width ON images(width);
CREATE INDEX IF NOT EXISTS ix_images_qtype ON images(query_type);
CREATE INDEX IF NOT EXISTS ix_images_source ON images(image_source);

CREATE TABLE IF NOT EXISTS image_entity (
  image_id    uuid REFERENCES images(image_id) ON DELETE CASCADE,
  entity_id   uuid REFERENCES entities(entity_id) ON DELETE CASCADE,
  image_order int,
  score       numeric(4,2),
  PRIMARY KEY (image_id, entity_id)
);
CREATE INDEX IF NOT EXISTS ix_ie_entity ON image_entity(entity_id);

CREATE TABLE IF NOT EXISTS verdicts (
  image_id      uuid REFERENCES images(image_id) ON DELETE CASCADE,
  stage         smallint,
  relevance     numeric(4,3),
  watermark     numeric(4,3),
  nsfw          numeric(4,3),
  violence      numeric(4,3),
  politics      numeric(4,3),
  decision      varchar(16),
  vlm_reason    text,
  model_version text,
  decided_at    timestamptz DEFAULT now(),
  PRIMARY KEY (image_id, stage)
);
CREATE INDEX IF NOT EXISTS ix_verdicts_decision ON verdicts(decision);

CREATE TABLE IF NOT EXISTS embeddings (
  image_id uuid PRIMARY KEY REFERENCES images(image_id) ON DELETE CASCADE,
  model    text NOT NULL,
  dim      int  NOT NULL,
  vector   vector(1152) NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_embeddings_hnsw
  ON embeddings USING hnsw (vector vector_cosine_ops) WITH (m = 32, ef_construction = 200);

CREATE TABLE IF NOT EXISTS graph_edges (
  src_id   text,
  relation text,
  dst_id   text,
  weight   numeric(4,2) DEFAULT 1.0,
  PRIMARY KEY (src_id, relation, dst_id)
);
CREATE INDEX IF NOT EXISTS ix_edges_dst ON graph_edges(dst_id);

CREATE TABLE IF NOT EXISTS api_keys (
  key_hash       varchar(128) PRIMARY KEY,
  label          text,
  scope          varchar(16) DEFAULT 'test',
  rate_limit_rpm int DEFAULT 600,
  active         boolean DEFAULT true,
  created_at     timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS query_logs (
  request_id   uuid PRIMARY KEY,
  api_key_hash varchar(128),
  raw_query    text,
  intent_type  varchar(24),
  sub_queries  jsonb,
  hop_chain    jsonb,
  llm_provider varchar(16),
  cache_hit    boolean,
  latency_ms   int,
  n_candidates int,
  result_ids   uuid[],
  created_at   timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_qlog_intent ON query_logs(intent_type);
CREATE INDEX IF NOT EXISTS ix_qlog_created ON query_logs(created_at);

CREATE TABLE IF NOT EXISTS backfill_queue (
  entity_id uuid PRIMARY KEY REFERENCES entities(entity_id) ON DELETE CASCADE,
  reason    varchar(24),
  n_current int,
  priority  varchar(4),
  queued_at timestamptz DEFAULT now()
);
