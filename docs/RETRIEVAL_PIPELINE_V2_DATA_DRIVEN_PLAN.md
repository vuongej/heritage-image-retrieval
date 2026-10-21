# PHẦN B — KẾ HOẠCH NÂNG CẤP PIPELINE TRUY XUẤT ẢNH V2

**Bản phản biện và thiết kế lại dựa trên kiểm kê toàn bộ 80.000 dòng CSV**  
**Ngày lập:** 21/10/2026 · **Mức tài liệu:** Technical Design + Implementation Plan + Evaluation Protocol  
**Đầu vào:** `retrieval-pipeline-current.md`, `phan-b-ke-hoach-hoan-thien-pipeline-retrieval.md`, `data_anh_pass_80000_full_pham_van_vuong(1).csv`  
**Phạm vi:** Phần B — image retrieval, không thiết kế lại toàn bộ Phần A  
**Mục tiêu:** truy xuất đúng thực thể, chọn đúng ảnh, hỗ trợ single/multi-intent/set/multi-hop, đo được chất lượng và độ trễ; không giả định model lớn hơn sẽ tốt hơn.

> **Cách đọc số liệu:** Nhãn **[CSV—ĐO]** = đã tính trực tiếp trên đủ 80.000 dòng của file tải lên; **[PIPELINE—BÁO CÁO]** = số của tài liệu `retrieval-pipeline-current.md`, chưa tự chạy lại API; **[ĐỀ XUẤT]** = thay đổi thiết kế cần triển khai; **[CẦN ĐO]** = mục tiêu/giả thuyết phải A/B test. Không trình bày mục tiêu như thành tích đã đạt.

---

## 0. Quyết định kiến trúc (Executive decision)

**Không áp dụng nguyên xi kế hoạch cũ.** Chuyển sang mô hình truy xuất **hai tầng: tìm đúng thực thể → chọn ảnh phù hợp trong thực thể**; duy trì đường tìm kiếm theo metadata ảnh để không bỏ sót mô tả riêng của từng ảnh. Kết hợp structured filters và kiểm duyệt ảnh, chỉ sử dụng visual embedding khi đã tải và mã hóa ảnh thực tế.

**7 quyết định cần chốt:**

1. **Rerank:** đánh giá `bge-reranker-v2-m3` và `Qwen3-Reranker-0.6B` đối chiếu với baseline Jina; ưu tiên phương án license phù hợp, **không khẳng định cùng tốc độ khi chưa đo**. Giữ Gemini cho parse truy vấn mơ hồ, không dùng Gemini rerank mặc định.
2. **Index:** giữ dense Qwen cho `name + description`, FTS5 và exact entity-name; `category` là metadata/phân cấp có cấu trúc, **không nhân bản 80.000 vector group như mặc định**. Nếu cần semantic category embedding, chỉ encode **669 category duy nhất** trước.
3. **Rank:** rerank **thực thể** trước; chọn ảnh theo verify/dimensions/watermark/visual relevance; diversification sau khi đã có điểm relevance phù hợp. **Không cap 3 ảnh cho mọi entity trong single-intent**.
4. **Multi-intent:** giữ pool riêng từng sub-query, áp dụng quota *có điều kiện đủ liên quan*; không đưa ảnh sai vào để ép đủ slot.
5. **Multi-hop:** KG có hướng, nguồn và bằng chứng; phân biệt `IN_CLASS` với quan hệ nhân thân; **không suy diễn `SIBLING` từ danh sách trong ngoặc của category**. Wikidata làm nguồn bổ trợ có timeout và cache.
6. **Dữ liệu ảnh:** `flag=approved` không đủ để suy ra pixel đẹp/đúng; `sha256` trống toàn bộ, chưa biết near-duplicate hoặc watermark. Không gắn nhãn “đã visual verified” chỉ dựa CSV.
7. **Đánh giá:** tách entity retrieval / image retrieval / relation resolution; goldset con người và benchmark cache-cold/cache-warm/chạy mới phải có quy tắc rõ.

**Hai ngưỡng thời gian phải ghi đúng:** pipeline hiện tại tuyên bố **SLO nội bộ p95 ≤ 1.500 ms**; kế hoạch cũ dùng yêu cầu **truy vấn < 3.000 ms**. V2 đặt **mục tiêu p95 ≤ 1.500 ms cho warm search thông thường**, **tỷ lệ vượt 3.000 ms là chỉ số riêng** (nếu đề bài yêu cầu *mọi truy vấn* < 3 giây thì báo thêm max, timeout và tỷ lệ vi phạm; p95 không thay thế điều kiện đó).

---

## 1. Kiểm kê dữ liệu thực tế — 80.000 dòng

### 1.1. Cấu trúc và tính toàn vẹn [CSV—ĐO]

| Chỉ số | Kết quả đo | Hệ quả thiết kế |
|---|---:|---|
| Dòng CSV / `flag=approved` | **80.000 / 80.000** | Đây là dữ liệu đầu vào, **không đồng nghĩa 80.000 ảnh đã indexed** |
| Số cột | **12** | `username, submitted_at, flag, entity_id, slug, canonical_name, category, sha256, image_url, source_url, description, from_db` |
| `entity_id` duy nhất | **11.294** | Định danh chuẩn của retrieval |
| `slug` duy nhất | **11.294** | Có thể index alias, nhưng cần map theo `entity_id` |
| Tên `canonical_name` duy nhất | **11.281** | **7 tên** được dùng cho >1 entity_id; tổng **13 lần gán vượt** số tên duy nhất |
| Tên trùng sau bỏ dấu/chuẩn hóa | **8 khóa tên** | Cần disambiguation, không lấy tên làm PK |
| Category nguyên bản duy nhất | **669** | Lượng category nhỏ so với 80.000 ảnh |
| `image_url` duy nhất | **80.000** | **0 URL trùng tuyệt đối**; không chứng minh nội dung pixel không trùng |
| `image_url` không phải HTTP(S) | **1** | URL dạng `x-raw-image:///...`; pipeline hiện loại nên chỉ còn 79.999 ảnh |
| `sha256` rỗng | **80.000 (100%)** | Chưa thể exact-dedup theo bytes |
| `source_url` rỗng | **328 (0,41%)** | Không được coi mọi nguồn đều có provenance |
| `description` rỗng | **16.110 (20,14%)** | Ảnh cần fallback metadata và ưu tiên kiểm duyệt |
| Thực thể **mọi ảnh** đều thiếu description | **862** | Entity-level semantic retrieval yếu |
| Thực thể có **một phần ảnh** thiếu description | **3.473** | Cần ranking ảnh có mô tả riêng, không chỉ theo entity |
| Chuỗi `(name, category, description)` duy nhất | **66.937** | Có **13.063 lượt lặp metadata bổ sung** |
| Nhóm metadata có lặp | **3.104 nhóm** | Một embedding không phân biệt được các ảnh trong nhóm |
| Nhóm metadata trùng xuyên entity | **0** | Lặp metadata quan sát được nằm **trong cùng entity**, không phải các entity khác nhau |
| Entity có ≥2 ảnh nhưng **tất cả metadata giống nhau** | **908 entities / 5.010 ảnh** | Trường hợp điển hình cần image quality/visual ranking |
| Host của URL ảnh HTTP(S) | **6.437** | Tải ảnh rất phân tán, cần retry/throttle theo host |
| Host của `source_url` có netloc | **7.163** | Phải lưu provenance độc lập với CDN |
| Người nộp `username` duy nhất | **8** | Không đưa `username` làm feature relevance |

**Lưu ý sửa sai kế hoạch cũ:** phép trừ `11.294 entity_id - 11.281 name = 13` là số *gán trùng vượt*, không phải 13 tên trùng. **Số tên thực sự bị dùng cho nhiều entity là 7.** Ví dụ `Lăng Tự Đức` có 4 `entity_id`, `Lăng Minh Mạng` có 3, `Lăng Thiệu Trị` có 2. Nhận định “10.188 tên thực thể bị lặp” trong kế hoạch cũ **sai cấp độ thống kê**: nhiều dòng ảnh chung một entity đương nhiên lặp `canonical_name`.

**Lưu ý thứ hai:** không được coi `source_url`/`image_url` khác nhau là ảnh khác nhau về nội dung: cùng tấm ảnh có thể được đăng trên nhiều website, resize/crop/đổi định dạng. Không thể đo near-duplicate hay ảnh phù hợp chỉ từ CSV URL.

### 1.2. Phân phối số ảnh / thực thể [CSV—ĐO]

| Số ảnh/entity | Số entity | Tổng ảnh trong nhóm | Entity thiếu toàn bộ description |
|---|---:|---:|---:|
| 1 | 1.096 | 1.096 | 255 |
| 2–3 | 2.358 | 5.911 | 250 |
| 4–9 | 4.922 | 30.027 | 257 |
| 10–19 | 2.477 | 32.534 | 86 |
| ≥20 | 441 | 10.432 | 14 |
| **Tổng** | **11.294** | **80.000** | **862** |

Số ảnh / entity: `min=1`, `p50=6`, `p90=15`, `p95=18`, `p99=25`, `max=41`, trung bình khoảng `7,08`.

**Hệ quả:** chính sách `max_per_entity=3` áp dụng cho mọi truy vấn sẽ khiến câu “cho tôi 10 ảnh Lăng Tự Đức” chỉ được tối đa 3 ảnh mặc dù dữ liệu có thể có nhiều hơn. Cap/quota phải phụ thuộc **intent** và mức xác thực entity.

### 1.3. Mức nhiễu của `category` và `description` [CSV—ĐO]

| Thống kê | Giá trị |
|---|---:|
| Độ dài `canonical_name` trung bình | 29,34 ký tự |
| Độ dài `category` trung bình / p50 / p90 | 80,78 / 74 / 145 ký tự |
| Độ dài `description` trung bình / p50 | 101,89 / 116 ký tự |
| Tỷ lệ `category` trong độ dài `name + category + description` | Trung bình ~39%; p90 ~71,56% |
| Category dài >120 ký tự | **116 giá trị**, phủ **19.356 ảnh (24,195%)** |
| `description` chứa nguyên tên thực thể (chuẩn hóa bỏ dấu) | **47.379 ảnh (~59,22%)** |
| `description` **bắt đầu** bằng tên thực thể (chuẩn hóa bỏ dấu) | **18.704 ảnh (23,38%)** |
| Số category còn lại sau khi bỏ *mọi* ngoặc đơn bằng regex thử nghiệm | 663 (từ 669) |

**Quan trọng:** thống kê `description chứa tên` (59,22%) **không đồng nghĩa** 59,22% mô tả có tên ở đầu để có thể cắt tiền tố an toàn. Chỉ 18.704 trường hợp thỏa điều kiện bắt đầu bằng tên. Còn các mô tả dùng tên ở giữa câu thì phải giữ nguyên để bảo toàn thông tin.

`category` dài không chứng minh chắc chắn là nguyên nhân của 27% nhiễu multi-intent; đó là giả thuyết **cần ablation**. Không xóa ngoặc đơn một cách mù quáng: phần ngoặc đôi khi chứa tỉnh/thành hoặc subtype hữu ích.

