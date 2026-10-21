# Multi-hop có bằng chứng — KG 3 giai đoạn, không phụ thuộc Wikidata (2026-10-21)

Truy vấn kiểu *"lăng của con trai vua Gia Long"* cần đi qua quan hệ người–người rồi người–nơi chốn
trước khi lấy ảnh. Luồng này dùng **đồ thị tri thức (KG) do dự án tự quản**, mỗi cạnh có bằng chứng
kiểm chứng được, dựng theo 3 giai đoạn. Không gọi Wikidata ở bất kỳ bước nào.

**Nguyên tắc:** resolver chỉ đi theo cạnh `verified = 1` (câu trích có nguyên văn trong văn bản nguồn,
hoặc chính tên thực thể catalog) hoặc `reviewed = 1` (người duyệt). Thiếu bằng chứng → trả trạng thái
thiếu dữ liệu, **không đoán, không trả ảnh tuỳ tiện**.

---

## 1. Kiến trúc

```text
"lăng của con trai vua Gia Long"
   │ rule parser: cấu trúc [lăng] + [con trai] + [người]  (LLM không được bỏ multi_hop)
   ▼
hop.plan  → target BURIED_AT, bước PARENT_OF (chiều xuôi, con = nam), seed "gia long"
   ▼
hop.resolve trên KG (SQLite: kg_node, kg_alias, kg_edge, kg_link)
   ├─ seed: khớp tên gọi (bỏ chức danh)               → person:gia-long
   ├─ PARENT_OF xuôi, giới tính nam                    → person:minh-mang   [3 nguồn]
   │     └─ không có cạnh? → giai đoạn 3 (online, chạy nền, ngân sách 2,5 s)
   └─ BURIED_AT                                        → place:<entity_id> … (Lăng Minh Mạng)
   ▼
ảnh của các entity_id đích (xen kẽ giữa các bản trùng tên) + `resolution` (chuỗi cạnh + câu trích + URL)
```

Cạnh chuẩn, lưu một chiều: `PARENT_OF` (cha/mẹ → con; "cha/mẹ của X" suy ra bằng chiều ngược + giới
tính), `SPOUSE_OF`, `BURIED_AT`, `WORSHIPPED_AT`, `MEMORIAL_AT` (người → nơi chốn trong catalog).

Trạng thái: `resolved` · `pending_online_lookup` · `seed_not_linked` · `no_evidence` (không có bằng
chứng ≠ quan hệ không tồn tại) · `target_not_in_catalog` (đích là người: catalog không có ảnh người;
kèm `related_places`) · `unsupported_relation` (anh/em/cháu/sáng lập…).

---

## 2. Ba giai đoạn

### Giai đoạn 1 — Seed thủ công (`scripts/kg_seed.py`)

| Nguồn | Nội dung | Kiểm chứng |
|---|---|---|
| `data/kg/seed_people.csv` | 17 người (7 vua Nguyễn + Thành Thái, Duy Tân, Bảo Đại, Nam Phương, Từ Cung; Hồ Chí Minh, Nguyễn Sinh Sắc, Hoàng Thị Loan, Nguyễn Thị Thanh, Nguyễn Sinh Khiêm), tên gọi khác, giới tính | — |
| Tên thực thể catalog | "Lăng X…", "Mộ X…", "Đền thờ X…", "Khu lưu niệm/Tượng đài X…" → **201 cạnh** người→nơi chốn | Bằng chứng = chính tên thực thể. Loại đồ vật ("Bộ tem Lăng Tự Đức", kim sách, tiền…) |
| `data/kg/seed_relations.csv` | 15 **khẳng định** người–người (verified=0) | `--verify`: tìm web, kiểm câu trích → **14/15 kiểm chứng**, $0,21 |

Khẳng định chưa kiểm chứng: *Khải Định – Từ Cung (vợ chồng)* — nguồn gọi bà là "phi thiếp", không có
câu trích chứa từ chỉ hôn nhân. (Giai đoạn 3 sau đó tìm được cạnh này từ nguồn khác.)

### Giai đoạn 2 — Gemini dựng KG offline (`scripts/kg_extract.py`)

- Phạm vi: 60 nơi chốn đã nối với seed (lăng/mộ/đền thờ/khu lưu niệm), không gọi Gemini cho từng ảnh.
- Tài liệu: trang `source_url` của ảnh thuộc thực thể (≤ 2 trang), tải an toàn (chặn IP nội bộ, ≤ 3 MB,
  ≤ 5 redirect) + cache. 100 trang tải được, 9 lỗi (chủ yếu 403).
