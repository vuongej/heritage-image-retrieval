# Giao diện local + bộ test case

## 1. Chạy giao diện

```powershell
.\.venv-gpu\Scripts\python.exe -X utf8 -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Mở **http://127.0.0.1:8000/** (tự chuyển sang `/ui/`). Dán giá trị `TEST_API_KEY` trong `.env` vào ô
**X-API-Key** ở góc phải trên. Trình duyệt lưu key trong `localStorage`, chỉ trên máy này.
Không cần `npm` hay build: trang là file tĩnh `web/local/index.html` do chính FastAPI phục vụ.
Swagger vẫn ở `http://127.0.0.1:8000/docs`.

| Tab | Làm gì |
|---|---|
| **Tìm kiếm** | Gõ truy vấn hoặc bấm chip ví dụ. Kết quả hiện intent, parser, số ảnh, thời gian server/trình duyệt, cảnh báo (vàng), thanh thời gian từng bước, chip facet (bấm để tìm tiếp), lưới ảnh có mô tả. Bấm một ảnh để xem chi tiết (id, link gốc, số thực thể cùng nhóm qua `/v1/graph`). |
| **Thực thể** | Lọc 4.481 thực thể theo tên (`/v1/entities`); bấm một dòng để tìm ảnh của thực thể đó. |
| **Test cases** | 18 ca trong `evals/ui_testcases.json`. Có thể **Chạy** từng ca hoặc **Chạy tất cả**. Mỗi ca gọi API thật rồi chấm ✓/✗ theo từng điều kiện; nút **Xem kết quả** mở truy vấn đó trong tab Tìm kiếm. |