Ví dụ category dài có thật trong CSV: `Cầu hệ sông Hậu & bán đảo Cà Mau (Cần Thơ, Vàm Cống, Châu Đốc, Đại Ngãi đang XD + ...)`. Trong truy vấn exact entity, toàn bộ danh sách cầu này có thể tạo matching giả với thực thể không phải mục tiêu.

### 1.4. Phủ từ khóa / kiểm tra ví dụ truy vấn [CSV—ĐO]

Đếm **sự hiện diện của cụm từ trong metadata** sau bỏ dấu; đây là phép đo lexical, **không phải** xác nhận một loại ảnh có/không trên Internet hay trong pixel.

| Cụm từ | `canonical_name` | `description` | `category` | Diễn giải đúng |
|---|---:|---:|---:|---|
| `công viên nước` | 0 | 0 | 0 | Không có **bằng chứng text** theo cụm này; không kết luận không có ảnh nhìn thấy công viên nước |
| `hồ bơi` | 0 | 121 | 0 | Phụ thuộc mô tả ảnh, không có entity mang cụm này trong tên |
| `Phạm Nhật Vượng` | 0 | 0 | 0 | Người seed có thể không nằm trong catalog; multi-hop cần external linking và kiểm tra target coverage |
| `Chùa Một Cột` | 50 | 36 | 0 | Đủ ví dụ exact-entity để test single |
| `Cầu Maspéro` | 6 | 6 | 0 | Đủ ví dụ exact-entity ít ảnh |
| `Phú Quốc` | 363 | 278 | 365 | Phải phân biệt địa điểm trong tên/description/category |
| `con trai` | 7 | 11 | 0 | Dữ liệu chứng cứ quan hệ nhân thân rất mỏng |
| `con gái` | 0 | 0 | 0 | Không thể trích nhiều quan hệ này từ metadata |

Không dùng grep từ đơn như `vợ` hay `cha` để khẳng định có quan hệ: sau bỏ dấu, `Võ` cũng dễ bị nhầm với `vợ` nếu phương pháp matching không giữ token/ngữ cảnh; `chồng` còn xuất hiện trong tên địa danh. Cần annotation quan hệ với chủ thể–thuộc tính–đối tượng và nguồn.

### 1.5. Chất lượng dữ liệu: điều đã biết và chưa biết

**Biết từ CSV:** số bản ghi; text fields; trùng literal; URL hợp lệ theo cú pháp; tên/nhóm; host; `flag` (tất cả `approved`).  
**Không biết từ CSV:** link còn tải được hay không; HTTP status, pixel có đúng entity không; ảnh mờ/giả/montage; kích thước thật; watermark; perceptual duplicate; ảnh có bao nhiêu người; giấy phép tái sử dụng.  
**Từ pipeline hiện tại [PIPELINE—BÁO CÁO]:** `verify`, `width`, `height`, `has_watermark`, `fetch_status` gần như chưa được điền; visual index `img_visual` chưa bật; SQLite/Qdrant đã nạp 79.999 ảnh (không phải 80.000).

**Hành động bắt buộc P0:** sửa hoặc thay URL non-HTTP duy nhất bằng ảnh hợp lệ, rồi **đo sau khi index**:

```text
csv_valid_rows >= 80000
sqlite_images   >= 80000
qdrant_img_text >= 80000
orphan_vectors = 0
missing_payload_ids = 0
```

Nếu chưa bổ sung được ảnh, báo đúng **79.999 ảnh indexed**, tuyệt đối không ghi đã đạt yêu cầu ≥80k chỉ vì CSV có 80k dòng.

---

## 2. So sánh thực trạng và những kết luận cần sửa

| Nội dung | Pipeline đang chạy [PIPELINE—BÁO CÁO] | Kết luận V2 |
|---|---|---|
| Text embed | Qwen3-Embedding-4B, 2.560d, Qdrant `img_text` | Giữ baseline, thử `text_core` vs metadata gốc |
| Dense visual | SigLIP2 chưa nạp `img_visual` | Phát triển theo mức download thành công; chưa coi đã có tính năng pixel |
| Sparse | SQLite FTS5 BM25 top-100 | Giữ và cải thiện field boosts/query normalization |
| Name match | RAM catalog/alias, RRF w=3 | Giữ entity-first; tránh duplicate names và fake entity |
| Fusion | RRF k=60, top-200 dense, name 30/entity, pool≤400 | Theo dõi coverage theo nguồn và sub-query; không cắt sớm mất entity |
| Parse | Rule + Gemini chạy nền, budget 600ms; phần lớn lần đầu timeout | Rule được bảo vệ; gọi Gemini có điều kiện, không tin mọi ghi đè intent |
| Rerank default | Gemini, 24 candidates, p95 ~2.376ms | A/B local CE; không ép cutoff score tuyệt đối/tương đối chưa calibrate |
| Rerank thử nghiệm | Jina, p95 rerank ~269ms, tổng ~623ms | Là **baseline thực đo**; khác cấu hình parser nên không so trực tiếp toàn bộ pipeline |
| Multi-intent | Có A và B 20/20; 73% ảnh thuộc A/B với Gemini | Xây assignment và relevance per-sub-query, không chỉ quota hình thức |
| Multi-hop | `NotImplementedError`, trả 0 | Đồ thị chuẩn + kết quả có nguồn/đường suy luận |
| Quality | Fields null, `watermark` vs `has_watermark` | Migrate/đồng bộ payload, xử lý null rõ ràng |
| SLO | p95 Gemini ~3.058ms > SLO 1.500ms | Giảm rerank là việc nhanh nhất, nhưng phải đo end-to-end cùng điều kiện |

**Không quy trách nhiệm toàn bộ multi-intent cho `category`:** cần đo tách lỗi ở **(1) query decomposition, (2) entity candidate recall, (3) fusion, (4) rerank, (5) final top-K allocation**. Nếu entity đúng không nằm trong candidate pool, đổi reranker không thể cứu.

---

## 3. Kiến trúc mục tiêu — Entity-first + Image-second

```text
POST /v1/search {query, top_k, filters}
   │
   ├── [0] Validate request + versioned cache
   │
   ├── [1] Query analysis
   │      rule span / aliases / location / intent / constraints
   │      └── Gemini parser (ONLY ambiguous or relation complex; finite budget)
   │
   ├── [2] MULTI-HOP? → link seed → traverse verified KG → target entity_id(s)
   │                            ╰── failed: return explicit unsupported/no-evidence
   │
   ├── [3] Candidate generation PER SUB-QUERY (parallel)
   │      ├── exact entity name + aliases + edit/substring controlled
   │      ├── FTS5: name boosted, description, category labels
   │      ├── Qwen3 text_core dense → img_text
   │      ├── group lookup/structured category filter (set queries)
   │      └── [optional] SigLIP2 text→image ONLY when img_visual ready
   │
   ├── [4] Candidate fusion + aggregate by entity_id
   │      RRF for ranking positions, keep provenance and subquery IDs
   │      └── enough distinct entities? oversample if not
   │
   ├── [5] Entity rerank (cross-encoder) + constraints
   │      batch candidate ENTITY REPRESENTATIVES, not many identical image texts
   │
   ├── [6] Image expansion for selected entity_id(s)
   │      ├── filter verify / width / orientation / fetch_status
   │      ├── score image-specific description + text/visual relevance
   │      └── near-dup family / watermark / quality, UNKNOWN remains UNKNOWN
   │
   ├── [7] Multi-intent coverage & final selection
   │      quota if relevant; adaptive cap; visual MMR when vectors available
   │
   └── [8] Top-K + facets + evidence + warnings + timings + cache
```

**Không bỏ nhánh image-level retrieval**: một ảnh có mô tả chi tiết hơn các ảnh khác trong cùng entity có thể phù hợp với query kiểu “ảnh cận cảnh mặt tiền” hoặc “tháp chuông”, dù bản entity-level chung không đủ mô tả. Hai tầng bổ trợ nhau: entity-first để bảo đảm định danh; image-level để không bỏ mất dấu hiệu trong mô tả ảnh cụ thể.

### 3.1. Hợp đồng đầu ra chuẩn (API contract)

```json
{
  "query": "ảnh Chùa Một Cột và Lăng Chủ tịch Hồ Chí Minh ở Hà Nội",
  "intent_type": "multi_intent",
  "parser": "rule|llm_assisted",
  "pipeline_version": "b3-entity-first-image-second",
  "index_version": "2",
  "sub_queries": [
    {"id": "q0", "text": "Chùa Một Cột ở Hà Nội", "coverage": "covered"},
    {"id": "q1", "text": "Lăng Chủ tịch Hồ Chí Minh ở Hà Nội", "coverage": "covered"}
  ],
  "hits": [
    {"image_id": "<id>", "entity_id": "<id>", "image_url": "https://...",
     "matched_subqueries": ["q0"], "rank_score": 0.0,
     "evidence": {"retrieval_sources": ["name", "fts"], "pixel_checked": false},
     "quality": {"width": null, "verify": "unknown", "watermark": "unknown"}}
  ],
  "warnings": [],
  "timings_ms": {"parse": 0, "retrieve": 0, "rerank_entity": 0, "select_image": 0, "total": 0}
}
```

`rank_score` **là điểm xếp hạng**, không tự nhận là xác suất đúng nếu chưa hiệu chuẩn. `coverage` và `evidence` phải phản ánh trạng thái thực, không sinh giả. JSON trên là **ví dụ cấu trúc**, không phải API response đã chạy.

---

## 4. Thiết kế lại dữ liệu và index

### 4.1. Chia nội dung thành các field có chức năng rõ

| Field | Nguồn | Dùng cho | Không làm |
|---|---|---|---|
| `name_text` | `canonical_name` | exact / alias / boost BM25 | Không lấy tên làm khóa duy nhất |
| `description_text` | `description` từng ảnh | search chi tiết, rerank image | Không coi rỗng là chất lượng ảnh kém |
| `text_core` | `name + description` | Qwen dense image-level | Không trộn category rất dài vào vector chính |
| `group_id`, `group_label`, `category_original` | `category` | filter, set query, group hierarchy | Không xóa bản gốc / suy diễn quan hệ sai |
| `entity_summary` | tên + tóm tắt có bằng chứng | rerank entity | Không dùng caption LLM không kiểm chứng làm sự thật |
| `aliases` | biến thể tên có kiểm soát | exact match/candidate expansion | Không tự đồng nhất 7 tên collision |
| `quality` | fetch + pixel verify khi có | filter và image selection | Không convert `NULL` thành `yes` |
| `visual_vector` | ảnh tải được | visual retrieval/dedup/diversity | Không đánh dấu hoàn thành khi chỉ có metadata |

