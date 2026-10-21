# Test case, quy trình benchmark và nghiệm thu

Ngày rà soát: **21/10/2026**, Asia/Saigon. Đọc cùng [tài liệu kỹ thuật](technical-report.vi.md) và [báo cáo performance](performance-benchmark.vi.md).

## 1. Cách đọc trạng thái

- **Đã chạy trong review:** frontend 18 test, typecheck và collector dữ liệu local đã đạt.
- **Có test tự động:** mã kiểm thử tồn tại; backend chưa chạy lại được do Python trong venv không khởi động. Không hiểu trạng thái này là pass mới.
- **Benchmark đã lưu:** kết quả có trong JSON nguồn; không chạy lại model hoặc endpoint trong review.
- **Cần nghiệm thu:** ca đề xuất để kiểm chứng hành vi thực tế, lỗ hổng coverage hoặc một yêu cầu chưa đạt. Chưa có kết quả pass được xác nhận.

Các ID trong ma trận dưới đây là ID tài liệu để truy vết yêu cầu, không phải tên pytest. Cột test/module chỉ rõ nơi có thể kiểm tra hiện trạng. Fixture trong test thường thay model/API bằng mock; test chức năng không chứng minh latency hoặc relevance trên dữ liệu thật.

## 2. Dữ liệu benchmark và kết quả từng ca

[benchmark-cases.csv](../reports/project_review/benchmark-cases.csv) chứa đầy đủ **244 ca** xuất từ `reports/master/quality/eval.json`:

| Prefix ID | Số ca | Nội dung |
|---|---:|---|
| `ENT-001` đến `ENT-100` | 100 | Query tên entity, metric precision/recall/Hit/nDCG/MRR và số relevant |
| `REG-001` đến `REG-104` | 104 | Hồi quy tên từng bị parser phân loại nhầm, đối chiếu đúng entity top-10/top-1 |
| `SET-001` đến `SET-020` | 20 | Query lớp, class kỳ vọng, exact/same-group precision và số entity khác nhau |
| `MUL-001` đến `MUL-020` | 20 | Query A và B, có đúng A/B, precision và coverage tự báo |

Các cột chung gồm query, intent, parser, số hit, thời gian quality và warning. Ô metric không áp dụng để trống, không thay bằng 0. `quality_run_ms` thuộc lượt quality, không phải latency benchmark chuyên biệt. CSV là bản xuất phục vụ đối chiếu; JSON gốc còn danh sách hit và chi tiết sub-query.

Các lỗi/giới hạn đã có bằng chứng cần giữ làm ca hồi quy:

| Query / tình huống | Kết quả đã lưu | Tiêu chí cần phân biệt |
|---|---|---|
| `Cacao hữu cơ và Tượng đài Kim Đồng` | Tự báo 2 ý covered, nhưng không có đúng entity B theo ID được lấy mẫu | Đối chiếu ID và relevance, không chỉ đọc cờ coverage |
| `các chùa khmer nam tông` | Parse `single` | Kỳ vọng intent set khi người dùng yêu cầu cả lớp |
| Năm tên lớp chứa `&` trong quality master | Parse `multi_intent` | Liên từ trong tên lớp cần được bảo vệ |
| `các nghĩa trang liệt sĩ vùng trung du & miền núi bắc bộ` | Same-group precision 0,5 | Đúng intent và đúng nhóm đều cần kiểm tra |
| `Nước actiso đỏ mật ong và Gốm Đồi Phòng Không` | Trả 8 ảnh | Cho phép trả thiếu khi thiếu bằng chứng; không lấp ảnh ngoài ý định |
| `Nhà thờ Hưng Phú (Quận 8, TP.HCM) và Vòng tay đá Đồng Đậu` | Trả 8 ảnh | Kiểm tra đủ ý riêng với số ảnh trả |
| Dòng master 113.894, `Nhà cổ 38 Hàng Đào` | URL `x-raw-image://` bị quarantine | Không giả ảnh thay; tiêu chí đủ 130.429 ảnh vẫn không đạt |

## 3. Ma trận test chức năng

### 3.1. API, dữ liệu và index

