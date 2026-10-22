# Báo cáo performance và benchmark

Cập nhật **22/10/2026**. Mọi số liệu dưới đây lấy từ một lượt chạy thật có file kết quả trong `reports/`. Lệnh tái lập ở cuối mỗi mục; phương pháp dựng test case ở [test-cases.vi.md](test-cases.vi.md).

**Tóm tắt:**

| Yêu cầu của đề | Kết quả | Nguồn |
|---|---|---|
| Index + retrieve ≥ 80.000 ảnh | **130.428 ảnh**, 11.749 entity | §1 |
| Latency < 3 s cho cả 3 loại truy vấn | **82/82 test case < 3 s**, p95 914 ms (cache tắt). Dồn tải vượt hạn mức endpoint: vẫn 100% < 3 s | §2.2 |
| Throughput rõ ràng | k6 qua HTTP, 0 lỗi / 1.282 request: truy vấn mới p95 ≤ 1.231 ms; có cache 20 req/s p95 15 ms, trần ≈ 200 req/s / worker. Truy vấn mới bị chặn bởi hạn mức endpoint (≈ 30–45 / phút) | §4 |
| Pipeline A: số liệu độ chính xác / thông lượng / chi phí | 34.780 nhãn người; cấu hình production Recall yes 85,2%, Recall no 44,8%; **$0,020 / 1.000 ảnh**; 13 ảnh/s/máy (nút thắt: tải ảnh) | §3 |

## 1. Môi trường và dữ liệu

| Thuộc tính | Giá trị |
|---|---|
| Máy đo | Windows 11, CPU 20 luồng, GPU RTX 4050 Laptop 6 GB; Docker Desktop 29.6 |
| Catalog | 130.428 ảnh (từ `data_anh_pass_master.csv`, 1 dòng URL lỗi bị loại), 11.749 entity, 670 nhóm |
| Vector | `qwen3-embedding-4b`, 130.428 × 2.560 float32 (1,3 GB), tìm cosine chính xác bằng NumPy |
| Dựng index | Import 35 s; embed 35,6 phút (106.093 đoạn metadata khác nhau, giới hạn 100 request/phút) |
| Rerank | `jina-reranker-v2` qua endpoint, 24 ứng viên |
| Image Docker | api 411 MB · web 94 MB · processor 1,88 GB (torch CPU) |
| Khởi động | api healthy sau vài giây khi index đã có; lần đầu kéo index 1,6 GB từ HF dataset ≈ 3 phút |

## 2. Pipeline B — chất lượng và latency trên 82 test case

### 2.1. Cách đo

- **Chạy:** `scripts/eval_testcases.py` gọi đúng đường `/v1/search` in-process với cấu hình giống bản deploy (`VECTOR_BACKEND=numpy`, `RERANK_BACKEND=api`).
- **Cache:** **cache kết quả tắt**, nên mọi ca đều phải embed, retrieve và rerank thật. Cache parse LLM giữ như khi người dùng hỏi lại.
- **Latency:** wall-clock của `search()`; không tính mạng trình duyệt ↔ server (phần đó đo ở §4).
- **Giãn cách 2,5 s/câu:** để nằm trong hạn mức 100 request/phút của endpoint. Có thêm lượt dồn tải (0 s) để đo hành vi khi vượt hạn mức.

### 2.2. Kết quả

| Loại | Ca | Hit@10 | Precision | nDCG@10 | MRR | p50 ms | p95 ms | max ms | < 3 s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Single (tên entity) | 30 | 100% | 87,7% | 100% | 100% | 554 | 801 | — | 100% |
| Single (tự nhiên) | 16 | 100% | 100% | 100% | 100% | 452 | 612 | — | 100% |
| Multi-intent | 15 | 100% | 97,3% | 97,5% | 100% | 564 | 1.123 | — | 100% |
| Multi-hop | 16 | 85,7% | 82,1% | 82,8% | 85,7% | 36 | 95 | — | 100% |
| Ngoài catalog | 5 | từ chối đúng 0/5 | | | | 664 | 1.190 | — | 100% |
| **Tất cả** | **82** | | | | | **509** | **914** | **1.190** | **100%** |