**Tạo `text_core` an toàn:** dùng `name + description`, giữ Unicode gốc; bỏ tên ở đầu description chỉ khi match qua ranh giới token/câu thật sự. Thử nghiệm 2 biến thể `raw_desc` và `strip_prefix_only`; đừng xóa tên xuất hiện giữa mô tả. Với description rỗng, `text_core = name`, còn `group_label` vẫn có sẵn cho FTS/group lookup.

### 4.2. Đừng build 80k `img_group` cùng vector nếu 669 group đủ dùng

Thứ tự phương án từ đơn giản đến phức tạp:

1. **V2A (khuyên dùng):** `img_text` vẫn chứa 80k vector của `text_core`; SQLite lookup từ `group_id → entity_ids`, Qdrant payload group filter.
2. **V2B (thử nghiệm):** encode **669 category được chuẩn hóa có kiểm duyệt** thành bảng `group_vectors`; truy vấn set theo group top-N rồi lookup entity. Chi phí dữ liệu thấp hơn 80k vector group.
3. **V2C (chỉ nếu benchmark chứng minh):** thêm named vector `group` trên từng image/entity hoặc hybrid ANN nhóm nếu nhu cầu thật.

Ước lượng float32 thuần (chưa tính HNSW/payload): **80.000 × 2.560 × 4 = 819,2 MB (~781,3 MiB)**; **80.000 × 1.024 × 4 = 327,68 MB (~312,5 MiB)**; **669 × 2.560 × 4 ≈ 6,85 MB**. Việc giảm chiều bằng MRL cần benchmark chất lượng, không mặc định bật.

### 4.3. Cấu trúc bảng khuyến nghị

```sql
-- PK theo định danh có sẵn; không tạo PK từ canonical_name.
CREATE TABLE IF NOT EXISTS entities_v2 (
  entity_id TEXT PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  canonical_name TEXT NOT NULL,
  group_id TEXT NOT NULL,
  entity_summary TEXT,
  wikidata_qid TEXT,
  summary_provenance TEXT
);
CREATE TABLE IF NOT EXISTS entity_aliases_v2 (
  entity_id TEXT NOT NULL,
  alias_norm TEXT NOT NULL,
  alias_type TEXT NOT NULL,
  PRIMARY KEY (entity_id, alias_norm)
);
CREATE INDEX IF NOT EXISTS idx_alias_norm_v2 ON entity_aliases_v2(alias_norm);
CREATE TABLE IF NOT EXISTS categories_v2 (
  group_id TEXT PRIMARY KEY,
  category_original TEXT NOT NULL,
  group_label TEXT NOT NULL,
  parent_group_id TEXT
);
CREATE TABLE IF NOT EXISTS relations_v2 (
  subject_entity_id TEXT NOT NULL,
  relation_type TEXT NOT NULL,
  object_entity_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  confidence REAL,
  reviewed INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(subject_entity_id, relation_type, object_entity_id, source_id)
);
CREATE INDEX IF NOT EXISTS idx_rel_subject_v2 ON relations_v2(subject_entity_id, relation_type);
CREATE INDEX IF NOT EXISTS idx_rel_object_v2 ON relations_v2(object_entity_id, relation_type);
```

Không chạy đoạn SQL này như migration đầy đủ: phải thêm cột/bảng cho `images`, `fetch_status`, `width`, `height`, `orientation`, `verify`, `has_watermark`, `visual_model_version`, `near_dup_cluster_id` và kiểm tra tương thích schema hiện có. Ghi `UNKNOWN` riêng, **không ghi `verify=no` chỉ vì ảnh chưa tải/không có nhãn**.

### 4.4. Build index an toàn và có thể rollback

1. Đọc CSV streaming; kiểm tra `entity_id`-`slug` mapping 1:1; check 7 tên collision ở đúng `entity_id`.
2. **Quarantine 1 URL sai scheme** với row offset/log; thay bằng ảnh hợp lệ khi cần đạt 80k thật.
3. Sinh `entities_v2`, `categories_v2`, alias, `text_core` và FTS5; giữ nguyên old catalog/index trước khi chuyển.
4. Encode mỗi chuỗi `text_core` **duy nhất** (bộ dữ liệu gốc có 66.937 metadata duy nhất, V2 cần đo lại uniqueness sau khi cắt category). Map nhiều image IDs về cùng embedding khi văn bản thực sự giống nhau.
5. Tạo collection Qdrant **mới** `img_text_v2` (không ghi đè in-place), upsert theo batch có kiểm tra kết quả.
6. Manifest phải có: `input_csv_sha256`, `dataset_rows`, `usable_image_rows`, `vector_count`, `embedding_model_id`, `embedding_dim`, `instruction_hash`, `text_normalizer_version`, `schema_version`, `built_at`, `url_policy`, `visual_count`.
7. Shadow query V1/V2 với cùng 100–300 test; kiểm tra counts, latency, candidate coverage. Chuyển alias active collection sau khi nghiệm thu; giữ V1 rollback.
8. Cache search key **phải gắn cả index alias generation + embedding model + reranker + parser policy + filter schema + visual readiness**; không phục vụ kết quả cache V1 cho V2.

**Filter sớm:** payload Qdrant có `entity_id`, `group_id`, `orientation`, `width`, `height`, `verify`, `fetch_status`; tạo payload index cho các field lọc nhiều. Nếu ANN trả không đủ sau lọc, overfetch có giới hạn; ghi `filtered_out_count` và `unknown_quality_count`.

---
## 5. Truy xuất và hợp nhất ứng viên (candidate retrieval)

### 5.1. Intent routing: rule là nền tảng, LLM chỉ giải quyết bất định

**Input:** `query`, `filters`, `top_k`. **Output bắt buộc:** `intent_type`, `subqueries[]`, `matched_entity_ids[]`, `constraints`, `relation_plan`, `parse_confidence`, `parse_source`, `warnings`.

| Trường hợp | Chính sách |
|---|---|
| Toàn bộ span truy vấn khớp chính xác 1 tên/alias rõ ràng | `single`, giữ entity_id; ưu tiên không gọi LLM |
| Hai tên thực thể rõ ràng nối bằng `và`, `với` | `multi_intent`, 2 sub-query; **không** để LLM cache đổi thành `single` thiếu bằng chứng |
| “các chùa ở …”, “những cây cầu …” | `set_query`, tách class/place và các ngoại lệ; không đánh đồng mọi từ `các` với nhu cầu group |
| “con trai của…”, “người sáng lập…” | `multi_hop` nếu có quan hệ ngữ nghĩa; tách title modifier với hop thật |
| Tên nhập thiếu / nhiều alias cùng khớp / quan hệ mơ hồ | Chạy Gemini JSON parser, kiểm tra schema, chỉ dùng nếu không phá invariant |
| Nhiều entity collision cùng tên | Giữ nhiều candidate + disambiguate bằng nhóm/địa điểm; không tự chọn một ID thiếu chứng cứ |

**Invariant cần có unit test:**

- Không cho LLM ghi đè `set_query` → `single` nếu không có căn cứ xác nhận rõ một thực thể duy nhất.
- Không cho LLM sinh thực thể/hop mà `entity linker` không xác minh được rồi xem là ground truth.
- Place cuối câu chỉ áp cho tất cả sub-query khi ngữ pháp thực sự chung; các tên địa danh nằm *bên trong tên entity* phải được che span.
- Parser được cache **theo policy version**; dữ liệu cache Gemini cũ không được tự động coi là chuẩn.
- Không dựa vào một số timeout tùy ý (150/600ms) mà kết luận chất lượng parser không thay đổi. A/B 0ms / 150ms / 600ms ở tập query mơ hồ để đo chất lượng–độ trễ.

### 5.2. Các nguồn candidate và việc dùng chúng

**Bản tối thiểu V2A, chưa dùng pixel:**

| Nguồn | Index | Truy vấn | Kết quả | Vai trò |
|---|---|---|---|---|
| Exact / alias | catalog RAM + SQL | normalized phrase + boundary-aware matching | `entity_id` | Đúng thực thể, đặc biệt truy vấn có tên |
| FTS5 / BM25 | SQLite name/description/group | từ khóa không dấu + tokenization | `image_id`/`entity_id` | Thuật ngữ, từ hiếm, địa danh |
| Qwen dense | Qdrant `img_text_v2` | `text_core` | `image_id` | Semantic retrieval theo văn bản ảnh |
| Group lookup | SQL category index | `group_id`, group label, location | `entity_id` | Set / loại hình / structured filters |
| Verified KG | `relations_v2` | entity+predicate | target entity IDs | Multi-hop, có evidence |

**Top-N chỉ là tham số cần dò**, không là chân lý: `dense_candidates=200`, `fts_candidates=100`, `exact_entity_limit=30` giữ làm baseline từ V1, sau đó thử `dense=100/200/400`, pool entity `30/50/80`, rerank entity `20/40/60`. Đo Recall của **entity đúng trong candidate pool** trước và sau mọi truncation; đừng chỉ đo top-10 cuối.

### 5.3. RRF là công cụ fusion, không phải xác suất

RRF được giữ như baseline:

\[
\operatorname{RRF}(x)=\sum_{r\in\mathcal R}\frac{w_r}{k+\operatorname{rank}_r(x)},\quad k=60.
\]

**Đề xuất thực thi:**

1. Mỗi sub-query có danh sách kết quả nguồn riêng và trace `source`, `rank`, `subquery_id`.
2. Gộp image candidates cùng image_id; tổng hợp lên `entity_id` theo **best image**, không cộng vô hạn từ 41 ảnh cùng entity (tránh entity nhiều ảnh lấn entity ít ảnh).
3. Đính kèm vào entity top 1–3 đại diện: ảnh metadata mô tả đầy đủ, ảnh độ tin cậy/visual cao nếu đã được kiểm tra, nhưng không để số ảnh nhiều tạo đặc quyền điểm.
4. Hợp nhất entity theo `best_image_rrf`, exact-name evidence và group match (weight/scale phải thử trên goldset).
5. Giữ lại `candidate_provenance` cho debug; nếu sub-query thiếu candidate sau fusion thì truy ngược retrieval branch gây thất bại.

Pseudocode mang tính **hợp đồng thuật toán** (cần ánh xạ sang model/schema hiện có):

```python
def retrieve_per_subquery(subq, request_filters, index):
    raw = parallel_fetch({
        "name": lambda: index.entity_name_match(subq),
        "fts": lambda: index.fts_search(subq, limit=100),
        "dense": lambda: index.qwen_dense_search(subq, limit=200),
        "group": lambda: index.group_lookup(subq),
    })
    img_candidates = rrf_fuse(raw, k=60, weights={
        "name": 3.0, "fts": 1.0, "dense": 1.0, "group": 0.7
    })
    # Đây là baseline thử nghiệm; chưa kết luận weight tối ưu.
    return aggregate_to_entity_by_best_image(img_candidates)
```

**Bất biến:** vị trí của một thực thể trong top entity không được phụ thuộc tuyến tính vào số ảnh metadata lặp của nó. Kiểm thử bằng cách nhân đôi 10 metadata cho một entity trong index mô phỏng: thứ hạng không được nhảy bất thường chỉ vì duplicate rows.

