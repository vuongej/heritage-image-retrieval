# Kế hoạch sửa chi tiết — Phần B (Truy xuất ảnh)

> Tài liệu này là **đặc tả thi công** cho Claude Code, dựa trên báo cáo
> `retrieval-painpoints.md` (review 2026-10-20, chạy `pham_van_vuong`).
> Mỗi mục nêu: file cần sửa, thay đổi cụ thể, mã tham khảo, tiêu chí nghiệm thu.
> Làm theo thứ tự phase 1 → 4. Không được tự đổi thiết kế khi chưa bàn.

## Thông số đã kiểm chứng (dùng cho cấu hình)

- Model LLM trên OpenRouter: `google/gemini-3.5-flash-lite`
  — $0.30/M input, $2.50/M output, context 1M, nhận ảnh + text,
  ~350 token/s. Biến thể batch `google/gemini-3.5-flash-lite:batch`
  giảm 50% ($0.15 in / $1.25 out) — **dùng cho job offline** (caption).
- Backup rẻ hơn cho parse nếu cần: `google/gemini-2.5-flash-lite`
  ($0.10 in / $0.40 out).
- Index mục tiêu: **80.000 ảnh** (SLO ghi), hiện 35.252 ảnh / 4.481 thực thể.
- SLO: p95 ≤ 1.500 ms. Hiện p50 2.483 / p95 2.825 / max 8.996 ms.
- Embedding: MiniLM `paraphrase-multilingual-MiniLM-L12-v2` 384d (giữ),
  SigLIP2 1152d (bổ sung — vector ảnh đã có ở `data/verify/emb.npz` từ Phần A).
- Cross-encoder: `BAAI/bge-reranker-v2-m3` (thiết kế gốc trong `config/models.yaml`).

## Quy ước chung

1. Mọi thay đổi schema/định dạng cache phải có `index_version` và
   `pipeline_version`; cache key của `/v1/search` thêm 2 trường này.
2. Không gọi LLM đồng bộ trên đường xử lý chính của `/v1/search` —
   mọi call LLM online đều qua wrapper có timeout và fallback.
3. Viết test cho từng phase; test hồi quy của Phase 1 phải pass 100%
   trước khi merge phase sau.
4. Giữ nguyên đường gọi hiện tại: `POST /v1/search` →
   `retrieval.search.search` → `retrieval.local_search.run`.

---

# PHASE 1 — Parse đúng + hết chờ LLM trên đường nóng

Giải quyết: điểm yếu #1 (SLO) và #2 (rule parser xếp nhầm).

## 1.1 Sửa `retrieval/rule_parser.py` — entity-first parsing

**Vấn đề hiện tại**: parser xét marker quan hệ (`của`, `con`, `wife`,
`chồng`…) trước khi nhận diện tên thực thể, nên các tên CHỨA marker
bên trong ("Hòn Chồng", "Tượng đài Mẹ Việt Nam Anh hùng",
"Lăng Chủ tịch Hồ Chí Minh") bị xếp `multi_hop` → search trả rỗng.
104/4.481 tên (2,3%) bị vậy; 973 tên (21,7%) không được xếp `single`.

**Thay đổi** — viết lại hàm `parse()` theo trình tự:

```python
import unicodedata
import re

PROVINCES = load_provinces()  # whitelist 63 tỉnh/thành VN, không dấu, lowercase

def normalize(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s.lower()).strip()

def parse(query: str, catalog) -> Intent:
    q_norm = normalize(query)

    # BƯỚC 1: tìm span tên thực thể TRƯỚC, longest-match-first, n-gram <= 6 token
    spans = catalog.match_entity_spans(q_norm)  # xem 1.2 — cần cài hàm này
    # che span: "hòn chồng nha trang" -> "⟦E⟧ nha trang" (nếu "Hòn Chồng" là entity)
    protected = mask_spans(q_norm, spans)

    # BƯỚC 2: marker chỉ xét trên phần ĐÃ CHE
    if HOP_RE.search(protected):
        # chỉ nhận multi_hop khi marker nằm NGOÀI span đã che
        return Intent(type="multi_hop", entities=spans, hop_chain=None)

    # BƯỚC 3: modifier địa danh đứng sau dấu phẩy KHÔNG tạo sub-query mới
    # "chùa một cột, hà nội" -> sub-query ["chùa một cột hà nội"], KHÔNG tách 2
    parts = split_on_commas(query)
    sub_queries = []
    for p in parts:
        tail = normalize(last_token(p))
        if tail in PROVINCES and sub_queries:
            sub_queries[-1] = sub_queries[-1] + " " + p  # gộp vào ý trước
        else:
            sub_queries.append(p)

    if len(sub_queries) > 1:
        return Intent(type="multi_intent", entities=spans, sub_queries=sub_queries)

    # BƯỚC 4: set-query marker ("các", "những", "tất cả" + danh từ chỉ loại)
    if SET_RE.search(protected):
        return Intent(type="set_query", entities=spans)

    return Intent(type="single", entities=spans)
```

