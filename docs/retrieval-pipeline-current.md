# Phần B — Pipeline truy xuất ảnh đang chạy (chi tiết, cập nhật 2026-10-21)

> **Đã lỗi thời một phần (2026-10-21, chiều):** pipeline đã nâng lên V2
> (`b3-guarded-parse-fair-multi`): rerank mặc định BGE-v2-m3 local, LLM parse chỉ cho truy vấn mơ
> hồ, multi-intent chia slot theo bằng chứng, multi-hop có nguồn. Xem
> [retrieval-v2-implementation-report.md](retrieval-v2-implementation-report.md).
> Dữ liệu nguồn nay là `data_anh_pass_master.csv` (130.428 ảnh index được, verify tay 100%).

Tài liệu này mô tả **code đang chạy thật** (`retrieval/`, `api/`, `storage/`) và cấu hình `.env`
hiện tại, không phải thiết kế ban đầu trong `docs/retrieval.md` / `docs/architecture.md`.
Mọi con số độ trễ / chất lượng là số **đo thật** ngày 2026-10-21 trừ khi ghi khác.

- `pipeline_version` = `b2-dual-dense-fts-size` (`retrieval/search.py`)
- `index_version` = `1` (`retrieval/local_index.py`)

---

## 1. Tóm tắt một trang

```
POST /v1/search {query, top_k, filters}
  │  (X-API-Key)
  ▼
retrieval.search.search  ──►  retrieval.local_search.run
  1. Cache SQLite                         trúng → trả ngay (~2 ms)
  2. Catalog tên thực thể (RAM)
  3. Rule parse entity-first              ~0,2 ms
  4. LLM parse SONG SONG (nền)            Gemini 3.5 Flash Lite · OpenRouter
  5. Retrieve theo rule, mỗi sub-query:
       a. embed truy vấn                  Qwen3-Embedding-4B (2560d) · endpoint riêng
       b. dense text                      Qdrant `img_text` top-200
       c. dense ảnh                       SigLIP2 `img_visual` (CHƯA BẬT)
       d. FTS5 BM25                       SQLite, top-100
       e. khớp tên thực thể               ≤ 30 ảnh / thực thể
       → RRF k=60, trọng số 1/1/1/3
  6. Chờ LLM parse ≤ 600 ms               khác rule → retrieve thêm theo LLM
  7. multi_hop → trả rỗng + cảnh báo
  8. Pool ≤ 400 → lọc metadata → cắt 24 ứng viên
  9. Rerank                               Gemini 3.5 Flash Lite (mặc định) | jina-reranker-v2
     → bỏ điểm < 0,2 (chỉ Gemini) → quota multi-intent → top_k
 10. Facet + ghi cache (trừ khi suy giảm)
```

**Tình trạng:** chất lượng truy vấn theo tên thực thể cao (Hit@10 0,99), nhưng **p95 ≈ 3,1 s
> SLO 1.500 ms** do rerank Gemini (~2 s). Toàn bộ pipeline hiện **chỉ dùng văn bản metadata**,
chưa dùng pixel ảnh.

---

## 2. Các model đang dùng