- Gemini (json_schema strict) đề xuất quan hệ + câu trích → **kiểm chứng bằng code**.
- Kết quả: 221 đề xuất → **114 chấp nhận**, 107 loại (có lý do). Chi phí lần đầu $0,15; chạy lại
  ~$0 (cache).

### Giai đoạn 3 — Online fallback (`retrieval/kg_online.py`)

- KG thiếu cạnh người–người → Gemini + **web search engine `exa`** (OpenRouter). Engine `native`
  (Google grounding) bỏ trích dẫn khi buộc trả JSON (đo: 0/15 lần có URL) nên không dùng.
- Kiểm chứng câu trích trên **đoạn trang do công cụ tìm kiếm trả** (không do model viết), nếu không đạt
  thì trên **trang hệ thống tự tải**. Nhiều nguồn chặn bot (Wikipedia 403) nên bước 1 quan trọng; hệ
  thống **không giả User-Agent trình duyệt** để lách.
- Chạy nền, ngân sách `HOP_ONLINE_BUDGET_MS=2500`: quá hạn → `pending_online_lookup`, lần sau dùng
  cạnh đã ghi. Kết quả "không có bằng chứng" được cache 7 ngày (không trả tiền tra lại).
- Ví dụ: "vợ vua Khải Định" → 3 bà vợ có nguồn (danviet.vn, vi.wikipedia.org); "con trai chủ tịch
  Phạm Nhật Vượng" → `no_evidence` (≈ $0,008/lượt tra).

---

## 3. Luật chất lượng (`retrieval/kg_quality.py`) — dùng chung cả 3 giai đoạn

| Luật | Lý do (lỗi thật đã gặp) | Bị loại ở giai đoạn 2 |
|---|---|---|
| Câu trích có **nguyên văn** trong văn bản nguồn | model chép sai / bịa | 6 |
| Câu trích nhắc **tên các bên** (đoạn ±400 ký tự cho đại từ "Ông là…") | quan hệ gán nhầm người | 55 |
| Câu trích **tự nói quan hệ** (con, thân phụ, kết hôn, an nghỉ, thờ…) | "Vua Khải Định có tên khai sinh…" không phải bằng chứng cha–con | 11 |
| **Chiều cha–con** do một lượt Gemini độc lập chỉ đọc câu trích xác nhận | "vua Thiệu Trị, con trai vua Minh Mạng" bị ghi ngược | 8 |
| **Tên nơi chốn có gần câu trích**; câu trích nêu nơi chốn khác thì nối thẳng tới thực thể đó | trang tổng hợp nhiều lăng: "nơi an nghỉ của Minh Mạng" bị gán cho Lăng Gia Long | 23 |
| Bỏ chức danh khi khớp tên, không tạo người từ tên 1 chữ | "Vua Gia Long" / "Nguyễn Phúc Đảm" / "Đảm" thành nhiều nút | — |
| Giới tính chỉ từ câu trích hoặc **chức danh trong tên nguồn** (hoàng hậu, vua…) | "mẹ vua Minh Mạng" trượt vì nút Thuận Thiên thiếu giới tính | — |
| Hai chiều `PARENT_OF` cùng tồn tại → giữ chiều nhiều nguồn hơn, hoà thì thu hồi cả hai | vòng lặp cha–con | 0 (sau luật chiều) |
| Đồ vật không phải nơi chốn | "Bộ tem Lăng Tự Đức" trả về cho "đền thờ mẹ vua Tự Đức" | — |

---

## 4. KG hiện tại

| | Số lượng |
|---|---|
| Cạnh đã kiểm chứng | **333**: tên catalog 201 · Gemini/tài liệu 115 · seed 14 · online 3 |
| Theo loại | BURIED_AT 152 · MEMORIAL_AT 104 · PARENT_OF 33 · WORSHIPPED_AT 25 · SPOUSE_OF 19 |
| Người / nơi chốn (= thực thể catalog có ảnh) | 43 / 200 |
| Tổng chi phí dựng | ≈ $0,40 (seed verify $0,21 + Gemini trích $0,15 + judge/online ~$0,04) |

## 5. Kết quả end-to-end qua API (`reports/kg/e2e.txt`)