Thêm cho multi-intent và multi-hop:
- **Multi-intent:** mọi ý đều có ảnh đúng trong top 10 (15/15). Parser nhận đúng loại `multi_intent` 12/15; 3 ca (M07, M12, M15) bị nhận là `set_query` nhưng vẫn được tách ý và phủ đủ.
- **Multi-hop:** nhận đúng loại 16/16; 13/14 ca có đích hợp lệ được `resolved`; 2/2 ca phải từ chối thì trả 0 ảnh (gồm "ảnh con trai chủ tịch Phạm Nhật Vượng"). Multi-hop ở lần hỏi đầu tiên (chưa có cache parse LLM): p50 646 ms, p95 2.450 ms.

Phân rã theo bước (p50 / p95, ms):

| Bước | Single | Multi-intent |
|---|---|---|
| Embedding truy vấn (endpoint) | 138 / 246 | 160 / 205 |
| Dense (NumPy 130k × 2.560) | 45 / 85 | 88 / 126 |
| BM25 + khớp tên + RRF | 81 / 187 | 48 / 129 |
| Filter metadata | 24 / 55 | 22 / 48 |
| Rerank (endpoint) | 162 / 296 | 182 / 329 (song song từng ý) |

Nguồn: [reports/testcases/report.md](../reports/testcases/report.md), từng ca ở [results.jsonl](../reports/testcases/results.jsonl).

### 2.3. Khi vượt hạn mức endpoint

| Chế độ | Ca suy giảm | p50 ms | p95 ms | max ms | < 3 s |
|---|---:|---:|---:|---:|---:|
| Giãn cách 2,5 s | 0% | 509 | 914 | 1.190 | 100% |
| Dồn tải (0 s) | multi-intent 100% | 345 | 518 | 574 | 100% |
| Dồn tải, **trước** khi có hạn chờ tổng | 25–33% | 415 | 4.309 | 30.627 | 89% |

Trước khi sửa, limiter phía client chờ tới 30 s khi hết hạn mức. Sau khi thêm **hạn chờ tổng 2,7 s / request** ([retrieval/budget.py](../retrieval/budget.py)):
- hết slot thì bỏ nhánh dense hoặc rerank ngay, dùng FTS5 + khớp tên + thứ tự RRF;
- kết quả suy giảm có warning và không được cache.

Chất lượng ở chế độ suy giảm gần như không đổi trên bộ test này, vì khớp tên đóng vai trò chính.

## 3. Pipeline A — chất lượng, thông lượng, chi phí

### 3.1. Chất lượng trên nhãn người (TEST 10.565 ảnh)

Nguồn: [verify-router-benchmark.md](verify-router-benchmark.md), [reports/verify_router/report.md](../reports/verify_router/report.md).

Lớp dương là `no`:
- **Recall no:** tỉ lệ ảnh xấu bị chặn.
- **Precision yes:** độ sạch của kho sau lọc.
- **Recall yes:** tỉ lệ ảnh tốt được giữ.
- **Retention:** tỉ lệ entity còn ảnh tốt.

| Classifier (không VLM) | AUC | Recall no | Precision yes | Recall yes | Retention | Suy luận ms / 1.000 ảnh |
|---|---:|---:|---:|---:|---:|---:|
| Head production cũ (nhãn VLM thầy) | 0,649 | không đạt ràng buộc | | | | 2,2 |
| Logistic, nhãn người | 0,718 | 37,9% | 73,9% | 87,7% | 95,4% | 2,2 |
| LightGBM 14 feature | 0,650 | 19,0% | 69,4% | 91,8% | 96,1% | 0,3 |
| **LightGBM 782 chiều (M1b)** | **0,735** | **43,2%** | **75,1%** | 85,5% | 95,2% | 2,4 |
| MLP trên embedding | 0,735 | 37,9% | 74,0% | 88,2% | 96,7% | 1,1 (GPU) |
| Stacking | 0,738 | 39,5% | 74,4% | 87,9% | 96,5% | 6,0 |

| M1b + router, ngân sách VLM | 0% | 5% | 10% | **15%** | 20% |
|---|---:|---:|---:|---:|---:|
| Recall no | 43,2% | 43,8% | 45,1% | **44,8%** | 47,5% |
| Precision yes | 75,1% | 75,3% | 75,6% | **75,5%** | 76,4% |
| Recall yes | 85,5% | 85,5% | 84,9% | **85,2%** | 84,7% |
| $ / 1.000 ảnh | 0,0003 | 0,007 | 0,014 | **0,020** | 0,027 |
| Latency p95 / ảnh | 5,1 s | 6,0 s | 6,2 s | **6,4 s** | 6,5 s |