| ID | Tiền điều kiện / thao tác | Kết quả mong đợi | Test hoặc bằng chứng |
|---|---|---|---|
| API-01 | Gọi health không có key | Health trả được theo contract | `test_api_contract.py::test_health_no_key_required` |
| API-02 | Enforce bật; gọi endpoint bảo vệ không key / sai key | 401 / 403; không phục vụ dữ liệu bảo vệ | `api/main.py`; test auth report trong `test_reports_api.py`; cần HTTP search riêng |
| API-03 | Search với response mock hợp lệ | Đủ request ID, intent, hits, facets, timing và schema | `test_api_contract.py::test_search_contract` |
| API-04 | Query trống/whitespace, >2.000 ký tự; top-k 0 hoặc 101 | 422; không làm model chạy trên input sai | `api/schemas.py`, `local_search.run`; cần nghiệm thu biên qua HTTP |
| API-05 | Filter có khóa không hỗ trợ | 422 với thông tin khóa sai | `local_search.run`; cần nghiệm thu qua HTTP |
| API-06 | CORS preflight khi key enforce | OPTIONS đi qua đúng CORS | `test_local_pipeline.py::test_cors_preflight_with_key_enforcement` |
| API-07 | Report ID ngoài allowlist / tên giống đường dẫn | 404, không cho chọn file tùy ý | `test_reports_api.py::test_unknown_report_is_404_not_a_path` |
| API-08 | POST ingest hoặc backfill | Ghi rõ ingest hiện chưa hoạt động async; backfill chưa queue thật | `api/routers/ingest.py`, `backfill.py`; không chấm số mẫu thành tính năng hoàn tất |
| DAT-01 | Import CSV approved hợp lệ hai lần | Lượt hai tái sử dụng, không tăng số ảnh | `test_local_pipeline.py::test_import_is_idempotent_and_excludes_non_http` |
| DAT-02 | CSV mới lỗi thiếu thông tin giữa quá trình import | Catalog trước còn nguyên qua rollback | `test_local_pipeline.py::test_failed_import_preserves_previous_catalog` |
| DAT-03 | Chọn một username / CSV không có cột username | Chỉ nhập đúng scope / báo lỗi cột bắt buộc | `test_scope_and_cascade.py`: hai test username |
| DAT-04 | URL không HTTP(S), flag không approved hoặc URL trùng | Không nhập dòng không đạt; lưu quarantine theo CLI, không tăng bản sao URL | `storage/local.py`, test import và report đếm |
| IDX-01 | Build dở ở checkpoint đã flush | Resume đúng vị trí, không nhận batch hỏng | `test_local_pipeline.py::test_index_resumes_only_flushed_batches` |
| IDX-02 | Đổi model/dim/catalog fingerprint | Không dùng lại index không tương thích | `retrieval/local_index.py`; cần nghiệm thu cả cấu hình Qdrant |
| IDX-03 | Parity SQLite, manifest, NPY và Qdrant | Số hàng, tập ID khớp; không orphan/missing; chỉ công bố live nếu thật sự đã gọi Qdrant | `scripts/check_index_counts.py`, collector local |
| IDX-04 | Yêu cầu 130.429 nhưng chỉ có 130.428 | Báo shortfall, exit khác 0 | `test_v2_invariants.py::test_indexed_image_count_reports_shortfall`, master report |
| IDX-05 | Model API trả thiếu vector, sai dim hoặc lỗi 401/400/503 | Lỗi có kiểm soát, retry đúng nhóm, không ghi batch sai | `test_embed_api.py` |

### 3.2. Parse và retrieve từng loại query

