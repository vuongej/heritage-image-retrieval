# Test case và phương pháp kiểm thử

Cập nhật 22/10/2026. Hệ thống được kiểm thử ở năm lớp:

| Lớp | Phạm vi | Số ca | Kết quả mới nhất | Lệnh |
|---|---|---:|---|---|
| Unit / integration backend | API, parser, fusion, rerank, hạn chờ, multi-hop, verify, processing | 351 | 351 pass, 12 s | `pytest -q` |
| Unit frontend | Hợp đồng API, adapter tìm kiếm | 26 | 26 pass | `cd web/spa && npm test` |
| **Test case Phần B** | 3 loại truy vấn + ngoài catalog, có nhãn | 82 | §2, [report](../reports/testcases/report.md) | `python -X utf8 -m scripts.eval_testcases` |
| **Test case Phần A** | 34.780 ảnh có nhãn người | 10.565 (TEST) | §3, [verify-router-benchmark.md](verify-router-benchmark.md) | `python -m scripts.bench_verify_router` |
| Load test | `/v1/search` qua HTTP, 3 loại | k6 | [performance-benchmark.vi.md](performance-benchmark.vi.md) §4 | `docker compose --profile loadtest run --rm k6` |

## 1. Nguyên tắc chung

- **Nhãn viết trước khi chạy hệ thống.** Nhãn không được sửa theo kết quả. Nếu soát thấy regex khớp nhầm (ví dụ "đông ba" khớp cả "đồng bằng") thì sửa regex dựa trên **danh sách tên trong catalog**, không dựa trên top-k hệ thống trả về.
- **Tách tập chọn và tập báo cáo.** Phần A chọn model / ngưỡng / ngân sách trên VAL và báo cáo trên TEST. Phần B không có tham số nào được chỉnh theo bộ test case.
- **Báo cáo ca thất bại cùng lúc với ca thành công.** Bao gồm các ca hệ thống được kỳ vọng phải từ chối.

## 2. Phần B — 82 test case truy xuất

### 2.1. Cách dựng

Bộ test case nằm ở [evals/testcases/cases.jsonl](../evals/testcases/cases.jsonl) và được sinh bởi [scripts/build_testcases.py](../scripts/build_testcases.py). Ảnh "đúng" là ảnh thuộc entity có tên khớp nhãn; tên entity được bỏ dấu và chuyển chữ thường trước khi so (`đ` → `d`).

| Nhóm | Số ca | Cách chọn truy vấn | Cách gán nhãn |
|---|---:|---|---|
| `single_entity` | 30 | Tự động: mỗi `parent_class` bốc 1 entity có ≥ 5 ảnh, seed 7. Rải khắp 30 nhóm (tranh dân gian, gốm, trà, đền, tháp Chăm…) | `entity_id` của chính tên đó và các entity trùng tên chuẩn hóa |
| `single` | 16 | Viết tay: địa danh / công trình nổi tiếng, cách nói tự nhiên ("phố cổ Hội An về đêm", "ruộng bậc thang") | Regex trên tên entity, soát trên danh sách tên catalog (pooling theo tên). Số entity khớp được in ra khi build |
| `multi_intent` | 15 | Viết tay: 2–3 ý trong một câu, có ý dùng chung địa danh ("chợ đêm và Dinh Cậu ở Phú Quốc") | Mỗi ý một regex riêng; chấm **coverage** (ý nào có ≥ 1 ảnh đúng trong top 10) |
| `multi_hop` | 16 | Viết tay: quan hệ cha / mẹ / con / vợ → lăng / mộ | Đích lấy theo **sử liệu**, không theo KG của hệ thống (tránh vòng lặp). Gồm 1 ca KG thiếu cạnh (vợ vua Tự Đức) và 2 ca phải từ chối (con vua Khải Định: Bảo Đại an táng ở Paris; con trai chủ tịch Phạm Nhật Vượng: ví dụ của đề, không có trong KG / catalog) |
| `out_of_catalog` | 5 | Hai ví dụ của đề (catalog **không có** entity bãi biển Nha Trang, hồ bơi, công viên nước) và 3 truy vấn ngoài phạm vi | Không có ảnh đúng: đúng khi trả 0 ảnh |

