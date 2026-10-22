# Benchmark router Phần A end-to-end (nhãn người `data/test.csv`)

Ràng buộc chọn cấu hình (trên VAL): Recall yes ≥ 85%, entity retention ≥ 95%; trong vùng khả thi tối đa Recall no, hòa (±0,5 điểm) thì rẻ hơn. Mọi số liệu TEST bên dưới **không** được dùng để chọn.

VLM phủ ảnh qua rule: VAL 100.0%, TEST 100.0%. Nhãn bootstrap cho P0: 4,000.

## Giai đoạn 1–2: classifier (không VLM, ngưỡng chọn trên VAL)

| Model | Nhãn | AUC | ECE | Recall no | Precision yes | Recall yes | Retention | Train s | ms/1.000 ảnh |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| P0 | VLM bootstrap | 0.649 | 0.206 | 31.3 | 70.9 | 83.6 | 96.2 | 0.9 | 2.24 |
| M0 | người | 0.718 | 0.019 | 37.9 | 73.9 | 87.7 | 95.4 | 10.3 | 2.18 |
| M1 | người | 0.650 | 0.022 | 19.0 | 69.4 | 91.8 | 96.1 | 1.3 | 0.32 |
| M1b | người | 0.735 | 0.017 | 43.2 | 75.1 | 85.5 | 95.2 | 29.5 | 2.38 |
| M2 | người | 0.735 | 0.019 | 37.9 | 74.0 | 88.2 | 96.7 | 5.0 | 1.14 |
| M3 | người | 0.738 | 0.014 | 39.5 | 74.4 | 87.9 | 96.5 | 46.1 | 6.02 |

## Giai đoạn 3: router end-to-end theo ngân sách (cấu hình chọn trên VAL, số đo TEST)

| Cấu hình | t | Đọc VLM | Gửi VLM | Recall no | Precision yes | Recall yes | Retention | Accuracy | $/1.000 ảnh | p95 ms |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| P0@0% | 0.05 | head | 0.0% | 31.3 | 70.9 | 83.6 | 96.2 | 66.2 | 0.000 | 5,112 |
| P0@5% | 0.05 | learned | 4.9% | 24.3 | 69.5 | 86.3 | 97.1 | 65.7 | 0.007 | 5,922 |
| P0@10% | 0.05 | chi_sai | 9.7% | 26.7 | 70.2 | 86.3 | 96.9 | 66.4 | 0.014 | 6,241 |
| P0@15% | 0.05 | chi_sai | 14.6% | 24.6 | 70.1 | 88.4 | 97.1 | 67.1 | 0.020 | 6,421 |
| P0@20% | 0.05 | bo_watermark | 19.4% | 29.6 | 71.3 | 87.3 | 96.6 | 68.1 | 0.027 | 6,550 |
| M0@0% | 0.525 | head | 0.0% | 37.9 | 73.9 | 87.7 | 95.4 | 71.1 | 0.000 | 5,112 |
| M0@5% | 0.575 | chi_sai | 4.9% | 42.6 | 74.7 | 84.5 | 94.0 | 70.5 | 0.007 | 5,938 |
| M0@10% | 0.525 | bo_watermark | 9.7% | 40.5 | 74.3 | 86.1 | 95.3 | 70.9 | 0.014 | 6,185 |
| M0@15% | 0.6 | chi_sai | 14.6% | 42.7 | 74.7 | 84.7 | 94.0 | 70.7 | 0.020 | 6,390 |
| M0@20% | 0.525 | bo_watermark | 19.4% | 42.3 | 74.6 | 84.8 | 94.9 | 70.7 | 0.027 | 6,498 |
| M1@0% | 0.475 | head | 0.0% | 19.0 | 69.4 | 91.8 | 96.1 | 67.5 | 0.000 | 5,112 |
| M1@5% | 0.525 | goc | 4.9% | 22.7 | 70.0 | 90.0 | 95.0 | 67.5 | 0.007 | 5,886 |
| M1@10% | 0.525 | goc | 9.7% | 28.5 | 71.0 | 87.6 | 94.6 | 67.9 | 0.014 | 6,234 |
| M1@15% | 0.525 | goc | 14.6% | 33.8 | 72.0 | 85.1 | 94.3 | 68.0 | 0.020 | 6,426 |
| M1@20% | 0.525 | bo_watermark | 19.4% | 35.4 | 72.5 | 85.3 | 94.9 | 68.7 | 0.027 | 6,551 |
| M1b@0% | 0.55 | head | 0.0% | 43.2 | 75.1 | 85.5 | 95.2 | 71.4 | 0.000 | 5,112 |
| M1b@5% | 0.55 | goc | 4.9% | 43.8 | 75.3 | 85.5 | 94.9 | 71.6 | 0.007 | 5,961 |
| M1b@10% | 0.6 | learned | 9.7% | 45.1 | 75.6 | 84.9 | 94.4 | 71.6 | 0.014 | 6,199 |
| M1b@15% **← chọn** | 0.55 | bo_watermark | 14.6% | 44.8 | 75.5 | 85.2 | 94.2 | 71.8 | 0.020 | 6,367 |
| M1b@20% | 0.55 | learned | 19.4% | 47.5 | 76.4 | 84.7 | 94.9 | 72.3 | 0.027 | 6,512 |
| M2@0% | 0.55 | head | 0.0% | 37.9 | 74.0 | 88.2 | 96.7 | 71.4 | 0.000 | 5,112 |
| M2@5% | 0.575 | goc | 4.9% | 41.2 | 74.6 | 86.2 | 94.9 | 71.2 | 0.007 | 5,894 |
| M2@10% | 0.575 | bo_watermark | 9.7% | 44.3 | 75.3 | 85.0 | 95.4 | 71.4 | 0.014 | 6,226 |
| M2@15% | 0.575 | learned | 14.6% | 46.7 | 76.0 | 84.4 | 95.7 | 71.8 | 0.020 | 6,408 |
| M2@20% | 0.55 | bo_watermark | 19.4% | 44.3 | 75.3 | 84.8 | 95.7 | 71.3 | 0.027 | 6,502 |
| M3@0% | 0.525 | head | 0.0% | 39.5 | 74.4 | 87.9 | 96.5 | 71.8 | 0.000 | 5,112 |
| M3@5% | 0.575 | chi_sai | 4.9% | 44.5 | 75.5 | 85.7 | 95.2 | 71.9 | 0.007 | 5,941 |
| M3@10% | 0.55 | bo_watermark | 9.7% | 43.1 | 75.2 | 86.1 | 95.5 | 71.8 | 0.014 | 6,207 |
| M3@15% | 0.55 | learned | 14.6% | 45.6 | 75.8 | 85.1 | 95.8 | 71.9 | 0.020 | 6,399 |
| M3@20% | 0.6 | chi_sai | 19.4% | 44.7 | 75.6 | 85.7 | 95.5 | 72.0 | 0.027 | 6,546 |
| production hiện tại (P0, t=0.5, α=15%, prompt gốc) | 0.5 | goc | 14.6% | 59.2 | 76.2 | 65.3 | 88.9 | 63.3 | 0.020 | 6,390 |