| Câu hỏi | Chuỗi | Kết quả |
|---|---|---|
| lăng của con trai vua Gia Long | Gia Long → Minh Mạng → lăng | resolved, 10 ảnh Lăng Minh Mạng |
| lăng của con trai của con trai vua Gia Long | → Minh Mạng → Thiệu Trị → lăng | resolved (3 bước) |
| lăng của mẹ vua Minh Mạng | ← Thuận Thiên Cao Hoàng hậu → lăng | resolved: lăng Thiên Thọ Hữu |
| lăng của cha vua Bảo Đại | ← Khải Định → lăng | resolved |
| lăng của vợ vua Bảo Đại | ↔ Nam Phương → lăng | resolved |
| mộ mẹ của Hồ Chí Minh | ← Hoàng Thị Loan → mộ | resolved |
| đền thờ cha của Hồ Chí Minh | ← Nguyễn Sinh Sắc → đền thờ | resolved |
| lăng của con trai vua Dục Đức | → Thành Thái → lăng | resolved |
| con trai vua Thành Thái | → Duy Tân | `target_not_in_catalog` (đích là người) |
| vợ vua Khải Định | ↔ 3 bà vợ (online) | `target_not_in_catalog` |
| con trai chủ tịch Phạm Nhật Vượng | — | `seed_not_linked` (online: không đủ bằng chứng) |
| anh của vua Tự Đức | — | `unsupported_relation` |
| Tượng đài Mẹ Việt Nam Anh hùng · Nhà thờ Cha Tam | — | vẫn là tìm theo tên (`single`) |

Độ trễ multi-hop dùng KG local: ~170–250 ms (cache hit) đến ~0,8 s; lần đầu cần tra online: ≤ 2,5 s
rồi `pending`.

## 6. Giới hạn

1. **Chưa có bộ đánh giá gold** cho multi-hop (kế hoạch V2: 120 ca có nhãn người). Bảng mục 5 là kiểm
   tra thủ công; độ chính xác chuỗi chưa được đo thống kê.
2. Phạm vi KG nhỏ: seed 17 người, giai đoạn 2 mới chạy 60 nơi chốn (`--scope memorial` cho toàn bộ
   nhóm tưởng niệm chưa chạy). Câu hỏi về người ngoài phạm vi phụ thuộc giai đoạn 3.
3. Quan hệ hỗ trợ: cha/mẹ/con, vợ/chồng, nơi an táng/thờ/lưu niệm. Chưa có anh/em, cháu, chức vụ,
   người sáng lập.
4. Kiểm chứng là **máy kiểm** (câu trích có trong nguồn + luật); chưa có người duyệt (`reviewed`).
   Nguồn web có thể sai; mỗi cạnh lưu URL + câu trích để người duyệt.
5. Liên kết nơi chốn theo tên/trang: thực thể trùng tên được giữ tất cả; trang tổng hợp có thể vẫn lọt
   nếu tên nơi chốn đứng gần câu trích.
6. Online fallback tốn ~$0,008/lượt và phụ thuộc OpenRouter + nguồn web; kết quả "không có bằng chứng"
   được cache 7 ngày.

## 7. Chạy lại

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.kg_seed --verify                         # giai đoạn 1
.\.venv\Scripts\python.exe -X utf8 -m scripts.kg_extract --scope seed --max-entities 60 # giai đoạn 2
.\.venv\Scripts\python.exe -X utf8 -m scripts.kg_extract --scope memorial --max-entities 500 --max-calls 800
```

| File | Vai trò |
|---|---|
| `retrieval/hop.py` | Lược đồ KG, plan câu hỏi, resolver, trạng thái |
| `retrieval/kg_sources.py` | Tải trang an toàn, HTML→text, cache, kiểm câu trích |
| `retrieval/kg_online.py` | Giai đoạn 3: web search exa, kiểm chứng, chạy nền + cache |
| `retrieval/kg_quality.py` | Luật chất lượng dùng chung |
| `scripts/kg_seed.py`, `data/kg/*.csv` | Giai đoạn 1 |
| `scripts/kg_extract.py` | Giai đoạn 2 |
| `retrieval/rule_parser.py`, `retrieval/speculative.py` | Nhận diện cấu trúc multi-hop; guard LLM |
| `tests/test_hop.py` | 24 test (mock, không gọi mạng) |