Bước soát nhãn: script dừng nếu một regex không khớp entity nào. Số entity khớp cho từng ca được in ra để người soát kiểm tra tay.

**Giới hạn của nhãn.** Nhãn do người viết test case định nghĩa (có công cụ hỗ trợ) ở mức **entity**, không phải người gán độc lập ở mức **từng ảnh**:
- Ảnh thuộc đúng entity nhưng chụp kém vẫn được tính là đúng.
- Ảnh của entity liên quan nhưng không khớp regex (ví dụ "Tháp chuông đôi Nhà thờ Đức Bà" thiếu chữ "Sài Gòn") bị tính là sai.

Muốn có relevance độc lập thì cần người thứ hai duyệt lại `reports/testcases/results.jsonl` (top 10 của từng ca).

### 2.2. Metric

| Metric | Định nghĩa |
|---|---|
| Hit@10 | Có ít nhất 1 ảnh đúng trong top 10 |
| Precision | Ảnh đúng / số ảnh trả về (0 nếu trả 0 ảnh khi lẽ ra phải có) |
| nDCG@10 | Nhị phân; lý tưởng = min(10, số ảnh đúng trong catalog) |
| MRR | 1 / hạng của ảnh đúng đầu tiên |
| Coverage | Multi-intent: tỉ lệ ý có ≥ 1 ảnh đúng trong top 10; "đủ mọi ý" = mọi ý đều có |
| Resolved | Multi-hop: resolver trả `resolved` cho ca có đích hợp lệ |
| Từ chối đúng | Ca không có ảnh đúng: hệ thống trả 0 ảnh |
| Latency | Thời gian `/v1/search` in-process, **cache kết quả tắt** (độ trễ lạnh) |

### 2.3. Kết quả

Lượt chạy 22/10/2026 08:46 trên 130.428 ảnh, cấu hình giống bản deploy (NumPy, rerank qua endpoint), giãn cách 2,5 s/câu để nằm trong hạn mức endpoint. Nguồn: [reports/testcases/report.md](../reports/testcases/report.md).

| Loại | Ca | Hit@10 | Precision | nDCG@10 | MRR | Ghi chú | p50 ms | p95 ms | < 3 s |
|---|---:|---:|---:|---:|---:|---|---:|---:|---:|
| single_entity | 30 | 100% | 87,7% | 100% | 100% | — | 554 | 801 | 100% |
| single | 16 | 100% | 100% | 100% | 100% | — | 452 | 612 | 100% |
| multi_intent | 15 | 100% | 97,3% | 97,5% | 100% | nhận đúng loại 12/15 (3 ca nhận `set_query`); coverage 100%, đủ mọi ý 15/15 | 564 | 1.123 | 100% |
| multi_hop | 16 | 85,7% | 82,1% | 82,8% | 85,7% | nhận đúng loại 16/16; trả `resolved` 13/14; từ chối đúng 2/2 | 36 | 95 | 100% |
| out_of_catalog | 5 | — | — | — | — | **từ chối đúng 0/5** | 664 | 1.190 | 100% |
| **Toàn bộ** | 82 | | | | | | **509** | **914** | **100%** (max 1.190) |

