# Phần B — Báo cáo triển khai V2 (Track A) · 2026-10-21

Thi công theo [RETRIEVAL_PIPELINE_V2_DATA_DRIVEN_PLAN.md](RETRIEVAL_PIPELINE_V2_DATA_DRIVEN_PLAN.md),
**Track A (A1→A8)**. Track B (text_core, entity-first đầy đủ, visual, KG lớn, 590 ca gold) chưa làm.
Mọi số dưới đây là **đo thật** trên máy local (Windows 11, RTX 4050 6 GB, Qdrant 1.19, endpoint
Qwen3-Embedding qua LiteLLM/tunnel) và dùng **nhãn silver** (tự sinh từ `entity_id`/`category` của
catalog) — **không phải gold người gán**, nên không được gọi là accuracy.

`pipeline_version = b3-guarded-parse-fair-multi`.

---

## 1. Trạng thái từng hạng mục

| # | Hạng mục kế hoạch | Kết quả | Bằng chứng |
|---|---|---|---|
| A1 | Snapshot V1 + baseline | Xong | `reports/v1_baseline/` (manifest index, 244 ca × 3 cấu hình, thí nghiệm verify) |
| A2 | 80k indexed thật | **Chưa đạt 80.000 — báo đúng 79.999.** ID parity SQLite = vectors.npy = Qdrant = 79.999, 0 vector thừa/thiếu. Dòng CSV 72.218 ("Nhà cổ 38 Hàng Đào", URL `x-raw-image:///…`) bị quarantine, **không bịa ảnh thay** | `scripts/check_index_counts.py --require 80000` → exit 1; `reports/v2/index_counts.json` |
| A3 | Chọn reranker nhanh bằng A/B cùng điều kiện | Xong: **BGE-reranker-v2-m3 local** làm mặc định | `scripts/eval_rerank_ab.py`, `reports/v2/rerank_ab.json` (mục 2) |
| A4 | Sửa LLM override + cutoff | Xong: LLM chỉ gọi cho truy vấn mơ hồ; guard không cho đè rule chắc / `set → single`; bỏ cutoff 0,2 | `retrieval/speculative.py`, `tests/test_v2_invariants.py` |
| A5 | Filter chất lượng biết/không biết | Xong: sửa khoá `has_watermark`; NULL = `unknown`; filter API = strict, filter suy từ câu = permissive; migrate dữ liệu đang có | `scripts/migrate_images_v2.py`, `reports/v2/migrate_v2.json` |
| A6 | Multi-intent tách ứng viên + chia slot công bằng | Xong: rerank RIÊNG từng sub-query, chỉ nhận ảnh có bằng chứng (thực thể khớp tên), round-robin, không lấp ảnh ngoài A/B, báo `coverage` | `retrieval/local_search.py::allocate_fair`, response `sub_queries` |
| A7 | Multi-hop pilot có nguồn | **Hạ tầng xong, chưa có dữ liệu KG**: Wikidata từ chối (HTTP 403) vì User-Agent phải có liên hệ thật. Hiện mọi câu multi-hop trả `seed_not_linked` + cảnh báo, **không trả ảnh tuỳ tiện** | `retrieval/hop.py`, `scripts/build_kg_pilot.py`, `tests/test_hop.py` |
| A8 | Báo cáo trung thực | File này | — |

Kèm theo: bộ giới hạn tốc độ phía client cho endpoint (§4), nạp sẵn model khi khởi động server,
`scripts/eval_latency.py` (§10.2), `scripts/eval_quality.py` thêm Precision@10 / Recall@10 thật.

---

## 2. A3 — A/B reranker trên pool ĐÓNG BĂNG (chỉ đổi đúng một biến)

244 truy vấn, parse chỉ bằng rule, cùng pool 24 ứng viên/truy vấn; entity đúng có mặt trong
pool ở **100%** ca tên thực thể (candidate entity recall@pool = 1,0).

