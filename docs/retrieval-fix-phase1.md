# Phần B — Phase 1: parse entity-first + bỏ chờ LLM trên đường nóng

Thi công theo `retrieval-b-fix-plan.md` (Phase 1, mục 1.1–1.5), giải quyết điểm yếu #1 và #2 trong
[retrieval-painpoints.md](retrieval-painpoints.md). Số đo ngày 2026-10-20 trên index thật
(35.252 ảnh / 4.481 thực thể, phạm vi `pham_van_vuong`), file kết quả `reports/phase1/bench.json`.

## 1. Đã làm

| Mục kế hoạch | File | Nội dung |
|---|---|---|
| 1.1 entity-first | `retrieval/rule_parser.py`, `retrieval/places.py` | Tìm tên thực thể trước, che span, chỉ xét marker quan hệ / tách ý định / tập hợp trên phần còn lại. Địa danh sau dấu phẩy là modifier ("Chùa Một Cột, Hà Nội" → 1 sub-query). Địa danh cuối câu áp cho mọi sub-query ("hồ bơi và công viên nước ở Phú Quốc" → `hồ bơi ở phú quốc`, `công viên nước ở phú quốc`). |
| 1.2 `match_entity_spans` | `retrieval/catalog.py` | Dict n-gram tên + alias, chuẩn hoá bỏ dấu, longest-match-first, không chồng lấn. Build 1 lần mỗi fingerprint CSV, giữ trong RAM. Thêm `suggest()` (ứng viên tên cho LLM). |
| 1.3 nối speculative | `retrieval/speculative.py`, `retrieval/local_search.py` | Rule parse → retrieve ngay; LLM chạy song song trong thread pool, chờ tối đa 600 ms tính từ lúc khởi chạy. Xoá lời gọi DeepSeek parse đồng bộ. Cache key `/v1/search` thêm `pipeline_version`, `index_version`, model parse. |
| 1.4 `llm_router` | `retrieval/llm_router.py` | Gemini 3.5 Flash Lite qua OpenRouter, `json_schema` strict, validate bằng Pydantic, cache SQLite, log `data/local/llm_router_usage.jsonl` (độ trễ, token, USD, tỉ lệ LLM/rule/timeout). Lỗi/timeout luôn fallback rule, không raise. |
| Test | `tests/test_rule_parser_regression.py`, `tests/test_speculative_search.py`, `tests/fixtures/misclassified_entities.csv` | 104 ca hồi quy + 15 ca địa danh sau dấu phẩy + 5 ca vẫn phải tách + hop thật vẫn là multi_hop + LLM chậm/lỗi/khác rule. |
| Benchmark | `scripts/bench_phase1.py` | Đo lạnh (tắt cache `/v1/search` và cache rerank DeepSeek), 2 lượt: LLM chưa cache / đã cache. |

Toàn repo: **212 test pass**, `ruff check .` sạch.

## 2. Tiêu chí nghiệm thu 1.5

| Tiêu chí | Kết quả | |
|---|---|---|
| `pytest tests/test_rule_parser_regression.py` 104/104 | 104/104 tên ra `single`; cả file 140/140 pass | ✅ |
| 0 ca trả rỗng trên 104 ca hồi quy | Search thật: **0 rỗng**, thực thể đúng nằm trong top-10 ở **104/104**, đứng top-1 ở 103/104 | ✅ |
| Parse giảm từ ~1.091 ms về < 10 ms | Rule parse **p50 0,2 ms · p95 0,4 ms** | ✅ |
| p95 ≤ 1.500 ms | **Chưa đạt**: p95 2.504 ms (lạnh) / 1.736 ms (LLM đã cache). Còn lại do rerank DeepSeek (p50 1.450 ms), sẽ bỏ ở Phase 3 | ❌ theo dự kiến của kế hoạch |
| Log tỉ lệ LLM vs rule, số timeout | `llm_router.usage_summary()` + `bench.json → llm_router_usage` | ✅ |

Toàn catalog (4.481 tên): parser cũ xếp sai 973 tên (104 multi_hop, 815 multi_intent, 54 set_query);
parser mới với catalog: **0 sai**. Có test `test_no_entity_name_in_real_catalog_is_misparsed`
chạy khi có catalog local.

## 3. Độ trễ đo được (ms)

| Bước | Trước (DeepSeek parse đồng bộ) | Lượt 1 — LLM chưa cache | Lượt 2 — LLM đã cache |
|---|---|---|---|
| parse (rule) | 1.091 (DeepSeek) | 0,2 | 0,2 |
| chờ LLM (`llm_wait`) | — | p50 471 · p95 518 | 0 |
| embed + retrieve | 138 | p50 120 · p95 170 | p50 104 · p95 129 |
| rerank (DeepSeek, không cache) | 1.451 | p50 1.450 · p95 1.864 | p50 1.439 · p95 1.565 |
| **tổng** | p50 2.483 · p95 2.825 | **p50 2.083 · p95 2.504** | **p50 1.561 · p95 1.736** |