**Cách đọc:**
- **Precision `single_entity` 87,7% < 100%:** khi entity đúng có ít hơn 10 ảnh, top 10 lấp thêm ảnh từ entity khác cùng chủ đề; theo nhãn entity thì những ảnh này tính là sai.
- **Multi-hop p50 36 ms:** parse LLM của các câu này đã có trong cache từ lượt trước, giống người dùng hỏi lại. Lượt đầu tiên (chưa cache) có p50 646 ms, p95 2.450 ms, vì phải chờ LLM tối đa 600 ms cộng tra KG online cho ca H14.
- **Hai ca multi-hop trượt:**
  - **H09** "lăng của mẹ vua Tự Đức": resolver trả `resolved` nhưng ra **Lăng Thiệu Trị (Xương Lăng)**, vì cạnh nơi an táng của bà Từ Dũ trong KG trỏ sang lăng của chồng. Lăng đúng là Xương Thọ Lăng: đây là lỗi dữ liệu KG.
  - **H14** "lăng của vợ vua Tự Đức": KG thiếu cạnh vợ / chồng của Tự Đức, tra online không ra bằng chứng nên trả `no_evidence` và 0 ảnh. Hệ thống không đoán, nhưng ca vẫn tính là trượt.
- **Ngoài catalog 0/5:** hệ thống vẫn trả 3–10 ảnh gần nhất. Ví dụ "bãi biển Nha Trang" trả Quảng trường 2/4, khu tắm bùn Tháp Bà…; "hồ bơi và công viên nước ở Phú Quốc" trả nhà tù Phú Quốc, hồ tiêu, nước mắm. Hạn chế này được ghi ở [technical-report.vi.md](technical-report.vi.md) §6.
- **Sửa nhãn sau khi soát:** regex của **M13** ("chợ đêm Đông Ba…") bản đầu bỏ sót entity "Chợ đêm Đông Ba" nên ca bị chấm phủ 1/2 ý dù hệ thống trả đúng. Regex đã được sửa (có ghi chú trong `build_testcases.py`) và chạy lại toàn bộ; đây là lần sửa nhãn duy nhất.

Chế độ dồn tải (không giãn cách, vượt hạn mức 100 request/phút của endpoint): 100% ca vẫn < 3 s (p95 518 ms). Mọi ca multi-intent chạy ở chế độ suy giảm (không dense / rerank) và chất lượng gần như không đổi. Nguồn: [reports/testcases_burst/report.md](../reports/testcases_burst/report.md).

### 2.4. Từng ca

Sinh từ [reports/testcases/results.jsonl](../reports/testcases/results.jsonl); top 10 tên entity của từng ca có trong file đó.

#### Single intent — tên entity (tự động)

