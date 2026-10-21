# Báo cáo performance và benchmark — Heritage Image Retrieval

Ngày rà soát: **21/10/2026**, Asia/Saigon. Pipeline `b3-guarded-parse-fair-multi`.

**Kết quả chính:** snapshot master có 130.428 ảnh. Trên 100 query tên thực thể với nhãn silver, Hit@10 và nDCG@10 đạt 1,0000; Recall@10 theo toàn bộ ảnh đúng đạt 0,8083. Một lượt latency master đạt p95 **842 ms** ở concurrency 1 nhưng **6.322 ms** ở concurrency 4. Một lượt master khác có p95 **2.753 / 2.471 ms** ở concurrency 1 / 4. Chưa đủ căn cứ kết luận hệ thống giữ SLO ổn định khi phục vụ thực tế.

## 1. Phạm vi và độ tin cậy của bằng chứng

| Loại bằng chứng | Nguồn | Cách sử dụng |
|---|---|---|
| Quality master, 244 ca | [master/quality/eval.json](../reports/master/quality/eval.json) | Nguồn chính cho chất lượng; có kết quả từng query |
| Latency master, 2 mức concurrency | [master/latency.json](../reports/master/latency.json) | Benchmark latency chính; không có trace từng request trong JSON |
| Lượt master bổ sung | [v2/latency.json](../reports/v2/latency.json), [v2/quality/eval.json](../reports/v2/quality/eval.json) | Cho thấy khác biệt giữa các lượt; tên thư mục `v2` không đồng nghĩa dataset 80k |
| Lượt V2 đúng dataset 79.999 | [v2/_index79999/latency.json](../reports/v2/_index79999/latency.json) | Tham khảo lịch sử, không trộn với master |
| A/B cùng pool | [v2/rerank_ab.json](../reports/v2/rerank_ab.json) | So reranker riêng trên ứng viên đóng băng |
| Verify pilot | [verify/report.json](../reports/verify/report.json) | Kết quả Phần A trên nguồn 80k cũ, không đại diện toàn master |
| KG seed | [kg/seed.json](../reports/kg/seed.json) | Thống kê dữ liệu quan hệ và chi phí đã ghi; chưa phải benchmark multi-hop |
| Kiểm tra trong lần review | [checks.json](../reports/project_review/checks.json), [evidence.json](../reports/project_review/evidence.json) | Frontend chạy mới, đối chiếu local SQLite/NPY và kiểm lại summary từ raw results |

Các benchmark có sẵn được phân tích lại, **không được chạy lại model/API** trong lần review. Evidence ghi SHA256 của các file nguồn quan trọng để nhận biết khi kết quả bị thay đổi. Các file benchmark gốc chưa có đầy đủ timestamp, hardware và commit của từng lượt; không suy ra thứ tự chạy chỉ từ tên thư mục.

Toàn bộ relevance của 244 ca Phần B được tự sinh từ `entity_id` hoặc category trong catalog: **silver**, chưa phải gold người gán độc lập. Nhãn `human_verified` của ảnh trong catalog là nguồn chấp thuận ảnh, không phải relevance judgment độc lập cho từng query.

## 2. Môi trường và dữ liệu benchmark

### 2.1. Môi trường được báo cáo

| Thuộc tính | Snapshot latency master |
|---|---|
| OS / Python | Windows 11, `Windows-11-10.0.26300-SP0` / Python 3.12.10 |
| GPU | NVIDIA GeForce RTX 4050 Laptop GPU |
| Embedding | API `qwen3-embedding-4b`, 2.560 chiều theo index manifest |
| Rerank | `local_ce`, `BAAI/bge-reranker-v2-m3` |
| Vector store | Qdrant |
| Parse | `ambiguous_only`; LLM `google/gemini-3.5-flash-lite` |
| Query / pool | `top_k=10`; workspace đặt `RERANK_TOP_K=24` |
| Cache latency | `warm_uncached`: model/kết nối warm; tắt đọc cache search, LLM parse và LLM rerank theo script |
| Tải gửi mục tiêu | 85 query/phút; limiter embedding cấu hình 95 request/phút |
| Cách gọi | Thread gọi `retrieval.search.search()` trong cùng process, **không qua HTTP** |