35 truy vấn smoke (30 thực thể + 5 truy vấn của lần chạy trước), khởi động trước 3 truy vấn.
104 ca hồi quy (lạnh): p50 2.101 · p95 2.241 ms.

Ước tính sau Phase 3 (bỏ rerank DeepSeek, giữ nguyên phần còn lại): lượt lạnh khoảng
600 ms + rerank cross-encoder; lượt đã cache khoảng 130 ms + rerank.

## 4. LLM parse — số đo thật

| | Giá trị |
|---|---|
| Model | `google/gemini-3.5-flash-lite` ($0,30 / $2,50 mỗi 1M token, đúng như kế hoạch) |
| Reasoning | Bắt buộc, không tắt được (HTTP 400 "Reasoning is mandatory"). Dùng `effort: minimal`: 1.545 → ~1.000 ms |
| Độ trễ 1 lượt gọi | p50 **1.117 ms** · p95 1.346 ms (141 lượt, 0 lỗi) |
| Chi phí | **$0,000524 / lượt** (kế hoạch ước $0,00042; prompt gồm schema + 20 ứng viên tên) |
| Kết quả trong 177 lượt search | timeout 79,7% · LLM đồng ý rule 19,2% · LLM ghi đè intent 1,1% |

Vì LLM chậm hơn timeout 600 ms, **lần đầu gặp một truy vấn gần như luôn dùng rule**. Luồng nền vẫn
chạy xong và ghi cache, nên lần sau parse LLM có ngay (`llm_wait` = 0).
Model dự phòng `google/gemini-2.5-flash-lite` cũng không lọt 600 ms (p50 804 ms, 6 lượt đo) và
xếp "hồ bơi và công viên nước ở Phú Quốc" là `single`.

## 5. Phát hiện cần bàn trước Phase 3

1. **LLM ghi đè intent sai cả 2/2 lần quan sát được.** "Mai Hịch và Sin Suối Hồ" (rule `multi_intent`,
   đúng) → LLM `set_query`; "các đền thờ" (rule `set_query`, đúng) → LLM `single`. Ảnh trả về
   không đổi vì sub-query giống nhau và ứng viên của rule vẫn được giữ, nhưng `intent_type` trong
   response bị sai. Phase 3 dùng `intent_type` để đi nhánh set query qua đồ thị, nên quy tắc "LLM
   khác loại intent thì dùng LLM" (mục 1.3) cần xem lại — ví dụ chỉ cho LLM ghi đè khi rule không
   tìm thấy tên thực thể nào trong câu.
2. **Timeout 600 ms gần như không bao giờ đủ** cho model đã chọn ở lần gọi đầu. Mỗi truy vấn mới
   tốn ~470 ms chờ vô ích. Có thể giảm timeout (vd 150 ms: chỉ dùng kết quả LLM khi đã có trong
   cache) mà không mất gì ở lần đầu.

## 6. Khác biệt so với kế hoạch (có lý do)

| Kế hoạch | Đã làm | Lý do |
|---|---|---|
| n-gram ≤ 6 token cho span tên | Span tên đầy đủ không giới hạn độ dài; cụm ≤ 6 token chỉ dùng để che marker nằm trong tên | 2.386/4.481 tên dài hơn 6 token |
| Che span tên đầy đủ | Thêm che theo cụm tên một phần (cụm 2–6 token chứa marker có trong tên nào đó) | "Hòn Chồng" không là thực thể riêng, chỉ nằm trong "Biệt thự cổ Bảo Đại Hòn Chồng (Nha Trang)"; tương tự "Đông Anh", "Đức Mẹ" |
| `HOP_RE` thêm `con`, `của`, `wife`... | Giữ bộ marker hiện có (nguyên từ) | `con` làm "những con vật" thành multi_hop; `của` xuất hiện trong mọi câu |
| `normalize` bỏ dấu cho cả sub-query | Bỏ dấu chỉ khi so khớp; sub-query giữ dấu | Embedding MiniLM tốt hơn với văn bản có dấu; test cũ kiểm tra sub-query có dấu |
| Whitelist 63 tỉnh | 63 tỉnh + tên/viết tắt sau sáp nhập + ~30 địa phương du lịch | Kế hoạch tự nêu ví dụ "Phú Quốc" (cấp huyện) |
| `asyncio` + `async def run` | Thread pool, `run` vẫn đồng bộ | Giữ nguyên đường gọi `/v1/search → search → run` (quy ước 4) |
| Schema LLM: chỉ `intent_type`, `entities` bắt buộc | Mọi trường bắt buộc, `additionalProperties: false` | Yêu cầu của chế độ `strict` |

## 7. Chạy lại

```powershell
.\.venv-gpu\Scripts\python.exe -X utf8 -m pytest tests/test_rule_parser_regression.py tests/test_speculative_search.py
.\.venv-gpu\Scripts\python.exe -X utf8 -m scripts.bench_phase1          # ~10 phút, gọi API thật
```

Benchmark gọi API thật: OpenRouter khoảng $0,07 và DeepSeek rerank không cache khoảng 175 lượt.
