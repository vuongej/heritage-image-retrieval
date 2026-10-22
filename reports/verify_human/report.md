# Benchmark Phần A trên nhãn người

Nguồn nhãn: `data/test.csv` · 34,780 ảnh · yes 23,169 / no 11,611.
Split theo nhóm tên (seed 42): {'val': 4866, 'train': 19349, 'test': 10565}. Head train bằng nhãn người trên TRAIN, chọn C và hiệu chỉnh trên VAL; mọi số dưới đây đo trên **TEST**.

Lớp dương = `no` (ảnh phải loại). *Recall loại* = tỉ lệ ảnh xấu bị chặn; *loại oan* = tỉ lệ ảnh tốt bị chặn nhầm.

| Cách quyết | n | Accuracy | Precision loại | Recall loại | F1 loại | Loại oan |
|---|---:|---:|---:|---:|---:|---:|
| Duyệt hết (baseline) | 10,565 | 66.7% | 0.0% | 0.0% | 0.0% | 0.0% |
| Head trên ảnh tải được | 10,275 | 71.8% | 67.2% | 29.5% | 41.0% | 7.2% |
| End-to-end: rule + head | 10,565 | 70.9% | 62.3% | 31.7% | 42.0% | 9.6% |

Head: AUC **0.718**, ECE 0.019, C = 0.003.

## Tự động hóa ở mức chính xác 95%

Ngưỡng chọn trên VAL: auto-yes khi p ≥ 0.9990000128746033, auto-no khi p ≤ -0.01. Trên TEST:

- Tự quyết không cần LLM: **0.5%** ảnh, accuracy 92.5% (auto-yes 92.5%, auto-no —).
- Còn lại 99.5% chuyển VLM / người.

Risk–coverage (giữ phần head tự tin nhất):

| Coverage | Accuracy phần giữ |
|---:|---:|
| 100.0% | 71.8% |
| 95.0% | 73.0% |
| 90.0% | 74.0% |
| 85.0% | 74.9% |
| 80.0% | 75.6% |
| 70.0% | 77.3% |

## Rule chặn trước head

| Rule | Số ảnh TEST | Trong đó người cũng nói `no` |
|---|---:|---:|
| `dead` | 272 | 36.0% |
| `dup_sha256` | 18 | 55.6% |

## Theo nhóm (end-to-end, TEST)

**query_type**

| Nhóm | n | Tỉ lệ `no` | Accuracy | Recall loại | Loại oan |
|---|---:|---:|---:|---:|---:|
| TOAN_CANH | 3,280 | 28.9% | 72.4% | 27.5% | 9.3% |
| HINH_ANH | 2,090 | 33.7% | 72.0% | 36.1% | 9.7% |
| LEAF | 1,540 | 41.0% | 65.6% | 31.5% | 10.7% |
| KIEN_TRUC | 1,303 | 36.8% | 68.2% | 30.2% | 9.7% |
| DAC_SAN | 1,195 | 28.6% | 76.6% | 37.1% | 7.5% |
| PHONG_CANH | 424 | 30.9% | 70.3% | 19.9% | 7.2% |
| VAN_HOA | 344 | 36.0% | 66.6% | 35.5% | 15.9% |
| CHECKIN | 251 | 43.0% | 65.3% | 35.2% | 11.9% |
| FLYCAM | 138 | 38.4% | 71.7% | 43.4% | 10.6% |

**branch**

| Nhóm | n | Tỉ lệ `no` | Accuracy | Recall loại | Loại oan |
|---|---:|---:|---:|---:|---:|
| D | 7,124 | 33.7% | 70.3% | 30.7% | 9.6% |
| F | 2,562 | 31.1% | 73.2% | 35.1% | 9.6% |
| A | 879 | 36.5% | 68.5% | 30.5% | 9.7% |

**priority**

| Nhóm | n | Tỉ lệ `no` | Accuracy | Recall loại | Loại oan |
|---|---:|---:|---:|---:|---:|
| P2 | 6,653 | 33.8% | 70.0% | 28.8% | 8.9% |
| P1 | 3,327 | 30.8% | 73.0% | 35.4% | 10.3% |
| P0 | 585 | 41.9% | 68.5% | 42.9% | 12.9% |

**source**

| Nhóm | n | Tỉ lệ `no` | Accuracy | Recall loại | Loại oan |
|---|---:|---:|---:|---:|---:|
| 50k | 6,672 | 33.8% | 70.0% | 28.8% | 8.9% |
| 30k_p0_p1 | 3,893 | 32.4% | 72.3% | 36.8% | 10.7% |

## Thông lượng và chi phí

- Tải ảnh: 2,290.1 s cho phần chưa có cache (I/O, scale ngang theo số máy/luồng).
- SigLIP2 (cuda): 279.1 ảnh/s (33,825 ảnh mới, 0 dùng lại cache).
- Feature + train head: 13.03 s.
- VLM cho phần routed: $0.180 / 1.000 ảnh (DeepSeek, 8 ảnh/lần, đã đo).

| Số ảnh | GPU-giờ SigLIP2 | Ảnh qua VLM | Chi phí VLM (cascade) | Nếu mọi ảnh qua VLM |
|---:|---:|---:|---:|---:|
| 80,000 | 0.08 | 77,402 | $14 | $14 |
| 1,000,000 | 0.97 | 967,525 | $174 | $175 |
| 10,000,000 | 9.68 | 9,675,251 | $1,742 | $1,751 |
| 100,000,000 | 96.79 | 96,752,517 | $17,415 | $17,506 |

Ngoại suy giả định tỉ lệ tải được và phân bố khó/dễ giống tập này.