Regex gợi ý (điều chỉnh theo file hiện có):

- `HOP_RE = r"\b(con|cha|me|mẹ|vợ|chồng|của|wife|husband|child|son|daughter|chairman|chủ tịch)\b"`
  — nhưng CHỈ áp lên `protected` (đã che entity), không áp lên query thô.
- `SET_RE = r"\b(các|những|tất cả|mọi)\s+\S+"`

**Bắt buộc**: thêm `tests/test_rule_parser_regression.py` chứa **đúng 104**
tên đang bị xếp nhầm `multi_hop` (trích từ phép kiểm tra catalog trong
báo cáo — lưu danh sách này vào `tests/fixtures/misclassified_entities.csv`)
và ~20 ca multi_intent chứa tỉnh/thành sau dấu phẩy. Kỳ vọng:

- 104/104 ca cũ xếp `multi_hop` giờ phải ra `single` (hoặc đúng loại thật
  nếu tên entity thật sự tham chiếu quan hệ — case-by-case ghi trong CSV).
- "Chùa Một Cột, Hà Nội" → `single` (không tách).
- "hồ bơi và công viên nước ở Phú Quốc" → `multi_intent`, 2 sub-query,
  "Phú Quốc" là modifier của CẢ HAI sub-query.

## 1.2 Bổ sung `catalog.match_entity_spans()` (file `retrieval/catalog.py` hoặc nơi quản lý entity)

- Nạp toàn bộ 4.481 tên thực thể + alias vào Aho-Corasick hoặc dict n-gram
  (4.481 tên là ít — dict n-gram đủ nhanh, build 1 lần lúc start, giữ trong RAM).
- Chuẩn hóa 2 phía (bỏ dấu, lowercase) trước khi so khớp.
- Trả về list span `(start, end, entity_id, matched_text)`, longest-match-first,
  không chồng lấn (ưu tiên span dài hơn).
- Đo và ghi log thời gian build + lookup (kỳ vọng lookup < 1 ms cho query
  < 20 token).

## 1.3 Nối `retrieval/speculative.py` vào `/v1/search`

**Vấn đề hiện tại**: `speculative.py` đã có (rule-parse + retrieve trước,
LLM song song, timeout 600 ms) nhưng `/v1/search` vẫn chạy parse DeepSeek
ĐỒNG BỘ tại `retrieval/local_search.py:55-62`.

**Thay đổi** trong `retrieval/local_search.py`:

```python
# local_search.run() — khung mới
async def run(query: str, top_k: int, filters: dict) -> Result:
    intent = rule_parser.parse(query, catalog)          # BƯỚC 1: rule, ~1-5 ms
    result = retrieve_by_intent(intent, top_k, filters) # BƯỚC 2: retrieve NGAY, không chờ LLM

    llm_task = asyncio.create_task(
        llm_router.parse(query, candidates=catalog.suggest(query)[:20])
    )                                                    # BƯỚC 3: LLM song song
    try:
        llm_intent = await asyncio.wait_for(llm_task, timeout=0.6)
    except (asyncio.TimeoutError, LLMError):
        llm_intent = None                                # fallback: giữ kết quả rule

    if llm_intent and llm_intent.type != intent.type:
        # chỉ re-retrieve khi LOẠI intent khác; nếu chỉ khác sub-query thì merge
        result = merge_results(result, retrieve_by_intent(llm_intent, top_k, filters))
    return result
```

- Xóa hẳn call DeepSeek đồng bộ tại `local_search.py:55-62` (parse) và
  `:158-162` (rerank — xử lý ở Phase 3).
- Cache key thêm `pipeline_version`; khi intent của LLM khác rule và được
  dùng, cache lưu intent nào đã sinh kết quả.

## 1.4 Tạo mới `retrieval/llm_router.py` — call Gemini 3.5 Flash Lite qua OpenRouter