### 5.4. Multi-intent: giải quyết việc trả ảnh “ngoài A/B”

Hiện có báo cáo `has_A_and_B = 20/20`, nhưng precision kết quả thuộc A hoặc B mới ~73% với Gemini và ~70,5% với Jina; số liệu dựa nhãn tự sinh, chưa phải goldset. Cần tách **coverage** khỏi **precision**.

**Thiết kế đúng:**

1. Parse `n_sub` sub-query độc lập; search và rerank **theo từng sub-query** (batch inference chung được nếu backend hỗ trợ).
2. Cho mỗi `(candidate_image, subquery)` điểm có nghĩa trong **cùng model**, không giả định điểm giữa các query đã calibrate thành xác suất.
3. Mark `supported_for_subquery` bằng evidence (exact entity/group, human label ở evaluation) thay vì chỉ “candidate này là lớn nhất trong các score thấp”.
4. Phân slot bằng **round-robin / weighted fair allocation** trên tập candidate đạt tiêu chí, sau đó fill từ global pool nếu còn slot. **Không tự tạo ảnh để ép quota**.
5. Với câu exact entity A+B, phần ảnh trả về cần xuất phát từ **A hoặc B**; nguồn khác chỉ được đưa vào nếu có bằng chứng rõ ràng truy vấn yêu cầu mở rộng.
6. Nếu một sub-query không có candidate đủ chứng cứ: `sub_query_no_coverage` và trả số ảnh thực sự phù hợp; không hạ threshold đến mức trả ảnh sai.
7. `top_k` có thể nhỏ hơn số sub-query. Ví dụ 4 intent nhưng `top_k=3`: không thể bảo đảm đủ 4; response cần nêu giới hạn và cho phép tăng `top_k`.

**Lỗi cần tránh ở kế hoạch cũ:** `quota = max(top_k//n_sub, 3)` có thể phân quá `top_k` (10 ảnh / 4 intent → 4×3 = 12). Không dùng công thức đó.

```python
def allocate_fair(subquery_ranked, top_k):
    """Không thêm item không liên quan. Mỗi phần tử đã được lọc support."""
    result, used = [], set()
    queues = {qid: list(items) for qid, items in subquery_ranked.items()}
    while len(result) < top_k:
        advanced = False
        for qid, queue in queues.items():
            while queue and queue[0]["image_id"] in used:
                queue.pop(0)
            if queue and len(result) < top_k:
                item = queue.pop(0)
                result.append(item)
                used.add(item["image_id"])
                advanced = True
        if not advanced:
            break
    return result
```

Code là baseline phân slot; production cần cân bằng điểm / geographic constraints / dedup / image relevance và kiểm tra `supported_for_subquery` trước khi gọi.

### 5.5. Set query: tăng coverage mà không nhầm nhóm

Với “các chùa tại Nghệ An”, hệ thống nên lấy candidate theo subtype “chùa” và địa điểm “Nghệ An” thay vì chỉ dense category. Trong catalog có category vừa chỉ loại, vừa có list địa danh nằm trong ngoặc; **tên tỉnh xuất hiện ở category không đủ để chứng minh ảnh/entity thuộc tỉnh đó**.

Chia rõ:

- `type`: chùa / cầu / nhà thờ / bảo tàng… (taxonomy có bằng chứng).
- `place`: tỉnh/thành/địa danh của entity (nếu metadata thực sự xác định); unknown nếu chưa tách được.
- `group_label`: nhãn nhóm cấp cao; `category_original`: giữ nguyên để debug.

**Không parse place bằng cách lấy tất cả địa danh liệt kê trong category:** ví dụ category “Chùa Bắc Tông — Bắc Trung Bộ (Thanh Hóa, Nghệ An, …)” liệt kê cả vùng; nếu gán tất cả entity trong group là “ở Nghệ An” sẽ sai. Cần extract từ tên/mô tả xác định, hoặc external validation/gán tay; lưu provenance của nơi suy ra.

### 5.6. Luồng degraded mode đúng bản chất

| Lỗi | Fallback an toàn | Không được làm |
|---|---|---|
| Qwen embedding timeout/429 | FTS5 + exact/alias + group SQL | Trả 503 toàn bộ nếu các nhánh khác vẫn hoạt động |
| Cross-encoder lỗi | RRF/FTS + entity prior, kèm warning | Giả làm scores rerank hợp lệ |
| Gemini parser timeout | Rule parse; warning nhẹ ở debug | Đợi LLM tới 6 giây nếu còn SLO 3 giây |
| Multi-hop external offline | Verified KG local hoặc `unsupported/no_evidence` | Fallback nhóm `IN_CLASS` cho `CHILD`/`SPOUSE` |
| Image dimension unknown | Giữ/loại theo **chính sách filter đã công bố**; thông báo số unknown | Im lặng bỏ qua `min_width` |
| Visual index chưa ready | Text-based ranking + chất lượng đã biết | Claim “đã tìm bằng pixel” |

---

## 6. Rerank: chọn model và tổ chức inference

### 6.1. Kết luận tạm thời từ benchmark hiện có [PIPELINE—BÁO CÁO]

| Thử nghiệm | Gemini rerank | Jina rerank |
|---|---:|---:|
| Tổng p50/p95 | 2.658 / **3.058 ms** | 432 / **623 ms** |
| Rerank p50/p95 | 1.989 / 2.376 ms | 164 / **269 ms** |
| Entity-name Hit@10 | 0,99 | 1,00 |
| Set: tỷ lệ ảnh đúng nhóm | 91,5% | 86,5% |
| Multi-intent: ảnh thuộc A/B | 73% | 70,5% |
| Độ đầy đủ top_k | Gemini có 31/244 truy vấn bị loại bởi cutoff 0,2 | Jina không cutoff tương tự |

**Bẫy benchmark:** lượt Jina đã được mô tả là “chỉ rule parse” tại bước chờ LLM = 0ms, trong khi lượt Gemini có chờ parse. Do đó so p95 tổng **chưa phải** thí nghiệm chỉ thay một biến `reranker`. Phải chạy ma trận cố định parser backend, candidate count, cache states, thời điểm tải, concurrency và endpoint.

### 6.2. Model candidates và điều kiện chọn

| Model | Vai trò | Điều kiện/chú ý |
|---|---|---|
| `jina-reranker-v2-base-multilingual` | **Reference chất lượng/tốc độ** đã đo | Model card HF license CC-BY-NC-4.0 (phi thương mại); kiểm tra quyền sử dụng thực tế |
| `BAAI/bge-reranker-v2-m3` | Ứng viên mặc định nếu đạt metric | Apache-2.0; phải đo với 24/40/60 pairs trên đúng phần cứng |
| `Qwen/Qwen3-Reranker-0.6B` | Ứng viên đối chứng | Apache-2.0; kiến trúc scoring và prompt template khác BGE; cần implementation tương ứng |
| Gemini 3.5 Flash Lite | Chỉ parse mơ hồ/fallback nếu cần | Gọi mạng gây tail latency; không rerank default |

**Tiêu chí quyết định**, theo ưu tiên: (1) không giảm gold nDCG@10 và entity hit@10 đáng kể; (2) p95 warm và concurrency đạt SLO; (3) ổn định/không 429; (4) VRAM và license; (5) chi phí vận hành. **Không chọn theo số tham số.**

**Các nguồn model để kiểm tra tại thời điểm cài đặt:**
- https://huggingface.co/BAAI/bge-reranker-v2-m3
- https://huggingface.co/Qwen/Qwen3-Reranker-0.6B
- https://huggingface.co/jinaai/jina-reranker-v2-base-multilingual
- https://huggingface.co/Qwen/Qwen3-Embedding-4B

### 6.3. Rerank ở cấp entity rồi mới chọn ảnh

Không nên đưa 24 ảnh có cùng metadata trong cùng entity vào cross-encoder và tiêu tốn compute để chấm 24 câu giống nhau. Xây một document **đại diện entity có provenance** (name + group ngắn + summary/desc chọn lọc), rerank 20–60 **entity candidates**. Với các truy vấn chú trọng thuộc tính hình ảnh, dùng mô tả từng ảnh để rerank image-level trong **các entity hàng đầu**.

Ví dụ dữ liệu: **908 entity có nhiều ảnh nhưng mọi ảnh cùng metadata**, gồm 5.010 ảnh. Rerank bằng text không giúp chọn ảnh nào đẹp hơn; bước image selection mới là nơi giải quyết.

### 6.4. Không dùng ngưỡng score 0,2 / `0,6*best` chưa hiệu chuẩn

Lỗi kế hoạch cũ:

```python
# KHÔNG dùng trực tiếp khi chưa calibrate:
keep = [x for x in items if x.score >= 0.60 * best_score]
```

Đây vẫn có thể làm top-10 thành top-3 và tỷ lệ score sigmoid không phải xác suất liên quan. V2 mặc định **rank + top_k sau filter hợp lệ**. Nếu cần cơ chế “trả rỗng khi không liên quan”, xây **query-specific rejector** dùng negative controls và human labels, tối ưu precision/false-positive rate; không đặt threshold tùy tiện.

### 6.5. Chia tài nguyên GPU/endpoint

Tài liệu hiện tại nhắc GPU RTX 4050 cho SigLIP2, còn Qwen embedding và Jina đi qua endpoint riêng sau LiteLLM/tunnel. **Không được mặc định** rằng toàn bộ Qwen3-Embedding-4B + BGE + SigLIP2 có thể đồng thời nằm trong GPU API host. Chỉ riêng Qwen 4B FP16 đã xấp xỉ 8GB weights (chưa tính activation/KV/batch/runtime), nên co-location có thể OOM trên GPU phổ thông.

**Thứ tự chọn deployment:**

1. Giữ Qwen endpoint như hiện tại; cho reranker chạy ở host có VRAM/CPU RAM phù hợp, đo thực.
2. Nếu tail 429/tunnel cao, cải thiện ổn định endpoint (domain ổn định, queue, bounded concurrency, timeout, retry budget, connection pooling), không nhất thiết phải chuyển tất cả về cùng GPU.
3. Chỉ colocate khi đo `nvidia-smi` (VRAM idle/peak), `torch.cuda.max_memory_allocated()`, p95 ở concurrency 1/4 và xác nhận không OOM.
4. Khi GPU không đủ, cân nhắc quantized runtime/ONNX/CPU reranker **sau benchmark**; không đưa ước tính ~200ms thành kết quả thật.

---

## 7. Image selection và visual retrieval — khoảng trống lớn nhất

### 7.1. Tách khái niệm “đúng entity” và “ảnh tốt”

Một truy vấn exact entity cần ít nhất hai điều kiện độc lập:

1. **Relevance:** ảnh đúng entity, đúng góc/nội dung truy vấn.
2. **Quality:** ảnh tải được, rõ, kích thước đạt yêu cầu, không watermark khó dùng, không trùng gần với ảnh đã chọn.