So với production cũ ở **cùng** ngân sách 15% và cùng mức giữ ảnh:

| | Recall no | Precision yes | Recall yes | Retention |
|---|---:|---:|---:|---:|
| Production cũ | 59,2% | 76,2% | 65,3% | 88,9% |
| M1b@15% | 65,7% | 80,1% | 69,2% | 86,3% |

### 3.2. Thông lượng và chi phí từng tầng

| Tầng | Đo được | Ghi chú |
|---|---|---|
| Gate | 80.000 dòng / 1,4 s | Rule thuần |
| Tải ảnh | **13,2 ảnh/s** mỗi máy (48 luồng); p50 3,3 s, p95 5,1 s / ảnh | **Nút thắt**, phụ thuộc host gốc; 2,5% URL chết |
| SigLIP2 | **279 ảnh/s** GPU (RTX 4050) · **8 ảnh/s** CPU (container Docker) | 34k ảnh: 2 phút trên GPU |
| LightGBM M1b ×5 | 2,4 ms / 1.000 ảnh (CPU) | Train lại: 25 s cho 5 model |
| VLM (DeepSeek, lô ≤ 8) | 18,4 ảnh/s với 8 luồng; p95 3,0 s / lô; **$0,136 / 1.000 ảnh được chấm** | 14.441 ảnh, $1,96, 2 lô lỗi / 2.893 |
| Cả luồng, cấu hình production | **$0,020 / 1.000 ảnh** đầu vào (VLM 14,6% + GPU $0,35/giờ) | |

Ngoại suy (giả định tỉ lệ tải được và tỉ lệ ảnh khó như tập đo):

| Số ảnh | GPU-giờ SigLIP2 | Ảnh qua VLM (15%) | Chi phí VLM + GPU | Máy tải ảnh cần để xong trong 24 giờ |
|---:|---:|---:|---:|---:|
| 1 triệu | 1 | 146.000 | ≈ $20 | 1 |
| 10 triệu | 10 | 1,46 triệu | ≈ $202 | 9 |
| 100 triệu | 100 | 14,6 triệu | ≈ $2.020 | 88 |

So sánh: cho VLM chấm mọi ảnh ≈ $13.600 / 100M ảnh (6,7 lần cấu hình production), chưa kể thời gian: ở 18 ảnh/s (8 luồng) mất ~64 ngày cho 100M ảnh nếu không tăng song song và hạn mức API.

### 3.3. Processing service end-to-end (qua giao diện / API)

| Lượt | Thiết bị | Ảnh | Tổng | Tải | SigLIP2 | Classifier | VLM | Chi phí | Throughput |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Dev local | GPU | 307 | 41,5 s | 25,8 s | 11,6 s (25,7 ảnh/s, gồm nạp model) | 37 ms | 4,1 s (44 ảnh) | $0,0048 | 7,4 ảnh/s |
| `docker compose` | CPU | 307 | 56,1 s | 13,7 s | 38,6 s (8,0 ảnh/s) | 80 ms | 3,7 s (44 ảnh) | $0,0034 | 5,5 ảnh/s |

Nguồn: [reports/process_docker_sample.json](../reports/process_docker_sample.json). Lần chạy lại cùng file dùng cache ảnh và embedding nên chỉ còn bước classifier + router + VLM.

## 4. Load test HTTP (k6, reproducible)

### 4.1. Cách đo

- **Công cụ:** k6 1.3.0 chạy trong docker compose (`--profile loadtest`). Gọi `POST /api/v1/search` **qua web proxy Caddy**, đúng đường trình duyệt dùng; stack đầy đủ api + processor + web trên cùng máy.
- **Truy vấn:** 82 truy vấn của bộ test case ([loadtest/queries.json](../loadtest/queries.json)), xen kẽ 3 loại.
- **Kịch bản** ([loadtest.js](../loadtest/loadtest.js)):
  - **cold:** mỗi truy vấn đúng 1 lần, header `Cache-Control: no-cache` (bỏ qua cache kết quả), nhịp 20 truy vấn/phút để nằm trong hạn mức endpoint. Đo độ trễ thật của một truy vấn mới.
  - **warm:** 20 request/s trong 1 phút, truy vấn lặp lại (có cache). Đo khả năng phục vụ.
  - **capacity:** đặt tải tăng dần để tìm trần throughput của 1 worker uvicorn.
