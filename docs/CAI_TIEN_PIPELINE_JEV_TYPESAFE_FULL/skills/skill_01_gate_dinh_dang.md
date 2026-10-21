# Skill 01 — Gate tất định & làm sạch URL (T0)

## Mục đích
Loại các ảnh chắc chắn không dùng được **trước khi tốn bất kỳ đồng nào** cho Jev hay VLM. Đo thật trên `data_anh_pass_80000_full_pham_van_vuong.csv`: loại 2.434/80.000 dòng (3,04%), còn 77.566 ảnh để xử lý.

## Khi nào kích hoạt (Triggers)
- Luôn chạy đầu tiên trong mọi run verify, mọi batch mới.
- Khi phát hiện dòng có URL lạ (không đuôi ảnh, có khoảng trắng, host bị chặn).

## Đầu vào / Đầu ra
| | Chi tiết |
|---|---|
| **Vào** | CSV gốc (cột bắt buộc: `entity_id`, `canonical_name`, `category`, `image_url`, `description`, `from_db`) |
| **Ra** | `gate_report.json` (thống kê từng rule) + bảng dòng sống/kèm mã gate; danh sách `retry_later` cho link chết tạm thời |

## Quy trình từng bước
1. Đọc CSV `utf-8` (hoặc `utf-8-sig`), giữ mọi cột dạng chuỗi.
2. Áp lần lượt các rule, gặp rule nào khớp thì gắn mã và dừng:
   - `R1_invalid` — URL không phải http/https hoặc thiếu host (đo được: 1 dòng).
   - `R1_blocked` — URL chứa `lookaside.fbsbx.com` / `scontent.xx.fbcdn.net/login` (787 dòng).
   - `R1_ws` — URL có khoảng trắng (4 dòng).
   - `R1_noext` — URL không có đuôi ảnh `.jpe?g/.png/.webp/.gif/.avif` (**rule mới**, bắt 1.642 dòng mà pipeline hiện tại đang gọi VLM vô ích).
3. **BỎ R4 pHash** — đã đo AUC = 0,369 (tệ hơn cả ngẫu nhiên), rule chết, không giữ lại.
4. **BỎ R5 "nhân 0,5 độ tự tin"** — ảnh thật đo được 100% aspect hợp lệ 0,4–3,0; đưa trường `aspect` vào state để Jev quyết thay vì loại cứng.
5. **Đổi xử lý R2**: link chết lúc tải KHÔNG bị `no` ngay → đưa vào bucket `retry_later`, thử lại 3 lần với backoff; chỉ `no` sau lần thứ 3 (benchmark cho thấy ~24% ảnh R2 người vẫn giữ).
6. Dedupe URL trong cùng entity (giữ `image_order` nhỏ nhất); **tính sha256 thật sau khi tải** vì cột `sha256` trong CSV rỗng 100%.
7. Ghi `gate_report.json` + xuất bảng dòng sống.

## Ví dụ
```python
BLOCK = ("lookaside.fbsbx.com", "scontent.xx.fbcdn.net/login")
EXT = re.compile(r"\.(jpe?g|png|webp|gif|avif)(\?|$)", re.I)

def gate(url):
    u = url or ""
    if not u.startswith(("http://", "https://")) or not re.match(r"https?://[^/]+", u):
        return "R1_invalid"
    if any(b in u for b in BLOCK): return "R1_blocked"
    if " " in u: return "R1_ws"
    if not EXT.search(u): return "R1_noext"
    return None
# Kết quả thật trên 80k: [(None, 77566), ('R1_noext', 1642),
#   ('R1_blocked', 787), ('R1_ws', 4), ('R1_invalid', 1)]
```

## Lỗi thường gặp & nhánh dự phòng
- URL redirect qua trình rút gọn → vẫn để sống, để bước tải ảnh (T1) quyết định theo nội dung thật.
- Dòng thiếu `description` (20,1%) → KHÔNG loại; chỉ gắn cờ `has_desc=0` cho bước feature.