Chạy cùng bộ ca bằng dòng lệnh (dùng chung một file JSON với UI):

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.run_ui_testcases --base http://127.0.0.1:8000
.\.venv\Scripts\python.exe -X utf8 -m scripts.run_ui_testcases --only TC03 TC09   # vài ca
.\.venv-gpu\Scripts\python.exe -X utf8 -m scripts.run_ui_testcases                # không cần server (in-process)
```

Kết quả ghi vào `reports/pham_van_vuong/ui_testcases.json`.
Lần chạy 2026-10-19: **18/18 pass** cả in-process lẫn qua HTTP.

> Lần đầu mỗi truy vấn mất khoảng 2–3 s vì gọi DeepSeek để phân tích và xếp hạng lại. Sau đó kết quả
> nằm trong cache SQLite và trả về trong vài ms. Muốn đo lại trường hợp chưa có cache, hãy sửa nhẹ
> câu truy vấn (thêm/bớt một từ).

## 2. Bộ test case

### Tìm kiếm

| ID | Truy vấn | Kiểm tra gì | Kỳ vọng |
|---|---|---|---|
| TC01 | `Quần thể Tràng An` | Tên chính xác | Ảnh #1 thuộc "Quần thể Tràng An"; ≥ 80% top 10 là ảnh của thực thể này |
| TC02 | `nem chua thanh hoa` | Gõ không dấu | Ảnh #1 là "Nem chua Thanh Hóa" |
| TC03 | `chợ họp trên sông, thuyền chở đầy trái cây` | Mô tả, không nêu tên | ≥ 50% kết quả là "chợ nổi…" (đo được 90%) |
| TC04 | `Phở bò và Bánh cuốn` | Multi-intent | intent `multi_intent`; cả "Phở bò" và "Bánh cuốn" đều có trong top 10 |
| TC05 | `các chợ truyền thống` | Set query theo nhóm | ≥ 60% thuộc nhóm "Chợ truyền thống" (đo được 100%), ≥ 3 chợ khác nhau (đo được 7) |
| TC06 | `Nhà cổ 48 Hàng Ngang` | Hồi quy: chữ "Ngang" trong tên phố | Không có cảnh báo `orientation`; ảnh #1 là "Nhà cổ 48 Hàng Ngang" |
| TC07 | `ảnh ngang Văn Miếu Huế` | Filter hướng ảnh | Có cảnh báo "filter orientation ignored…" nhưng **vẫn** trả ảnh Văn Miếu Huế |
| TC08 | `con trai của chủ tịch tập đoàn Vingroup` | Multi-hop | 0 ảnh, intent `multi_hop`, cảnh báo thiếu dữ liệu quan hệ (không bịa) |
| TC09 | `Văn Miếu` | Tên mơ hồ | ≥ 80% là "Văn Miếu…", trải trên ≥ 3 thực thể (đo được 7) |
| TC10 | `nhà thờ ở Đà Lạt` | Loại + địa điểm | ≥ 70% tên có "Đà Lạt" và ≥ 70% có "nhà thờ" (đo được 100%/100%) |
| TC11 | `old merchant house in Hoi An` | Truy vấn tiếng Anh | ≥ 50% kết quả ở "Hội An" (đo được 100%) |
| TC12 | `xyzqw blorf kraznik` | Truy vấn vô nghĩa | ≤ 3 ảnh (đo được 0; rerank cắt mọi ứng viên < 0,2) |
| TC13 | `Quần thể Tràng An` × 2 | Cache | Lần 2 có `cache_lookup`, `total_ms` ≤ 200 (đo được 2–10 ms) |

### API / bảo mật / dữ liệu

| ID | Request | Kỳ vọng |
|---|---|---|
| TC14 | `POST /v1/search` **không** gửi `X-API-Key` | 401 |
| TC15 | `POST /v1/search {"query":"Tràng An","top_k":0}` | 422 |
| TC16 | `POST /v1/search {"query":""}` | 422 |
| TC17 | `GET /v1/entities?q=Bát Tràng` | 200, `total` ≥ 10 (đo được 33) |
| TC18 | `GET /v1/health` | `index_complete = true`, 35.252 ảnh, `usernames = [pham_van_vuong]`, Stage 3 bật |

### Thử tay trên giao diện (không tự chấm)

1. **Sai key**: xoá hoặc gõ sai key rồi tìm → hộp đỏ "Sai hoặc thiếu API key…"; thanh health vẫn hiện (health không cần key).
2. **Chip facet**: sau TC05 bấm chip `nhóm: Chợ truyền thống` → chạy truy vấn "các chợ truyền thống"; bấm chip tên thực thể → tìm đúng thực thể đó.
3. **Chi tiết ảnh**: bấm một ảnh → hộp thoại có image_id, entity_id, link gốc, dòng "N thực thể khác trong cùng nhóm"; bấm "Tìm thực thể này".
4. **Ảnh bị chặn hotlink**: một số host ảnh không cho nhúng → ô xám "Host ảnh chặn tải trực tiếp"; link gốc trong chi tiết vẫn mở được.
5. **Tab Thực thể**: lọc `Hội An` → bấm "Nhà cổ họ Trần (Hội An)" → tab Tìm kiếm chạy truy vấn đó.
6. **top_k**: chọn 40 cho `các chợ truyền thống` → tối đa 40 ảnh (sau khi rerank cắt các ảnh < 0,2 có thể ít hơn).
7. **Điện thoại / cửa sổ hẹp**: thu cửa sổ còn khoảng 400 px → lưới còn 2 cột, ô key xuống dòng, không bị cuộn ngang.

## 3. Lỗi tìm được nhờ bộ test này

**TC09 ban đầu FAIL**: `Văn Miếu` chỉ ra 2 thực thể. Nguyên nhân: các ứng viên khớp tên được nối
tuần tự theo từng thực thể (mỗi thực thể tối đa 30 ảnh, trọng số RRF 3). Vì vậy riêng thực thể khớp đầu tiên
đã lấp gần hết 24 chỗ của pool rerank. Đã sửa trong `retrieval/local_search.py`: thực thể có tên **trùng hẳn**
với truy vấn giữ toàn bộ ảnh ở đầu, các thực thể khớp một phần thì xen kẽ round-robin.
Sau khi sửa, TC09 ra 7 thực thể. Eval 30 thực thể không đổi (Recall@10 0,993, MRR 1,0).
Có test hồi quy `test_partial_name_matches_are_interleaved`.