| Vai trò | Model | Tham số | Chạy ở đâu | Input → output | Cấu hình (`.env`) |
|---|---|---|---|---|---|
| **Embedding text** (dense chính) | `qwen3-embedding-4b` (Qwen3-Embedding-4B) | ~4B | Endpoint OpenAI-compatible riêng (vLLM sau LiteLLM, qua Cloudflare quick tunnel) | văn bản → vector **2.560 chiều**, đã chuẩn hoá. Truy vấn có tiền tố `Instruct: … / Query: …`; metadata gửi nguyên văn | `EMBED_BACKEND=api`, `EMBED_MODEL=qwen3-embedding-4b`, `EMBED_DIM=2560`, `EMBED_API_BASE`, `EMBED_API_KEY` |
| **Parse truy vấn** (LLM, chạy nền) | `google/gemini-3.5-flash-lite` | không công bố | OpenRouter (provider Google) | truy vấn + 20 tên ứng viên → JSON `QueryParse` (json_schema strict). Reasoning bắt buộc → `effort: minimal` | `LLM_PROVIDER≠none`, `OPENROUTER_API_KEY`, `LLM_ONLINE_MODEL`, `LLM_PARSE_TIMEOUT_MS=600` |
| **Rerank** (mặc định) | `google/gemini-3.5-flash-lite` | không công bố | OpenRouter | truy vấn + 24 ứng viên (tên, nhóm, mô tả ≤ 500 ký tự) → điểm 0..1 mỗi ứng viên | `RERANK_BACKEND` (trống = `llm`), `RERANK_LLM_MODEL` |
| Rerank (tuỳ chọn, chưa bật trên server) | `jina-reranker-v2` (≈ jina-reranker-v2-base-multilingual) | ~278M | Cùng endpoint với embedding (`hosted_vllm/jina-reranker-v2`, input tối đa 1.024 token) | cross-encoder: (truy vấn, văn bản ứng viên) → điểm | `RERANK_BACKEND=api`, `RERANK_API_MODEL=jina-reranker-v2` |
| Rerank dự phòng | cosine Qwen3-Embedding | — | như embedding | vector truy vấn · vector metadata ứng viên | tự động khi rerank chính lỗi |
| **Embedding ảnh** (CHƯA BẬT) | `google/siglip2-base-patch16-256` | ~375M (2 tháp) | Local GPU (RTX 4050), encoder của Phần A | ảnh → 768d; truy vấn → 768d (text tower) | `VERIFY_ENCODER`; bật tự động khi có `data/local/visual_index.json` |
| Ứng viên tên cho LLM | IDF trên token tên thực thể | — | Local (RAM) | truy vấn → 20 tên thực thể gần nhất | — |

Model **không còn dùng** trên đường search: `paraphrase-multilingual-MiniLM-L12-v2` (384d, index
cũ sao lưu ở `data/local/backup_minilm_80k/`), DeepSeek (parse + rerank trước đây),
`bge-reranker-v2-m3` (chỉ còn tên trong `RERANK_MODEL`, không được gọi).

> **Về pixel ảnh:** cả Qwen3-Embedding, Gemini (như đang gọi) và jina đều chỉ nhận **văn bản
> metadata**. Chỉ nhánh SigLIP2 (`img_visual`) nhìn pixel — code đã có nhưng chưa bật.

---

## 3. Dữ liệu và chỉ mục

| Thành phần | Nội dung | File / nơi lưu |
|---|---|---|
| Nguồn | `data/data_anh_pass_80000_full_pham_van_vuong.csv` (80.000 dòng, mọi username) | — |
| Catalog SQLite | **79.999 ảnh** (1 dòng bỏ: URL không http) · **11.294 thực thể** · 66.937 chuỗi metadata khác nhau | `data/local/catalog.sqlite3` |
| `metadata_text` mỗi ảnh | `"<canonical_name>. <category>. <description>"` | bảng `images` |
| Vector text | 79.999 × 2.560 float32 (~820 MB) | `data/local/vectors.npy` + `index.json` (manifest: model, dim, backend, csv_sha256) |
| Qdrant `img_text` | 79.999 điểm, cosine, HNSW `m=16, ef_construct=128`, tìm với `ef=128`; self-test recall@10 = 1,0 | Docker `qdrant/qdrant` 1.19.0, `localhost:6343` |
| Qdrant `img_visual` | **chưa nạp** (lượt tải ảnh mới ~57%) | — |
| FTS5 | `image_fts(text)` = `metadata_text` **đã bỏ dấu** | bảng `image_fts` |
| Đồ thị | 11.294 cạnh `IN_CLASS` (thực thể → nhóm). Không có quan hệ người/tổ chức | bảng `graph_edges` |
| Cột chất lượng (schema v2) | `verify`, `width`, `height`, `has_watermark`, `fetch_status`, `caption`, `caption_source` — **đều NULL** (chưa chạy migrate), trừ 50 caption pilot | bảng `images` |

Build lại index: `retrieval.local_index.build()` (resumable theo chunk 512, mã hoá 1 lần cho mỗi
chuỗi metadata trùng) rồi `python -m scripts.build_vector_store text`. Với Qwen3: **23,6 phút**
build + 2 phút nạp Qdrant. Index tự bị coi là hết hạn khi đổi CSV, model, số chiều hoặc backend.

---

## 4. Từng bước chi tiết