CPU, RAM, VRAM đỉnh, phiên bản CUDA/driver và toàn bộ tham số phục vụ endpoint chưa được lưu đủ trong JSON master. Con số VRAM trong tài liệu triển khai cũ chưa được đo lại ở lần review, nên không dùng làm kết quả mới.

### 2.2. Tính toàn vẹn dữ liệu

| Chỉ số | Kết quả | Phạm vi bằng chứng |
|---|---:|---|
| Dòng nguồn | 130.429 | Báo cáo đếm đã lưu |
| URL hợp lệ theo báo cáo | 130.428 | Một dòng `x-raw-image://` bị quarantine |
| Ảnh SQLite / hàng vector / manifest | 130.428 / 130.428 / 130.428 | Đã kiểm tra lại trực tiếp local |
| Điểm Qdrant / orphan / missing | 130.428 / 0 / 0 | Báo cáo đã lưu; không gọi Qdrant trong review |
| Thực thể / lớp | 11.749 / 670 | Đọc lại SQLite |
| Shape / dtype vector | 130.428 × 2.560 / float32 | Header NPY và kích thước file đã được kiểm lại |
| Metadata khác nhau đã encode | 106.093 | Manifest |
| Build index | 2.134,89 giây ≈ 35,58 phút | Manifest; có thể phụ thuộc resume, không suy ra throughput encode tổng quát |
| Upload Qdrant | 325,1 giây | [phase2/vector_store.json](../reports/phase2/vector_store.json), snapshot 130.428 điểm |
| ANN recall@10 so exact | 1,0000; 500 vector mẫu | Self-test đã lưu, xử lý hòa điểm bằng ngưỡng score |

ANN recall trên vector đã có trong index đo độ gần của ANN với exact search; **không phải Recall@10 semantic của truy vấn người dùng**. Review chỉ đọc header/shape và kích thước NPY, chưa quét lại giá trị hữu hạn hoặc chuẩn hóa từng vector.

`reports/master/index_counts.json` yêu cầu `require=130429`, trả `ok=false` và vấn đề `indexed 130428 < required 130429`. Vì vậy parity đạt nhưng tiêu chí đủ toàn bộ số dòng nguồn **chưa đạt**. Nếu nghiệm thu chỉ trên 130.428 URL hợp lệ, phải ghi rõ tiêu chí khác đó.

## 3. Thiết kế tập đánh giá và định nghĩa metric

### 3.1. Tập 244 ca

| Nhóm | Số ca | Cách chọn / nhãn |
|---|---:|---|
| Entity | 100 | Lấy mẫu theo catalog, seed 42; relevant là ảnh của entity được chọn |
| Regression | 104 | Tên trong `tests/fixtures/misclassified_entities.csv`; kiểm đúng entity xuất hiện và đứng đầu |
| Set query | 20 | Lấy mẫu lớp có ≥ 5 entity, seed 7; query `các <tên lớp rút gọn>` |
| Multi-intent | 20 | Ghép hai entity theo seed 7; kiểm ảnh thuộc hai ID và coverage tự báo |
| Multi-hop / mô tả thị giác / truy vấn âm | 0 ca có gold độc lập | Chưa có kết quả chất lượng đại diện |

Các nhóm được chấm bằng metric riêng, không gộp thành một “accuracy 244 ca”. Cùng seed nhưng đổi catalog có thể tạo tập khác; không so các dataset như một A/B duy nhất.

### 3.2. Công thức đang được dùng

Gọi `P` là tối đa 10 ảnh trả về, `R` là toàn bộ ảnh có relevance cho query và `h=|P ∩ R|`.

