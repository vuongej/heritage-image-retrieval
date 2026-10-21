# Benchmark Phần A — head vs Jev (OpenRouter) trong cascade verify

Chạy thật ngày 2026-10-20. Pilot 400 nhóm thực thể · 3.150 ảnh tải được · đánh giá trên
**TEST 895 ảnh** (không nhóm nào trùng với train/val) · ngân sách VLM α = 15%.
Báo cáo gốc: `reports/verify/report_head_only.json` (head làm tầng quyết định) và
`reports/verify/report.json` (Jev làm tầng quyết định).

## Nhãn dùng để đo

| Nguồn | Ý nghĩa | Giới hạn |
|---|---|---|
| `flag = approved` trong CSV | quyết định của người, 100% dòng = yes | không có ảnh bị loại → **chỉ đo được tỉ lệ loại nhầm** (accuracy = tỉ lệ máy nói yes) |
| Nhãn VLM bootstrap (DeepSeek, 1 ảnh/lần) | "thầy" để train head | là ý kiến của model, không phải sự thật; coi watermark là `no` |

## 1. Accuracy

| Tầng / hệ thống | So với người (`approved`) | Đồng thuận với nhãn DeepSeek |
|---|---|---|
| DeepSeek VLM chấm từng ảnh | 70,4% | — |
| DeepSeek VLM, nếu chấp nhận watermark | **92,6%** | — |
| Head (logistic trên SigLIP2) | 76,7% | 91,3% |
| Jev (typesafe/jev-router) | 76,7% | 91,3% |
| Cascade head + VLM 15% | 71,7% | 89,3% |
| Cascade Jev + VLM 15% | **76,5%** | **91,6%** |

Chất lượng confidence (dùng để chọn ảnh chuyển VLM):

| | Head | Jev |
|---|---|---|
| ECE thô (VAL) | 0,076 | 0,093 |
| ECE sau isotonic (cross-fit VAL) | 0,047 | 0,035 |
| ECE trên TEST | 0,033 | 0,030 (chỉ ảnh Jev tự quyết) |
| AURC (thấp = tốt) | **0,052** | 0,065 |
| Đồng thuận phần giữ lại khi cắt 15% ít tự tin nhất | **93,7%** | 91,2% |

## 2. Latency

| Bước | p50 | p95 | max | Thông lượng |
|---|---|---|---|---|
| Head (quyết định) | < 1 ms | < 1 ms | — | 3.150 ảnh trong 0,5 s (gồm cả train) |
| **Jev (quyết định)** | **3.133 ms** | **5.372 ms** | 12.813 ms | 1.262 ảnh / 636 s, 16 luồng ≈ 2 ảnh/s; có lỗi 429 |
| VLM DeepSeek 1 ảnh | 1.415 ms | 1.684 ms | 2.567 ms | 5,6 ảnh/s (8 luồng) |
| VLM DeepSeek 8 ảnh/lần | 2.214 ms | 2.835 ms | 3.309 ms (mỗi lần gọi) | ~7 ảnh/s |

Tài liệu nói Jev mất 70–500 ms. Đo thật qua OpenRouter chậm hơn **6–40 lần**: router gọi một LLM sinh text đầy đủ, mỗi lần ~167 token ra.

## 3. Chi phí (USD thật; DeepSeek theo giá cao điểm, ngoài giờ cao điểm = 1/2)

| | Pilot | / 1.000 ảnh | Ngoại suy 77.566 ảnh |
|---|---|---|---|
| Jev (1.181 request tính phí) | 0,275 | **0,233** | **18,05** |
| ↳ router chọn z-ai/glm-5.3-flash (74%) | | 0,117 | |
| ↳ deepseek-v4.1-flash (19%) | | 0,328 | |
| ↳ google/gemini-3.8-flash (7%) | | 1,135 | |
| DeepSeek VLM 1 ảnh/lần | | 0,238 | 18,47 (chấm 100%) |
| DeepSeek VLM 8 ảnh/lần (ảnh được chấm) | | 0,180 | |
| **Cascade head + VLM 15%** (+ bootstrap 5.000) | | | **≈ 4,2** |
| **Cascade Jev + VLM 15%** (+ bootstrap 5.000) | | | **≈ 22,2** |

Tài liệu ước tính Jev ≈ 1,63 USD cho 77k ảnh (giá $0,042/MTok, output miễn phí). Thực tế qua
OpenRouter ≈ 18 USD, tức **gấp ~11 lần**: giá là của model mà router chọn, và output có tính tiền.

## 4. Jev thực sự đang làm gì

- Trên 722 ảnh TEST Jev tự quyết (yes/no), nó **đồng ý với head 100%**.
  Theo `head_p_yes` trong state:

  | head_p_yes | Jev trả |
  |---|---|
  | ≥ 0,9 (588 ảnh) | 579 yes · 9 defer |
  | 0,7–0,9 (87) | 77 yes · 10 defer |
  | < 0,3 (208) | 61 no · **147 defer** |

  Jev chỉ đọc lại con số của head. "Defer" của nó gần như nghĩa là "head nói no".
- Ảnh Jev defer **không khó hơn**: trên đó head khớp nhãn DeepSeek 93,2%, so với 91% trên ảnh Jev tự quyết.
- Cascade Jev được 76,5% so với 71,7% **không phải vì Jev thông minh hơn**. Router chuyển các ảnh head-nói-no sang VLM; một phần được VLM đổi thành yes; mà bộ nhãn toàn approved thì thưởng mọi chữ "yes".
- Trường phân loại kém tin cậy: `ly_do = "trung_lap"` (trùng lặp) xuất hiện ở 753/895 ảnh, kể cả ảnh `verify = yes`.
- Lỗi: 81/1.262 request (6,4%) hỏng, gồm 73 JSON không hợp lệ dù đã ép `json_schema` strict (một số model được route không tuân thủ) và 7 lỗi 429. Các ảnh này bị coi là defer.
- Logprob chỉ có ở 11/1.011 câu trả lời; còn lại là confidence tự khai, tập trung ở vài giá trị 0,90 / 0,86 / 0,55.

## 5. Kết luận

| Tiêu chí | Head | Jev qua OpenRouter |
|---|---|---|
| Accuracy so với người | 76,7% | 76,7% (giống hệt) |
| Xếp hạng độ không chắc (AURC) | tốt hơn | kém hơn |
| Latency / ảnh | < 1 ms | ~3,1 s |
| Chi phí 77k ảnh | ~0 | ~18 USD |
| Lỗi | 0 | 6,4% |

Với state hiện tại (có chứa `head_p_yes`), **Jev không đem lại giá trị**. Nó tốn chi phí ngang với cho VLM nhìn từng ảnh, trong khi chỉ đọc state text.

Đòn bẩy lớn nhất cho accuracy nằm ở **tiêu chí watermark**: chấp nhận watermark thì DeepSeek khớp người 92,6%, thay vì 70,4%.

Phép thử còn thiếu (chi phí ~0,3 USD): chạy Jev **không có `head_p_yes`** trong state. Phép thử này cho biết Jev có tự suy luận được từ các feature khác (cos_centroid, host, kích thước…) hay không.
