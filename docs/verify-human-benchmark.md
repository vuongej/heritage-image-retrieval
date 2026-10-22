# Benchmark Phần A trên nhãn người (`data/test.csv`)

Ngày đo: 22/10/2026. Đây là lần đầu Phần A được chấm bằng **nhãn người có cả ảnh bị loại**. Các báo cáo trước ([verify-benchmark-jev.md](verify-benchmark-jev.md)) chỉ đo được mức đồng thuận với VLM thầy, hoặc chấm trên tập toàn ảnh đã duyệt.

## 1. Bộ nhãn

| | Giá trị |
|---|---|
| Ảnh có nhãn | **34.780** (4.947 entity) |
| `yes` / `no` | 23.169 / **11.611 (33,4%)** |
| Trùng index Phần B | 23.273 ảnh (23.169 yes + **104 no**) |
| Cột `note` (lý do loại) | Trống: không tách được lỗi theo tiêu chí |
| Entity ≥ 3 ảnh có cả yes lẫn no | **74,3%**, tức là người loại theo từng ảnh chứ không loại cả entity |

Split theo **nhóm tên** (seed 42, cùng thuật toán với pipeline): TRAIN 19.349 / VAL 4.866 / TEST 10.565 ảnh. Head train trên TRAIN, chọn `C` và hiệu chỉnh isotonic trên VAL. Mọi số liệu dưới đây đo trên **TEST**, phần không được dùng để chọn tham số hay ngưỡng.

## 2. Kết quả

Lớp dương là `no` (ảnh phải loại). **Recall loại** là tỉ lệ ảnh xấu bị chặn; **loại oan** là tỉ lệ ảnh tốt bị chặn nhầm.

### 2.1. Tầng rẻ (rule + SigLIP2 + head), toàn bộ TEST 10.565 ảnh

| Cách quyết | Accuracy | Precision loại | Recall loại | Loại oan | AUC |
|---|---:|---:|---:|---:|---:|
| Duyệt hết (baseline) | 66,7% | — | 0% | 0% | — |
| Head trên ảnh tải được | 71,8% | 67,2% | 29,5% | 7,2% | 0,718 |
| Rule + head (end-to-end) | 70,9% | 62,3% | 31,7% | 9,6% | — |

- Ở mức chính xác 95% (ngưỡng chọn trên VAL), head **chỉ tự quyết được 0,5% số ảnh**. Phần còn lại phải chuyển lên tầng trên.
- Rule `dead` (URL chết khi tải): 272 ảnh TEST, trong đó người chỉ gắn `no` cho 36%. Các ảnh này **bắt buộc phải loại**, vì không còn phục vụ được, dù lúc gán nhãn chúng vẫn đạt.

### 2.2. Tầng VLM và cascade, mẫu 100 entity TEST (582 ảnh, seed 7)

| Cách quyết | Accuracy | Precision loại | Recall loại | Loại oan | AUC |
|---|---:|---:|---:|---:|---:|
| Duyệt hết | 62,5% | — | 0% | 0% | — |
| Head | 69,1% | 72,6% | 28,0% | 6,3% | 0,728 |
| VLM, prompt gốc (đúng chủ thể **và** không watermark) | 68,2% | 54,7% | **87,6%** | **43,4%** | — |
| VLM, bỏ qua watermark | 73,4% | 62,2% | 73,9% | 26,9% | — |
| VLM, chỉ loại khi `subject = sai` | 71,6% | **78,5%** | 33,5% | 5,5% | — |
| **Head + VLM** (logistic, CV theo entity) | **76,0%** | 71,7% | 59,2% | 14,0% | **0,829** |

Risk–coverage của head + VLM:

| Tự quyết | 100% | 80% | 60% | 50% |
|---|---:|---:|---:|---:|
| Accuracy | 76,0% | 80,0% | 85,7% | 89,7% |

Lượt VLM này tốn 100 request (173k token vào, 27k token ra), tương đương **$0,145 / 1.000 ảnh**, tốc độ 18 ảnh/s với 8 luồng.

## 3. Chẩn đoán