### Bước 0 — API
- `POST /v1/search` (`api/routers/search.py`), header `X-API-Key` (middleware `api/main.py`).
- Request: `query` 1–2.000 ký tự, `top_k` 1–100 (mặc định 10), `filters` tuỳ chọn ∈
  {`entity_id`, `entity_slug`, `parent_class`, `min_width`, `orientation`}; khoá khác → 422.
- Lỗi `RuntimeError` → 503, `ValueError` → 422.

### Bước 1 — Cache kết quả
- Bảng `llm_cache`, khoá `search:v6:<sha256>` của: query, top_k, filters, manifest index,
  `index_version`, `pipeline_version`, backend vector + số điểm `img_visual`, số ảnh biết kích
  thước, model parse, `[rerank_mode, rerank_model]`.
- Trúng cache: trả ngay, `timings_ms = {cache_lookup}` (~2 ms).
- **Không cache** câu trả lời suy giảm (cảnh báo `llm_*`, `embedding_*`, `rerank_*`, `deepseek_*`)
  hoặc khi LLM parse timeout/lỗi — để lần sau dùng được kết quả LLM.

### Bước 2 — Catalog tên thực thể (`retrieval/catalog.py`)
- Build 1 lần cho mỗi `csv_sha256`, giữ trong RAM (~0,2–0,5 s lần đầu).
- Với mỗi thực thể: tên đầy đủ + **alias** (bỏ ngoặc đơn cuối, tách theo ` – ` / ` — ` / ` / `),
  chuẩn hoá bỏ dấu (`đ → d`), lowercase.
- Tập **cụm 2–6 token** xuất hiện trong mọi tên (dùng để che marker nằm *trong* tên).
- Postings + IDF theo token → `suggest()` trả 20 tên ứng viên cho LLM.

### Bước 3 — Rule parse entity-first (`retrieval/rule_parser.py`, `retrieval/places.py`)
1. Chuẩn hoá: NFC, lowercase, bỏ tiền tố `ảnh/hình/hình ảnh (của|về)`, `cho tôi/tìm/xem…`.
2. **Tìm span tên thực thể** (longest-match-first, không chồng lấn) → che. Che thêm cụm 2–6 token
   có trong tên nào đó ("Hòn Chồng", "Đông Anh", "Đức Mẹ"). Từ nối (`và`, `với`) chỉ được che khi
   cụm có ngữ cảnh **cả hai phía** ("mộ và đền thờ").
3. Marker quan hệ ngoài phần che (`con trai, con gái, vợ, chồng, chủ tịch, giám đốc, cha, mẹ,
   anh, em, sáng lập`) → **`multi_hop`**.
4. Tách ý định theo `,` / `và` / `với` / `cùng` / `&` ngoài phần che:
   - phần sau dấu phẩy là **địa danh** (63 tỉnh + 14 tên/viết tắt + 29 địa phương du lịch) →
     gộp vào ý trước: "Chùa Một Cột, Hà Nội" → 1 sub-query;
   - địa danh cuối câu áp cho mọi sub-query: "hồ bơi và công viên nước ở Phú Quốc" →
     `hồ bơi ở phú quốc` + `công viên nước ở phú quốc`;
   - còn ≥ 2 phần → **`multi_intent`**.
5. Marker tập hợp (`những, các, tất cả, danh sách, loại, họ, mọi`) → **`set_query`**.
6. Còn lại → **`single`**. Kèm filter từ câu: `ảnh ngang/dọc` → `orientation`,
   `chất lượng cao / độ nét cao` → `min_width=1200`.

Kết quả trên catalog thật: **0/11.294** tên thực thể bị xếp sai loại (parser cũ sai 973/4.481 trên
catalog 35k, trong đó 104 tên ra `multi_hop` → trả rỗng).

### Bước 4 & 6 — LLM parse song song (`retrieval/speculative.py`, `retrieval/llm_router.py`)
- Khởi chạy ngay sau rule parse trong thread pool (4 luồng); retrieve theo rule **không chờ**.
- Payload: Gemini 3.5 Flash Lite, `json_schema` strict (`intent_type`, `entities[]`,
  `sub_queries[]`, `hop_chain[]` với 6 quan hệ chuẩn, `modifiers{place,time,style}`),
  `temperature 0`, `max_tokens 300`, `reasoning.effort=minimal`; validate Pydantic; cache SQLite
  `llmparse:`; HTTP client dùng chung (giữ kết nối TLS); timeout cứng 6 s.
