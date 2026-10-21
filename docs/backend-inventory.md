# Backend inventory — Kho Ảnh Thông Minh (khảo sát 21/10/2026)

> Bước 0 của `docs/UI_Capstone_v2/SKILL.md`. Mọi giá trị dưới đây đọc từ source, config, SQLite,
> Qdrant hoặc file báo cáo **tại thời điểm khảo sát**; không phải cam kết hiện trạng sau này.
> Lệnh kiểm tra lại nằm ở cuối file.

## 1. Runtime đang phục vụ

| Thành phần | Giá trị thực | Bằng chứng |
|---|---|---|
| API | FastAPI `api.main:app`, chạy `uvicorn` tại `127.0.0.1:8000` | `api/main.py`, `docs/local-approved-run.md` |
| Auth | Header `X-API-Key` cho mọi `/v1/*` trừ `/v1/health`; so khớp với `TEST_API_KEY` (một key dev chung, **không có phân quyền reviewer**) | `api/main.py::api_key_and_timing`, `api/security.py::verify_key` |
| Metadata catalog | SQLite `data/local/catalog.sqlite3` (WAL) | `storage/local.py::connect` |
| Lexical | SQLite FTS5 `image_fts` (BM25), văn bản bỏ dấu, có stopword tiếng Việt | `storage/local.py::lexical_candidates` |
| Vector store | Qdrant `QDRANT_URL=http://localhost:6343`, collection `img_text`, 2560 chiều, Cosine, HNSW m=16 ef_construct=128 | `retrieval/vector_store.py`, `GET /collections/img_text` |
| Text embedding | `qwen3-embedding-4b` (2560d) qua endpoint OpenAI-compatible `EMBED_API_BASE` (`EMBED_BACKEND=api`), nhúng **metadata văn bản** (`embedding_source=approved_csv_metadata`) | `data/local/index.json`, `retrieval/embed.py` |
| Visual embedding | `img_visual` (SigLIP2) **KHÔNG tồn tại** trong Qdrant; `visual_index.json` không có ⇒ `has_visual()=false` | `GET /collections/img_visual` → 404 |
| Parser | Rule-based entity-first (`retrieval/rule_parser.py`), LLM speculative chỉ khi rule không chắc (`LLM_PARSE_MODE=ambiguous_only`, timeout 600 ms) | `retrieval/speculative.py`, `.env` |
| Rerank | `local_ce` = `BAAI/bge-reranker-v2-m3` (cross-encoder, GPU) — fallback embedding similarity, rồi thứ tự RRF | `retrieval/rerank.py`, `reports/v2/latency.json` |
| Multi-hop | `retrieval/hop.py`: chỉ đi theo cạnh có `source_url` trong `kg_relations` (Wikidata) | bảng `kg_*` |
| Cache | Kết quả `/v1/search` cache trong bảng `llm_cache` theo khoá gồm index/pipeline/model | `retrieval/local_search.py::run` |
| Media | **Không có media proxy.** `image_url` là URL gốc ngoài (http/https) của ảnh `flag=approved`; trình duyệt tải trực tiếp | `storage/local.py::import_approved` |
| Docker | `docker-compose.yml` vẫn là skeleton cũ (Postgres, MinIO, Next.js) — **không khớp** runtime local ở trên | `docker-compose.yml` |

## 2. Số liệu dữ liệu quan sát được

| Đại lượng | Giá trị | Nguồn |
|---|---|---|
| Ảnh trong SQLite `images` | **130.428** (catalog master) | `SELECT count(*) FROM images` |
| Thực thể | 11.749 | `SELECT count(*) FROM entities` |
| Point trong Qdrant `img_text` | **79.999** (`indexed_vectors_count` 79.872) | `GET /collections/img_text` |
| Manifest vector local | `count=130428`, `indexed_count=100864`, `complete=false` | `data/local/index.json` |
| Báo cáo đếm index gần nhất | 79.999 indexed, `require=80000`, `ok=false` | `reports/v2/index_counts.json` |
| KG (`kg_nodes`, `kg_relations`, `kg_aliases`, `kg_entity_links`) | **0 dòng mỗi bảng** | SQLite |
| Ảnh có width/height | 0 trong catalog master (`dimensions_known` metadata = 42.665 là của catalog trước) | SQLite |