| Metric | Định nghĩa | Điểm cần lưu ý |
|---|---|---|
| `precision@10` trong script | `h / |P|`, bằng 0 nếu rỗng | Mẫu số là số ảnh thực trả; khác `h/10` khi trả thiếu |
| `recall@10` thật | `h / |R|` | Không đạt 1 nếu `|R|>10` và chỉ trả 10 ảnh |
| `recall@10_capped` | `h / min(10, |R|)` | Hàm `evals.harness.recall_at_k` cũ dùng công thức này; phải ghi hậu tố capped |
| Hit@10 | 1 khi `h ≥ 1`, ngược lại 0 | Trung bình là tỷ lệ query tìm được ít nhất một ảnh đúng |
| nDCG@10 | `sum(rel_i/log2(i+2)) / IDCG@10`, relevance nhị phân | IDCG có tối đa `min(10, |R|)` ảnh đúng |
| MRR | `1 / vị trí ảnh đúng đầu tiên`, 0 nếu không có | Tính trên danh sách trả về, tối đa 10 trong lượt đo này |
| Set exact / same-group precision | Tỷ lệ ảnh đúng `parent_class` / đúng tên lớp sau rút gọn | Same-group là tiêu chí rộng hơn exact |
| Multi precision | Tỷ lệ ảnh có entity ID thuộc `{A,B}` | Không thay cho tỷ lệ query có đủ cả A và B |
| Exact two-subject coverage | Query có ít nhất một hit đúng A và một hit đúng B | Đối chiếu ID được lấy mẫu |
| Reported sub-query coverage | Mọi `sub_queries[].coverage == covered` | Tự báo từ anchor/rank; có thể khác exact coverage |

Các số summary là trung bình theo query, không phải tỷ lệ trên tổng tất cả ảnh. `precision@10_quality` trong harness là metric khác: dựa vào `passes_quality`; chưa có bộ nhãn hoàn chỉnh để báo cáo chất lượng pixel theo metric đó.

Percentile trong script: sắp xếp n giá trị, lấy vị trí 0-based `min(n-1, floor(q*n))`, rồi làm tròn; không dùng nội suy. Không cộng p95 các bước để tính p95 toàn pipeline. Các lỗi request bị loại khỏi mẫu thời gian thành công nhưng đếm riêng.

Nguồn phương pháp: [eval_quality.py](../scripts/eval_quality.py), [eval_latency.py](../scripts/eval_latency.py), [harness.py](../evals/harness.py).

## 4. Kết quả chất lượng Phần B trên master

### 4.1. Entity và regression

| Chỉ số | Kết quả |
|---|---:|
| Entity cases | 100 |
| Precision theo số ảnh trả @10 | **0,8180** |
| Recall@10 thật | **0,8083** |
| Recall@10 capped | **1,0000** |
| Hit@10 / nDCG@10 / MRR | **1,0000 / 1,0000 / 1,0000** |
| Entity query trả rỗng | 0 |
| Regression đúng entity trong top-10 | **104/104** |
| Regression đúng entity top-1 | **104/104** |
| Regression được parse `single` | 104/104 |

nDCG cao cùng Precision thấp hơn 1 có thể xảy ra khi entity có ít ảnh đúng và các ảnh đó đã đứng đầu, phần còn lại là ảnh ngoài tập relevance. Recall thật giảm khi tổng số ảnh đúng lớn hơn số slot. Các metric đo những khía cạnh khác nhau, không mâu thuẫn về mặt công thức.

### 4.2. Set query và multi-intent

