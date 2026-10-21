# Skill 06 — Split 70/30 & checklist đánh giá (T-đo)

## Mục đích
Chia dữ liệu 70/30 không rò rỉ (leakage) và đo để con số "accuracy 75–80% trên tập test" là số thật, không phải số đẹp.

## Khi nào kích hoạt (Triggers)
- Trước lần đầu train head (B2 trong workflow).
- Trước MỌI lần báo cáo accuracy — chạy checklist mục dưới.

## Đầu vào / Đầu ra
| | Chi tiết |
|---|---|
| **Vào** | CSV sau gate, danh sách group đã fuzzy-merge |
| **Ra** | `split.json` (train 56.433 dòng/7.899 group · test 23.567 dòng/3.379 group), sub-split train/val 45.146/11.287 |

## Quy trình từng bước
1. Chuẩn hoá `canonical_name` (bỏ dấu, lowercase, bỏ ký tự đặc biệt) làm **group key** — không dùng `entity_id` (UUID trùng địa danh: 10 group trùng tên tuyệt đối trên 26 entity_id).
2. Fuzzy-merge group còn lại bằng Jaccard token ≥ 0.9 ("Chùa X" / "Chùa X (Hà Nội)").
3. Stratified theo bucket category (479 bucket — lấy tiền tố trước `—`/`(`), shuffle seed cố định, lấy `max(1, round(0.30·n))` group/bucket vào test.
4. Kết quả thật trên file 80k: **train 56.433 dòng / 7.899 group · test 23.567 dòng / 3.379 group (70,5%/29,5%)**.
5. Trong train trích tiếp 20% làm **val** (45.146/11.287): val dùng chọn θ và kiểm ECE; **test chỉ chạm 1 lần**.
6. Chặn 3 bẫy leakage:
   - **Theo entity**: gom fuzzy match trước khi split (bước 2).
   - **Qua cache VLM**: khoá `sha256(image_url)` chỉ được xuất hiện ở MỘT phía (bạn có ~80.500 file cache cũ).
   - **Jev/VLM vừa thầy vừa giám khảo**: cấm train head bằng nhãn Jev/VLM rồi báo accuracy trên chính nhãn đó. Bắt buộc ≥300–500 ảnh test do **người** chấm, stratified theo category và bin u.

## Checklist bắt buộc khi báo cáo
| Phải báo cáo | Cách tính | Vì sao |
|---|---|---|
| Risk–coverage curve | accuracy theo α ∈ {5,10,15,20,30%} | một con số duy nhất ở 100% vô nghĩa với cascade |
| AURC | diện tích dưới risk–coverage | so sánh head A/B độc lập ngưỡng |
| ECE của Jev | \|acc − conf\| theo bin trên val | kiểm chứng "higher confidence = higher accuracy" |
| Defer rate thực tế vs θ | conformal check trên test | bảo đảm "10–20%" là bảo đảm |
| Cấp entity | %entity ≥5 yes, trung vị yes/entity trên test | mục tiêu thực là entity |
| Theo category & host | bảng chéo | 61,9% vs 30,7% — trung bình che lỗi hệ thống |
| Chi phí/1k ảnh + cache hit | log client (VLM và Jev tính riêng) | kiểm soát ngân sách |

## Ví dụ điều kiện đạt mục tiêu
```
acc_tổng = (1 − α)·A_keep + α·A_VLM|deferred
α = 15%, cần acc ≥ 0.78 → với A_VLM|deferred ≈ 0.55
   → A_keep ≥ (0.78 − 0.15·0.55)/0.85 = 0.82  (bắt buộc, không có ngưỡng cứu được)
```

## Lỗi thường gặp & nhánh dự phòng
- Chỉ tiêu "%entity ≥5 ảnh yes" bất khả thi về cấu trúc (41% entity < 5 ảnh sống; kỳ vọng 3,09 yes/entity) → đổi thành ≥3 yes + gắn cờ "cần bổ sung ảnh".
- Tính accuracy trên dòng pending/link chết như dự đoán đúng → loại khỏi mẫu số, báo riêng.
