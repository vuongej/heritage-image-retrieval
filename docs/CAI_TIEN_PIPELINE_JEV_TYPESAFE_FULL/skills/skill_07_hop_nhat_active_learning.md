# Skill 07 — Hợp nhất, active learning & export (T6)

## Mục đích
Ghép nhãn Jev (80–90%) + nhãn VLM (10–20%) + audit người thành nhãn cuối; mua nhãn người đúng chỗ khó để retrain — đòn bẩy rẻ nhất nâng A_keep (+3…6 điểm).

## Khi nào kích hoạt (Triggers)
- Sau khi nhánh VLM trả kết quả (T5) cho mỗi batch.
- Định kỳ mỗi batch ~5.000 ảnh hoặc khi ECE trượt trên val.

## Đầu vào / Đầu ra
| | Chi tiết |
|---|---|
| **Vào** | `decisions.parquet` (Jev), `vlm_results.csv`, nhãn người audit |
| **Ra** | CSV giao người dùng (cột gốc + `verify` yes/no + `note`), `learning_curve.png`, batch retrain |

## Quy trình từng bước
1. **Hợp nhất nhãn** mỗi ảnh:
   - Jev `yes/no` (không defer) → lấy ngay; ghi `ly_do` + `confidence` vào `note` nếu là ca cảnh báo (watermark, `match=một phần`, confidence thấp).
   - Jev `defer` → VLM đã chấm → lấy nhãn VLM; ca 2-lượt không đồng thuận mà Jev-judge cũng phân vân → `no` an toàn + note "máy không chắc chắn".
   - `pending` (chưa chấm dở) → bỏ entity đó khỏi file giao (quy tắc cũ giữ nguyên).
2. **Giữ nhãn người**: dòng đã có nhãn người không bị ghi đè.
3. **Chọn mẫu audit người ~200 ảnh/batch**, stratified theo (category bucket × bin u × nhãn dự đoán) — ưu tiên ảnh có confidence Jev 0.4–0.8 (vùng mơ hồ) và ảnh defer có chi phí VLM cao.
4. **Retrain head** với nhãn người mới (nhãn người có trọng số cao hơn nhãn Jev/VLM trong loss).
5. **Vẽ learning curve** accuracy-vs-số-nhãn-người → biết khi nào ngừng mua nhãn (đường cong phẳng = dừng, tiết kiệm tiền dài hạn nhất).
6. **Export** đúng quy ước cũ: chỉ cột gốc + `note`; `review → no`; ghép các đoạn entity hoàn chỉnh thành `*_verified.csv`.

## Ví dụ note
```
verify=yes | note: "CẦN VERIFY TAY: có logo/watermark/chữ chèn; độ tự tin thấp (0.74)"
verify=no  | note: "CẦN VERIFY TAY: máy cho là sai thực thể nhưng chưa chắc (0.72)"
verify=no  | note: "máy không chắc chắn (Jev defer → VLM bất đồng thuận)" 
```

## Lỗi thường gặp & nhánh dự phòng
- Ghi đè nhãn người khi merge → luôn khóa các dòng có `assigned_member`/nhãn cũ.
- Entity dở dang do hết tiền → loại entity, không xuất dòng verify trống.
- Audit lệch hẳn vùng khó → ép quota tối thiểu 30% mẫu audit từ bin confidence 0.4–0.8.