- Sau retrieve, chờ phần còn lại của **600 ms** tính từ lúc khởi chạy:
  - LLM trùng rule → giữ (`parser = rule+llm`);
  - LLM khác loại intent hoặc sub-query → retrieve thêm theo LLM, ứng viên rule xếp sau
    (`parser = llm`); riêng LLM nói `multi_hop` thì **bỏ qua** (chưa resolve được quan hệ);
  - timeout / lỗi → giữ rule (`parser = rule (llm timeout|error)`), luồng nền vẫn chạy xong và
    ghi cache cho lần sau.
- Đo thật: 1 lượt gọi p50 **1.124 ms**, p95 1.611 ms → **~87% lần đầu timeout**; ~$0,00052/lượt.
- Log: `data/local/llm_router_usage.jsonl` (`kind=call|rerank_call|outcome`).

### Bước 5 — Retrieve (`retrieval/local_search.py::_retrieve`)
Với **mỗi sub-query**:

| Nguồn | Cách làm | Top | Trọng số RRF |
|---|---|---|---|
| a+b. **Dense text** | `embed_query` → Qwen3 qua `/v1/embeddings` (tiền tố instruction) → Qdrant `img_text` | 200 | 1 |
| c. **Dense ảnh** | SigLIP2 text tower 768d → `img_visual` — *chỉ khi `visual_index.json` complete* | 200 | 1 (hiện 0 nguồn) |
| d. **FTS5 BM25** | bỏ 98 hư từ (so trên dạng **còn dấu**: bỏ "cho", giữ "chợ"), AND trước rồi OR bổ sung | 100 | 1 |
| e. **Khớp tên** | tên (≥ 4 ký tự) nằm trong truy vấn, hoặc truy vấn (≥ 8 ký tự) nằm trong tên; thực thể trùng hẳn lấy hết ảnh trước, ≤ 20 thực thể khớp một phần xen kẽ round-robin; ≤ 30 ảnh / thực thể | — | **3** (0 nếu không khớp) |

- Gộp: RRF `score(d) = Σ wᵢ / (60 + rankᵢ(d))`.
- Dense text và dense ảnh của mọi sub-query được gửi song song (thread pool 8).
- Embedding endpoint gửi theo lô ≤ 128 câu, 4 luồng, retry 3 lần (HTTP 429: chờ theo
  `Retry-After`, tối đa 5 s), kiểm tra đủ 2.560 chiều. Lỗi → `EmbeddingUnavailable` → **bỏ nhánh
  dense**, vẫn trả từ FTS + khớp tên, cảnh báo `embedding_failed`.

### Bước 7 — Multi-hop
`intent_type = multi_hop` → trả **0 ảnh** + cảnh báo *"Approved CSV has no factual relation
chains"*. `graph.resolve_hops` vẫn là `NotImplementedError`.

### Bước 8 — Pool và lọc
- Multi-intent: xen kẽ danh sách của các sub-query (mỗi ý đều có mặt ở đầu), phần còn lại theo
  RRF chung; nối thêm ứng viên rule khi LLM ghi đè.
- Lấy ≤ **400** ứng viên → đọc dòng từ SQLite → lọc `entity_id / entity_slug / parent_class`.
- `min_width` / `orientation`: **bị bỏ qua kèm cảnh báo** vì `dimensions_known` chưa có (chưa
  migrate). Khi có, ảnh không rõ kích thước bị loại và có cảnh báo đếm số ảnh bị loại.
- Cắt pool còn **24** ứng viên (`RERANK_TOP_K=24`, tối thiểu = `top_k`).

### Bước 9 — Rerank (`retrieval/rerank.py`)
- Backend theo `RERANK_BACKEND` (hiện trống → `llm`; không có OpenRouter key → `embedding`).
- **`llm` (đang chạy):** Gemini 3.5 Flash Lite, json_schema `{scores:[{id,score}]}`, id gọn 0..23,
  phải chấm đủ mọi id, điểm 0..1, cache `llmrerank:`. Sau đó **bỏ ứng viên điểm < 0,2** → có thể
  trả < 10 ảnh (31/244 truy vấn đo được).