| ID | Input / tình huống | Kết quả mong đợi | Test hoặc bằng chứng |
|---|---|---|---|
| PAR-01 | 104 tên trong fixture hồi quy | Giữ intent kỳ vọng; không nhận nhầm từ trong tên là quan hệ | `test_rule_parser_regression.py::test_entity_names_get_their_expected_intent` |
| PAR-02 | Tên có liên từ nằm trong entity | Không tách span tên thành các ý khác | `test_conjunction_inside_a_name_does_not_split` trong file regression |
| PAR-03 | Địa danh sau dấu phẩy hoặc sau toàn câu multi | Áp modifier đúng; không lan địa danh nằm trong tên entity sang ý khác | `test_rule_parser_regression.py`, `test_v2_invariants.py::test_place_inside_entity_name_is_not_shared_modifier` |
| PAR-04 | Query neo chắc tên, mode ambiguous_only | Không gọi LLM; confidence high | `test_v2_invariants.py::test_ambiguous_only_skips_llm_for_confident_rule` |
| PAR-05 | LLM đề xuất khác rule high hoặc set→single | Guard giữ rule | `test_llm_cannot_override_confident_rule`, `test_llm_cannot_turn_set_query_into_single` |
| PAR-06 | Query mơ hồ, LLM trả cách chia ý hợp lệ trong ngân sách | Dùng parse mới và retrieve bổ sung | `test_speculative_search.py::test_llm_split_is_used_when_it_differs` |
| PAR-07 | LLM chậm, lỗi hoặc đề xuất multi-hop không được hỗ trợ ở lớp parse | Giữ rule, không làm rỗng câu trả đúng; có trạng thái timeout/error | `test_speculative_search.py`: slow/error/multi-hop tests |
| RET-01 | Entity trùng hoàn toàn có đủ ảnh | Ảnh entity đúng ở trước, đủ top-k nếu pool/filter cho phép | `test_v2_invariants.py::test_exact_name_returns_full_topk_if_enough_images` |
| RET-02 | Reranker ưu tiên entity gần tên hơn entity trùng tên | Tầng exact vẫn đứng trên các tầng khác | `test_entity_first_keeps_exact_entity_above_reranker_preference` |
| RET-03 | Query như `Văn Miếu` khớp nhiều entity | Xen kẽ partial match, hạn chế một entity chiếm hết pool | `test_scope_and_cascade.py::test_partial_name_matches_are_interleaved` |
| RET-04 | Multi-intent A và B có ảnh hỗ trợ | Retrieve/rerank riêng, round-robin, ID không trùng, không vượt top-k | `test_v2_invariants.py`, `test_local_pipeline.py::test_multi_intent_preserves_both_subjects` |
| RET-05 | Một ý không có ứng viên hoặc top-k < số ý | Báo thiếu coverage; không thêm ảnh ngoài queue để lấp | `test_multi_intent_has_no_hallucinated_fill`, `test_multi_intent_top_k_below_subquery_count` |
| RET-06 | Cờ covered có anchor khớp tên nhưng không đúng entity kỳ vọng | Đánh giá riêng exact coverage với relevance độc lập | Ca `Cacao hữu cơ...`; cần nghiệm thu mapping, chưa có test sửa lỗi |
| RET-07 | Set query có `&`, tên lớp hoặc tên giống entity | Giữ yêu cầu tập hợp; top-k đúng lớp | 20 ca SET đã lưu; 6 lỗi intent cần sửa và kiểm lại |
| RET-08 | Từ khóa có dấu và hư từ `cho/chợ`, `đến/đền` | Lọc hư từ trước bỏ dấu; ưu tiên đủ từ AND rồi mới OR | `test_phase2_index.py`: stopwords/lexical tests |
| RET-09 | Có visual manifest hoàn chỉnh và vector test | Nhánh visual đóng góp vào fusion | `test_phase2_index.py::test_visual_branch_joins_fusion`; chưa chạy visual thật trên master |
| RET-10 | Query chỉ mô tả thuộc tính pixel | Chấm bằng relevance người gán, báo giới hạn metadata | Cần goldset; hiện chưa có metric đại diện |

### 3.3. Filter, chất lượng và dự phòng