| Chỉ số | Kết quả |
|---|---:|
| Set: precision exact class | **0,8300** |
| Set: precision same-group | **0,9300** |
| Set: số entity khác nhau trung bình | 4,00 |
| Set: intent được parse đúng `set_query` | **14/20 = 70%** |
| Multi: intent `multi_intent` | 20/20 |
| Multi: precision ảnh thuộc A hoặc B | **0,9250** |
| Multi: đúng cả hai entity ID | **19/20 = 95%** |
| Multi: pipeline tự báo đủ mọi sub-query | **20/20 = 100%** |
| Multi: số ảnh trả trung bình | 9,80 |
| Toàn bộ 244 ca: câu trả 1–9 ảnh | 2; cả hai trả 8 ảnh |
| Lỗi xử lý trong quality snapshot | 0 |

Ca phân biệt hai loại coverage: **`Cacao hữu cơ và Tượng đài Kim Đồng`** có ảnh đúng entity A nhưng thiếu entity B theo ID được lấy mẫu. Pipeline vẫn báo mỗi ý đã có 5 ảnh được anchor hỗ trợ. Cần đối chiếu các entity trùng/gần tên và nhãn relevance; chưa đủ căn cứ quy toàn bộ chênh lệch cho lỗi ảnh hoặc lỗi metric.

Sáu ca set query bị phân loại khác gồm năm câu chứa `&` bị tách thành multi-intent và `các chùa khmer nam tông` thành single. Riêng câu `các nghĩa trang liệt sĩ vùng trung du & miền núi bắc bộ` có same-group precision 0,5. Chi tiết từng ca có trong CSV đính kèm.

### 4.3. Độ nhạy giữa các snapshot chất lượng

`reports/v2/quality/eval.json` có cùng model/pipeline và metric entity như master, nhưng set precision exact / same-group chỉ **0,7850 / 0,8850**, số câu trả thiếu là 3. Quality latency p95 lần đó là **2.437 ms**, trong khi snapshot master là **713 ms**.

Lượt quality chỉ tắt đọc search cache; cache parse/rerank không được tắt theo cùng quy trình của latency benchmark. Các con số này cho thấy biến động lượt chạy và phải được lưu riêng; không thay thế kết quả warm-uncached ở mục 5.

## 5. Latency, throughput và SLO

### 5.1. Phương pháp đo thực tế

`scripts.eval_latency` khởi động bằng **3 query warm-up**, sau đó chạy 244 query cho từng mức concurrency. Thứ tự được xáo bằng seed `13 + concurrency`. Đây là 488 lần gọi search được ghi trong hai lượt master chính.

Thời gian chờ pacing để giữ tải 85 query/phút được đặt **trước timer của request**. Thread gọi hàm search trực tiếp, nên không đo HTTP, middleware auth/CORS, serialization và mạng giữa client–server. Report tổng chỉ lưu summary, chưa lưu timestamp/trace từng request để phân tích lại phân phối hoặc confidence interval.

Quy trình 200 warm-up và 10.000 request mỗi loại trong tài liệu cũ là yêu cầu đề xuất, **chưa phải quy trình đã thực hiện** của snapshot này. Cũng chưa có bằng chứng đã chạy đầy đủ `none/local/gemini` hoặc benchmark riêng `/embed` và `/rerank` qua HTTP.

### 5.2. Lượt master chính — 130.428 ảnh

| Metric | Concurrency 1 | Concurrency 4 |
|---|---:|---:|
| Số request / lỗi | 244 / 0 | 244 / 0 |
| p50 | 449 ms | 2.953 ms |
| **p95** | **842 ms** | **6.322 ms** |
| p99 | 1.443 ms | 6.826 ms |
| Max | 8.018 ms | 7.184 ms |
| Tỷ lệ < 1.500 ms | 99,18% | 47,54% |
| Tỷ lệ < 3.000 ms | 99,59% | 50,41% |
| Warning chứa 429 / warning suy giảm được đếm | 0 / 0 | 0 / 0 |
| `rule (llm timeout)` | 20 | 7 |
| Wall time | 186,7 giây | 274,5 giây |
| Throughput quan sát | 1,31 query/giây | 0,89 query/giây |
| SLO p95 < 1.500 ms | **Đạt trong lượt này** | **Không đạt** |