- **`api`:** `POST {EMBED_API_BASE}/rerank` với `jina-reranker-v2`; không cắt theo ngưỡng.
- **`embedding`:** cosine Qwen3 giữa truy vấn và metadata ứng viên.
- Trừ điểm chất lượng: `verify=no` −0,15 · `width<600` −0,10 · watermark −0,25. **Hiện luôn = 0**
  (cột chưa có dữ liệu; và hàm đọc khoá `watermark` trong khi cột tên `has_watermark` — cần sửa).
- Lỗi: rerank chính lỗi → cosine embedding; cosine cũng lỗi → giữ thứ tự RRF. Cảnh báo
  `llm_rerank_failed` / `rerank_failed`, không cache.
- Multi-intent: gán mỗi ảnh về sub-query nó xếp hạng cao nhất, **quota** tối thiểu
  `top_k // số_sub_query` ảnh mỗi ý (`fusion.with_quota`), phần còn lại theo RRF.

### Bước 10 — Response
- Mỗi hit: `image_id, image_url, score, entity_id, entity_slug, leaf_label, parent_class,
  query_type="approved_metadata", description`.
- `facets`: thực thể, nhóm, query_type (giao diện render thành chip bấm lại được).
- `intent_type`, `parser`, `timings_ms` từng bước, `total_ms`, `warnings`.

---

## 5. Các đường suy giảm (không bao giờ 503 vì phụ thuộc ngoài)

| Sự cố | Hành vi | Cảnh báo | Cache? |
|---|---|---|---|
| LLM parse chậm > 600 ms | dùng rule | — (`parser = rule (llm timeout)`) | không |
| LLM parse lỗi | dùng rule | `llm_parse_failed` | không |
| Endpoint embedding lỗi / 429 hết lượt thử | bỏ dense text, còn FTS + tên | `embedding_failed` | không |
| Rerank chính lỗi | cosine embedding | `llm_rerank_failed` / `rerank_failed` | không |
| Cả cosine cũng lỗi | thứ tự RRF | như trên | không |
| Không có OpenRouter key | rule parse + rerank cosine | — | có |
| Filter kích thước khi chưa migrate | bỏ filter | `filter … ignored` | có |

---

## 6. Hiệu năng đo được (79.999 ảnh, 244 truy vấn, cache search tắt)

### 6.1 Độ trễ theo cấu hình rerank

| Bước (ms) | Rerank Gemini (đang chạy) p50 / p95 | Rerank jina p50 / p95 |
|---|---|---|
| Embed truy vấn (Qwen3 qua tunnel) | 180 / 310 | 132 / 237 |
| Dense Qdrant | 33 / 55 | 30 / 39 |
| FTS + khớp tên | 93 / 331 | 66 / 121 |
| Chờ LLM parse | 274 / 415 | 0 (đo chỉ rule) |
| **Rerank** | **1.989 / 2.376** | **164 / 269** |
| **Tổng** | **2.658 / 3.058** | **432 / 623** |
| Tỉ lệ < 1.500 ms | 0% | 96,7% |

Cache trúng: ~2 ms. 3,3% truy vấn jina vượt 1,5 s do endpoint trả **HTTP 429** khi gửi liên tục.

### 6.2 Chất lượng (nhãn tự sinh từ catalog — không phải goldset người)

| Loại | Gemini rerank | jina rerank |
|---|---|---|
| Tên thực thể (100): Recall@10 / Hit@10 / MRR | 0,940 / 0,99 / 0,981 | 0,996 / 1,00 / 0,995 |
| 104 tên từng trả rỗng: đúng thực thể trong top-10 | 103 | 104 |
| Set query (20): ảnh đúng nhóm | 91,5% | 86,5% |
| Multi-intent (20): có đủ A và B / ảnh thuộc A hoặc B | 20/20 / 73% | 20/20 / 70,5% |
| Truy vấn mô tả, multi-hop | **chưa đo** (không có nhãn) | — |

Thử "jina rồi Gemini verify top-10": không cải thiện set/multi, cộng thêm 1,3–1,7 s
(`reports/rerank_verify/summary.json`).

### 6.3 Chi phí mỗi truy vấn mới

| | Gemini rerank | jina rerank |
|---|---|---|
| Parse (Gemini) | $0,00052 | $0,00052 |
| Rerank | $0,00199 | $0 (endpoint riêng) |
| Embedding | $0 (endpoint riêng) | $0 |
| **Tổng** | **≈ $0,0025** | **≈ $0,0005** |

---

## 7. Cấu hình liên quan (`.env`)