| ID | Input / tình huống | Kết quả mong đợi | Test hoặc bằng chứng |
|---|---|---|---|
| QUA-01 | Min-width/orientation API trên catalog có một phần kích thước | Loại ảnh sai hoặc chưa biết theo strict | `test_phase2_index.py::test_size_filters_use_real_dimensions` |
| QUA-02 | Modifier kích thước suy từ query | Giữ ảnh unknown, warning; không nhầm tên địa danh là hướng ảnh | `local_search.py`, `test_scope_and_cascade.py::test_orientation_filter_ignores_place_names` |
| QUA-03 | Catalog chưa biết kích thước nào | Hiện bỏ filter và warning; cần xác nhận đây có đáp ứng yêu cầu sản phẩm không | `local_search.run`; cần test biên riêng |
| QUA-04 | Verify/watermark NULL | Xuất unknown; không thưởng/phạt tự động | `test_v2_invariants.py::test_missing_quality_is_unknown` |
| QUA-05 | Watermark đã biết / ảnh người đã duyệt | Dùng `has_watermark`; bỏ watermark penalty khi nguồn human | `test_quality_penalty_reads_has_watermark_and_ignores_unknown`, `test_human_verified_image_is_not_penalised_for_watermark` |
| DEG-01 | Embedding API down | FTS + tên vẫn phục vụ, có warning, không ghim kết quả suy giảm | `test_embed_api.py::test_search_degrades_when_embedding_endpoint_is_down` |
| DEG-02 | Rerank và fallback embedding đều lỗi | Trả fusion order và warning thay vì hỏng request trong phạm vi lỗi được bắt | `test_search_survives_when_rerank_and_fallback_both_fail` |
| DEG-03 | LLM trả ID ảnh không nằm trong ứng viên | Từ chối output không hợp lệ | `test_local_pipeline.py::test_llm_rerank_rejects_invented_ids` |
| DEG-04 | Đổi parse policy giữa hai lượt cùng query | Cache key đổi, không dùng câu trả của policy trước | `test_v2_invariants.py::test_cache_key_changes_with_parse_policy` |
| DEG-05 | Thêm cạnh KG, đổi quality label nhưng không đổi số kích thước biết | Kiểm cách vô hiệu cache; không tái dùng response lỗi thời | Cần test bổ sung; key hiện chưa phản ánh mọi thay đổi dữ liệu |
| DEG-06 | Gọi limiter vượt cửa sổ | Chờ theo cấu hình; đo riêng thời gian chờ; kiểm nhiều process | `test_embed_api.py::test_rate_limiter_waits_instead_of_bursting`; nhiều process chưa được nghiệm thu |

### 3.4. Multi-hop và bằng chứng

| ID | Tiền điều kiện / truy vấn | Kết quả mong đợi | Test hiện có |
|---|---|---|---|
| HOP-01 | Fixture có seed → con → nơi an táng | `resolved`, đúng entity đích, trace có cạnh và nguồn | `test_hop.py::test_two_hop_chain_resolves_with_evidence` |
| HOP-02 | Truy vấn cha/mẹ cần đi ngược `PARENT_OF` | Duyệt đúng chiều và giới tính | `test_reverse_direction_derives_father` |
| HOP-03 | Có claim nhưng verified=0, reviewed=0 | Không dùng claim để tìm đích | `test_unverified_claims_are_never_used` |
| HOP-04 | Đích là người chưa link ảnh | `target_not_in_catalog`, không trả ảnh thay; có thể gợi ý nơi liên quan | `test_person_target_lists_related_places_without_images` |
| HOP-05 | Seed không có alias / quan hệ anh-em chưa hỗ trợ | `seed_not_linked` / `unsupported_relation` | `test_unknown_seed_and_unsupported_relation` |
| HOP-06 | Online bắt đầu pending rồi có cạnh hợp lệ | Lần đầu pending, lần sau dùng cạnh tin cậy | `test_online_fallback_pending_then_found` |
| HOP-07 | Online không có evidence, hoặc câu trích thiếu hai bên | Không tạo cạnh tin cậy; cache âm có chính sách | `test_online_no_evidence_is_cached`, `test_verify_quote_requires_source_text_and_both_parties` |
| HOP-08 | Quote có spacing, case, ellipsis hoặc đại từ | Chấp nhận theo rule hiện có; đối chiếu false-positive khi nghiệm thu | Các test quote/snippet trong `test_hop.py` |
| HOP-09 | Resolver không giải được trong search | `hits=[]`, resolution và warning nêu lý do | `test_search_unresolved_hop_returns_nothing_with_status` |
| HOP-10 | Resolver giải được và target có ảnh | Chỉ trả ảnh entity đích và ghi resolution | `test_search_returns_target_images_with_resolution` |

## 4. Ma trận test Phần A