0 warning suy giảm không đồng nghĩa không có timeout parse: timeout còn được biểu diễn trong trường `parser`. Bộ đếm `warnings_degraded` đếm chuỗi warning khớp tiền tố, không phải tỷ lệ request lỗi.

### 5.3. Theo nhóm query

| Nhóm | Số ca/mức concurrency | C1 p50 / p95 (ms) | C4 p50 / p95 (ms) |
|---|---:|---:|---:|
| Entity | 100 | 400 / 979 | 2.644 / 6.132 |
| Regression | 104 | 452 / 801 | 3.100 / 6.349 |
| Set | 20 | 719 / 842 | 4.386 / 7.184 |
| Multi-intent | 20 | 679 / 900 | 2.398 / 6.546 |
| Multi-hop | Chưa đo | — | — |

Report gốc chỉ có p50/p95 theo nhóm; **chưa có p99 theo nhóm**. Đặc biệt 20 query là mẫu nhỏ để suy rộng về tail latency.

### 5.4. Theo bước xử lý

| Bước | C1 p50 / p95 (ms) | C4 p50 / p95 (ms) |
|---|---:|---:|
| Rule parse | 0 / 1 | 0 / 1 |
| Embed query | **141 / 244** | **2.638 / 5.680** |
| Dense search | 30 / 43 | 26 / 40 |
| `retrieve`: lexical, tên và fusion | 105 / 239 | 113 / 210 |
| Phần chờ LLM còn lại | 0 / 410 | 0 / 0 |
| Rerank | 96 / 218 | 200 / 562 |

Độ trễ bước embed tăng mạnh nhất khi C4, phù hợp giả thuyết endpoint hoặc hàng đợi trước endpoint là điểm nghẽn chính trong lượt này. Timing embed bao gồm gọi API, limiter và retry có thể phát sinh; thiếu trace riêng để kết luận chính xác phần nào gây chậm. Rerank C4 cũng tăng, nên không loại trừ tranh chấp tài nguyên local. Đây là suy luận từ timing, chưa phải thí nghiệm cô lập nguyên nhân.

### 5.5. Các lượt khác và độ ổn định

| Dataset / nguồn | C1 p50 / p95 / p99 (ms) | C4 p50 / p95 / p99 (ms) |
|---|---:|---:|
| 79.999 ảnh, `v2/_index79999/latency.json` | 550 / 954 / 1.203 | 532 / 816 / 1.065 |
| 130.428 ảnh, `master/latency.json` | 449 / 842 / 1.443 | 2.953 / 6.322 / 6.826 |
| 130.428 ảnh, `v2/latency.json` | 1.625 / 2.753 / 3.153 | 1.053 / 2.471 / 2.696 |

Tất cả báo `warm_uncached`, tải mục tiêu 85 query/phút và cùng pipeline/model chính. Kết quả khác nhau đáng kể; khác dataset, thời điểm, trạng thái endpoint và process chưa được kiểm soát đầy đủ. Không dùng bảng này để tuyên bố tăng dữ liệu làm latency giảm, hoặc V2 đạt SLO ổn định trên mọi lần chạy.

### 5.6. Throughput và chi phí

Throughput 0,89–1,31 query/giây trong lượt chính là **tải thực hoàn thành dưới pacing**, chưa phải công suất tối đa của hệ thống. Một request embedding có thể chứa nhiều sub-query; parse lại, input lớn hoặc rerank qua API có thể tăng số lần gọi. 95 request/phút của limiter không tương đương 95 truy vấn/phút được bảo đảm ở mọi loại query, và limiter không chia sẻ giữa các process.

Chưa có breakdown chi phí tổng cho embedding, rerank local, lưu trữ và vận hành. Delta usage LLM trong quality master chỉ mô tả lượt đó; có tác vụ nền và cache, nên không ngoại suy thành tổng chi phí/query hoặc chi phí một triệu ảnh. Không coi các số USD giả định trong `pipeline/routing.py` là benchmark tài chính.