Mặc dù CSV 100% `approved`, điều này **không xác minh pixel**. `description` từng ảnh có ích nhưng có thể sai hoặc chưa mô tả đủ. Cần ghi chất lượng bằng pipeline Processing data (Phần A) hoặc human review; chỉ tin những field có provenance.

### 7.2. Sơ đồ dữ liệu quality (nullable)

```text
image_id
entity_id
fetch_status: pending|downloaded|failed|blocked|unknown
fetch_http_code: nullable
mime_type: nullable
width, height: nullable integers
orientation: landscape|portrait|square|unknown
verify: yes|no|unknown
verify_source: human|cv_model|none
verify_confidence: nullable float
has_watermark: true|false|unknown
sha256_bytes: nullable string
phash: nullable string
visual_model_id: nullable string
visual_vector_ready: bool
near_dup_cluster_id: nullable string
original_source_url, downloaded_at, content_bytes: nullable
```

**Không dùng `if c.get('width')` như cách duy nhất lọc** khi có `min_width`; `None` là chưa biết và cần chính sách rõ. Ví dụ `quality_policy=permissive` cho tìm kiếm thông thường; `strict` cho filter bắt buộc.

### 7.3. Giới hạn và điểm chất lượng phải theo mục đích

| Intent | Số ảnh/entity tối đa | Quy tắc |
|---|---|---|
| Exact single entity | **Tối đa `top_k`**, không cap 3 | Ưu tiên ảnh khác góc/khác nội dung |
| Descriptive single, không xác định entity | Cap mềm / diversity | Tránh một entity thống trị nếu truy vấn mang tính khám phá |
| Multi-intent A+B | Cap động sau phân slot | Đủ A/B **nếu có ảnh liên quan**, không ép ảnh rác |
| Set query | Ưu tiên **nhiều entity khác nhau** | `distinct_entity@k` là metric chính |
| Multi-hop | Entity target đã xác minh | Chọn ảnh target, không nới sang các entity cùng nhóm tùy tiện |

### 7.4. Dedup 3 mức, không lấy 0,97 làm quy tắc bất biến

**Level 1 — exact bytes:** SHA-256 ảnh đã tải về → exact duplicates (tối đa an toàn, nhưng ảnh resize/re-encode sẽ hash khác).  
**Level 2 — perceptual:** pHash/dHash để bắt resize/nén ảnh giống nhau; phải calibrate Hamming distance theo tập nhãn.  
**Level 3 — semantic visual:** SigLIP2/cosine hoặc feature khác để phát hiện crop/góc gần và tạo diversity; cần ngưỡng theo chính dataset (không áp `cosine≥0,97` vô điều kiện, vì có thể gộp ảnh khác chỉ giống chủ đề).

Lưu các duplicate cluster theo `entity_id` là mặc định; dedup xuyên entity cần cảnh báo vì một ảnh có thể liên quan tới nhiều entity hoặc do crawl gán sai.

### 7.5. SigLIP2 khi ảnh tải chưa đủ

**Bật từng phần:** tạo manifest cho từng image `visual_ready = true/false`, không chỉ một cờ `visual_index.json complete`. Có thể triển khai hybrid trên tập đã tải, nhưng **coverage báo rõ**; không để ảnh chưa tải bị xem là kém liên quan chỉ vì thiếu vector.

Hai tác vụ riêng:

- **text→image retrieval:** SigLIP2 text tower → image tower, hữu ích cho thuộc tính nhìn thấy được; cần benchmark trên truy vấn hình ảnh Việt/Anh.
- **image→image similarity:** near-dup/diversity trong kết quả, không thay thế nhãn entity đúng.

Hãy ưu tiên tải **ảnh của các entity trong goldset và top candidates thường gặp** trước để chứng minh hiệu quả, sau đó mở rộng độ phủ theo host với rate limiting, retry/backoff và file manifest resumable. Không khẳng định SigLIP2 “yếu với mọi truy vấn chi tiết” chỉ từ một issue; dataset task-specific mới quyết định.

### 7.6. MMR đúng thứ tự, đúng vector

**Sai trong kế hoạch cũ:** DAG đặt MMR **trước** rerank nhưng code MMR dùng `rerank_score` **sau** rerank; sẽ sai thứ tự dữ liệu hoặc thiếu khóa. Đồng thời dùng text embedding của metadata trùng không phân biệt các ảnh cùng entity.

**Đúng khi có visual vectors:** `entity rerank → image relevance/quality → visual dedup clusters → MMR/final diversity → top_k`.

\[
\operatorname{MMR}(i)=\lambda\,\widetilde{R}(i) - (1-\lambda)\max_{j\in S}\operatorname{sim}_{visual}(i,j)
\]

Trong đó `R` phải được **chuẩn hóa/cân theo query**, không cộng trực tiếp sigmoid text rerank và cosine pixel nếu hai thang không tương thích. `λ=0,7` là tham số khảo sát, thử `0,5/0,7/0,9`. Nếu thiếu vector cho một ảnh, thực thi **fallback chính sách minh bạch** (giữ item, hạn chế suy luận diversity), không giả sim=0 rồi cho ảnh đó lợi thế giả.

---
## 8. Multi-hop có bằng chứng (không ngụy tạo Knowledge Graph)

### 8.1. Định nghĩa rõ bài toán

**Entity lookup**: “Ảnh Lăng Tự Đức” → tra một entity.  
**Set / taxonomic traversal**: “Các lăng tẩm thuộc nhóm lăng tẩm hoàng triều” → `ENTITY → IN_CLASS → CATEGORY → HAS_MEMBER → ENTITY`. Đây là **duyệt phân loại**, có thể tính là graph traversal nhưng không chứng minh khả năng hỏi quan hệ nhân thân.  
**Multi-hop factual**: “Ảnh con trai của người sáng lập tổ chức X” → phải giải `X --founder--> P --child--> C`, kiểm tra C có trong catalog và ảnh có chứng cứ.

**Không được đánh tráo hai loại graph** trong bài báo cáo chỉ để ghi multi-hop đã hoạt động.

### 8.2. Relation schema đề xuất

```text
RelationEdge {
  subject_id: external_qid | local_entity_id
  predicate: CHILD | SPOUSE | FOUNDER_OF | CHAIRPERSON_OF |
             PARENT | LOCATED_IN | PART_OF | IN_CLASS | ...
  object_id: external_qid | local_entity_id
  predicate_direction: forward
  source_url: required
  source_type: wikidata | reliable_page | manual
  last_verified_at: timestamp
  confidence: float?  # score nội bộ, không thay fact provenance
  reviewed: bool
}
```

**Các quan hệ Wikidata phổ biến** (xem schema thực tế khi triển khai): `P40 = child`; `P26 = spouse`; `P22 = father`; `P25 = mother`; `P112 = founded by` (hướng tổ chức → người sáng lập); `P488 = chairperson` (tổ chức → người giữ chức). `P39 = position held` không tự đủ để biết “chủ tịch của công ty nào”. `FOUNDER_OF` nội bộ có thể là **cạnh đảo** của `P112`, phải xử lý hướng chứ không đưa `P112` từ người sang tổ chức. Nguồn: https://www.wikidata.org/wiki/Property:P40 ; https://www.wikidata.org/wiki/Property:P112 ; https://www.wikidata.org/wiki/Property:P488 .

### 8.3. Ví dụ “con trai của chủ tịch Phạm Nhật Vượng”

**Đọc ngữ nghĩa:** Trong câu này, “chủ tịch” có thể là **bổ ngữ chức danh của seed Phạm Nhật Vượng**, không nhất thiết là hop qua một tổ chức. Xử lý:

1. Extract `seed_person = "Phạm Nhật Vượng"`, `target_relation = CHILD`, `target_gender = male`, `title_hint = "chủ tịch"`.
2. Entity link tên seed sang Wikidata QID có bằng chứng (entity có thể **không nằm trong CSV**, thực tế lexical phrase không xuất hiện trong 80k metadata).
3. Duyệt hướng `seed --P40--> child`; tùy query dùng `P21`/nguồn đáng tin kiểm tra điều kiện “con trai” (không suy đoán giới tính khi thiếu dữ liệu).
4. Map các target QID có chứng cứ về `entity_id` qua QID đã liên kết hoặc alias + ngữ cảnh; **không lấy chuẩn hóa tên là đủ**.
5. Nếu target không có ảnh trong catalog: `target_not_in_catalog` (nêu rõ), không tự đưa ảnh người thân/người cùng nhóm.
6. Nếu không có quan hệ trong Wikidata: `relation_unverified` hoặc `no_evidence`, không suy luận phủ định “người đó không có con trai”.

### 8.4. Resolver thực dụng theo latency

**Chặng offline ưu tiên:** pre-link QID và các quan hệ thật được chọn trong goldset → lưu bảng `relations_v2` nội bộ.  
**Chặng online bổ sung:** `wbsearchentities` để lấy QID candidate + lấy statements có kiểm soát qua API; WDQS/SPARQL dùng có cache khi cần, không đưa vào critical path của mọi truy vấn.  
**Giới hạn online:** tổng ngân sách multi-hop được định nghĩa theo deadline request (ví dụ 500–800ms dành cho external, là **ngân sách mục tiêu** chứ không phải thời gian chắc chắn). Nếu hết ngân sách, trả kết quả local hoặc cảnh báo/tiếp tục thử tại request sau qua cache; không chờ `timeout=6s` nếu bắt buộc dưới 3s.

Resolver phải xử lý: redirects/aliases, QID disambiguation, thuộc tính thời gian (chủ tịch hiện tại/cựu), thiếu gender, property direction, nguồn xung đột, các quan hệ chỉ được xác nhận thủ công, entity target chưa có trong corpus, vòng lặp graph, max hop depth.

### 8.5. Không sử dụng `SIBLING_VIA` từ category cũ

Trong đoạn `build_kg.py` kế hoạch cũ:

```python
for a in ents:
    for b in ents:
        if a != b:
            con.execute(..., (a, "SIBLING_VIA", tok, ...))
```

Biến `b` **không được lưu** trong cạnh; nhiều dòng `(a, SIBLING_VIA, token)` lặp vô ích. Quan trọng hơn, cùng nằm trong dấu ngoặc category chỉ là **co-occurrence**, không phải sibling hay quan hệ gia đình. Nếu cần graph đồng nhóm, tạo `ENTITY -[IN_CLASS]-> GROUP`, sau đó duyệt `GROUP -[HAS_MEMBER]-> ENTITY`, có thể dùng hoàn toàn từ 11.294 mapping entity→category trong CSV. Nhãn cạnh phải là **cùng nhóm**, không phải “anh em”.

### 8.6. API trả provenance của chuỗi suy luận

```json
{
  "intent_type": "multi_hop",
  "resolution": {
    "status": "resolved|no_evidence|target_not_in_catalog|unsupported_relation",
    "seed": {"text": "<seed>", "qid": "<verified-QID-or-null>"},
    "steps": [
      {"predicate": "CHILD", "direction": "forward",
       "source": "wikidata-statement-or-curated-record", "target_qid": "<qid>"}
    ],
    "mapped_target_entity_ids": ["<local-id>"],
    "evidence_checked": true
  }
}
```

