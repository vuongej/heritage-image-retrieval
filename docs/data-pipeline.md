# PHẦN A — Pipeline lọc ảnh tự động, scale 10–100M

## 1. Cascade 3 tầng

| Tầng | Chạy trên | Kiểm tra | Vai trò |
|---|---|---|---|
| **Stage 1** Heuristics | CPU | `width >= 600`, `height >= 400`, aspect ∈ [0.4, 3.0], Laplacian variance, entropy, pHash Hamming ≤ 6, mật độ cạnh 4 góc | Loại rẻ, loại chắc chắn — **trước khi tốn GPU** |
| **Stage 2** Small classifier | GPU (ONNX) | 5 head: `relevance`, `watermark`, `nsfw`, `violence`, `politics` | Quyết định phần lớn; xuất xác suất để định tuyến |
| **Stage 3** VLM | API batch / local | Gemini 3.5 Flash-Lite đọc ảnh + `leaf_label` + `description`, trả JSON verdict | **Chỉ ~8% dải bất định** |

## 2. Định tuyến theo dải bất định

```
p >= 0.70        -> ACCEPT
0.35 < p < 0.70  -> VLM (chỉ ~8% tổng số ảnh; hiệu chỉnh bằng calibration curve)
p <= 0.35        -> REJECT
```

Khi `LLM_PROVIDER=none`: dải bất định đẩy sang `human_review_queue` thay vì gọi VLM.
Cascade còn **2 tầng** và chi phí API = **$0**.

## 3. Cost model (giả định có ghi rõ — thay bằng số đo thực khi có key)

| Tầng | Thông lượng giả định | Đơn giá hạ tầng | $/1M ảnh | 10M ảnh | 100M ảnh |
|---|---|---|---|---|---|
| Stage 1 CPU (16 vCPU ≈ 640 ảnh/s) | 2,3M ảnh/giờ | $0,68/h (c5.4xlarge) | ≈ $0,30 | $3 | $30 |
| Stage 2 GPU (1×L4, batch 128, fp16 ≈ 1.500 ảnh/s) | 5,4M ảnh/giờ | $0,80/h (g6.xlarge) | ≈ $0,15 | $1,5 | $15 |
| Stage 3 VLM (8% × ~1.320 tok in + 60 tok out) | Batch API | xem bảng sensitivity | $0,08 – $0,31 | $8 – $31 | **$624 – $2.496** |
| **Tổng** | | | **≈ $0,53 – $0,76** | **$12 – $35** | **$670 – $2.540** |

### Sensitivity Stage 3

| $/1M input | $/1M output | $/ảnh | 8M ảnh (100M × band 8%) |
|---|---|---|---|
| 0,05 | 0,20 | $0,000078 | **$624** |
| 0,10 | 0,40 | $0,000156 | **$1.248** |
| 0,20 | 0,80 | $0,000312 | **$2.496** |

> ⚠️ Đơn giá token tuyệt đối của Gemini 3.5 Flash-Lite **phải lấy từ trang giá chính thức tại thời
> điểm build**. Script `scripts/bench_stage3_cost.py` đo giá thật khi có `GEMINI_API_KEY`.

**So sánh:** verify **100%** ảnh bằng VLM nhân chi phí Stage-3 lên **1/0,08 = 12,5 lần**
→ tương đương **$7.800 – $31.200 cho 100M ảnh**. Đó là lý do cascade thắng.

## 4. Throughput 100M ảnh

| Tầng | Tổng thời gian | Ghi chú |
|---|---|---|
| Stage 1 | ≈ 4,3 giờ | 10 node × 2,3M/h |
| Stage 2 | ≈ 2,3 giờ | 8 × L4 × 5,4M/h |
| Stage 3 | ≈ 6,7 giờ | Batch API ~20.000 ảnh/phút |
| **Wall-clock (song song)** | **≈ 8 – 10 giờ** | pipeline streaming 3 tầng |

## 5. Vì sao Stage 3 rẻ đi nhiều

- Ảnh **resize về cạnh dài 512 px** trước khi gửi → giảm mạnh token ảnh.
- Prompt cố định + **structured output JSON schema** → output ~60 token, không sinh văn xuôi.
- **Prompt caching** cho system + tiêu chí (bất biến giữa các ảnh).
- **Batch API** → throughput cao hơn nhiều so với synchronous.

## 6. Đo chất lượng

- **Gold set 1.500 ảnh** mẫu phân tầng theo `branch × priority × query_type`, gán nhãn nhị phân từng tiêu chí.
- Chỉ số: per-criterion Precision / Recall / F1, AUC của Stage 2, confusion ở dải bất định.
- **927 ảnh `verify = no`** trong CSV nhóm 1 tái dùng làm negative seed miễn phí.
- Ngưỡng chấp nhận: Stage 2 F1 ≥ 0,90 cho `relevance`; sau VLM precision tổng ≥ 0,97.

## 7. Số liệu từ CSV nhóm 1 (đo thật)

| Chỉ số | Giá trị |
|---|---|
| Dòng | 3.226 · Entity | 500 · Ảnh/entity | 6,45 |
| `branch` | F 1.950 · D 1.207 · A 69 |
| `priority` | P1 2.692 · P0 534 |
| `verify` | yes 2.299 (71,3%) · no 927 (28,7%) |
| `so_anh_pass_master = 0` | **242 entity** |
| `entity_duoi_5_master = yes` | **478 entity** |
| Độ phân giải | median 894×675 · min 400×300 · **318 ảnh < 600 px** |
| Nguồn | laodong.vn 108 · thanhnien.vn 101 · tuoitre.vn 82 · danviet.vn 62 · mia.vn 38 · vov.vn 32 |