| ID | Tình huống | Tiêu chí kiểm tra | Nơi có test / trạng thái |
|---|---|---|---|
| VER-01 | URL sai, blocked, whitespace và không đuôi | Đúng mã gate; chính sách download/reject rõ ràng | `test_verify_pipeline.py::test_gate_rules_and_noext_policy` |
| VER-02 | Cùng URL trong một entity và ở hai entity | Dedupe đúng phạm vi entity của verify | `test_gate_dedupes_url_within_entity_only` |
| VER-03 | Tên `X` và `X (Hà Nội)` | Cùng nhóm split; nhóm không rò giữa TRAIN/VAL/TEST | `test_split_keeps_name_variants_together_and_never_leaks` |
| VER-04 | Ảnh cùng SHA xuất hiện qua split | Kiểm chính xác bản nào bị loại; đánh giá cả TRAIN–VAL và near-duplicate | Mã run có bỏ bản TEST; cần coverage thêm cho các kiểu rò còn lại |
| VER-05 | Jev payload/schema và confidence | Text-only, schema hợp lệ, logprob/self confidence theo rule | `test_jev_logprob_confidence_and_schema` |
| VER-06 | Jev thiếu key hoặc hết credit | Không làm mất toàn pipeline; báo unavailable/soft-stop theo mã | `test_jev_without_key_is_unavailable`, `test_jev_soft_stops_on_no_credit` |
| VER-07 | Budget alpha, nhóm quá ít ảnh hoặc đã đủ yes | Chọn không vượt budget; đúng rule nhóm | `test_router_budget_and_entity_rules` |
| VER-08 | Risk–coverage, ECE và conformal trên mảng biết đáp án | Tính đúng bằng công thức, không đổi thành accuracy gold | `test_risk_coverage_and_ece`, `test_conformal_threshold_bounds_defer_rate` |
| VER-09 | VLM batch bỏ sót ảnh / output sai | Chấm đủ danh sách; không im lặng mất ảnh | `test_vlm_batch_validates_every_image` |
| VER-10 | API gán nhãn người | Không lộ dự đoán trong luồng gán nhãn mù; validate label | `test_label_api_is_blind_and_validated` |
| VER-11 | Đánh giá trên dữ liệu người gán có cả positive và negative | Confusion matrix, precision/recall/F1, false-accept/reject, ECE và CI | Cần tập nhãn mới; report hiện chưa có human_eval |
| VER-12 | Chạy verify lạnh và chạy lại cache | Đo riêng tải, encode, bootstrap, Jev, router, VLM, cost và cache hit | Cần benchmark mới; không dùng 21,16 giây cached làm cold throughput |

Các test cascade cũ trong `test_stage1_gates.py`, `test_routing.py`, `test_scope_and_cascade.py` vẫn có ích cho gate/routing cũ, nhưng không thay thế test head/Jev của `pipeline/verify/`.

## 5. Frontend và chỉ số đã chạy mới

| Kiểm tra | Kết quả trong review | Giới hạn |
|---|---|---|
| `web/spa/src/api/searchAdapter.test.ts` | 13/13 pass | Test adapter; không gọi model thật |
| `web/spa/src/api/contract.test.ts` | 5/5 pass | Test API contract phía client; không chứng minh server live |
| `npm.cmd run typecheck` | Pass | Kiểm tra TypeScript; không phải test tương tác browser |
| Collector metadata/NPY/quality | Pass | Đọc local; không xác minh Qdrant live hay giá trị mọi vector |

Để nghiệm thu UI cần thêm thao tác browser: tìm từng intent, bấm facet, hiển thị warning, unknown quality, query trả thiếu, pending multi-hop, trạng thái loading/error, tải report và API key. Những ca này là kế hoạch kiểm tra, chưa được chấm pass trong review.

## 6. Lệnh tái lập

Các lệnh dưới đây dành cho PowerShell từ thư mục repo, trừ các lệnh frontend có `Push-Location`. Môi trường Python hiện đang hỏng đường dẫn interpreter; cần khôi phục Python 3.12 và môi trường theo dependency của dự án trước khi chạy các lệnh Python. Không ghi đè `.env` hoặc index đang phục vụ chỉ để tạo một lượt benchmark.

### 6.1. Kiểm tra tài liệu và tái xuất bằng chứng local

Yêu cầu Node hỗ trợ `node:sqlite`, đã thực thi bằng Node 22.15.1. Lệnh đọc các snapshot, SQLite và NPY; chỉ ghi lại evidence/CSV trong `reports/project_review/`.

```powershell
node --experimental-sqlite reports/project_review/collect_evidence.cjs
```

Collector giữ `checks.json` là bản ghi các lệnh đã quan sát trong review; chạy collector lại **không chạy lại các kiểm thử** hoặc tự cập nhật trạng thái pytest/frontend trong file đó.

### 6.2. Kiểm thử tự động