| ID | Truy vấn | Nhãn đúng (regex trên tên entity bỏ dấu) | Hệ thống nhận | Kết quả | ms |
|---|---|---|---|---|---:|
| SE01 | Bia tiến sĩ Văn Miếu Thăng Long | `entity_id của chính tên (1 entity)` | single | Hit, P 100% | 913 |
| SE02 | Sung muối | `entity_id của chính tên (1 entity)` | single | Hit, P 100% | 441 |
| SE03 | Xuồng năm lá | `entity_id của chính tên (1 entity)` | single | Hit, P 80% | 412 |
| SE04 | Đê sông Cà Lồ (Vĩnh Phúc – Hà Nội) | `entity_id của chính tên (1 entity)` | single | Hit, P 100% | 785 |
| SE05 | Con kê (con chống) trong lò gốm | `entity_id của chính tên (1 entity)` | single | Hit, P 60% | 429 |
| SE06 | Tem CHXHCN bộ Lăng Chủ tịch Hồ Chí Minh | `entity_id của chính tên (1 entity)` | single | Hit, P 100% | 609 |
| SE07 | Trống đồng minh khí Đông Sơn | `entity_id của chính tên (1 entity)` | single | Hit, P 70% | 801 |
| SE08 | Ớt A Riêu | `entity_id của chính tên (1 entity)` | single | Hit, P 100% | 422 |
| SE09 | Chăn thổ cẩm Thái | `entity_id của chính tên (1 entity)` | single | Hit, P 50% | 550 |
| SE10 | Hoa hồng thủy tinh thổi | `entity_id của chính tên (1 entity)` | single | Hit, P 100% | 539 |
| SE11 | Tháp Nhạn nhìn xuống đồng lúa Tuy Hòa | `entity_id của chính tên (1 entity)` | single | Hit, P 100% | 549 |
| SE12 | Đỉnh trầm men rạn | `entity_id của chính tên (1 entity)` | single | Hit, P 70% | 446 |
| SE13 | Rèn Phúc Sen (làng rèn dao Cao Bằng) | `entity_id của chính tên (1 entity)` | single | Hit, P 60% | 621 |
| SE14 | Trụ sở UBND TP HCM | `entity_id của chính tên (1 entity)` | single | Hit, P 100% | 476 |
| SE15 | Đèn con cá (đèn cá chép Trung thu) | `entity_id của chính tên (1 entity)` | single | Hit, P 100% | 642 |
| SE16 | Thảm cói Phú Tân | `entity_id của chính tên (1 entity)` | single | Hit, P 60% | 450 |
| SE17 | Trường Đại học Khoa học Huế (Morin Frères cũ, Huế) | `entity_id của chính tên (1 entity)` | single | Hit, P 100% | 545 |
| SE18 | Hàng nông sản tại Chợ phiên Cán Cấu (Si Ma Cai) | `entity_id của chính tên (1 entity)` | single | Hit, P 90% | 599 |
| SE19 | Tượng Vishnu Khương Mỹ | `entity_id của chính tên (1 entity)` | single | Hit, P 80% | 549 |
| SE20 | Biệt phủ giấy (dinh thự hàng mã) | `entity_id của chính tên (1 entity)` | single | Hit, P 80% | 579 |
| SE21 | Tòa Thánh Tây Ninh | `entity_id của chính tên (1 entity)` | single | Hit, P 100% | 454 |
| SE22 | Làng Đường Lâm (Sơn Tây - Hà Nội) | `entity_id của chính tên (1 entity)` | single | Hit, P 100% | 554 |
| SE23 | Thành Cổ Loa | `entity_id của chính tên (1 entity)` | single | Hit, P 100% | 586 |
| SE24 | Vòng tay bạc Thái | `entity_id của chính tên (1 entity)` | single | Hit, P 100% | 421 |
| SE25 | Bộ tem Lăng Tự Đức - Huế VNCH | `entity_id của chính tên (1 entity)` | single | Hit, P 60% | 661 |
| SE26 | Tượng Bồ Tát Địa Tạng thếp vàng | `entity_id của chính tên (1 entity)` | single | Hit, P 100% | 651 |
| SE27 | Cối đá giã thuốc nam (cối thuốc bắc) | `entity_id của chính tên (1 entity)` | single | Hit, P 100% | 628 |
| SE28 | Cầu Đà Rằng | `entity_id của chính tên (1 entity)` | single | Hit, P 100% | 520 |
| SE29 | Gương sơn mài Bình Dương | `entity_id của chính tên (1 entity)` | single | Hit, P 70% | 727 |
| SE30 | Cá chép đỏ (chép cúng ông Công ông Táo) | `entity_id của chính tên (1 entity)` | single | Hit, P 100% | 690 |

#### Single intent — truy vấn tự nhiên