| Chỉ số (silver) | fusion (không rerank) | jina-v2 (endpoint) | **BGE-v2-m3 (local)** | Qwen3-Reranker-0.6B (local) | Gemini 3.5 FL |
|---|---|---|---|---|---|
| Tên: nDCG@10 / MRR | **1,000 / 1,000** | 0,991 / 0,995 | 0,950 / 0,950 | 0,949 / 0,951 | 0,946 / 0,981 |
| Tên: Precision@10 | 0,663 | 0,659 | 0,637 | 0,642 | 0,611 |
| Tên: Recall@10 **thật** (÷|R|) | 0,914 | 0,910 | 0,881 | 0,877 | 0,860 |
| Tên: Recall@10 kiểu V1 (÷min(10,|R|)) | 1,000 | 0,996 | 0,963 | 0,963 | 0,940 |
| Set query: ảnh đúng nhóm | 0,815 | 0,895 | **0,975** | **0,975** | 0,935 |
| Multi: ảnh thuộc A hoặc B (pool chung) | 0,745 | 0,765 | 0,775 | 0,785 | 0,795 |
| Rerank p50 / p95 | — | 136 / 185 ms | **109 / 151 ms** | 580 / 1.089 ms | (đọc cache) |
| Giấy phép | — | CC-BY-NC-4.0 | Apache-2.0 | Apache-2.0 | dịch vụ trả phí |
| VRAM đỉnh | — | — | 1,17 GB | 3,33 GB | — |

**Kết luận:** (1) reranker giúp nhiều cho set query nhưng **làm kém** truy vấn tên thực thể chính
xác (kéo ảnh thực thể gần tên lên) → chính sách **entity-first** (§3); (2) BGE và Qwen3-0.6B ngang
chất lượng, BGE nhanh hơn ~5 lần → chọn **BGE local**. Công thức Recall@10 của V1 (÷min(10,|R|))
cao hơn recall thật ~9 điểm — đúng như kế hoạch §9.4 cảnh báo; từ nay báo cả hai, ghi rõ tên.

---

## 3. Thay đổi hành vi pipeline

| Bước | V1 | V2 |
|---|---|---|
| Parse LLM | Gọi mọi truy vấn; ghi đè được rule (kể cả đổi mọi "các …" thành `single`) | `LLM_PARSE_MODE=ambiguous_only`: chỉ gọi khi rule **chưa neo chắc** (đo được 56/244 truy vấn). Guard: không đè rule `high`, không đổi `set_query → single`, `multi_hop` của LLM bị bỏ qua |
| Độ tin cậy rule | — | `high` = mỗi sub-query có **một** tên thực thể phủ ≥ 60% token (thử cả câu đầy đủ lẫn câu bỏ địa danh cuối); `medium` = set query; `low` = còn lại |
| Địa danh cuối câu | Gắn vào mọi sub-query (sai với "… và Lăng Chủ tịch Hồ Chí Minh") | Không lan nếu địa danh nằm **trong tên thực thể** |
| Rerank | Gemini (~2 s), cắt điểm < 0,2 | **BGE local** (~110 ms), không cắt; mỗi văn bản ứng viên chấm 1 lần; entity-first: thực thể trùng đúng tên → khớp một phần → còn lại, reranker xếp trong từng tầng |
| Multi-intent | 1 pool chung, quota hình thức | Rerank riêng từng sub-query; chỉ ảnh có bằng chứng; `allocate_fair`; không lấp ảnh ngoài A/B; `sub_query_no_coverage`, cảnh báo khi `top_k` < số ý |
| Chất lượng ảnh | Phạt đọc nhầm khoá `watermark` (luôn 0) | Đọc `has_watermark`; NULL không phạt; mỗi hit có `quality` (width/height/verify/watermark, `unknown` khi NULL, `pixel_checked=false`) |
| Filter kích thước | Bỏ qua (chưa có dữ liệu) | Có dữ liệu cho 53% ảnh: filter API **strict** (loại ảnh chưa biết), filter suy từ câu **permissive** (giữ ảnh chưa biết, báo số lượng) |
| Multi-hop | Luôn rỗng + câu cảnh báo chung | Resolver theo KG có nguồn; trạng thái `resolved / seed_not_linked / no_evidence / target_not_in_catalog / unsupported_relation`; response có `resolution` (chuỗi cạnh + URL nguồn) |
| Response | — | Thêm `sub_queries`, `parse_confidence`, `pipeline_version`, `resolution`, `hit.matched_subqueries`, `hit.quality` (tương thích ngược) |
| Cache | Khoá theo model | + chính sách parse (`LLM_PARSE_MODE`, `POLICY_VERSION`), chế độ cutoff, backend rerank |