```powershell
Push-Location web/spa
npm.cmd test
npm.cmd run typecheck
Pop-Location

# Sau khi khôi phục interpreter của môi trường này:
.\.venv-gpu\Scripts\python.exe -X utf8 -m pytest -q --junitxml=reports/review_run/pytest.xml
```

`tests/conftest.py` tắt key OpenRouter, chọn NumPy và thay cấu hình model cho test; nhiều test còn mock encoder/model. Cần lưu stdout và JUnit mới để thay trạng thái “chưa chạy” của backend.

### 6.3. Kiểm tra parity trên dataset master hiện có

```powershell
.\.venv-gpu\Scripts\python.exe -X utf8 -m scripts.check_index_counts --csv data/data_anh_pass_master.csv --require 130428 --out reports/review_run/index_counts_valid.json
```

Nếu hợp đồng yêu cầu **đủ 130.429 dòng nguồn**, chạy riêng với `--require 130429` và ghi nhận fail cho đến khi có ảnh hợp lệ thay dòng quarantine. Lệnh kiểm tra Qdrant chỉ thực hiện khi `VECTOR_BACKEND=qdrant`; nếu dùng NumPy thì không được gọi kết quả là parity Qdrant.

### 6.4. Quality và latency mới

```powershell
.\.venv-gpu\Scripts\python.exe -X utf8 -m scripts.eval_quality --out reports/review_run/quality
.\.venv-gpu\Scripts\python.exe -X utf8 -m scripts.eval_latency --concurrency 1,4 --offered-rpm 85 --seed 13 --out reports/review_run/latency.json
```

Giữ nguyên index/model/policy khi so sánh các lượt. Lệnh quality tắt đọc search cache; lệnh latency tắt đọc search/parse/LLM-rerank cache theo script và thực hiện 3 warm-up. Chúng vẫn có thể ghi cache, log usage và gọi endpoint theo `.env`. Chưa hỗ trợ tham số tự tăng lên 10.000 request/intent; cần harness mở rộng cho quy trình tải lớn.

### 6.5. A/B reranker

```powershell
# Chạy trong bản sao workspace dành cho thí nghiệm:
.\.venv-gpu\Scripts\python.exe -X utf8 -m scripts.eval_rerank_ab --backends fusion,bge,qwen06
```

Script hiện ghi cố định vào `reports/v2/`; không có `--out`. Mặc định dùng lại `frozen_pools.json` nếu đã tồn tại, kể cả khi catalog hiện tại đã đổi. Cần bảo toàn report gốc và xác định đúng snapshot pool trước khi chạy. Chỉ dùng `--refreeze` trong workspace thí nghiệm khi chủ đích tạo pool mới; nếu đổi pool, không gọi đó là cùng A/B đã lưu. Chọn thêm Jina/Gemini cần giữ cache state và endpoint budget có thể so sánh được.

### 6.6. Goldset và verify

```powershell
# Sau khi thay đầy đủ placeholder bằng relevance người gán:
.\.venv-gpu\Scripts\python.exe -X utf8 -m evals.harness --goldset evals/goldset --out reports/review_run/gold/report.json

# Một lượt verify pilot mới, có thể gọi VLM/Jev và ghi dữ liệu verify:
.\.venv-gpu\Scripts\python.exe -X utf8 -m pipeline.verify --csv data/data_anh_pass_master.csv --entities 400 --budget 0.15 --target test --seed 42 --out reports/review_run/verify
```

Hiện 4 file JSONL goldset có tổng 5 query, cả 5 đều thiếu relevance thật/đang là placeholder; harness chủ động dừng. Hàm `recall_at_k` của harness vẫn là recall capped; muốn báo recall thật cần tính thêm rõ ràng.

`--out` của verify chỉ tách report; cache, state và artifact dưới thư mục verify vẫn có thể được chia sẻ. Muốn so lạnh/ấm hoặc đổi dataset phải cô lập và ghi nhận cả thư mục artifact, không chỉ đổi `--out`. `--skip-vlm` dừng trước bước VLM cuối theo CLI, không bảo đảm bootstrap/Jev không gọi dịch vụ. Ngân sách 15% không bao gồm mọi chi phí bootstrap/chấm lại.

## 7. Kế hoạch benchmark HTTP còn cần thực hiện