Baseline TEST: duyệt hết → Recall no 0%, Precision yes 66.7%; chỉ rule → Recall no 3.1%, Precision yes 66.8%, Recall yes 97.4%.

### So sánh cùng điểm vận hành với production hiện tại

Production hiện tại (P0, t = 0,5, α = 15%, prompt gốc) trên VAL có Recall yes 64.1%, retention 86.5%. Mỗi model mới được chỉnh trên VAL để **không thấp hơn** hai mức đó, rồi so trên TEST:

| Cấu hình | t | Đọc VLM | Recall no | Precision yes | Recall yes | Retention | Accuracy |
|---|---:|---|---:|---:|---:|---:|---:|
| production hiện tại | 0.5 | goc | 59.2 | 76.2 | 65.3 | 88.9 | 63.3 |
| M0@15% (iso production) | 0.675 | bo_watermark | 66.1 | 79.9 | 67.4 | 86.0 | 67.0 |
| M1@15% (iso production) | 0.675 | learned | 49.7 | 74.3 | 72.5 | 86.6 | 64.9 |
| M1b@15% (iso production) | 0.675 | bo_watermark | 65.7 | 80.1 | 69.2 | 86.3 | 68.0 |
| M2@15% (iso production) | 0.7 | partial_yes | 66.2 | 80.2 | 68.1 | 87.6 | 67.5 |
| M3@15% (iso production) | 0.7 | partial_yes | 67.1 | 80.4 | 67.6 | 87.6 | 67.4 |

## Giai đoạn 4: cấu hình production

**M1b@15%**: ngưỡng t = 0.55, đọc VLM = `bo_watermark`

| Chỉ số | VAL | TEST |
|---|---:|---:|
| recall_no | 46.5 | 44.8 |
| precision_no | 60.1 | 60.3 |
| f1_no | 52.4 | 51.4 |
| precision_yes | 77.0 | 75.5 |
| recall_yes | 85.4 | 85.2 |
| entity_retention | 95.2 | 94.2 |
| balanced_accuracy | 65.9 | 65.0 |
| accuracy | 72.8 | 71.8 |
| approved_share | 75.1 | 75.2 |

- Gửi VLM: 1,541 / 10,565 ảnh TEST (14.6%).
- Chi phí: **$0.020 / 1.000 ảnh** (VLM $0.020 + GPU $0.0003, giả định GPU $0.35/giờ). 10M ảnh ≈ $202; 100M ≈ $2,020.
- Latency mỗi ảnh (tải + chờ batch SigLIP2 + classifier + VLM nếu route): p50 3,436 ms, **p95 6,367 ms**.
- Throughput một máy (48 luồng tải, 1 GPU, 8 luồng VLM): **13.2 ảnh/s**, nút thắt `fetch`; theo tầng {'fetch': 13.2, 'siglip2_gpu': 287.0, 'vlm': 126.4}.

Ảnh TEST theo tầng quyết định:

| Tầng:quyết định | Số ảnh |
|---|---:|
| `head:yes` | 7,255 |
| `head:no` | 1,479 |
| `vlm:no` | 848 |
| `vlm:yes` | 693 |
| `rule:dead` | 272 |
| `rule:dup_sha256` | 18 |

Đơn giá đầu vào: VLM $0.136 / 1.000 ảnh (đo trong lượt thu), 18.43 ảnh/s (8 luồng); SigLIP2 279.1 ảnh/s; tải 13.2 ảnh/s (48 luồng). Bootstrap P0 (một lần): $0.9401.