### Cập nhật 12:43 cùng ngày (`GET /v1/stats`)

Reindex bộ master đã xong trong lúc khảo sát: SQLite **130.428** ảnh, Qdrant `img_text` **130.428** point (`indexed_vectors` 130.048, status green), manifest `indexed_count=130428`, `complete=true`.

### ⚠️ Rủi ro đang mở

1. **Đã đo lại trên index 130.428 (13:05):** `check_index_counts` `ok=true`, không lệch ID. `eval_latency`: concurrency 4 đạt 100% < 3.000 ms (p95 2.471); concurrency 1 có **5/244 vi phạm** (p95 2.753, max 3.669). `embed_query` p50 tăng từ 140 lên 1.042 ms ⇒ endpoint embedding từ xa là nút cổ chai. Báo cáo cũ ở `reports/v2/_index79999/`.
2. **Multi-hop không có dữ liệu quan hệ:** KG trống ⇒ mọi truy vấn multi-hop trả `seed_not_linked`. Cần chạy `scripts/build_kg_pilot.py`.
3. **Nhãn intent không nhất quán:** khi LLM parse thắng (`retrieval/speculative.py::decide`), `intent_type` có thể là `single` trong khi `sub_queries` có 2 phần tử và nhánh multi-intent vẫn chạy (đã thấy với "hồ bơi và công viên nước ở Phú Quốc").

## 3. Endpoint có thật

| Route | Method | Auth | Dùng ở UI |
|---|---|---|---|
| `/v1/health` | GET | không | Header + capability (model, rerank, visual, index_complete, catalog count) |
| `/v1/search` | POST `{query, top_k≤100, filters?}` | có | Trang Tìm kiếm |
| `/v1/entities` | GET `?q&limit` | có | (chưa dùng) |
| `/v1/graph` | GET/POST | có | (chưa dùng — `graph_edges` là quan hệ IN_CLASS, không phải KG có nguồn) |
| `/v1/verify/audit` | GET `?limit&include_done` | có | Hàng đợi gán nhãn (chỉ đọc) |
| `/v1/verify/label` | POST | có | **Không bật trên UI**: thiếu phân quyền reviewer |
| `/v1/verify/report` | GET | có | Trang Kiểm duyệt |
| `/thumbs/{sha256}.jpg` | GET | không | Thumbnail của hàng đợi audit (ảnh pilot, nguồn đều `flag=approved`) |
| `/v1/stats` | GET | có | **Mới thêm** (`api/routers/reports.py`): SQLite + Qdrant + manifest |
| `/v1/reports`, `/v1/reports/{id}` | GET | có | **Mới thêm**: đọc chỉ-đọc báo cáo trong allowlist |

Không có: phân trang/cursor, tổng số kết quả, `forced_type`, conjunction (AND) trên từng ảnh, constraint tách riêng, media proxy, endpoint ghi quyết định moderation có phân quyền.

## 4. Hợp đồng `/v1/search` (thực tế)

```jsonc
{
  "request_id": "uuid",
  "intent_type": "single | multi_intent | multi_hop | set_query",
  "parser": "rule | rule+llm | llm | rule (llm timeout) | ...",
  "hits": [{
    "image_id": "uuid5(url)", "image_url": "https://...", "score": 0.93,
    "entity_id": "...", "entity_slug": "...", "leaf_label": "Tên thực thể",
    "parent_class": "Nhóm", "query_type": "approved_metadata", "description": "...",
    "matched_subqueries": ["q0"],
    "quality": {"width": null, "height": null, "verify": "unknown", "watermark": "unknown", "pixel_checked": false}
  }],
  "facets": {"entities": {}, "classes": {}, "query_types": {}},
  "timings_ms": {"catalog": 0, "parse": 0, "embed_query": 0, "dense": 0, "retrieve": 0,
                 "llm_wait": 0, "metadata_filter": 0, "rerank": 0, "hop_resolve": 0, "cache_lookup": 0},
  "total_ms": 812,
  "warnings": ["sub_query_no_coverage: q1 (...)", "multi_hop seed_not_linked: ..."],
  "sub_queries": [{"id": "q0", "text": "hồ bơi ở phú quốc", "coverage": "covered", "returned": 5,
                   "evidence": "entity_name | retrieval_rank | verified_relation_chain"}],
  "parse_confidence": "high | medium | low",
  "pipeline_version": "b3-guarded-parse-fair-multi",
  "resolution": {"status": "resolved | seed_not_linked | no_evidence | target_not_in_catalog | unsupported_relation",
                 "seed": {"text": "...", "qids": []},
                 "steps": [{"phrase": "con trai", "predicate": "CHILD", "gender": "male",
                            "edges": [{"subject": "Q..", "subject_label": "..", "object": "Q..",
                                       "object_label": "..", "source": "https://www.wikidata.org/..."}]}],
                 "target_qids": [], "mapped_target_entity_ids": [], "evidence_checked": true}
}
```