```python
import os, json, httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL_ONLINE = "google/gemini-3.5-flash-lite"       # online: $0.30/$2.50
MODEL_BATCH  = "google/gemini-3.5-flash-lite:batch" # offline: $0.15/$1.25

SCHEMA = {
    "type": "object",
    "properties": {
        "intent_type": {"enum": ["single", "multi_intent", "multi_hop", "set_query"]},
        "entities": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": {"type": "string"},
                           "type": {"enum": ["poi", "person", "org", "place"]}},
            "required": ["name", "type"]}},
        "sub_queries": {"type": "array", "items": {"type": "string"}},
        "hop_chain": {"type": "array", "items": {
            "type": "object",
            "properties": {"subject": {"type": "string"},
                           "relation": {"enum": ["child_of", "spouse_of",
                                                  "chairman_of", "located_in",
                                                  "parent_of", "sibling_of"]},
                           "object": {"type": "string"}},
            "required": ["subject", "relation", "object"]}},
        "modifiers": {"type": "object", "properties": {
            "place": {"type": "string"}, "time": {"type": "string"},
            "style": {"type": "string"}}},
    },
    "required": ["intent_type", "entities"],
}

SYSTEM_PROMPT = (
    "Bạn là bộ phân tích truy vấn tìm ảnh du lịch Việt Nam. Chỉ trả JSON đúng schema. "
    "Tên riêng địa danh/người PHẢI khớp danh sách ứng viên thực thể nếu được cung cấp. "
    "KHÔNG tách ý định khi cụm từ sau dấu phẩy là tên tỉnh/thành. "
    " Với câu hỏi quan hệ người (con/vợ/chồng/chủ tịch), sinh hop_chain với "
    "relation chuẩn; object '?' nghĩa là thứ cần tìm."
)

async def parse(query: str, candidates: list[str]) -> dict:
    payload = {
        "model": MODEL_ONLINE,
        "response_format": {"type": "json_schema",
                             "json_schema": {"strict": True, "schema": SCHEMA}},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",
             "content": f"Query: {query}\nỨng viên thực thể: {candidates}"},
        ],
        "max_tokens": 300,
        "temperature": 0,
    }
    headers = {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
               "HTTP-Referer": "https://yourapp.example"}
    async with httpx.AsyncClient(timeout=6.0) as c:
        r = await c.post(OPENROUTER_URL, json=payload, headers=headers)
        r.raise_for_status()
        return json.loads(r.json()["choices"][0]["message"]["content"])
```

Ghi chú thi công:

- `OPENROUTER_API_KEY` đọc từ env, không hardcode.
- Ghi log: latency, token dùng, tỉ lệ LLM ghi đè rule, tỉ lệ timeout —
  phục vụ báo cáo chi phí ($/query ≈ 400 in + 120 out token ≈ $0.00042).
- Khi LLM lỗi/trượt timeout → LUÔN fallback kết quả rule, không raise.

## 1.5 Tiêu chí nghiệm thu Phase 1

- [ ] `pytest tests/test_rule_parser_regression.py` — 104/104 pass.
- [ ] Benchmark lại trên bộ query smoke: p95 ≤ 1.500 ms (chưa tính Phase 3
      rerank — nếu chưa đạt vì rerank vẫn là DeepSeek thì ghi rõ số đo
      parse-only: thời gian parse giảm từ ~1.091 ms về < 10 ms).
- [ ] 0 ca trả rỗng trên 104 ca hồi quy.
- [ ] Log hiện: tỉ lệ dùng kết quả LLM vs rule, số lần timeout.

---

# PHASE 2 — Index: nạp verify + kích thước ảnh, SigLIP2, caption thiếu mô tả

Giải quyết: #3 (vector trùng / thiếu mô tả), #4 (verify không nạp),
#8 (filter vô hiệu), nền cho #10.

## 2.1 Migrate schema bảng `images` (SQLite)

```sql
ALTER TABLE images ADD COLUMN verify TEXT;         -- 'yes' | 'no' | NULL
ALTER TABLE images ADD COLUMN width INTEGER;
ALTER TABLE images ADD COLUMN height INTEGER;
ALTER TABLE images ADD COLUMN has_watermark INTEGER; -- 0/1
```

Script migrate một lần `scripts/migrate_images_v2.py`:

- Nạp cột `verify` từ `reports/verify/*_verified.csv` (khớp theo
  image_id/path — kiểm tra 100% dòng match, báo cáo dòng không khớp).
- `width/height`: probe bằng Pillow — chỉ đọc header (`Image.open` +
  `.size` rồi đóng, không decode). Chạy batch, ghi tiến độ vào log.
  Nếu record crawl đã có width/height trong `record_json` thì ưu tiên
  dùng, chỉ probe cái thiếu.
- `has_watermark`: lấy từ kết quả verify của Phần A nếu cột có; nếu
  không có thì để NULL (penalty sẽ bỏ qua).

## 2.2 Caption ảnh thiếu mô tả (offline, batch)

- Đếm số ảnh `metadata_text` rỗng (báo cáo: 16.110/80k).
- Script `scripts/caption_missing.py`:
  - Gom nhóm 10 ảnh/request, gửi thumbnail 256px + prompt:
    "Mô tả 1–2 câu tiếng Việt: đối tượng chính, địa điểm (nếu biết),
    đặc điểm thị giác (màu mái, thời điểm trong ngày, góc chụp,
    cảnh quan xung quanh). Không suy đoán tên người cụ thể."
  - Model `google/gemini-3.5-flash-lite:batch` (giá nửa).
  - Ước tính chi phí: ~350 output token/ảnh → 16.110 ảnh ≈ 5,6M token
    output ≈ **$7 một lần**. Ghi thực tế chạy vào báo cáo.
  - Retry 3 lần, ghi request thất bại vào file lỗi để chạy lại.
- Caption ghi vào `metadata_text` (nối thêm, KHÔNG xóa dữ liệu cũ),
  đánh dấu nguồn `caption_source='gemini3.5fl'`.

## 2.3 Hai collection Qdrant (thay brute-force `vectors.npy`)

- Chạy Qdrant local (docker-compose có sẵn hoặc cài mới).
- Collection `img_text`: 384d, cosine — vector MiniLM của `metadata_text`
  (re-embed TOÀN BỘ 80k, vì nhiều dòng thiếu mô tả giờ đã có caption).
- Collection `img_visual`: 1152d, cosine — SigLIP2 từ `data/verify/emb.npz`
  của Phần A; ảnh nào chưa có vector → embed bổ sung bằng chính pipeline
  SigLIP2 của Phần A (không viết encoder mới).
- HNSW: `m=16, ef_construct=128`, search `ef=128` (đo và tune sau).
- Khi query: embed text bằng CẢ MiniLM và SigLIP2 text-tower, query 2
  collection song song (`asyncio.gather`).

## 2.4 FTS5 chuẩn hóa

- Thêm cột `metadata_text_ascii` (bỏ dấu) để FTS5 match "chua mot cot" ≈
  "Chùa Một Cột".
- Tokenize bỏ stopword tiếng Việt (danh sách ~100 từ phổ thông).
- Thay logic nối từ bằng OR hiện tại: dùng câu truy vấn BM25 chuẩn
  (các term AND ưu tiên, OR fallback) — đo Recall trên goldset Phase 4.

## 2.5 Tiêu chí nghiệm thu Phase 2

- [ ] 100% dòng trong `images` có `verify` và `width/height` (hoặc NULL
      có ghi lý do trong báo cáo migrate).
- [ ] Số ảnh không mô tả = 0 sau caption.
- [ ] Qdrant: 80k vector × 2 collection, recall của self-test ANN
      (query chính vector của ảnh đó) ≥ 0.99 @ top-10.
- [ ] Filter `min_width`, `orientation` chạy được trên query thật.

---

# PHASE 3 — Rerank local + multi-hop + set query

Giải quyết: #5 (rerank), #6 (multi-hop), #7 (set query).

## 3.1 Thay rerank DeepSeek bằng cross-encoder

- `retrieval/rerank.py` (mới): `BAAI/bge-reranker-v2-m3` qua
  `sentence-transformers` CrossEncoder, hoặc ONNX int8 nếu cần CPU.
- Input pair: `(sub_query, caption + entity_name + group_name + mô tả)`.
- Rerank top-100 sau fusion → chọn top_k; ngưỡng giữ 0.2 (tune sau trên
  goldset).
- `apply_quality_penalty` sửa: đọc cột thật từ Phase 2 —
  `verify='no'` −0.15, `has_watermark=1` −0.10, `width<640` −0.05
  (hằng số đặt trong `config/models.yaml`, không hardcode).