1. **Đổi mô hình không giúp, giới hạn nằm ở feature.** Logistic với nhiều mức `C`, gradient boosting và PCA embedding đều cho AUC 0,69–0,73.
2. **Ảnh bị loại phần lớn không vì lỗi kỹ thuật.** AUC của từng feature đơn:
   - Feature zero-shot SigLIP2 (watermark, chữ chèn, chụp màn hình, poster, ảnh mờ, nsfw, chính trị…): 0,50–0,56.
   - Kích thước, host, dung lượng: 0,51–0,54.
   - Mạnh nhất là `cos_centroid` (0,63), tức "ảnh có giống các ảnh khác cùng entity không".
3. **Tiêu chí watermark của prompt lệch với người.** VLM gắn watermark cho 172 ảnh, trong đó người vẫn duyệt **87 ảnh (51%)**. Bỏ tiêu chí này tăng accuracy VLM từ 68,2% lên 73,4% và giảm loại oan từ 43% xuống 27%.
4. **`unsafe` không xuất hiện** trong mẫu (0/582). Bộ nhãn không đo được tiêu chí nội dung nhạy cảm.
5. **Trần của tín hiệu cấp entity:** dự đoán bằng tỉ lệ `no` của các ảnh khác cùng entity (oracle, dùng chính nhãn người) chỉ đạt AUC 0,742. Ngay cả biết trước entity nào "khó" cũng chưa đủ.

## 4. Hệ quả cho bài toán 10–100M ảnh

| | 1M ảnh | 10M ảnh | 100M ảnh |
|---|---:|---:|---:|
| SigLIP2 (RTX 4050, 279 ảnh/s) | 1 GPU-giờ | 9,7 GPU-giờ | 97 GPU-giờ |
| VLM cho **mọi** ảnh ($0,145 / 1.000) | $145 | $1.450 | $14.500 |
| Ảnh vẫn phải chuyển người nếu muốn phần tự động đạt ~90% (head + VLM, coverage 50%) | 500k | 5M | 50M |

- **Tải ảnh là nút thắt:** 2.290 s cho 30.320 ảnh với 48 luồng, tức khoảng 13 ảnh/s mỗi máy. Bước này là I/O và scale ngang theo số máy.
- Điểm head + VLM cần câu trả lời VLM cho **mọi** ảnh. Head một mình chỉ tự quyết được 0,5% ảnh ở mức 95%, nên cascade hiện **chưa cắt được chi phí VLM**: chi phí thực là cột "VLM cho mọi ảnh".- Tầng rẻ hiện tại **không thay được người hay VLM** cho tiêu chí "ảnh đúng và tiêu biểu cho địa danh". Nó chỉ chặn được ảnh hỏng, ảnh trùng và ảnh lệch hẳn khỏi cụm cùng entity.
- Để giảm chi phí VLM cần một trong các hướng sau:
  - Head học trực tiếp từ nhãn người như trong lượt này. Có 34k nhãn thì nên fine-tune thêm một lớp trên embedding ảnh + tên + mô tả, thay vì logistic.
  - Đưa thêm feature "đúng chủ thể" rẻ hơn VLM, ví dụ so khớp với ảnh tham chiếu đã duyệt của entity.
  - Hạ tiêu chí watermark trong prompt cho khớp quy ước của người duyệt.

## 5. Tái lập

```bash
# Tầng rẻ: tải + SigLIP2 + head (resumable; ~40 phút tải lần đầu)
.venv-gpu/Scripts/python -m scripts.eval_verify_human --csv data/test.csv
# Tầng VLM trên mẫu 100 entity TEST (~$0,08; câu trả lời được cache)
.venv-gpu/Scripts/python -m scripts.eval_verify_human_vlm --entities 100
```

Kết quả: `reports/verify_human/report.md`, `report.json`, `predictions.csv` (từng ảnh), `vlm_sample.json`.

## 6. Hạn chế của phép đo

- **Một người gán nhãn**, không có đo đồng thuận giữa người với người, nên chưa biết trần thực tế. Nếu hai người chỉ khớp khoảng 80% thì 76% là gần trần.
- **Mẫu VLM 582 ảnh:** khoảng tin cậy 95% của accuracy cỡ ±3,5 điểm.
- Không có lý do loại (`note`), nên không báo được recall theo từng tiêu chí của đề (độ phân giải, watermark, phản động, khiêu dâm, chính trị).