---

## 4. Ràng buộc vận hành phát hiện khi đo

**Endpoint embedding/rerank giới hạn 100 request/phút/key** (LiteLLM: `Limit type: requests.
Current limit: 100`, reset theo phút) — dùng chung cho embedding và rerank qua API. Mỗi truy vấn tốn
1 request embedding (+1 nếu LLM đổi parse, +1/sub-query nếu rerank qua API). Với rerank local,
**một key phục vụ tối đa ~95 truy vấn/phút**. V2 thêm `retrieval/ratelimit.py`
(`EMBED_API_RPM=95`): client tự chờ thay vì nhận 429 rồi retry. Muốn tải cao hơn cần nâng hạn mức
key hoặc nhiều key/endpoint ổn định (URL `trycloudflare.com` cũng không có SLA).

---

## 5. Kết quả end-to-end

### 5.1 Chất lượng — 244 ca, cùng bộ với V1 (silver)

| Chỉ số | V1 (Gemini rerank, LLM parse luôn gọi) | **V2** |
|---|---|---|
| Tên thực thể (100): nDCG@10 / MRR / Hit@10 | 0,949 / 0,981 / 0,99 | **0,985** / 0,980 / 0,99 |
| Tên thực thể: Precision@10 / Recall@10 thật | — | 0,660 / 0,903 |
| Hồi quy 104 tên: trong top-10 / top-1 | 103 / 102 | **104 / 103** |
| Set query (20): ảnh đúng nhóm / đúng nhóm con | 90,5% / 79,5% | **92,5% / 82,5%** |
| **Multi-intent (20): ảnh thuộc A hoặc B** | 73,0% | **86,0%** |
| Multi-intent: đủ mọi ý / số ảnh trả TB | 20/20 / — | 20/20 / 9,35 |
| Truy vấn trả < 10 ảnh | 31 | **2** |

V1→V2 **không phải thí nghiệm một biến** (đổi cả reranker, parse policy, allocator); phần đóng
góp của riêng reranker xem §2.

### 5.2 Độ trễ — đo đúng §10.2 (cache search + parse + rerank đều TẮT, thứ tự xáo, tải 85 truy vấn/phút)

| | Concurrency 1 | Concurrency 4 |
|---|---|---|
| p50 / p95 / p99 / max | 550 / **954** / 1.203 / 1.953 ms | 532 / **816** / 1.065 / 2.437 ms |
| < 1.500 ms / < 3.000 ms | **99,6% / 100%** | **99,6% / 100%** |
| Lỗi / 429 / suy giảm | 0 / 0 / 0 | 0 / 0 / 0 |
| p95 theo loại: tên / set / multi | 827 / 1.382 / 1.203 ms | 763 / 1.084 / 1.065 ms |
| Bước p50 (p95): embed / dense / retrieve / chờ LLM / rerank | 140 (241) / 31 (46) / 124 (370) / 0 (379) / 110 (220) | 139 (229) / 31 (43) / 92 (312) / 0 (385) / 111 (206) |

So V1 (Gemini rerank): p50 2.658 / p95 3.058 ms, 0% < 1.500 ms. **V2 đạt SLO p95 ≤ 1.500 ms** ở
điều kiện trên. Truy vấn đầu sau khởi động server không còn chờ ~20 s nạp BGE (nạp sẵn nền).

**LLM parse trong ngân sách 600 ms gần như không bao giờ kịp khi cache tắt** (55/56 lần gọi
timeout; p50 một lần gọi ~1,1 s). Lợi ích thực của LLM hiện chỉ đến từ cache ở lần lặp lại.
Kế hoạch §5.1 đề xuất A/B 0/150/600 ms trên tập truy vấn mơ hồ có nhãn — chưa làm vì chưa có nhãn.

---

## 6. Giới hạn còn lại (không che)