```dotenv
LLM_PROVIDER=deepseek                 # khác "none" => bật LLM parse/rerank (qua OpenRouter)
OPENROUTER_API_KEY=...                # parse + rerank Gemini
LLM_ONLINE_MODEL=google/gemini-3.5-flash-lite   # mặc định trong code
LLM_PARSE_TIMEOUT_MS=600

EMBED_BACKEND=api
EMBED_MODEL=qwen3-embedding-4b
EMBED_DIM=2560
EMBED_API_BASE=https://<tunnel>.trycloudflare.com/v1   # URL đổi mỗi lần tunnel khởi động lại
EMBED_API_KEY=...

RERANK_TOP_K=24                       # số ứng viên đưa vào rerank
RERANK_LLM_MODEL=google/gemini-3.5-flash-lite
# RERANK_BACKEND=api                  # bật để dùng jina-reranker-v2 (khuyến nghị: p95 ~0,6 s)
# RERANK_API_MODEL=jina-reranker-v2

VECTOR_BACKEND=qdrant
QDRANT_URL=http://localhost:6343
```

Đổi `EMBED_*` ⇒ phải build lại index. Đổi `RERANK_*` / `LLM_*` ⇒ chỉ cần restart server
(cache search tự hết hạn vì model nằm trong khoá cache).

---

## 8. Chưa có / giới hạn đã biết

| Hạng mục | Tình trạng |
|---|---|
| Tìm theo nội dung pixel (SigLIP2 `img_visual`) | Code xong; cần tải nốt ~32k ảnh rồi encode |
| Cột `verify` / kích thước / watermark | Script `scripts/migrate_images_v2.py` xong; chưa chạy |
| Caption ảnh thiếu mô tả (~16k ảnh) | Pilot 50 ảnh; toàn bộ ~$7,3, chờ duyệt |
| Multi-hop, set query qua đồ thị | Chưa làm |
| Lọc ảnh trùng gần trong kết quả | Chưa làm (pHash vô dụng; nên dùng cosine SigLIP2) |
| Goldset người gán | Chưa có — mọi chất lượng ở mục 6.2 là nhãn tự sinh |
| LLM ghi đè intent sai | Khi parse LLM đã cache, mọi "các …" bị đổi thành `single` |
| Thực thể trùng trong catalog | VD "Súng chống tăng RPG-7" / "…B-41 (RPG-7)" — làm thấp điểm đo |
| Phụ thuộc tunnel | Embedding (và jina) qua `trycloudflare.com`: không SLA, có giới hạn tốc độ |
| Giấy phép jina-reranker-v2 | CC-BY-NC-4.0 (phi thương mại) |

---

## 9. Bản đồ file

| File | Vai trò |
|---|---|
| `api/routers/search.py` | Endpoint `/v1/search` |
| `api/routers/health.py` | `/v1/health`: model embedding / rerank / parse thật đang phục vụ |
| `retrieval/search.py` | `SearchHit`, `SearchResponse`, `PIPELINE_VERSION`, facet |
| `retrieval/local_search.py` | Toàn bộ DAG: cache, parse, retrieve, fusion, lọc, rerank, quota |
| `retrieval/rule_parser.py`, `retrieval/places.py` | Parse entity-first, địa danh |
| `retrieval/catalog.py` | Chỉ mục tên thực thể, span, ứng viên cho LLM |
| `retrieval/speculative.py` | Chạy LLM parse nền, chờ có hạn, quyết định ghi đè |
| `retrieval/llm_router.py` | Gọi OpenRouter (parse + rerank Gemini), cache, log chi phí |
| `retrieval/embed.py` | Embedding Qwen3 qua API (query/document), MiniLM local, SigLIP2 text |
| `retrieval/vector_store.py` | Qdrant `img_text` / `img_visual` (hoặc numpy), self-test |
| `retrieval/local_index.py` | Build `vectors.npy` + manifest |
| `retrieval/rerank.py` | Rerank llm / api (jina) / embedding, phạt chất lượng |
| `retrieval/fusion.py` | RRF, quota |
| `storage/local.py` | SQLite catalog, FTS5 + hư từ, cache |
| `scripts/eval_quality.py`, `scripts/eval_rerank_verify.py` | Bộ đo 244 ca, thí nghiệm verify |
| `reports/quality*/`, `reports/rerank_verify/` | Kết quả đo |
