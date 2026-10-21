# Skill 03 — Feature & xây state cho Jev (T2)

## Mục đích
Ghép embedding với 6 nhóm feature miễn phí thành (a) ma trận X cho head tuyến tính, (b) **state text ≤ ~500 token** để gửi Jev. Đây là nơi tín hiệu đồng thuận nội entity được tạo ra — thứ pHash đã chứng minh không làm được (AUC 0,369).

## Khi nào kích hoạt (Triggers)
- Sau khi có `emb_all.npy` (T1).
- Mỗi lần train lại head hoặc đổi schema state.

## Đầu vào / Đầu ra
| | Chi tiết |
|---|---|
| **Vào** | `emb_all.npy`, CSV sau gate |
| **Ra** | `X.npy` (embedding + 7 feature rời), `states.jsonl` (một state/ảnh cho Jev) |

## Quy trình từng bước
1. Gom ảnh theo **canonical_name đã chuẩn hoá** (bỏ dấu, lowercase) — không theo entity_id (có 10 group trùng tên qua 26 entity_id).
2. Tính 2 feature nội entity (thay pHash):
   - `cos_centroid` — cosine giữa embedding ảnh và centroid các ảnh khác cùng entity.
   - `cos_nn` — cosine với ảnh gần nhất cùng entity (bắt ảnh "lạc đàn").
3. Tính 5 feature miễn phí:
   - `host_prior` = log1p(tần suất host) — 368 host phủ 72% số dòng, tín hiệu rất mạnh.
   - `category_prior` = log1p(tần suất bucket category) — tỉ lệ yes chênh 30,7% → 61,9% theo nhóm.
   - `has_desc` (cờ), `desc_len_norm` (min(len,600)/600), `from_db`.
4. Nén thành state text ≤ ~500 token cho Jev (Jev tính tiền input $0,042/MTok, output miễn phí — 77.566 ảnh × 500 token ≈ 1,63 USD/lượt; nén về 300 token còn ~0,98 USD).
5. Ghi `states.jsonl` một dòng một ảnh.

## Ví dụ
```python
def to_jev_state(r, p_yes, f):
    # f = [cos_cen, cos_nn, host_prior, cat_prior, has_desc, desc_len_norm, from_db]
    return (f"entity: {r['canonical_name']} | query_type: {r['category']}\n"
            f"head_p_yes: {p_yes:.3f} | cos_centroid: {f[0]:.3f} | cos_nn: {f[1]:.3f}\n"
            f"host_prior: {f[2]:.2f} | cat_prior: {f[3]:.2f} "
            f"| has_desc: {f[4]:.0f} | desc_len_norm: {f[5]:.2f} | from_db: {f[6]:.0f}")
```
State mẫu:
```
entity: Cầu Maspéro (Sóc Trăng) | query_type: CHINH
head_p_yes: 0.91 | cos_centroid: 0.93 | cos_nn: 0.95
host_prior: 7.79 | cat_prior: 9.57 | has_desc: 1 | desc_len_norm: 0.69 | from_db: 1
```

## Lỗi thường gặp & nhánh dự phòng
- Ảnh đơn độc (entity 1 ảnh) → `cos_centroid`/`cos_nn` lấy chính nó = 1.0; gắn cờ `n_siblings=0` để Jev biết không có đồng thuận.
- `description` rỗng (16.110 dòng) → `has_desc=0`, `desc_len_norm=0`, vẫn giữ các feature còn lại.
- Token state vượt 500 → cắt `category` về bucket đầu tiên, làm tròn số 2 chữ số thập phân.
