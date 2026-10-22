# Benchmark Phần B trên bộ test case

82 ca · pipeline `b5-relevance-floor` · 2026-10-22 08:36 · cache tìm kiếm tắt (latency lạnh) · giãn cách 0 s/câu · VECTOR_BACKEND=numpy, RERANK_BACKEND=api, EMBED_MODEL=qwen3-embedding-4b, LLM_PARSE_MODE=-

| Loại | Ca | Hit@10 | Precision | nDCG@10 | MRR | Coverage / đúng loại | Từ chối đúng | p50 ms | p95 ms | < 3 s | Suy giảm |
|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|
| single_entity | 30 | 100.0% | 87.7% | 100.0% | 100.0% | — | — | 417 | 522 | 100.0% | 0.0% |
| single | 16 | 100.0% | 100.0% | 100.0% | 100.0% | — | — | 402 | 574 | 100.0% | 0.0% |
| multi_intent | 15 | 100.0% | 94.7% | 94.8% | 96.7% | coverage 96.7%, đủ mọi ý 93.3% | — | 45 | 286 | 100.0% | 100.0% |
| multi_hop | 16 | 85.7% | 82.1% | 82.8% | 85.7% | nhận multi_hop 100.0%, resolved 92.9% | 100.0% | 26 | 41 | 100.0% | 0.0% |
| out_of_catalog | 5 | — | — | — | — | — | 0.0% | 46 | 284 | 100.0% | 100.0% |

Toàn bộ: p50 345 ms · p95 518 ms · max 574 ms · 100.0% ca dưới 3 s.

## Từng ca