| ID | Truy vấn | Nhãn đúng (regex trên tên entity bỏ dấu) | Hệ thống nhận | Kết quả | ms |
|---|---|---|---|---|---:|
| S01 | chợ Bến Thành | `^cho ben thanh` | single | Hit, P 100% | 428 |
| S02 | Nhà thờ Đức Bà Sài Gòn | `duc ba sai gon/^nha tho duc ba( \(\|$)` | single | Hit, P 100% | 486 |
| S03 | Lăng Tự Đức | `lang tu duc/khiem lang` | single | Hit, P 100% | 405 |
| S04 | chùa Thiên Mụ Huế | `chua thien mu(?!c)/linh mu` | single | Hit, P 100% | 452 |
| S05 | phố cổ Hội An về đêm | `pho co hoi an/hoi an.*(dem\|den long)` | single | Hit, P 100% | 468 |
| S06 | Chùa Cầu Hội An | `chua cau` | single | Hit, P 100% | 448 |
| S07 | Thánh địa Mỹ Sơn | `thanh dia my son/my son (nhom\|[a-h]\d)/kalan my son/thap.*my son` | single | Hit, P 100% | 443 |
| S08 | tháp Bà Ponagar Nha Trang | `po ?nagar/\bthap ba\b` | single | Hit, P 100% | 484 |
| S09 | Hồ Gươm | `ho guom/ho hoan kiem/thap rua/cau the huc` | single | Hit, P 100% | 380 |
| S10 | Đại Nội Huế | `dai noi/ngo mon/kinh thanh hue` | single | Hit, P 100% | 386 |
| S11 | ruộng bậc thang | `ruong bac thang` | single | Hit, P 100% | 390 |
| S12 | Dinh Độc Lập | `dinh doc lap/hoi truong thong nhat` | single | Hit, P 100% | 526 |
| S13 | Văn Miếu Quốc Tử Giám Hà Nội | `quoc tu giam/van mieu.*ha noi` | single | Hit, P 100% | 386 |
| S14 | Lăng Chủ tịch Hồ Chí Minh | `lang chu tich ho chi minh` | single | Hit, P 100% | 612 |
| S15 | chợ đêm Phú Quốc | `cho dem phu quoc` | single | Hit, P 100% | 509 |
| S16 | tượng Phật nằm chùa Long Sơn Nha Trang | `long son.*nha trang/phat nam.*long son` | single | Hit, P 100% | 522 |

#### Multi-intent

| ID | Truy vấn | Nhãn đúng (regex trên tên entity bỏ dấu) | Hệ thống nhận | Kết quả | ms |
|---|---|---|---|---|---:|
| M01 | Lăng Minh Mạng và lăng Khải Định | `lang minh mang/hieu lang · lang khai dinh/ung lang` | multi_intent | đủ mọi ý, P 100% | 575 |
| M02 | chợ Bến Thành và nhà thờ Đức Bà Sài Gòn | `^cho ben thanh · duc ba sai gon/^nha tho duc ba( \(\|$)` | multi_intent | đủ mọi ý, P 100% | 464 |
| M03 | Chùa Cầu và phố cổ Hội An | `chua cau · pho co hoi an` | multi_intent | đủ mọi ý, P 100% | 543 |
| M04 | chợ đêm và Dinh Cậu ở Phú Quốc | `cho dem phu quoc · dinh cau` | multi_intent | đủ mọi ý, P 100% | 998 |
| M05 | Hồ Gươm và Văn Miếu Quốc Tử Giám | `ho guom/ho hoan kiem/cau the huc · quoc tu giam/van mieu.*ha noi` | multi_intent | đủ mọi ý, P 100% | 483 |
| M06 | Đại Nội Huế và chùa Thiên Mụ | `dai noi/ngo mon · chua thien mu(?!c)` | multi_intent | đủ mọi ý, P 100% | 467 |
| M07 | Thánh địa Mỹ Sơn và tháp Po Nagar | `thanh dia my son/my son (nhom\|[a-h]\d)/kalan my son · po ?nagar` | set_query | đủ mọi ý, P 100% | 980 |
| M08 | Dinh Độc Lập và chợ Bến Thành | `dinh doc lap/hoi truong thong nhat · ^cho ben thanh` | multi_intent | đủ mọi ý, P 100% | 505 |
| M09 | Lăng Tự Đức, lăng Minh Mạng và lăng Khải Định | `lang tu duc/khiem lang · lang minh mang/hieu lang · lang khai dinh/ung lang` | multi_intent | đủ mọi ý, P 100% | 645 |
| M10 | ruộng bậc thang Tú Lệ và ruộng bậc thang Pù Luông | `ruong bac thang tu le · pu luong` | multi_intent | đủ mọi ý, P 100% | 532 |
| M11 | chùa Một Cột và Lăng Chủ tịch Hồ Chí Minh | `chua mot cot · lang chu tich ho chi minh` | multi_intent | đủ mọi ý, P 100% | 522 |
| M12 | Hoàng thành Thăng Long và Văn Miếu | `hoang thanh thang long · quoc tu giam/van mieu.*ha noi` | set_query | đủ mọi ý, P 60% | 914 |
| M13 | chợ đêm Đông Ba và Đại Nội Huế | `(cho\|cho dem\|pho\|cau\|cua) dong ba\b · dai noi` | multi_intent | đủ mọi ý, P 100% | 564 |
| M14 | biệt thự Nam Phương Hoàng hậu và dinh Bảo Đại | `biet thu nam phuong · dinh bao dai` | multi_intent | đủ mọi ý, P 100% | 603 |
| M15 | tháp Po Nagar, chùa Long Sơn và nhà thờ chính tòa Nha Trang | `po ?nagar · long son.*nha trang/phat nam.*long son · nha tho chinh toa nha trang` | set_query | đủ mọi ý, P 100% | 1,123 |