Ghi chú ánh xạ sang type UI (`web/spa/src/api/searchAdapter.ts`):

- `score`: điểm cross-encoder khi rerank thành công; khi có warning `rerank_failed` là cosine; với multi-hop là **thứ hạng quy đổi** `1 - i/n` (không phải độ liên quan) ⇒ `score_kind='rank'`.
- Multi-intent: địa danh chung được parser **gộp vào text từng sub-query** ("hồ bơi ở phú quốc"); backend không trả constraint riêng. UI chỉ hiển thị "điều kiện chung" khi mọi sub-query có cùng đuôi `ở/tại …` và ghi rõ là *suy ra từ sub-query backend trả về*.
- Nhóm theo ý định dùng `matched_subqueries` (bằng chứng backend). Chế độ "Phải đáp ứng cả hai" bị tắt: backend không hỗ trợ.
- `timings_ms` là các stage tuần tự đo bằng `perf_counter`; `total_ms` tính tới khi dựng response. Phần chênh = "chưa phân bổ". Response từ cache chỉ có `cache_lookup`.
- `X-Response-Time` (header) = thời gian middleware, gồm cả serialize.

## 5. Báo cáo đo có thật (dùng ở /benchmark và /moderation)

| ID (API) | File | Nội dung | Provenance |
|---|---|---|---|
| `latency` | `reports/v2/latency.json` | 244 request × concurrency 1 và 4, p50/p95/p99/max, `under_3000ms`, stage p50/p95, by_kind, RTX 4050 Laptop | ACTUAL (cache `warm_uncached`) |
| `quality` | `reports/v2/quality/eval.json` (chỉ `summary`) | entity Recall/Hit/nDCG/MRR, multi-intent coverage, set query | ACTUAL, **nhãn silver** (tự sinh từ catalog) |
| `index_counts` | `reports/v2/index_counts.json` | CSV ↔ SQLite ↔ Qdrant, quarantine | ACTUAL |
| `rerank_ab` | `reports/v2/rerank_ab.json` | A/B reranker trên pool đóng băng | ACTUAL |
| `verify` | `reports/verify/report.json` | Phần A: gate, split, fetch, head, Jev, router, VLM, risk-coverage | ACTUAL (lần chạy dùng cache ⇒ chi phí/throughput không đại diện) |

Thiếu: latency theo đúng 3 nhãn SINGLE/MULTI_INTENT/MULTI_HOP (báo cáo dùng `entity/regression/set/multi`), mẫu raw từng request, MULTI_HOP chưa đo, git SHA (repo chưa có git), chi phí/1k ảnh có phạm vi chuẩn, precision/recall Phần A trên nhãn người có cả lớp âm.

## 6. Lệnh kiểm tra lại

```powershell
.\.venv\Scripts\python.exe -X utf8 -m uvicorn api.main:app --host 127.0.0.1 --port 8000
curl http://127.0.0.1:8000/v1/health
curl -H "X-API-Key: <TEST_API_KEY>" http://127.0.0.1:8000/v1/stats
curl http://localhost:6343/collections/img_text
.\.venv\Scripts\python.exe -X utf8 -m scripts.check_index_counts --require 80000
```