| ID | Truy vấn | Parse | Kết quả | ms | Top 3 entity |
|---|---|---|---|---:|---|
| SE01 | Bia tiến sĩ Văn Miếu Thăng Long | single | Hit · P 100% | 414 | Bia tiến sĩ Văn Miếu Thăng Long |
| SE02 | Sung muối | single | Hit · P 100% | 343 | Sung muối |
| SE03 | Xuồng năm lá | single | Hit · P 80% | 345 | Xuồng năm lá; Xuồng ba lá |
| SE04 | Đê sông Cà Lồ (Vĩnh Phúc – Hà Nội) | single | Hit · P 100% | 540 | Đê sông Cà Lồ (Vĩnh Phúc – Hà Nội) |
| SE05 | Con kê (con chống) trong lò gốm | single | Hit · P 60% | 417 | Con kê (con chống) trong lò gốm; Bình gốm hoa nâu hình con kê (gà) lò Tức Mặc; Khạp gốm lò Hưng Lợi (Xóm Lò Gốm) |
| SE06 | Tem CHXHCN bộ Lăng Chủ tịch Hồ Chí Minh | single | Hit · P 100% | 498 | Tem CHXHCN bộ Lăng Chủ tịch Hồ Chí Minh |
| SE07 | Trống đồng minh khí Đông Sơn | single | Hit · P 70% | 522 | Trống đồng minh khí Đông Sơn; Trống đồng |
| SE08 | Ớt A Riêu | single | Hit · P 100% | 416 | Ớt A Riêu |
| SE09 | Chăn thổ cẩm Thái | single | Hit · P 50% | 345 | Chăn thổ cẩm Thái; Chăn con công Mường; Thổ cẩm Thái dệt tay; Gối thổ cẩm Thái |
| SE10 | Hoa hồng thủy tinh thổi | single | Hit · P 100% | 432 | Hoa hồng thủy tinh thổi |
| SE11 | Tháp Nhạn nhìn xuống đồng lúa Tuy Hòa | single | Hit · P 100% | 446 | Tháp Nhạn nhìn xuống đồng lúa Tuy Hòa |
| SE12 | Đỉnh trầm men rạn | single | Hit · P 70% | 406 | Đỉnh trầm men rạn; Đỉnh trầm gốm men rạn Bát Tràng; Đỉnh gốm Bát Tràng men rạn |
| SE13 | Rèn Phúc Sen (làng rèn dao Cao Bằng) | single | Hit · P 60% | 510 | Rèn Phúc Sen (làng rèn dao Cao Bằng); Dao Phúc Sen Cao Bằng người Nùng An rèn; Rèn Pác Rằng (xóm rèn Phúc Sen); Dao rèn  |
| SE14 | Trụ sở UBND TP HCM | single | Hit · P 100% | 354 | Trụ sở UBND TP HCM |
| SE15 | Đèn con cá (đèn cá chép Trung thu) | single | Hit · P 100% | 406 | Đèn con cá (đèn cá chép Trung thu) |
| SE16 | Thảm cói Phú Tân | single | Hit · P 60% | 343 | Thảm cói Phú Tân; Chiếu cói Tân Châu (An Giang); Thảm cói Kim Sơn (Ninh Bình) |
| SE17 | Trường Đại học Khoa học Huế (Morin Frères cũ, Huế) | single | Hit · P 100% | 431 | Trường Đại học Khoa học Huế (Morin Frères cũ, Huế) |
| SE18 | Hàng nông sản tại Chợ phiên Cán Cấu (Si Ma Cai) | single | Hit · P 90% | 518 | Hàng nông sản tại Chợ phiên Cán Cấu (Si Ma Cai); Chợ phiên Si Ma Cai (Lào Cai) |
| SE19 | Tượng Vishnu Khương Mỹ | single | Hit · P 80% | 382 | Tượng Vishnu Khương Mỹ; Tượng Brahma Khương Mỹ |
| SE20 | Biệt phủ giấy (dinh thự hàng mã) | single | Hit · P 80% | 415 | Biệt phủ giấy (dinh thự hàng mã); Vàng mã phố Hàng Mã (Hà Nội) |
| SE21 | Tòa Thánh Tây Ninh | single | Hit · P 100% | 324 | Tòa Thánh Tây Ninh |
| SE22 | Làng Đường Lâm (Sơn Tây - Hà Nội) | single | Hit · P 100% | 498 | Làng Đường Lâm (Sơn Tây - Hà Nội) |
| SE23 | Thành Cổ Loa | single | Hit · P 100% | 427 | Thành Cổ Loa |
| SE24 | Vòng tay bạc Thái | single | Hit · P 100% | 377 | Vòng tay bạc Thái |
| SE25 | Bộ tem Lăng Tự Đức - Huế VNCH | single | Hit · P 60% | 383 | Bộ tem Lăng Tự Đức - Huế VNCH; Lăng Tự Đức - Huế |
| SE26 | Tượng Bồ Tát Địa Tạng thếp vàng | single | Hit · P 100% | 450 | Tượng Bồ Tát Địa Tạng thếp vàng |
| SE27 | Cối đá giã thuốc nam (cối thuốc bắc) | single | Hit · P 100% | 519 | Cối đá giã thuốc nam (cối thuốc bắc) |
| SE28 | Cầu Đà Rằng | single | Hit · P 100% | 401 | Cầu Đà Rằng |
| SE29 | Gương sơn mài Bình Dương | single | Hit · P 70% | 421 | Gương sơn mài Bình Dương; Sơn mài Bình Dương |
| SE30 | Cá chép đỏ (chép cúng ông Công ông Táo) | single | Hit · P 100% | 448 | Cá chép đỏ (chép cúng ông Công ông Táo) |
| S01 | chợ Bến Thành | single | Hit · P 100% | 340 | Chợ Bến Thành |
| S02 | Nhà thờ Đức Bà Sài Gòn | single | Hit · P 100% | 387 | Nhà thờ Đức Bà Sài Gòn |
| S03 | Lăng Tự Đức | single | Hit · P 100% | 355 | Lăng Tự Đức |
| S04 | chùa Thiên Mụ Huế | single | Hit · P 100% | 487 | Chùa Thiên Mụ Huế |
| S05 | phố cổ Hội An về đêm | single | Hit · P 100% | 444 | Phố cổ Hội An nhà cổ; Phố cổ Hội An ven sông Hoài; Phố đi bộ Hội An (Đêm phố cổ); Phố cổ Hội An (khu phố đi bộ Hội An);  |
| S06 | Chùa Cầu Hội An | single | Hit · P 100% | 434 | Chùa Cầu Hội An (Lai Viễn Kiều - chùa) |
| S07 | Thánh địa Mỹ Sơn | single | Hit · P 100% | 398 | Thánh địa Mỹ Sơn |
| S08 | tháp Bà Ponagar Nha Trang | single | Hit · P 100% | 402 | Tháp Bà Ponagar |
| S09 | Hồ Gươm | single | Hit · P 100% | 334 | Hồ Gươm (hồ Hoàn Kiếm) |
| S10 | Đại Nội Huế | single | Hit · P 100% | 444 | Đại Nội Huế |
| S11 | ruộng bậc thang | single | Hit · P 100% | 372 | Ruộng bậc thang Cao Phạ; Ruộng bậc thang Bát Xát; Ruộng bậc thang Dế Xu Phình; Ruộng bậc thang Hoàng Su Phì; Ruộng bậc t |
| S12 | Dinh Độc Lập | single | Hit · P 100% | 457 | Dinh Độc Lập |
| S13 | Văn Miếu Quốc Tử Giám Hà Nội | single | Hit · P 100% | 352 | Bia tiến sĩ tại Văn Miếu Quốc Tử Giám Hà Nội; Văn miếu Khải Thánh (Quốc Tử Giám, Hà Nội) |
| S14 | Lăng Chủ tịch Hồ Chí Minh | single | Hit · P 100% | 475 | Lăng Chủ tịch Hồ Chí Minh |
| S15 | chợ đêm Phú Quốc | single | Hit · P 100% | 372 | Chợ đêm Phú Quốc |
| S16 | tượng Phật nằm chùa Long Sơn Nha Trang | single | Hit · P 100% | 574 | Tượng Phật nằm chùa Long Sơn (Nha Trang) |
| M01 | Lăng Minh Mạng và lăng Khải Định | multi_intent | đủ ý · P 100% | 284 | Lăng Minh Mạng; Lăng Khải Định |
| M02 | chợ Bến Thành và nhà thờ Đức Bà Sài Gòn | multi_intent | đủ ý · P 100% | 37 | Chợ Bến Thành; Nhà thờ Đức Bà Sài Gòn |
| M03 | Chùa Cầu và phố cổ Hội An | multi_intent | đủ ý · P 100% | 36 | Chùa Cầu (Hội An, Quảng Nam); Phố cổ Hội An (khu phố đi bộ Hội An); Chùa Cầu Hội An (Lai Viễn Kiều - chùa); Phố đi bộ Bạ |
| M04 | chợ đêm và Dinh Cậu ở Phú Quốc | multi_intent | đủ ý · P 100% | 286 | Chợ đêm Phú Quốc; Dinh Cậu ven biển đảo Phú Quốc |
| M05 | Hồ Gươm và Văn Miếu Quốc Tử Giám | multi_intent | đủ ý · P 100% | 27 | Hồ Gươm (hồ Hoàn Kiếm); 82 bia tiến sĩ Văn Miếu Quốc Tử Giám; Bia tiến sĩ tại Văn Miếu Quốc Tử Giám Hà Nội; Tượng Rùa độ |
| M06 | Đại Nội Huế và chùa Thiên Mụ | multi_intent | đủ ý · P 100% | 36 | Đại Nội Huế; Chùa Thiên Mụ; Hiển Lâm Các (Đại Nội Huế) |
| M07 | Thánh địa Mỹ Sơn và tháp Po Nagar | set_query | đủ ý · P 100% | 217 | Thánh địa Mỹ Sơn; Tháp Bà Po Nagar (Khánh Hòa) |
| M08 | Dinh Độc Lập và chợ Bến Thành | multi_intent | đủ ý · P 100% | 35 | Dinh Độc Lập; Chợ Bến Thành |
| M09 | Lăng Tự Đức, lăng Minh Mạng và lăng Khải Định | multi_intent | đủ ý · P 100% | 45 | Lăng Tự Đức; Lăng Minh Mạng; Lăng Khải Định |
| M10 | ruộng bậc thang Tú Lệ và ruộng bậc thang Pù Luông | multi_intent | đủ ý · P 100% | 34 | Ruộng bậc thang Tú Lệ; Ruộng bậc thang Pù Luông |
| M11 | chùa Một Cột và Lăng Chủ tịch Hồ Chí Minh | multi_intent | đủ ý · P 100% | 30 | Bia chùa Một Cột (Diên Hựu tự); Lăng Chủ tịch Hồ Chí Minh; Cột đá chùa Một Cột Diên Hựu; Tranh thêu chùa Một Cột; Chùa M |
| M12 | Hoàng thành Thăng Long và Văn Miếu | set_query | đủ ý · P 70% | 59 | Cây sấu cổ thụ Hoàng thành Thăng Long; Đền thờ Khổng Tử Hà Nội (Văn Miếu) (Đống Đa, Hà Nội); Tem bộ Hoàng thành Thăng Lo |
| M13 | chợ đêm Đông Ba và Đại Nội Huế | multi_intent | phủ 50% · P 50% | 93 | Chợ đêm Đông Ba / chợ đêm Huế; Đại Nội Huế; Hiển Lâm Các (Đại Nội Huế) |
| M14 | biệt thự Nam Phương Hoàng hậu và dinh Bảo Đại | multi_intent | đủ ý · P 100% | 101 | Biệt thự Nam Phương Hoàng hậu (Đà Lạt); Dinh Bảo Đại tại Nha Trang (Lầu Bảo Đại); Dinh Bảo Đại (Lầu Bảo Đại) Đồ Sơn; Din |
| M15 | tháp Po Nagar, chùa Long Sơn và nhà thờ chính tòa Nha Trang | set_query | đủ ý · P 100% | 90 | Tháp Po Nagar Tháp Nam (Khánh Hòa); Chùa Long Sơn (Nha Trang - chùa Phật Trắng); Nhà thờ chính tòa Nha Trang; Chùa Long  |
| H01 | lăng của con trai vua Gia Long | multi_hop | Hit · P 100% · resolved | 41 | Bia lăng Minh Mạng (Hiếu Lăng, Huế); Lăng Minh Mạng Hiếu Lăng; Lăng Minh Mạng - Huế; Lăng Minh Mạng; Cửa đồng bửu thành  |
| H02 | lăng của cha vua Thiệu Trị | multi_hop | Hit · P 100% · resolved | 37 | Bia lăng Minh Mạng (Hiếu Lăng, Huế); Lăng Minh Mạng Hiếu Lăng; Lăng Minh Mạng - Huế; Lăng Minh Mạng; Cửa đồng bửu thành  |
| H03 | lăng của con trai vua Minh Mạng | multi_hop | Hit · P 100% · resolved | 25 | Lăng Thiệu Trị; Lăng Thiệu Trị Xương Lăng; Lăng Thiệu Trị (Xương Lăng, Huế); Bửu thành lăng Thiệu Trị; Nghi môn Lăng Thi |
| H04 | lăng của cha vua Tự Đức | multi_hop | Hit · P 100% · resolved | 27 | Lăng Thiệu Trị; Lăng Thiệu Trị Xương Lăng; Lăng Thiệu Trị (Xương Lăng, Huế); Bửu thành lăng Thiệu Trị; Nghi môn Lăng Thi |
| H05 | lăng của con trai vua Thiệu Trị | multi_hop | Hit · P 100% · resolved | 27 | Lăng Tự Đức Khiêm Lăng; Lăng Tự Đức - Huế; Lăng Tự Đức (Khiêm Lăng, Huế); Lăng Tự Đức; Mộ vua nhà Nguyễn tại Huế lăng Tự |
| H06 | lăng của con trai vua Đồng Khánh | multi_hop | Hit · P 100% · resolved | 30 | Tượng voi chầu lăng Khải Định; Tượng ngựa chầu lăng Khải Định; Bia Bảo Đại lăng Khải Định (Ứng Lăng bi); Cung Thiên Định |
| H07 | lăng của cha vua Khải Định | multi_hop | Hit · P 100% · resolved | 23 | Lăng mộ Đồng Khánh; Lăng Đồng Khánh (Tư Lăng); Lăng Đồng Khánh |
| H08 | lăng của cha vua Bảo Đại | multi_hop | Hit · P 100% · resolved | 38 | Tượng voi chầu lăng Khải Định; Tượng ngựa chầu lăng Khải Định; Bia Bảo Đại lăng Khải Định (Ứng Lăng bi); Cung Thiên Định |
| H09 | lăng của mẹ vua Tự Đức | multi_hop | Trượt · P 0% · resolved | 23 | Lăng Thiệu Trị (Xương Lăng, Huế) |
| H10 | lăng của vợ vua Bảo Đại | multi_hop | Hit · P 100% · resolved | 24 | Lăng Nam Phương Hoàng hậu Pháp; Lăng Hoàng hậu Nam Phương (Đà Lạt) |
| H11 | mộ của cha Chủ tịch Hồ Chí Minh | multi_hop | Hit · P 80% · resolved | 28 | Mộ cụ Nguyễn Sinh Sắc (Cao Lãnh, Đồng Tháp); Mộ cụ Phó bảng Nguyễn Sinh Sắc; Mộ cụ Phó bảng Nguyễn Sinh Sắc (Cao Lãnh, Đ |
| H12 | mộ của mẹ Chủ tịch Hồ Chí Minh | multi_hop | Hit · P 70% · resolved | 26 | Mộ Bà Hoàng Thị Loan; Khu di tích Kim Liên – mộ bà Hoàng Thị Loan (Nghệ An); Khu lưu niệm Chủ tịch Hồ Chí Minh (Kim Liên |
| H13 | lăng của cha vua Thành Thái | multi_hop | Hit · P 100% · resolved | 21 | Chùa An Lăng (Huế - lăng Dục Đức); Lăng Dục Đức (An Lăng); Lăng Dục Đức |
| H14 | lăng của vợ vua Tự Đức | multi_hop | Trượt · P 0% · no_evidence | 19 |  |
| H15 | lăng của con trai vua Khải Định | multi_hop | từ chối đúng · no_evidence | 7 |  |
| H16 | ảnh con trai chủ tịch Phạm Nhật Vượng | multi_hop | từ chối đúng · seed_not_linked | 5 |  |
| O01 | bãi biển Nha Trang | single | trả 10 ảnh sai | 88 | Nhà sàn người Thái trắng Bản Áng (Mộc Châu); Quảng trường 2 tháng 4 (Nha Trang); Làng chài Bãi Xếp Quy Nhơn; Sân bay Nha |
| O02 | hồ bơi và công viên nước ở Phú Quốc | single | trả 10 ảnh sai | 284 | Hồ tiêu Quảng Trị; Khu di tích lịch sử Nhà tù Phú Quốc (Kiên Giang); Cung đường Hồ Chí Minh huyền thoại; Tượng đài Nguyễ |
| O03 | tháp Eiffel Paris | single | trả 10 ảnh sai | 19 | Biệt thự cổ Pháp Le Petit Paris (Đà Lạt); Nghề kim hoàn Hoa Chợ Lớn; Bình trà gốm Biên Hòa men đá |
| O04 | ảnh con hổ và con mèo | single | trả 10 ảnh sai | 44 | Hồ Công viên 29/3 (Đà Nẵng); Dinh thự họ Cao (Vua Mèo Mèo Vạc, Hà Giang); Hồ Gươm (hồ Hoàn Kiếm) |
| O05 | những con vật sống trong rừng | set_query | trả 10 ảnh sai | 46 | Cải xoong; Cột mốc 835 (thác Bản Giốc, Cao Bằng); Chiến khu Rừng Sác (Cần Giờ); Mây làng nghề Phú Vinh (Chương Mỹ, Hà Nộ |