- Xóa hẳn call DeepSeek rerank tại `local_search.py:158-162`; fallback
  cosine MiniLM chỉ giữ khi model file chưa tải.

## 3.2 Cài `graph.resolve_hops()` (thay NotImplementedError)

File `retrieval/multi_hop.py` (mới):

```python
async def resolve_hops(query: str, llm_parse: dict, graph, kb) -> list[str]:
    # llm_parse["hop_chain"] do LLM sinh ở Phase 1
    # B1: node đầu = entity trong catalog (fuzzy match)
    # B2: mỗi cạnh relation tra theo thứ tự:
    #     a) đồ thị nội bộ (cạnh SPOUSE_OF / CHILD_OF / CHAIRMAN_OF / LOCATED_IN)
    #     b) Wikidata SPARQL (endpoint miễn phí, timeout 2s, cache kết quả
    #        vào bảng kb_cache để không query lại)
    # B3: node cuối = entity đích -> trả entity_id để retrieve
    # Không resolve được node nào -> trả [] + reason, KHÔNG trả rỗng im lặng
```

- Cạnh đồ thị nội bộ: thêm vào pipeline index (Phase 2) các cạnh
  `SPOUSE_OF`, `CHILD_OF`, `CHAIRMAN_OF`, `LOCATED_IN` — nguồn: metadata
  crawl + Wikidata dump của entity người/tổ chức trong catalog.
- **Giới hạn bắt buộc (không được vi phạm)**: KHÔNG dùng nhận diện
  khuôn mặt để xác định danh tính người trong ảnh. Truy vấn về người
  chỉ được suy luận qua quan hệ trong KB (Wikidata/metadata công khai)
  và khớp tên thực thể; ảnh về người chỉ trả khi metadata công khai đã
  gắn nhãn. Cá nhân tư không có trên KB → trả kết quả suy giảm + giải
  thích (facet chip ghi "không xác nhận được danh tính"), không đoán.
  Lý do: chính sách nhà cung cấp model cấm nhận dạng cá nhân từ khuôn
  mặt; Nghị định 13/2023/NĐ-CP (VN) và GDPR (EU) về dữ liệu cá nhân.
- Đo "hop-accuracy" (tỉ lệ resolve đúng entity đích) trên goldset Phase 4.

## 3.3 Set query qua đồ thị

- `local_search.run` nhánh `set_query`: gọi `graph.siblings_of(class)` /
  `parents_of(class)`.
- Retrieval: multi-vector — centroid vector của class + vector từng
  entity con; fuse RRF; MMR ưu tiên đa dạng entity (max 2 ảnh/entity
  trước khi lấp chỗ trống).
- Mục tiêu: class precision 0.8 → ≥ 0.95 trên goldset.

## 3.4 Tiêu chí nghiệm thu Phase 3

- [ ] Rerank 100 cặp ≤ 200 ms CPU (không GPU), không call LLM.
- [ ] "ảnh con trai chủ tịch Phạm Nhật Vượng" trả kết quả (không rỗng,
      không cảnh báo NotImplemented).
- [ ] Recall@10 ca tên trùng (Vạn Thủy Tú) từ 0.8 → ≥ 0.9.

---

# PHASE 4 — Fusion hoàn thiện, dedup, goldset, đo trên 80k

Giải quyết: #9 (đánh giá), #10 (dedup), hoàn thiện #3.

## 4.1 Dedup bằng cosine SigLIP2 (KHÔNG pHash)

- Phần A đã chứng minh pHash vô dụng (AUC 0.522 trên 18.445 cặp) —
  KHÔNG cài pHash.
- `fusion.dedup_by_phash` đổi tên `dedup_by_visual`: greedy trên thứ tự
  điểm sau rerank, 2 ảnh cosine SigLIP2 ≥ 0.92 → cụm, giữ ảnh điểm cao.
- Ngưỡng 0.92 là placeholder: calibrate trên bộ cặp trùng đã gán nhãn
  của Phần A, chọn ngưỡng đạt precision ≥ 0.95 trên cặp truly-duplicate.
- Sau dedup: MMR λ=0.7 để đa dạng thực thể (không cho 1 entity chiếm
  >30% top_k).

## 4.2 Goldset 3 tầng (bắt buộc làm TRƯỚC khi tune thêm)

File `eval/goldset/*.jsonl`, schema mỗi dòng:
`{"qid", "query", "type", "gold_entity_ids" | "gold_image_ids", "notes"}`.