#### Multi-hop

| ID | Truy vấn | Nhãn đúng (regex trên tên entity bỏ dấu) | Hệ thống nhận | Kết quả | ms |
|---|---|---|---|---|---:|
| H01 | lăng của con trai vua Gia Long | `lang minh mang/hieu lang` | multi_hop | Hit, P 100%, `resolved` | 95 |
| H02 | lăng của cha vua Thiệu Trị | `lang minh mang/hieu lang` | multi_hop | Hit, P 100%, `resolved` | 16 |
| H03 | lăng của con trai vua Minh Mạng | `lang thieu tri/xuong lang` | multi_hop | Hit, P 100%, `resolved` | 42 |
| H04 | lăng của cha vua Tự Đức | `lang thieu tri/xuong lang` | multi_hop | Hit, P 100%, `resolved` | 29 |
| H05 | lăng của con trai vua Thiệu Trị | `lang tu duc/khiem lang` | multi_hop | Hit, P 100%, `resolved` | 52 |
| H06 | lăng của con trai vua Đồng Khánh | `lang khai dinh/ung lang` | multi_hop | Hit, P 100%, `resolved` | 46 |
| H07 | lăng của cha vua Khải Định | `lang (mo )?dong khanh/tu lang` | multi_hop | Hit, P 100%, `resolved` | 41 |
| H08 | lăng của cha vua Bảo Đại | `lang khai dinh/ung lang` | multi_hop | Hit, P 100%, `resolved` | 32 |
| H09 | lăng của mẹ vua Tự Đức | `xuong tho lang` | multi_hop | **Trượt**, P 0%, `resolved` | 36 |
| H10 | lăng của vợ vua Bảo Đại | `lang (hoang hau )?nam phuong` | multi_hop | Hit, P 100%, `resolved` | 24 |
| H11 | mộ của cha Chủ tịch Hồ Chí Minh | `\bmo\b.*nguyen sinh sac` | multi_hop | Hit, P 80%, `resolved` | 45 |
| H12 | mộ của mẹ Chủ tịch Hồ Chí Minh | `hoang thi loan` | multi_hop | Hit, P 70%, `resolved` | 25 |
| H13 | lăng của cha vua Thành Thái | `lang duc duc/thanh thai an lang/chua an lang` | multi_hop | Hit, P 100%, `resolved` | 36 |
| H14 | lăng của vợ vua Tự Đức | `khiem tho lang` | multi_hop | **Trượt**, P 0%, `no_evidence` | 40 |
| H15 | lăng của con trai vua Khải Định | `không có ảnh đúng → kỳ vọng 0 ảnh` | multi_hop | từ chối đúng, `no_evidence` | 12 |
| H16 | ảnh con trai chủ tịch Phạm Nhật Vượng | `không có ảnh đúng → kỳ vọng 0 ảnh` | multi_hop | từ chối đúng, `seed_not_linked` | 7 |

