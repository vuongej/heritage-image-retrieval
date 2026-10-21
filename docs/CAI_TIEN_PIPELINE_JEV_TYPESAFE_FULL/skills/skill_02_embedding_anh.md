# Skill 02 — Tải ảnh & Embedding một lượt (T1)

## Mục đích
Biến toàn bộ 77.566 ảnh thành vector embedding (frozen encoder), lưu `.npy` để mọi thử nghiệm sau chạy offline — không tải lại ảnh, không tốn tiền API.

## Khi nào kích hoạt (Triggers)
- Sau khi T0 gate xong, trước khi huấn luyện head.
- Khi thêm nguồn ảnh mới hoặc đổi encoder.

## Đầu vào / Đầu ra
| | Chi tiết |
|---|---|
| **Vào** | Bảng dòng sống sau gate (`image_url`) |
| **Ra** | `emb_all.npy` (~157 MB: 80k × 1024 × float16) + thư viện ảnh cache theo sha256 |

## Quy trình từng bước
1. Tải ảnh 1 lần, concurrency 32, UA trình duyệt, timeout 25s, tối đa 32 MiB. Dung lượng dự kiến ~15,6 GB (med 201 KB, p90 607 KB/ảnh).
2. Lỗi tải → vào bucket `retry_later` (3 lần, backoff) — không `no` ngay.
3. Ảnh tải được: decode bằng Pillow, loại file HTML/hỏng; **tính sha256 thật** đặt tên cache.
4. Kiểm kích thước thật: < 300×200 → `R3_too_small_actual` → `no`, không tốn forward (đo thật: 0% ảnh < 300×200 trên bộ mẫu 66 ảnh).
5. Resize cạnh dài 256, chuẩn hoá theo preprocess của encoder.
6. Forward frozen encoder — chọn theo mục tiêu:
   - Chính: `facebook/dinov3-vitb16-pretrain-lvd1689m` (frozen features mạnh nhất cho ít nhãn).
   - Cross-modal với text tiếng Việt: `google/siglip2-base-patch16-256` (so ảnh ↔ canonical_name/description).
   - Nhánh phụ cho ensemble: `facebook/ijepa_vith14_1k` (I-JEPA mạnh ở low-shot).
7. Lấy CLS token, float16, ghép một mảng, `np.save`.
8. Tốc độ tham chiếu: 300–800 ảnh/s trên 1 GPU (ViT-B/16) → 2–5 phút forward; nút cổ chai là download ~15–25 phút.

## Ví dụ
```python
import torch, numpy as np
from PIL import Image
from transformers import AutoModel
m = AutoModel.from_pretrained("facebook/dinov3-vitb16-pretrain-lvd1689m").cuda().eval()

@torch.no_grad()
def embed(paths, bs=64):
    out = []
    for i in range(0, len(paths), bs):
        batch = torch.stack([preprocess(Image.open(p).convert("RGB")) for p in paths[i:i+bs]]).cuda()
        out.append(m(pixel_values=batch).last_hidden_state[:, 0].half().cpu().numpy())
    return np.concatenate(out).astype(np.float32)

# np.save("emb_all.npy", embed(all_paths))   # ~157 MB
```

## Lỗi thường gặp & nhánh dự phòng
- Ảnh WEBP/PNG ít (5/2 trên 66 ảnh mẫu) → preprocess phải hỗ trợ đủ 3 format.
- ~4% ảnh tải không decode được (thí điểm 3/69) → gắn `dead` sau 3 lần retry, không gọi API nữa.
- GPU không có → dùng ONNX/CPU qua đêm, hoặc chỉ embed phần train trước.