1. **Chưa có gold người**: mọi chất lượng là silver; 590 ca / 295 gold của kế hoạch §9.2 chưa làm.
2. **79.999 ≠ 80.000**: cần một URL ảnh thật cho "Nhà cổ 38 Hàng Đào" rồi ingest lại.
3. **Multi-hop chưa có dữ liệu**: cần `WIKIDATA_CONTACT` (email/URL thật) để chạy
   `python -m scripts.build_kg_pilot`; pilot dự kiến: các vua Nguyễn (P40 con, P119 nơi an táng) →
   lăng trong catalog. Liên kết lăng ↔ catalog dùng so khớp tên (`label_exact` / `name_prefix`),
   giữ mọi `entity_id` trùng tên.
4. **Set query bị gắn nhãn sai ở 5/20 ca** do tên nhóm có `&` ("các bộ gõ mộc & idiophone…" →
   `multi_intent`); kết quả ảnh vẫn đúng nhóm phần lớn.
5. **Dữ liệu chất lượng mỏng**: kích thước 53,3% ảnh, `verify` 1,1% (915 ảnh pilot Phần A),
   watermark 3,9%. Lượt tải ảnh 80k mới ~57% (đang dừng).
6. **Chưa dùng pixel**: `img_visual` (SigLIP2) chưa nạp; `pixel_checked=false` trên mọi hit.
7. **Thực thể trùng tên** (vd 4–7 `entity_id` cho mỗi "Lăng …") được giữ tất cả, chưa gộp/khử trùng
   — làm thấp Precision@10 silver dù ảnh đúng đối tượng.
8. Track B (text_core/group SQL, entity rerank theo đại diện, visual dedup/MMR, KG lớn) chưa làm.

---

## 7. Cấu hình V2 (đã ghi vào `.env.example`)

```dotenv
RERANK_BACKEND=local_ce
RERANK_LOCAL_MODEL=BAAI/bge-reranker-v2-m3
RERANK_CUTOFF_MODE=none
LLM_PARSE_MODE=ambiguous_only
LLM_PARSE_CAN_OVERRIDE_CONFIDENT_RULE=false
EMBED_API_RPM=95
WIKIDATA_CONTACT=            # bắt buộc trước khi dựng KG
```

Quay lại hành vi V1: `RERANK_BACKEND=llm`, `RERANK_CUTOFF_MODE=legacy_llm_0.2`,
`LLM_PARSE_MODE=always`, `LLM_PARSE_CAN_OVERRIDE_CONFIDENT_RULE=true`.

---

## 8. Tái lập

```powershell
.\.venv-gpu\Scripts\python.exe -X utf8 -m pytest                          # 256 test
.\.venv-gpu\Scripts\python.exe -X utf8 -m scripts.check_index_counts --require 80000
.\.venv-gpu\Scripts\python.exe -X utf8 -m scripts.eval_rerank_ab           # A/B pool đóng băng
.\.venv-gpu\Scripts\python.exe -X utf8 -m scripts.eval_quality --out reports/v2/quality
.\.venv-gpu\Scripts\python.exe -X utf8 -m scripts.eval_latency --concurrency 1,4 --offered-rpm 85
```

| File mới / sửa chính | Vai trò |
|---|---|
| `retrieval/speculative.py` | Độ tin cậy rule, `LLM_PARSE_MODE`, guard |
| `retrieval/rule_parser.py` | Không lan địa danh nằm trong tên thực thể |
| `retrieval/local_search.py` | Entity-first, multi-intent theo sub-query + `allocate_fair`, chính sách size, multi-hop |
| `retrieval/rerank.py` | `local_ce` (BGE / Qwen3-Reranker), chấm khử trùng văn bản, `has_watermark`, retry 429 |
| `retrieval/ratelimit.py` | Giới hạn 95 request/phút dùng chung embedding + rerank API |
| `retrieval/hop.py`, `scripts/build_kg_pilot.py` | Multi-hop có nguồn |
| `api/main.py` | Nạp sẵn catalog + reranker khi khởi động |
| `scripts/check_index_counts.py`, `eval_rerank_ab.py`, `eval_latency.py`, `eval_quality.py` | Đo lường |
| `tests/test_v2_invariants.py`, `tests/test_hop.py` (+ cập nhật test cũ) | Bất biến §11.2 |

---

## 9. Chuyển sang bộ dữ liệu master (2026-10-21, chiều)