| Loại | Số ca | Cách sinh |
|---|---|---|
| Single — tên | 100 | lấy mẫu catalog; BAO GỒM 104 ca từng lỗi parse (chọn 100 trong số đó nếu thiếu) |
| Single — mô tả | 100 | template thị giác ("mái ngói đỏ", "chụp ban đêm", "ven biển có đá đen") × entity; gán nhãn tay relevant/irrelevant trên top-20 mỗi query |
| Multi-intent | 60 | LLM sinh từ cặp intent thật + người sửa; gold theo từng sub-query |
| Multi-hop | 50 | quan hệ thật từ Wikidata của entity trong catalog; gold = entity đích |
| Set query | 40 | class trong catalog; gold = toàn bộ entity đúng class |
| Tên trùng/gây nhiễu | 30 | cặp entity trùng tên khác tỉnh (Vạn Thủy Tú…) |

Quy tắc sinh: LLM chỉ ĐỀ XUẤT ca, người xác nhận mới vào goldset —
không cho model tự chấm chính mình.

## 4.3 Harness đo

`eval/run_eval.py`:

- Chỉ số: Recall@10, nDCG@10, MRR, class precision (set), hop-accuracy,
  p50/p95/max latency, $/query thực tế (từ log token của llm_router).
- Chạy trên index **80.000 ảnh** (re-index toàn bộ trước khi đo — số
  0.993 hiện tại là đo trên 35k với query trùng tên thực thể, không hợp lệ).
- Xuất `reports/eval-b-after.md` so sánh before/after từng điểm yếu #1–#10.

## 4.4 Tiêu chí nghiệm thu Phase 4 (điều kiện hoàn thành phần B)

- [ ] Goldset ≥ 380 ca đủ 6 loại, có file JSONL + phương pháp sinh ghi trong báo cáo.
- [ ] p95 ≤ 1.500 ms trên 80k ảnh, đo bằng harness (không phải smoke test).
- [ ] Recall@10 / nDCG@10 báo cáo theo từng loại query.
- [ ] Dedup: 0 cặp ảnh trùng gần trong top-10 của goldset (kiểm bằng bộ cặp đã gán nhãn).
- [ ] Báo cáo cuối liệt kê từng điểm yếu #1–#10: trạng thái đã giải quyết + số liệu chứng minh.

---

# Thứ tự phụ thuộc & rủi ro

```
Phase 1 (parser + speculative + llm_router)   — độc lập, làm đầu tiên
Phase 2 (schema + caption + Qdrant + FTS5)    — độc lập Phase 1, chạy song song được
Phase 3 (rerank + multi-hop + set query)      — cần Phase 2 (verify/width, Qdrant)
Phase 4 (dedup + goldset + harness)           — cần cả 1-3
```

Rủi ro cần chú ý khi thi công:

1. `emb.npz` của Phần A có thể thiếu một phần ảnh (verify=no bị loại) —
   ảnh thiếu phải embed bổ sung, không được để vector NULL lẫn trong collection.
2. Caption VLM có thể chứa tên người cụ thể sai sự thật — prompt đã cấm
   suy đoán tên người; review mẫu 50 caption trước khi nạp toàn bộ.
3. Wikidata SPARQL có thể rate-limit — bắt buộc cache `kb_cache` và
   timeout 2s; không resolve được thì suy giảm chức năng, không treo request.
4. Không đổi trọng số RRF (1/1/1/3) trước khi có goldset — đây là số
   đo được từ chạy cũ, tune sau Phase 4.

# Env & config mới

```bash
# .env bổ sung
OPENROUTER_API_KEY=...            # bắt buộc từ Phase 1
LLM_ONLINE_MODEL=google/gemini-3.5-flash-lite
LLM_BATCH_MODEL=google/gemini-3.5-flash-lite:batch
QDRANT_URL=http://localhost:6333
```

`config/models.yaml` bổ sung:

```yaml
rerank:
  model: BAAI/bge-reranker-v2-m3
  top_in: 100
  threshold: 0.2
quality_penalty:
  verify_no: 0.15
  watermark: 0.10
  min_width: 640
  low_width: 0.05
dedup:
  visual_cos_threshold: 0.92   # calibrate lại theo Phần A
  mmr_lambda: 0.7
llm:
  online_timeout_ms: 600
  hard_timeout_ms: 6000
  max_tokens: 300
```