#### Ngoài catalog

| ID | Truy vấn | Nhãn đúng (regex trên tên entity bỏ dấu) | Hệ thống nhận | Kết quả | ms |
|---|---|---|---|---|---:|
| O01 | bãi biển Nha Trang | `không có ảnh đúng → kỳ vọng 0 ảnh` | single | **trả 10 ảnh sai** | 664 |
| O02 | hồ bơi và công viên nước ở Phú Quốc | `không có ảnh đúng → kỳ vọng 0 ảnh` | single | **trả 10 ảnh sai** | 1,190 |
| O03 | tháp Eiffel Paris | `không có ảnh đúng → kỳ vọng 0 ảnh` | single | **trả 3 ảnh sai** | 519 |
| O04 | ảnh con hổ và con mèo | `không có ảnh đúng → kỳ vọng 0 ảnh` | single | **trả 10 ảnh sai** | 912 |
| O05 | những con vật sống trong rừng | `không có ảnh đúng → kỳ vọng 0 ảnh` | set_query | **trả 10 ảnh sai** | 517 |

## 3. Phần A — test case kiểm duyệt ảnh

### 3.1. Bộ nhãn và cách chia

- **Nguồn:** `data/test.csv`, gồm **34.780 ảnh / 4.947 entity** do người duyệt gán `verify = yes | no` (23.169 yes, 11.611 no).
  - Người duyệt quy ước `yes` = duyệt, `no` = loại.
  - Đối chiếu với master: 100% ảnh `yes` có trong bộ đã duyệt; 11.507/11.611 ảnh `no` không có.
- **Chia theo nhóm tên entity** (gộp tên gần nhau bằng Jaccard ≥ 0,9, phân tầng theo nhóm category, seed 42) để ảnh của cùng một địa danh không rơi vào hai phía:
  - TRAIN 19.349 ảnh: học classifier.
  - VAL 4.866 ảnh: chọn C / ngưỡng / ngân sách / cách đọc VLM, hiệu chỉnh isotonic.
  - **TEST 10.565 ảnh**: chỉ để báo cáo.
- **Ràng buộc chọn cấu hình** (trên VAL): Recall yes ≥ 85% (giữ ảnh tốt) và entity retention ≥ 95%. Trong vùng đó tối đa Recall no; hòa thì chọn phương án rẻ hơn.
- **CSV mẫu cho demo:** [processing/samples/sample.csv](../processing/samples/sample.csv).
  - 307 ảnh / 30 entity lấy từ TEST, có cả yes lẫn no trong mỗi entity.
  - Tải được từ giao diện; kết quả được chấm với cột `verify`.

### 3.2. Kết quả

Chi tiết: [verify-router-benchmark.md](verify-router-benchmark.md).

| Cấu hình (TEST) | Recall no | Precision yes | Recall yes | Retention | Gửi VLM |
|---|---:|---:|---:|---:|---:|
| Không lọc (duyệt hết) | 0% | 66,7% | 100% | 100% | 0% |
| Production cũ: head nhãn VLM, t = 0,5, α = 15% | 59,2% | 76,2% | 65,3% | 88,9% | 14,6% |
| **Production mới: M1b + router 15% + `bo_watermark`, t = 0,55** | 44,8% | 75,5% | **85,2%** | **94,2%** | 14,6% |
| M1b ở cùng mức giữ ảnh của production cũ | **65,7%** | **80,1%** | 69,2% | 86,3% | 14,6% |