## 6. A/B reranker trên pool đóng băng

244 query, pool trung bình **24 ứng viên**, chỉ thay reranker trong phép chấm offline. `candidate_entity_recall@pool=1,0` trong báo cáo là tỷ lệ query entity có **ít nhất một** ảnh relevant trong pool, không phải thu hồi toàn bộ ảnh relevant. Không phải phép đo end-to-end master sau mọi policy V2.

| Metric | Fusion | Jina API | BGE local | Qwen3-0.6B local | Gemini LLM |
|---|---:|---:|---:|---:|---:|
| Entity nDCG@10 | 1,0000 | 0,9910 | 0,9497 | 0,9489 | 0,9458 |
| Entity MRR | 1,0000 | 0,9950 | 0,9499 | 0,9505 | 0,9812 |
| Entity Precision@10 theo số trả | 0,6630 | 0,6590 | 0,6370 | 0,6420 | 0,6110 |
| Entity Recall@10 thật | 0,9140 | 0,9104 | 0,8806 | 0,8769 | 0,8604 |
| Entity Recall@10 capped | 1,0000 | 0,9959 | 0,9634 | 0,9625 | 0,9396 |
| Entity Hit@10 | 1,0000 | 1,0000 | 0,9900 | 0,9900 | 0,9900 |
| Set group precision | 0,8150 | 0,8950 | **0,9750** | **0,9750** | 0,9350 |
| Multi precision A hoặc B | 0,7450 | 0,7650 | 0,7750 | 0,7850 | 0,7950 |
| Multi có đủ hai entity | 1,0000 | 0,6500 | 0,8500 | 0,7500 | 1,0000 |
| Rerank p50 / p95 (ms) | — | 135,9 / 184,7 | **109,4 / 150,9** | 580,2 / 1.089,1 | 6,0 / 9,7* |
| Rerank max (ms) | — | 30.280,8 | 1.123,0 | 3.725,7 | 3.612,9* |

\* Gemini có cache trong phép đo; **6–10 ms không phải latency inference LLM uncached**. Các backend không cùng điều kiện cache/mạng, nên bảng latency chưa phải so sánh công bằng tuyệt đối giữa tất cả phương án. JSON đã lưu cũng không có trường lỗi cho từng backend như phiên bản script hiện tại có thể tạo.

BGE và Qwen3-0.6B có cùng set group precision trong phép thử, BGE có p95 thấp hơn khoảng **7,2 lần**. Fusion đã rất tốt cho entity chính xác nhưng BGE nâng set precision; đó là căn cứ chọn BGE cùng chính sách ưu tiên entity. Kết quả A/B chưa chứng minh một reranker tốt nhất cho mọi nhóm query.

## 7. Performance và chất lượng Phần A

### 7.1. Dataset và kết quả xử lý

Nguồn của [verify/report.json](../reports/verify/report.json) là **CSV 80.000 ảnh cũ**, pilot 400 nhóm tên, target TEST, alpha 0,15. Không áp dụng tỷ lệ của pilot cho toàn bộ master 130.428 ảnh.

| Chỉ số | Kết quả |
|---|---:|
| Gate: nguồn / live / loại | 80.000 / 79.208 / 792 |
| Lý do loại | 787 blocked, 4 whitespace, 1 invalid |
| Dòng pilot | 3.240 |
| Fetch `ok` / dead / trùng SHA trong entity | 3.151 / 83 / 6 |
| Bản TEST trùng nội dung qua split bị bỏ | 1 |
| Ảnh có embedding và nhãn bootstrap | 3.150 |
| Head TRAIN / VAL có nhãn | 1.888 / 367 |
| Target TEST có nhãn bootstrap | 895 |
| Input head / C được chọn | 782 chiều / 0,01 |
| Router chọn / target | 134/895 = 14,97% |
| Nhóm TEST / median ảnh `yes` | 118 / 4 |
| Tỷ lệ nhóm có ≥3 / ≥5 ảnh `yes` | 69,49% / 45,76% |