Không xuất `steps` bịa ra chỉ từ output của LLM. `steps` phải tái dựng được từ cạnh có nguồn. Đánh giá đúng **chuỗi quan hệ**, không chỉ kết quả ảnh tình cờ trùng.

---

## 9. Phương pháp đánh giá — sửa bộ 590 test case cho có giá trị khoa học

### 9.1. Không dùng nhãn từ CSV để chứng minh ảnh đúng pixel

Dataset chứa tên và mô tả, không có ground-truth quan hệ ảnh–thực thể do người gán trong lượt này. Những phép đo V1 như Hit@10, Recall@10 trên nhãn sinh từ catalog phải ghi là **silver/offline regression**. Nếu gold label chỉ dựa `entity_id` ban đầu, nó **không phát hiện ảnh được gán sai entity ngay từ lúc crawl**.

**Hai tập nhãn tách biệt:**

- **Silver:** từ cấu trúc CSV (`entity_id`, `category`, image_id, expected target`) để so regression và đo candidate coverage.
- **Gold:** người xem pixel và nhãn `relevance ∈ {0,1,2,3}`; kiểm chứng entity, đặc trưng hình ảnh, chất lượng và độ đa dạng. Với multi-hop, xác nhận factual relation riêng từ nguồn và match target với ảnh.

### 9.2. Phân bổ 590 truy vấn (đề xuất, chưa gán nhãn thực tế)

| Intent | Số query | Gold người dự kiến | Silver/cases còn lại | Kỹ thuật sinh và cân bằng |
|---|---:|---:|---:|---|
| Single | 200 | 100 | 100 | Sample entity theo bucket 1 / 2–3 / 4–9 / 10–19 / ≥20, phân tầng nhóm, có alias, bỏ dấu, mô tả |
| Multi-intent | 150 | 75 | 75 | Cặp cùng nhóm/cùng tỉnh/khác nhóm; 2–4 intent; có case top_k < số intent |
| Multi-hop | 120 | **120** | 0 | **Chỉ lấy quan hệ có nguồn được xác minh**, gồm cả case không tìm thấy target trong catalog; nếu không đủ 120 thì công khai giảm target |
| Set query | 60 | 0 ban đầu | 60 | Theo category/taxonomy và filter place; bổ sung human sample nếu thời gian đủ |
| Negative / ambiguous | 60 | 0 ban đầu | 60 | Không có lexical evidence, unknown target, tên collision, filter không thể thỏa |
| **Tổng** | **590** | **295** | **295** | **Đúng số học: 100+75+120 = 295 gold**, không phải 275 |

**Cảnh báo về negative test:** `"công viên nước"=0` trong text **không đủ chứng minh toàn bộ ảnh không có công viên nước**. Một negative gold phải được người kiểm tra/corroborate hoặc có tiêu chí quy định rõ (ví dụ entity_id không tồn tại, tên vô nghĩa và không có candidate liên quan sau kiểm tra). Không quy kết tập corpus thiếu một đối tượng chỉ từ grep.

**Khó khăn thực tế:** không được tự chế 120 factual-hop để vừa đủ con số. Nếu kiến thức ngoại bộ không có đủ 120 target được xác minh/coverage, có thể lập test split “hop supported” vs “hop unsupported” và báo tỷ lệ resolution đúng; mục tiêu 590 là kế hoạch, không phải nhãn gold đã có.

### 9.3. Chi tiết rubric gán nhãn ảnh

| Nhãn | Định nghĩa | Ví dụ |
|---|---|---|
| `0` | Sai entity, sai ý định hoặc ảnh không dùng được | Tên Chùa Một Cột nhưng pixel là chùa khác |
| `1` | Liên quan yếu / không rõ entity / chất lượng thấp | Cảnh rộng không nhận ra đối tượng, mô tả mơ hồ |
| `2` | Đúng entity/ý chính, chấp nhận được | Cảnh toàn / mặt tiền đúng |
| `3` | Đúng entity và ràng buộc chi tiết, chất lượng tốt | Góc cụ thể đúng, rõ, phù hợp định dạng |

Với **multi-intent**, annotator phải ghi `supported_subqueries[]` trên từng ảnh (A, B, cả hai, hay không cái nào). Với **multi-hop**, người gán nhãn relation (`fact_true`, `fact_false`, `not_verifiable`) **tách riêng** với việc ảnh đúng entity target.

Hai người gán độc lập trên tập giao nhau; tính agreement/κ thích hợp, người thứ ba xử lý bất đồng; báo rõ số lượng ảnh được gán, tỷ lệ mẫu giao nhau, công cụ và bias sampling. Không claim đã có Cohen's κ khi chưa thực hiện.

### 9.4. Định nghĩa chỉ số và bẫy Recall@10

| Tầng | Metric | Mô tả |
|---|---|---|
| Parser | Intent accuracy, subquery exactness, entity linking precision | Đo từng thành phần parsing |
| Candidate retrieval | **Candidate Entity Recall@M** | Entity đúng có trong pool trước rerank hay không |
| Entity ranking | Entity Hit@10, MRR, nDCG@10 | Không bị ảnh lặp làm đẹp điểm |
| Image ranking | Precision@10, nDCG@10, image Recall@10 **khi có danh sách ảnh liên quan đầy đủ** | Pixel relevance theo gold |
| Multi-intent | All-intents-covered@K, supported-result Precision@K, slot distribution, no-coverage accuracy | Không trộn “có A/B” và “tỷ lệ ảnh ngoài A/B” |
| Set query | DistinctEntity@K, group precision, place-filter precision | Đa dạng entity, không áp cap bừa |
| Multi-hop | Fact-chain accuracy, target entity Hit@K, unsupported precision | Đánh giá suy luận quan hệ |
| Visual selection | Duplicate@K, near-duplicate precision/recall, usable-image rate | Chống ảnh lặp và ảnh hỏng |
| Latency | p50/p95/p99/max, `%<1500ms`, `%<3000ms`, error/429 rate | Báo cùng với cache-state và concurrency |

**Ví dụ chuẩn:** một entity có 20 ảnh được xác nhận liên quan, hệ thống trả 10/10 ảnh liên quan ⇒ **image Recall@10 = 10/20 = 0,5**, còn **image Precision@10 = 1,0**. Vì vậy con số “Recall@10 = 0,996” trong V1 **cần kiểm tra lại công thức** (có thể đang đo đúng entity trong các ảnh top-10, hay goldset chỉ một mẫu). Không sao chép chỉ số có nhãn sai.

### 9.5. Phân tầng để ngăn benchmark đẹp giả

- Theo số ảnh/entity (5 bucket thật ở §1.2), không chỉ chọn entity có nhiều ảnh.
- Theo `description` (đầy đủ / một phần / hoàn toàn trống), vì 862 entity không có mô tả nào.
- Theo category dài (>120 ký tự) và ngắn.
- Theo tên trùng/collision (7 tên trùng xuyên ID + alias bỏ dấu).
- Theo khả năng tải ảnh (downloaded/pending/failed) khi có manifest.
- Theo truy vấn exact name vs descriptive vs modifier pixel; theo 1, 2, 3+ intent; theo multi-hop supported vs unsupported.
- Theo source-host/domain nếu muốn phát hiện thiên lệch chất lượng ảnh.

### 9.6. Ma trận A/B/ablation bắt buộc

| Experiment | Chỉ khác đúng một yếu tố | Tiêu chí quyết định |
|---|---|---|
| E0 | V1 production baseline | Lưu query IDs + candidate IDs + timings |
| E1 | Jina vs BGE vs Qwen reranker | Gold nDCG/Hit/Precision, p95/p99, VRAM, license |
| E2 | `metadata_text` gốc vs `text_core` | Candidate entity recall + set/multi precision; cùng reranker |
| E3 | Group SQL vs category dense index | Set coverage + latency + index size |
| E4 | Image-level rerank vs entity-first rerank | Entity Hit + output image precision + compute |
| E5 | Cap cứng 3 vs adaptive entity cap | Single exact top_k fill + set diversity + multi coverage |
| E6 | Visual dedup off/on, MMR λ=0,5/0,7/0,9 | Duplicate@K + relevance preservation |
| E7 | Rule only vs hybrid LLM conditional | Parser error, p95, overwrite regression |
| E8 | KG local vs online fallback | Chain accuracy + timeouts + target coverage |

**Không đổi đồng thời embedder, reranker, parse budget và candidate count trong một phép so**, nếu không không biết cải thiện đến từ đâu.

---

## 10. Benchmark latency và độ bền vận hành

### 10.1. Số V1 hiện có [PIPELINE—BÁO CÁO]

| Backend | Tổng p50/p95 | Điều kiện cần lưu ý |
|---|---:|---|
| Gemini | 2.658 / 3.058 ms | Có gọi/chờ LLM parser |
| Jina | 432 / 623 ms | Lượt so được ghi **rule-only** ở parser; không thuần so sánh một biến |
| Cache hit | Khoảng 2ms | Không đại diện latency truy vấn mới |

### 10.2. Thiết kế thí nghiệm latency đúng

1. Ghi rõ phần cứng **thực tế của máy chạy benchmark**, model deployment, GPU/VRAM, CPU, RAM, Qdrant version, endpoint/tunnel, Python/CUDA runtime; không dựa chỉ trên GPU nêu trong tài liệu nếu hạ tầng đã đổi.
2. Dùng một phiên bản index bất biến (`manifest hash`) và cùng bộ query ID; cố định parser mode, candidate limit, rerank pool, API retry policy.
3. **Cold:** truy vấn đầu tiên sau restart, báo riêng. **Warm uncached:** đã warm model, nhưng **search cache và rerank/parse cache** hoặc tắt theo cùng policy; đo chính. **Cache hit:** báo riêng không trộn.
4. Randomize query order, cân bằng truy vấn exact/descriptive/multi/hop; một vài truy vấn giống nhau lặp lại dễ ấm cache, cần tách thống kê; nếu muốn đo rerank model thuần, gọi trên cùng **frozen candidate lists**.
5. Concurrency 1 và 4; đo 429, timeout, OOM, percentiles theo từng intent. Thêm concurrency 8 nếu máy xử lý nổi.
6. Ghi **client elapsed** và server stage traces; network loopback có thể khác mốc >5ms khi có queue, serialization hoặc TLS, đừng hard-code “lệch 5ms là sai”.
7. Không cộng p95 của từng stage để suy ra p95 tổng; đo **end-to-end** từ raw individual requests vì percentiles không cộng tuyến tính và nhiều stage chạy song song.
8. Đo 1 ngày/ nhiều đợt nếu endpoint có biến động 429; ghi thời điểm, trạng thái Qdrant và tải GPU.

### 10.3. Budget chỉ là mục tiêu [ĐỀ XUẤT, CHƯA ĐO]

| Stage | Gợi ý budget p95 cho warm ordinary | Cách đạt |
|---|---:|---|
| Parse rule + selective LLM wait | 0–150ms | LLM ngoài critical path cho exact entity |
| Query embedding | 100–300ms | endpoint ổn định, queue/concurrency hợp lý |
| Retrieve/fusion entity | 100–300ms | Qdrant + FTS + RAM index, tối ưu SQL |
| Entity rerank | 200–500ms | batch 20–40 entity docs, model đo thật |
| Image expand/quality/diversity | 50–200ms | preload metadata, vector local, no live image download |
| Cache/serialize/overhead | 50–150ms | pool/SQLite, bounded work |

Các con số trên **không được trình bày là p95 thực nghiệm**. Tổng budget chỉ để phân bổ; warm p95 phải đo e2e. Multi-hop online có ngân sách độc lập và cần báo `%timeouts / %unsupported`.

### 10.4. Bảo mật và sự cố tải ảnh

Corpus có **6.437 image hosts**, nguồn phân tán. Nếu hệ thống download lại ảnh hoặc cho người dùng nhập image_url tự do, **chặn SSRF**: chỉ HTTP(S), resolve DNS và chặn private/loopback/link-local IP, giới hạn redirect/response size/timeout, kiểm tra MIME, sandbox decode, per-host rate-limit, retry-backoff; không follow image URL nguồn đáng ngờ trong luồng API sync. Bảo vệ dữ liệu API key; provenance không đồng nghĩa có giấy phép chia sẻ ảnh. Khi dùng Cloudflare quick tunnel, ghi rõ không có SLA production và độ trễ/rate limit phụ thuộc môi trường.

---
## 11. Danh sách sửa cụ thể theo module (Implementation Backlog)

> **Lưu ý:** đường dẫn module từ `retrieval-pipeline-current.md`. Các function/signature dưới đây là giao diện thiết kế; phải đọc code thật trước khi patch, không khẳng định chúng đã có.

| Ưu tiên | File/module | Thay đổi chính | Test bắt buộc (Definition of Done) |
|---|---|---|---|
| **P0** | `retrieval/rule_parser.py` | Confidence/intent invariants, name span, location, relation/title distinction | 104 regression names không thành multi-hop sai, set không bị override |
| **P0** | `retrieval/speculative.py` | LLM chỉ assist query ambiguous; giới hạn wait; cache parse theo policy | Same query lặp trả cùng intent; 150/600ms được đánh giá |
| **P0** | `retrieval/rerank.py` | Adapter `local_ce` hoặc API BGE/Qwen; batch, stable tie-break; bỏ cutoff cứng | Trả đủ `top_k` khi có đủ ảnh đạt filter; fallback đúng |
| **P0** | `storage/local.py` | Sửa key `has_watermark`; null-aware quality/filter; FTS name boost | `min_width`/orientation không bị silently ignored |
| **P0** | `retrieval/search.py` | Bump version cache; warnings & evidence; expose candidate stats | Không dùng cache index/rerank cũ |
| **P0** | `scripts/eval_quality.py` | Bổ sung metric phân tầng, định nghĩa Recall vs Precision; gold/silver | Xuất raw predictions + labels + metrics tái lập |
| **P0** | `scripts/eval_latency.py` (mới) | Cùng parser/candidate/cache, latency p50/95/99 | Có client+server timings và concurrency |
| **P0** | Ingestion/import | Thay 1 URL x-raw-image; xác nhận count end-to-end | SQLite/Qdrant có ≥80k IDs thật |
| **P1** | `retrieval/local_index.py` | Build `text_core`, group structured, manifest hash V2 | Distinct text handling, rollback V1 |
| **P1** | `retrieval/vector_store.py` | Collection `img_text_v2`, payload index, optional group vector | Exact 80k count và query self-test ANN |
| **P1** | `retrieval/catalog.py` | Group taxonomy, aliases, collision map (7 tên) | Name collisions không tự merge |
| **P1** | `retrieval/fusion.py` | RRF per-query, image→entity aggregation, adaptive quota | Không tăng entity score chỉ vì duplicate images |
| **P1** | `retrieval/local_search.py` | Điều phối entity-first/image-second; trace candidates; filter trước final | Single exact có thể trả >3 ảnh cùng entity |
| **P1** | `scripts/migrate_images_v2.py` | Nạp verify/size/watermark có provenance + UNKNOWN | Null vs false vs verified khác nhau |
| **P2** | `scripts/build_kg.py` | Build `IN_CLASS` đúng nghĩa và verified factual edges | Không có `SIBLING` tự dựng từ category |
| **P2** | `retrieval/hop.py` (mới) | Offline-first Wikidata QID linker, statement resolver, timeout/cache | Quan hệ đúng hướng, chain có evidence |
| **P2** | `retrieval/graph.py` | `resolve_hops` query verified edges | Unsupported/unknown có status trung thực |
| **P2** | `retrieval/embed.py` / encoder | SigLIP2 vector khi download ready; versioned visual manifest | Coverage rõ, vector dimension đúng, fallback |
| **P2** | `retrieval/fusion.py` (giai đoạn 2) | Near-dup clusters, optional visual MMR sau rerank | Duplicate@K giảm mà nDCG không tụt mạnh |
| **P2** | `api/routers/search.py` | Response evidence/coverage/timings, model metadata | Pydantic schema, backward compatibility |

### 11.1. Cấu hình V2 mẫu (không thay production trước khi benchmark)

```dotenv
# Các dòng này là đề xuất thêm/sửa; giữ secrets trong môi trường an toàn.
PIPELINE_VERSION=b3-entity-first-image-second
INDEX_VERSION=2

SEARCH_STRATEGY=entity_first_image_second
TEXT_FIELD_VARIANT=text_core
GROUP_RETRIEVAL_MODE=sql
EMBED_MODEL=qwen3-embedding-4b
EMBED_DIM=2560

RERANK_BACKEND=local_ce         # CHỈ khi host chạy nổi, không có thì api
RERANK_LOCAL_MODEL=BAAI/bge-reranker-v2-m3
RERANK_ENTITY_TOP_M=40        # giá trị thử nghiệm
RERANK_IMAGE_PER_ENTITY=5     # chỉ ảnh có desc riêng / visual relevance
RERANK_CUTOFF_MODE=none

LLM_PARSE_MODE=ambiguous_only
LLM_PARSE_BUDGET_MS=150       # tham số thử nghiệm, không phải đã tối ưu
LLM_PARSE_CAN_OVERRIDE_CONFIDENT_RULE=false

MAX_PER_ENTITY_EXACT=top_k
MAX_PER_ENTITY_SET=soft
MULTI_INTENT_ALLOCATOR=conditional_round_robin
VISUAL_RANKING=off            # bật khi có visual manifest thật
VISUAL_MMR_LAMBDA=0.7

REQUIRE_EXACT_INDEX_COUNT=80000
SEARCH_CACHE_VERSION=b3
```

Một số giá trị `top_k`, `soft`, `local_ce` là **biểu tượng chính sách**, phải được code parse đúng hoặc thay bằng số/hằng hợp lệ trong `.env` thực tế; **không copy nguyên khối và mong server tự hiểu**.

### 11.2. Unit & integration tests phải viết trước refactor lớn

```text
test_exact_name_returns_full_topk_if_enough_valid_images
  query exact 1 entity, top_k=10, entity có >=10 ảnh hợp lệ
  expected: 10 ảnh cùng entity, không cap xuống 3

test_collision_name_keeps_multiple_entities_until_disambiguated
  duplicate canonical name -> >1 entity_id
  expected: không merge nhầm PK; location/group hint phân giải đúng khi có chứng cứ

test_multi_intent_no_hallucinated_fill
  A có 6 ảnh hợp lệ, B không có
  expected: 6 từ A, warning B uncovered; không lấp top_k bằng C không liên quan

test_multi_intent_topk_below_subquery_count
  4 subqueries, top_k=3
  expected: không vượt 3 ảnh và báo coverage tối đa 3 ý

test_set_query_uses_entity_location_evidence
  category liệt kê nhiều tỉnh, entity thực ở tỉnh khác
  expected: không gán mọi tỉnh của category vào thực thể

test_multi_hop_property_direction
  org --P112--> founder và parent --P40--> child
  expected: hướng đảo được kiểm soát, không query ngược sai

test_multi_hop_no_external_evidence
  relation không tồn tại trong KG đã xác minh
  expected: no_evidence, không trả ảnh arbitrary same-group

test_visual_mmr_not_before_relevance
  visual vector có; rerank_score cấp ảnh đã có
  expected: MMR chạy sau rerank; text-only fallback không giả visual

test_missing_quality_is_unknown
  width=NULL, watermark=NULL, verify=NULL
  expected: null policy explicit, không đổi thành pass hoặc fail mặc định

test_cache_invalidated_by_index_alias_and_policy
  pipeline/index/re-ranker thay đổi
  expected: cache V1 không được reuse

test_indexed_image_count
  csv=80000 nhưng một URL sai schema
  expected: fail threshold nếu SQLite/Qdrant còn 79999
```

### 11.3. Telemetry tối thiểu để có khả năng debug

Một trace tương ứng một request, giữ trường `request_id`, `query_hash` (không log bí mật không cần thiết), `intent_type`, `parser_source`, `parse_confidence`, `subquery_count`, `candidate_per_source`, `candidate_entity_count`, `after_filter_count`, `entity_rerank_count`, `image_expand_count`, `visual_ready_count`, `near_dup_removed`, `final_count`, `subquery_coverage`, `warnings`, `stage_timings_ms`, `http_429`, `timeout`, `model_versions`, `index_manifest_sha`. Với đánh giá, có thể lưu toàn bộ candidate IDs vào JSONL tách biệt, tránh log payload lớn trong production.

---

## 12. Kế hoạch thực hiện có ưu tiên (tính đến 21/10/2026)

Kế hoạch cũ chia 6 ngày. Nếu deadline Capstone vẫn là **22/10/2026**, không nên tuyên bố có thể hoàn thành cả KG 120 gold hop, SigLIP2 80k ảnh và benchmark 590 ca chỉ trong một ngày. Dưới đây là kế hoạch **phân mức bắt buộc vs mở rộng**, không hứa kết quả chưa làm.

### Track A — Nghiệm thu phiên bản tối thiểu, ưu tiên trước deadline

| Thứ tự | Việc | Sản phẩm hữu hình | Điều kiện qua cổng |
|---|---|---|---|
| **A1** | Snapshot V1 + cố định baseline | manifest V1, 244 query IDs, raw latency files | Có rollback và nguồn so sánh |
| **A2** | Đạt 80k indexed thật | thay record URL lỗi + ingest/reindex | Counts SQLite/Qdrant, ID parity OK |
| **A3** | Chọn backend rerank nhanh | A/B Jina vs BGE (và Qwen nếu đủ nguồn lực) | Cùng parser, candidate list, latency + quality |
| **A4** | Sửa LLM override và cutoff top_k | parser guard + score policy | Test name/set + exact top_k |
| **A5** | Fix quality filter biết/không biết | migrate theo dữ liệu đã có, watermark key | API không silently ignore filter |
| **A6** | Multi-intent candidate separation + fair allocator | per-intent trace + slot relevance | Có đủ A/B khi có dữ liệu; giảm false positive trên test gán nhãn |
| **A7** | Multi-hop **pilot xác minh được** | số ca ít nhưng fact chain đúng, status khi không có dữ liệu | Chain có nguồn, không fake `SIBLING` |
| **A8** | Report thành thật | limitations, baseline, test method, SLA | Không dùng estimated metric như benchmark |

**Nếu không đủ thời gian:** ưu tiên A2, A3, A4, A6, A8; multi-hop có thể trình diễn tập con **đã xác minh**, nêu giới hạn. Không cắt bỏ kiểm chứng chỉ để có con số đẹp.

### Track B — Hoàn thiện hệ thống sau mốc nộp hoặc khi có thêm thời gian

| Workstream | Mục tiêu | Phụ thuộc |
|---|---|---|
| B1 `text_core` + group taxonomy | Ablation cho category leakage | E2/E3 |
| B2 entity-first pipeline | Cross-encoder chấm entity thay vì duplicate image text | E4 + goldset |
| B3 visual download/index | Visual coverage theo image_id, resumable | Phần A download & encoder |
| B4 visual dedup/ranking | pHash + SigLIP2 + MMR | B3 + ảnh gold |
| B5 KG robust | Verified facts + offline cache + QID mapping | Relation goldset |
| B6 590 queries | 295 gold case theo bảng + human image labels | B1–B5 tùy loại query |
| B7 performance tuning | p95/p99 under load, endpoint ổn định | Frozen architecture |

### 12.1. Stop/go cho từng thay đổi

- **Rerank model mới:** không đưa lên mặc định nếu chỉ tốt hơn p95 mà giảm rõ nDCG/image precision; cân nhắc Pareto frontier.
- **Tách category:** nếu candidate recall của query nhóm giảm đáng kể mà set-specific route chưa bù được, rollback hoặc dùng hybrid group lookup.
- **Entity-first:** nếu descriptive query mất ảnh đúng do entity candidate recall thấp, tăng pool/hybrid image-level trước khi rollout.
- **MMR:** nếu duplicate@10 giảm nhưng gold nDCG@10 giảm vượt tolerance đã định nghĩa trước, điều chỉnh λ/candidate set hoặc tắt.
- **Wikidata:** nếu online p99/timeout vượt SLO, chỉ phục vụ local verified KG trong critical path và báo unsupported.
- **Migrate quality:** nếu missing ratio quá cao, không tự động loại hết; hiển thị unknown coverage và tiếp tục thu thập.

---

## 13. Checklist nghiệm thu sản phẩm

### Dữ liệu / index

- [ ] CSV hợp lệ; SQLite ≥80.000 ảnh **thực sự query được**; Qdrant count khớp; ID parity, không orphan.
- [ ] Đã log rõ 1 `x-raw-image://` và cách giải quyết; `sha256` chỉ điền khi thật sự tải bytes.
- [ ] Bản V1 còn rollback; manifest gắn hash CSV/model/normalizer/cache version.
- [ ] 7 tên collision được xử lý theo `entity_id`; không merge chỉ vì giống tên.
- [ ] Description trống 16.110 bản ghi không bị vô tình coi `verify=no`.

### Retrieval / relevance

- [ ] Single exact query có thể trả `top_k` ảnh cùng entity nếu đủ ảnh đạt filter.
- [ ] Set query đưa nhiều entity và dùng provenance địa điểm; không lấy mọi tỉnh trong category làm location.
- [ ] Multi-intent đo cả coverage lẫn precision; không ép quota bằng candidate ngoài A/B.
- [ ] Multi-hop chain factual có nguồn; phân biệt unknown/uncovered với false; không tạo SIBLING giả.
- [ ] Trước rerank có candidate entity recall báo riêng; sau rerank có gold nDCG@10 và P@10.
- [ ] Không claim pixel retrieval nếu SigLIP2 chưa indexed; visual coverage % có số liệu thật.

### Vận hành

- [ ] Reranker model chính được chốt qua A/B cùng điều kiện; license rõ.
- [ ] p50/p95/p99 theo single, multi-intent, set, multi-hop, cache cold/warm/uncached riêng.
- [ ] Báo `%<1500ms`, `%<3000ms`, max, HTTP 429, timeout và concurrency.
- [ ] Filter `min_width` / `orientation` có ngữ nghĩa `unknown`; `has_watermark` đúng key.
- [ ] Graceful degradation có warning + provenance; cache không lẫn các phiên bản.
- [ ] Chống SSRF khi tải URL ảnh, per-host rate-limit, model inference concurrency guard.

### Báo cáo / khoa học

- [ ] Công thức metric được định nghĩa và implementation được audit; Recall không nhầm Precision.
- [ ] Silver và Gold tách biệt; gold cần **người xem ảnh**, không lấy nhãn `approved` làm gold.
- [ ] 590 test cases là **kế hoạch**, nếu chưa đủ phải ghi số đã thực hiện; 295 gold theo phân bổ tại §9.2.
- [ ] Có thí nghiệm ablation tách biến, raw result IDs, hardware/environment và những giới hạn còn lại.

---

## 14. Phụ lục A — Audit CSV có thể tái lập (Python standard library)

Đoạn script dưới đây **đọc dữ liệu gốc 80k**, không thay đổi file; chạy với Python 3.10+:

```python
import csv
from collections import Counter, defaultdict
from urllib.parse import urlsplit
from pathlib import Path

path = Path("data/data_anh_pass_80000_full_pham_van_vuong.csv")
with path.open(encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))

entities = defaultdict(list)
name_to_ids = defaultdict(set)
metadata_to_ids = defaultdict(set)
metadata_freq = Counter()
categories = Counter()
urls = Counter()
invalid_urls = []
for line, r in enumerate(rows, start=2):
    eid = r["entity_id"]
    entities[eid].append(r)
    name_to_ids[r["canonical_name"]].add(eid)
    meta = (r["canonical_name"], r["category"], r["description"])
    metadata_to_ids[meta].add(eid)
    metadata_freq[meta] += 1
    categories[r["category"]] += 1
    url = r["image_url"].strip()
    urls[url] += 1
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        invalid_urls.append((line, url))

collisions = {k: v for k, v in name_to_ids.items() if len(v) > 1}
all_missing_desc = sum(
    all(not r["description"].strip() for r in group)
    for group in entities.values()
)
multimage_all_metadata_identical = [
    group for group in entities.values()
    if len(group) > 1
    and len({(r["canonical_name"],r["category"],r["description"])
             for r in group}) == 1
]

print("rows", len(rows))
print("entities", len(entities), "names", len(name_to_ids))
print("colliding unique names", len(collisions))
print("excess entity/name assignments", sum(len(v)-1 for v in collisions.values()))
print("unique categories", len(categories))
print("unique image URLs", len(urls))
print("invalid image URLs", invalid_urls)
print("empty SHA-256", sum(not r["sha256"].strip() for r in rows))
print("empty descriptions", sum(not r["description"].strip() for r in rows))
print("entities all descriptions empty", all_missing_desc)
print("unique metadata", len(metadata_freq))
print("repeated metadata extra rows", sum(n-1 for n in metadata_freq.values()))
print("metadata groups across entity IDs", sum(len(s)>1 for s in metadata_to_ids.values()))
print("entities with >=2 images but identical metadata",
      len(multimage_all_metadata_identical))
```

**Kỳ vọng kết quả trên bản CSV đính kèm (đã chạy audit trong phiên tạo tài liệu):** 80.000 rows, 11.294 entities, 11.281 names, 7 colliding names, 13 excess assignments, 669 categories, 80.000 URL riêng biệt, 1 invalid HTTP URL, 80.000 SHA-256 trống, 16.110 mô tả trống, 862 entity hoàn toàn trống mô tả, 66.937 metadata duy nhất, 13.063 lượt trùng bổ sung, 0 metadata groups xuyên entity, 908 entity nhiều ảnh có metadata đồng nhất.

**Để tái lập đầy đủ** các phép đếm từ khóa bỏ dấu, category >120, host và distribution, dùng quy tắc `utf-8-sig`, `csv.DictReader`, `unicodedata.normalize('NFKD')` + chuyển `đ→d` và **phân biệt rõ substring với whole-word/token match**; nguồn mẫu có tiếng Việt và một số text không chuẩn.

---

## 15. Phụ lục B — Các nguồn kỹ thuật & bằng chứng

### Tài liệu nội bộ được người dùng cung cấp

1. `retrieval-pipeline-current.md`: mô tả code đang chạy, cấu hình, 79.999 indexed, Qwen3, Qdrant, parse Gemini, rerank Gemini/Jina và số benchmark ngày 21/10/2026.
2. `phan-b-ke-hoach-hoan-thien-pipeline-retrieval.md`: kế hoạch sửa trước đây; các giả định sai/cần chứng minh đã được nêu rõ trong file này.
3. `data_anh_pass_80000_full_pham_van_vuong(1).csv`: **nguồn duy nhất** cho tất cả số liệu gắn [CSV—ĐO]. Không hề tải pixel 80.000 ảnh để xác minh nội dung thực.

### Tài liệu công khai tham khảo (kiểm tra lại khi dùng model/API)

- BGE reranker v2 m3 / license: https://huggingface.co/BAAI/bge-reranker-v2-m3
- Qwen3 Reranker 0.6B / license: https://huggingface.co/Qwen/Qwen3-Reranker-0.6B
- Jina reranker v2 multilingual / giới hạn non-commercial: https://huggingface.co/jinaai/jina-reranker-v2-base-multilingual
- Qwen3 Embedding 4B / MRL và dimension: https://huggingface.co/Qwen/Qwen3-Embedding-4B
- SigLIP2 encoder: https://huggingface.co/google/siglip2-base-patch16-256
- Qdrant HNSW / payload filters: https://qdrant.tech/documentation/
- Wikidata property P40 `child`: https://www.wikidata.org/wiki/Property:P40
- Wikidata property P112 `founded by`: https://www.wikidata.org/wiki/Property:P112
- Wikidata property P488 `chairperson`: https://www.wikidata.org/wiki/Property:P488

### Chốt lại

**Không có một “model thần kỳ” sửa được CSV chỉ có text metadata.** Với dữ liệu thực tế này, thứ tự giá trị cao nhất là: **(1) kết quả entity đúng và nhất quán → (2) image selection có quality/pixel khi có → (3) multi-intent coverage thật → (4) multi-hop có chứng cứ → (5) tối ưu latency có benchmark chuẩn.**

> **Bản thiết kế này là phương án đề xuất có kiểm chứng thống kê; chưa phải kết quả implementation.** Nếu được triển khai đúng, điểm khác biệt rõ nhất với kế hoạch cũ là không dùng cap cứng và MMR sai thứ tự, không nhân bản group vectors chưa cần thiết, không ngụy tạo quan hệ graph, và không nhầm các chỉ số dựa metadata với chất lượng ảnh thực tế.