- **Gate:** p95 của từng (pha, loại) < 3.000 ms và tỉ lệ lỗi < 1%. `make_report.py` thoát mã 1 khi vi phạm (CI dùng làm cổng chặn).

### 4.2. Kết quả (`PROFILE=standard`, 22/10/2026)

| Pha | Loại | Request | p50 ms | p95 ms | p99 ms | max ms | SLO p95 < 3 s |
|---|---|---:|---:|---:|---:|---:|---|
| cold (không cache) | single | 51 | 554 | 943 | 1.061 | 1.168 | ĐẠT |
| cold (không cache) | multi_intent | 15 | 649 | 1.231 | 1.245 | 1.248 | ĐẠT |
| cold (không cache) | multi_hop | 16 | 34 | 46 | 50 | 51 | ĐẠT |
| warm (20 req/s) | single | 737 | 8 | 11 | 12 | 12 | ĐẠT |
| warm (20 req/s) | multi_intent | 202 | 8 | 11 | 12 | 13 | ĐẠT |
| warm (20 req/s) | multi_hop | 261 | 9 | 15 | 17 | 18 | ĐẠT |

Tổng 1.282 request trong 361 s, **0 lỗi**, 0 request suy giảm, p95 phía server (`X-Response-Time`) 372 ms. Báo cáo sinh tự động: [reports/loadtest/report.html](../reports/loadtest/report.html), [report.json](../reports/loadtest/report.json).

### 4.3. Throughput

| Tình huống | Throughput | Giới hạn bởi |
|---|---|---|
| Truy vấn mới (chưa cache) | **≈ 30–45 truy vấn/phút** bền vững với đầy đủ dense + rerank. Vượt mức thì tự suy giảm, vẫn < 3 s (§2.3) | Hạn mức endpoint 100 request/phút/key; mỗi truy vấn tốn 1 embedding + 1 rerank mỗi ý |
| Truy vấn lặp lại (có cache), 1 worker | 20 req/s: p95 15 ms. **Trần ≈ 200 req/s**: đặt 300 req/s thì phục vụ 200,7 req/s, p95 1,9 s do xếp hàng, 1 lỗi timeout / 12.260 | CPU một tiến trình uvicorn |

Nguồn trần throughput: [reports/loadtest_capacity/report.json](../reports/loadtest_capacity/report.json).

Muốn tăng throughput truy vấn mới:
- tăng hạn mức / số key của endpoint;
- hoặc chạy embedding + rerank local trên GPU (`EMBED_BACKEND=torch`, `RERANK_BACKEND=local_ce`).

Muốn tăng throughput truy vấn có cache: chạy nhiều worker, đồng thời chuyển limiter sang dùng chung (Redis) để không vượt hạn mức.

## 5. Tái lập

```bash
python -X utf8 -m scripts.eval_testcases --pace 2.5           # §2.2
python -X utf8 -m scripts.eval_testcases --pace 0 --out reports/testcases_burst   # §2.3
python -m scripts.bench_verify_router                         # §3.1 (cần cache VLM của bench_verify_collect)
docker compose up -d --build && docker compose --profile loadtest run --rm k6     # §4.2
python -m loadtest.make_report reports/loadtest/raw.json -o reports/loadtest/report.html
MSYS_NO_PATHCONV=1 docker compose --profile loadtest run --rm -e PROFILE=capacity -e RATE=300   -e SUMMARY_PATH=/reports/capacity_raw.json k6                                    # §4.3
```

## 6. Giới hạn của phép đo

- Một máy laptop; latency endpoint embedding / rerank phụ thuộc mạng tới nhà cung cấp tại thời điểm đo.
- Nhãn test case Phần B ở mức entity, do người viết test case định nghĩa ([test-cases.vi.md](test-cases.vi.md) §2.1). Nhãn Phần A do một người gán, không có lý do loại.
- Chi phí GPU là giả định ($0,35/giờ); đơn giá DeepSeek theo giờ cao điểm (ngoài giờ cao điểm bằng 1/2).
- Latency từng ảnh của Pipeline A được cộng từ số đo từng tầng, không phải một luồng chạy đồng thời thật.