Số fetch 3.151 `ok` và số cuối 3.150 khác nhau do bước loại nội dung trùng qua split. Không chia tổng dòng pilot cho thời gian cache để công bố tốc độ tải/encode mới.

### 7.2. Metric proxy và calibration

| Metric | Head | Jev / cascade |
|---|---:|---:|
| Đồng thuận nhãn bootstrap trên 895 ảnh | 0,9128 | Jev 0,9128; cascade 0,9162 |
| AURC, thấp hơn tốt hơn | 0,0523 | Jev 0,0649 |
| ECE confidence trên target | 0,0329 | Jev 0,2037 |
| ECE VAL trước / crossfit sau calibration | 0,0756 / 0,0470 | Jev 0,0933 / 0,0352 |
| Head ECE xác suất target trước / sau | 0,0628 / 0,0343 | — |
| Đồng thuận cascade trên phần giữ lại | — | 0,9133 |
| Đồng thuận trên phần route VLM | — | 0,9328 |

ECE dùng 10 bin: tổng có trọng số `|mean(nhãn) - mean(xác suất)|`; ECE confidence dùng nhãn đúng/sai của quyết định. Hai loại ECE không có cùng target. Risk–coverage xếp ảnh theo confidence và đánh giá lỗi trên phần giữ lại; AURC là trung bình risk theo coverage trong triển khai hiện tại.

Jev có 1.262 bản ghi quyết định trên VAL + target, defer share 19,89%, 81 bản ghi lỗi; confidence tự khai 1.000 và logprob 11 bản ghi. Jev đồng thuận head 1,0 trên phần quyết định được trong báo cáo. Chưa thấy bằng chứng lợi ích chất lượng độc lập của Jev so với head trên gold người gán.

`human_eval` vẫn ghi chưa có nhãn người. Vì vậy 91–92% ở bảng là **agreement với VLM bootstrap**, không được gọi là accuracy đối với thực tế.

### 7.3. Duyệt nguồn và chi phí

`approved_flag_eval` có 895 ảnh đều `approved`, không có negative. Tỷ lệ cascade đồng ý giữ ảnh là **0,7654**, tương đương tỷ lệ từ chối ảnh nguồn đã chấp thuận khoảng **23,46%** theo tiêu chí này. Đây chỉ đo mặt false-reject, không suy ra false-accept, specificity hoặc độ chính xác trên hai lớp. Khi cho phép watermark, mức đồng ý của VLM teacher tăng từ 0,7039 lên 0,9263; cần thống nhất quy ước nhãn trước khi đánh giá.

Tổng thời gian report là **21,16 giây**; download 0,03 giây và encode 0,02 giây vì dùng lại dữ liệu cache. Cost Jev của lượt đó ghi 0 request và 0 USD; không có nghĩa pipeline ban đầu không tốn tiền. Chưa có benchmark tải/encode/VLM lạnh end-to-end hoặc chi phí tổng trên toàn master.

## 8. KG và multi-hop

Seed report ghi **17 người**, **205 cạnh nơi chốn** gồm 99 `BURIED_AT`, 5 `WORSHIPPED_AT`, 101 `MEMORIAL_AT`; 14/15 claim người–người được xác minh, chi phí ghi nhận **0,0878 USD**. Một số claim đã dùng cache.

SQLite đọc lại có 99/101/5 cạnh nơi chốn tương ứng, `PARENT_OF` 24 hàng với 12 hàng tin cậy và `SPOUSE_OF` 5 hàng với 2 hàng tin cậy. Bảng có thể giữ nhiều bản ghi nguồn hoặc claim chưa xác minh; số hàng không đồng nghĩa số quan hệ ngữ nghĩa khác nhau.