`loadtest/loadtest.js` có sáu scenario và threshold, nhưng chưa đủ để xác nhận quy trình nghiệm thu trong tài liệu cũ. Trước khi dùng làm evidence cần xử lý các điểm sau:

1. Thay query ngoài miền dữ liệu bằng tập query đã đóng băng và có đáp án; ca multi-hop hiện tại không đại diện KG đang hỗ trợ.
2. Tách warm-up và measured requests; ghi riêng response cache hit, model warm uncached và cold start. Script hiện không thực hiện rõ 200 warm-up hoặc bảo đảm 10.000 request/intent.
3. Giữ tải trong khả năng endpoint khi đo cấu hình hiện tại; các scenario 120 VU tổng cộng có thể vượt xa limiter một key, không phải cùng điều kiện 85 query/phút.
4. Kiểm correctness tối thiểu theo từng query. Check hiện tại chỉ yêu cầu trường `hits` tồn tại, nên `hits=[]` vẫn được xem là hợp lệ về tải.
5. Dùng ứng viên rerank có metadata thật. Hai ID mẫu không có nội dung không đại diện workload 24 ứng viên.
6. Lưu client latency, header `X-Response-Time`, `total_ms`, HTTP status, warning, intent, cache và số hit cho từng request. Giữ cả thời gian queue và pacing theo định nghĩa phép đo.
7. Kiểm tương thích định dạng k6 summary với `loadtest/make_report.py`. Hàm extract hiện đọc các metric trực tiếp, cần xác minh với phiên bản k6 thực tế; không coi report thiếu metric là pass.
8. Gate riêng p95 search 1.500 ms, embed 200 ms, rerank 400 ms và error rate <1%. `make_report.py` hiện chỉ kiểm ngưỡng chung trên những metric đọc được, chưa bảo đảm gate đủ mọi tiêu chí.

Các con số threshold ở mục này là mục tiêu có trong cấu hình dự án, **không phải kết quả đã đo**. Không chạy tải lớn mặc định và dùng sự thành công của lệnh làm thay cho kiểm tra dữ liệu đầu ra.

## 8. Tiêu chí nghiệm thu và cấu trúc một lượt benchmark

| Nhóm | Điều kiện chấp nhận |
|---|---|
| Dữ liệu | Nguồn/fingerprint đúng; ghi rõ valid rows, quarantine, scope; parity local và Qdrant nếu có dùng |
| Chức năng | API/parse/filter/fallback đáp ứng ma trận; assertion test chạy mới có log và không dùng dịch vụ thật ngoài ý muốn |
| Entity quality | Hit@10, nDCG, MRR và cả hai công thức recall; công bố riêng silver/gold |
| Multi-intent | Exact coverage, reported coverage, precision và số ảnh; giải thích mọi ca chênh nhau |
| Set query | Intent accuracy, exact/same-group precision, diversity; không suy top-k thành toàn bộ tập |
| Multi-hop | Seed linking, từng cạnh/nguồn, đúng đích, ảnh đúng và ca không đủ evidence; tránh đánh giá vòng tròn bằng cùng KG tự tạo nhãn |
| Verify | Có negative, nhãn mù độc lập, confusion matrix, calibration và risk–coverage; tách chi phí bootstrap khỏi router |
| Latency | Đo qua HTTP, từng intent và mức concurrency, cache/cold rõ ràng; p50/p95/p99/max, lỗi và tail latency |
| Tính tái lập | Manifest/model/policy, timestamp, phần cứng, phiên bản phụ thuộc, script, seed và trace được lưu cùng report |

Một lượt mới nên lưu trong `reports/<run_id>/` gồm `environment.json`, `checks`/JUnit, danh sách query và relevance, `requests.jsonl`, `quality.json`, `latency.json`, `cost.json`, summary Markdown và SHA256 các input. Script hiện có chưa tạo đủ tất cả các file này; đây là cấu trúc đề xuất cho lần nghiệm thu tiếp theo.

Ngưỡng chất lượng gốc của harness là recall capped ≥0,70, Hit@10 ≥0,95, nDCG@10 ≥0,75 và MRR ≥0,80. Nếu dùng recall thật, cần đặt mục tiêu theo số relevant và miền query thay vì âm thầm dùng lại công thức capped. Với tập nhỏ, công bố mẫu số, số ca lỗi và khoảng tin cậy; không chỉ báo một số trung bình.
