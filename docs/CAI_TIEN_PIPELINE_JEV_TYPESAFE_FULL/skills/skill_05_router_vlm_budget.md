# Skill 05 — Router ngân sách + tầng VLM 10–20% (T4–T5)

## Mục đích
Chia ngân sách VLM (10–20% ảnh) như bài toán knapsack theo ưu tiên entity, và thiết kế lại cách gọi VLM cho đúng tập khó nhất — nơi accuracy VLM sẽ thấp hơn 71,4% nếu giữ prompt cũ.

## Khi nào kích hoạt (Triggers)
- Sau khi Jev trả `decisions.parquet` (T3).
- Khi ngân sách α thay đổi hoặc hết tiền giữa chừng.

## Đầu vào / Đầu ra
| | Chi tiết |
|---|---|
| **Vào** | `decisions.parquet` (verify/confidence), thống kê yes/entity, ngân sách α ∈ {0.10–0.20} |
| **Ra** | `defer_set.json` (danh sách ảnh gọi VLM), `vlm_results.csv`, nhãn cuối hợp nhất |

## Quy trình từng bước — Router (T4)
1. Tập ứng viên VLM = ảnh Jev trả `defer` + ảnh entropy cao (`u = −p·ln p −(1−p)·ln(1−p)`).
2. **Ưu tiên theo entity, không ngưỡng toàn cục**:
   - Entity đang thiếu ảnh yes (<5) → đẩy thêm 2–3 ảnh sang VLM (1 ảnh đúng ở entity 3 ảnh giá trị cao hơn entity 20 ảnh).
   - Entity đã có ≥8 ảnh yes chắc chắn → cắt hẳn, không tiêu tiền.
   - Entity <5 ảnh sống sau gate (4.616 entity = 41%) → không gọi VLM để "cố"; đưa vào danh sách cần bổ sung ảnh.
3. Greedy: sắp (giảm accuracy kỳ vọng)/(chi phí), lấp đến ngân sách B = α·77.566. Thường ăn hơn ngưỡng toàn cục 3–6 điểm accuracy cùng chi phí.
4. Kiểm conformal: nếu |defer thực tế| > α, hạ xuống bằng cách bỏ các defer có confidence Jev cao nhất.

## Quy trình từng bước — VLM (T5)
1. **Gửi 8 ảnh cùng entity trong 1 message**, yêu cầu so sánh và trả mảng JSON: ảnh nào đúng chủ thể, ảnh nào lạc. "Trong 8 ảnh này ảnh nào không phải X" dễ hơn nhiều so với "ảnh này có phải X không". Token/ảnh gần như không đổi.
2. Prompt v2.0 bổ sung: (a) danh sách ảnh cùng entity; (b) luật "khác chủ thể nhưng cùng không gian văn hoá → partial"; (c) bắt buộc trả `which_is_wrong` + evidence để audit.
3. Tham số giữ nguyên pipeline cũ: `deepseek-flash`, temperature 0, `max_tokens 900`, `response_format json_object`, retry 5 lần backoff 1.5·2ⁿ × jitter, rate limit 300 rpm / 12 luồng, tự hạ concurrency khi 429.
4. 3–5% ca bất định nhất: 2 lần gọi độc lập (temperature 0.3), chỉ nhận khi đồng thuận; **không đồng thuận → nhờ Jev làm judge** (đưa mô tả output 2 lượt + state vào câu hỏi "nên defer cho người không?"); vẫn không rõ → review cho người.
5. Giá tham chiếu (đã đo): 0,19 USD/1k ảnh đêm · 0,30 thấp điểm · 0,43 cao điểm → α=15% là 11.635 request ≈ **2,21 USD đêm / 5,00 USD cao điểm**. Chạy ngoài giờ cao điểm VN (trước 08:00, 11:00–13:00, sau 17:00).

## Ví dụ
```
Entity "Chùa X" có 7 ảnh sống, Jev defer 4 ảnh, yes 2, no 1.
→ Router: entity thiếu yes (<5) → chọn 3/4 ảnh defer có confidence thấp nhất + 1 ảnh
   entropy cao nhất → 4 call VLM. Ảnh defer còn lại nhận nhãn "no (máy không chắc)".
```

## Lỗi thường gặp & nhánh dự phòng
- HTTP 402/401/403 "hết tiền" → dừng mềm ngay, phần còn lại = pending, chạy lại dùng cache 0 đồng.
- Token/ảnh tăng 10–25% khi gửi 8 ảnh/lần → đo trước trên 200 entity trước khi chạy toàn bộ.
- Link chết lúc VLM tự tải → `R2_` → đưa về `retry_later`, KHÔNG tính `no` ngay (~24% ca này người vẫn giữ).