Theo yêu cầu, **mọi luồng** (Phần A verify, Phần B import/index, đo lường, graph) dùng một nguồn
duy nhất `SOURCE_CSV=data/data_anh_pass_master.csv` — bộ người dùng xác nhận **đã verify tay 100%**.

| | Bộ 80k (trước) | **Bộ master** |
|---|---|---|
| Dòng CSV / ảnh index được | 80.000 / 79.999 | **130.429 / 130.428** |
| Thực thể / nhóm | 11.294 / 669 | 11.749 / 670 |
| Chuỗi metadata khác nhau (số lần gọi embedding) | 66.937 | 106.093 |
| Quan hệ với bộ 80k | — | chứa **trọn** 80.000 URL của bộ 80k |
| Dòng bị loại | dòng 72.218, "Nhà cổ 38 Hàng Đào", URL `x-raw-image://` | cùng ảnh đó (dòng 113.894) |

- ID parity SQLite = `vectors.npy` = Qdrant `img_text` = **130.428**, 0 vector thừa/thiếu, self-test
  recall@10 = 1,0 (`reports/master/index_counts.json`). Build Qwen3: 35,6 phút; nạp Qdrant 5,4 phút.
- `verify = yes`, `verify_source = human` cho 130.428 ảnh (ghi đè 230 nhãn "no" của VLM pilot Phần A);
  ảnh người đã duyệt **không bị phạt watermark**; kích thước ảnh mới biết 32,7% (lượt tải đang dừng).
- Rollback bộ 80k: `data/local/backup_80k_qwen_v2/` (catalog + vectors + manifest), nạp lại Qdrant.

### 9.1 Chất lượng trên master (244 ca, silver, nhãn sinh từ catalog master)

| Chỉ số | Bộ 80k (V2) | **Master (V2)** |
|---|---|---|
| Tên thực thể: nDCG@10 / MRR / Hit@10 | 0,985 / 0,980 / 0,99 | **1,000 / 1,000 / 1,00** |
| Tên thực thể: Precision@10 / Recall@10 thật | 0,660 / 0,903 | **0,818** / 0,808 |
| Hồi quy 104: top-10 / top-1 | 104 / 103 | **104 / 104** |
| Set query: đúng nhóm / đúng nhóm con | 92,5% / 82,5% | **93,0% / 83,0%** |
| Multi-intent: ảnh thuộc A hoặc B / đủ mọi ý | 86,0% / 20/20 | **92,5% / 20/20** |
| Truy vấn trả < 10 ảnh | 2 | 2 |

Bộ 100 thực thể đánh giá được lấy mẫu lại từ catalog master (cùng seed, khác catalog) — so sánh hai
cột là **định hướng**, không phải cùng tập. Precision@10 tăng chủ yếu vì thực thể có nhiều ảnh hơn;
Recall@10 thật giảm vì |R| lớn hơn (đúng bản chất công thức).

### 9.2 Độ trễ trên master (cache tắt, 85 truy vấn/phút)

| | Concurrency 1 | Concurrency 4 |
|---|---|---|
| p50 / p95 / p99 | 449 / **842** / 1.443 ms | 2.953 / **6.322** / 6.826 ms |
| < 1.500 ms / < 3.000 ms | **99,2% / 99,6%** | 47,5% / 50,4% |
| Bước embed truy vấn p50 / p95 | 141 / 244 ms | **2.638 / 5.680 ms** |

**Concurrency 4 không đạt SLO, do endpoint embedding**, không do pipeline: đo trực tiếp endpoint
cùng lúc — 6 request tuần tự 120–140 ms; **4 request song song thì 3/4 mất ~6 s** (LiteLLM/vLLM qua
tunnel xếp hàng). Sáng cùng ngày, trên bộ 80k, concurrency 4 vẫn đạt p95 816 ms → năng lực endpoint
thay đổi theo thời điểm (khả năng có người dùng chung). Các bước local (Qdrant, FTS, BGE rerank) không
đổi. Cần: nâng giới hạn song song/hạn mức của key, hoặc endpoint có SLA; chạy Qwen3-Embedding-4B
local không vừa GPU 6 GB (FP16 ~8 GB).