Chạy file mẫu 307 ảnh qua giao diện (job thật, VLM thật): Recall no 38,2%, Precision yes 64,0%, Recall yes 81,8%, retention 93,3%. File mẫu khó hơn trung bình vì được chọn để mỗi entity có cả ảnh duyệt lẫn ảnh loại (43% no).

## 4. Ma trận test tự động

| File | Số test | Kiểm tra |
|---|---:|---|
| `test_rule_parser_regression.py` | 140 | Tên entity từng bị parser cũ xếp nhầm loại (multi-hop / multi-intent) |
| `test_query_guard.py` | 55 | Chặn truy vấn khiếm nhã / nhạy cảm trước khi tốn quota; không chặn nhầm tên địa danh |
| `test_hop.py` | 24 | Planner chuỗi quan hệ, link alias, lọc giới tính, trạng thái `resolution` |
| `test_v2_invariants.py` | 17 | Bất biến V2: entity-first, guard LLM, chia slot multi-intent, không cache kết quả suy giảm |
| `test_embed_api.py` | 15 | Client embedding / rerank qua endpoint, lỗi và retry |
| `test_speculative_search.py` | 13 | Parse LLM song song, timeout, guard ghi đè |
| `test_verify_pipeline.py` | 12 | Gate, split, feature, head, router của Pipeline A |
| `test_local_pipeline.py`, `test_phase2_index.py` | 15 | Import CSV, index, checkpoint, parity |
| `test_scope_and_cascade.py` | 10 | Scope import, cascade cũ |
| `test_processing.py` | 8 | Đọc CSV (alias cột, `;`, BOM, nhãn), cách đọc VLM, metric, chạy end-to-end không mạng / GPU, API upload → tiến độ → items → CSV, chặn path traversal ở thumbnail |
| `test_rule_parser.py` | 7 | Tách ý, nhận diện tên entity |
| `test_deadlines.py` | 5 | Hạn chờ embedding / rerank, hạn chờ tổng request, limiter báo hết hạn mức ngay, rerank lỗi thì giữ thứ tự RRF |
| Còn lại (API contract, fusion, metric, report, routing, relevance floor, gate…) | 30 | |
| **Tổng backend** | **351** | 351 pass trong 12 s |
| `web/spa/src/**/*.test.ts` | 26 | Client API, hợp đồng payload, adapter tìm kiếm |

Giao diện được kiểm tra thủ công qua stack docker compose, có chụp màn hình:
- **Tìm kiếm:** 3 loại truy vấn.
- **Xử lý dữ liệu:** upload CSV mẫu, theo dõi tiến độ 8 tầng, xem kết quả / ma trận nhầm lẫn / lọc theo lý do, tải CSV kết quả.
- **Lỗi upload:** thiếu cột → 422 kèm thông báo, sai đuôi → 422.

## 5. Lệnh tái lập

```bash
pytest -q                                              # 351 test backend
cd web/spa && npm test && cd ../..                     # 26 test frontend
python -m scripts.build_testcases                      # dựng + soát nhãn 82 ca Phần B
python -X utf8 -m scripts.eval_testcases --pace 2.5    # chấm Phần B (≈ 3,5 phút, cần endpoint embedding)
python -X utf8 -m scripts.eval_testcases --pace 0 --out reports/testcases_burst
# Phần A (cần data/test.csv; lần đầu tải ~34k ảnh ≈ 40 phút, GPU cho SigLIP2)
python -m scripts.eval_verify_human                    # tải + SigLIP2 + head baseline
python -m scripts.bench_verify_collect                 # VLM cho VAL + TEST và bootstrap (≈ $2,90)
python -m scripts.bench_verify_router                  # giai đoạn 1–4, chọn cấu hình
python -m scripts.train_verify_model                   # đóng gói models/verify cho processing service
docker compose --profile loadtest run --rm k6          # load test qua web proxy
python -m loadtest.make_report reports/loadtest/raw.json -o reports/loadtest/report.html
```