Chưa có bộ query multi-hop với đích do người gán độc lập để đo seed linking, relation precision/recall, chain accuracy, image Hit@10, hallucination rate hoặc p95 online. Việc unit test resolver có fixture không thay thế benchmark dữ liệu thật. Trạng thái `resolved` cũng không tự chứng minh cạnh đúng về lịch sử nếu nguồn hoặc mapping tên sai.

## 9. Kiểm tra chạy mới và khoảng trống nghiệm thu

| Kiểm tra trong review | Kết quả |
|---|---|
| SPA `npm.cmd test` | **18/18 pass**, 2 file test: adapter 13, contract 5 |
| SPA `npm.cmd run typecheck` | **Pass**, `tsc` không có diagnostic |
| Python pytest | **Chưa khởi chạy được**: launcher của `.venv-gpu` trỏ tới Python WindowsApps không chạy được; `py -3.12` cũng không khởi tạo process |
| Collector local | Đạt: count SQLite/manifest/NPY, dtype/file size, 244 ca, kiểm lại trung bình metric entity và hai loại coverage |
| HTTP load test, benchmark model/API mới, full browser E2E | Chưa chạy trong review |

Không lấy số “256 test pass” từ tài liệu cũ làm kết quả chạy mới. Vấn đề interpreter chưa phải một test assertion thất bại, nhưng backend chưa được xác nhận lại ở workspace hiện tại.

| Tiêu chí | Trạng thái có thể kết luận |
|---|---|
| SLO p95 < 1.500 ms ổn định trên master | **Chưa đạt bằng chứng**; đã có lượt không đạt ở cả C1 và C4 |
| Quality entity trên silver master | Đạt các ngưỡng Hit/nDCG/MRR của harness cho nhóm 100 ca này |
| Recall thật ≥0,70 trên nhóm entity silver | 0,8083, đạt trong snapshot; không phải kết luận cho mọi intent |
| 100% ảnh nguồn được index | Chưa đạt; thiếu 1 URL hợp lệ để thay dòng quarantine |
| Đúng intent mọi set query | Chưa đạt; 14/20 |
| Đúng cả hai entity mọi multi-intent | Chưa đạt; 19/20 |
| Accuracy kiểm duyệt ảnh / relevance gold | Chưa đủ nhãn độc lập |
| SLO HTTP, cold start, nhiều worker, tất cả mode | Chưa đo đầy đủ |

## 10. Tái lập và bàn giao

Lệnh, điều kiện và tiêu chí chấm ở [test-cases.vi.md](test-cases.vi.md). Sau khi khôi phục Python, hãy dùng thư mục output mới cho mỗi lượt để giữ nguyên bằng chứng hiện có. Chạy script evaluation có thể gọi API theo cấu hình và ghi cache/usage; đó là một lượt benchmark mới cần lưu model, dữ liệu và điều kiện riêng.

Các file bàn giao:

- [244 ca dạng CSV](../reports/project_review/benchmark-cases.csv): metric từng query từ quality master. `quality_run_ms` là thời gian trong **lượt quality**, không phải trace latency warm-uncached ở mục 5; ô metric không áp dụng để trống.
- [Evidence JSON](../reports/project_review/evidence.json): hash nguồn và kết quả kiểm tra lại dữ liệu local.
- [Collector](../reports/project_review/collect_evidence.cjs): tái xuất evidence và CSV bằng Node, không gọi HTTP hoặc model.
- [Checks JSON](../reports/project_review/checks.json): các lệnh và trạng thái đã quan sát trong lần rà soát này.

Những thông số còn thiếu cho lượt đo kế tiếp: CPU/RAM/driver, process/worker count, readiness, cache đầy đủ, thời điểm chạy, endpoint capacity, request trace qua HTTP, p99 từng intent, bộ nhãn gold và khoảng tin cậy. Các trường chưa đo được để trống hoặc ghi chưa đo; không thay bằng ngân sách thiết kế.
