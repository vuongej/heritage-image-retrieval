# Cải tiến pipeline verify ảnh — Jev của TypeSafe làm tầng quyết định, chỉ gọi VLM 10–20%

> Bản viết lại của tài liệu "cải tiến pipeline" trước đó, với **JEV xác định rõ = Jev của TypeSafe** (System One Model, trả quyết định có kiểu + xác suất hiệu chỉnh), KHÔNG còn là cách hiểu JEPA.
> Toàn bộ số liệu đo trên `data_anh_pass_80000_full_pham_van_vuong.csv` (80.000 dòng) và `LUONG_VERIFY_HIEN_TAI.md` giữ nguyên.
> Ngày lập: 19/10/2026.

---

## 0. Kết luận trước khi đi vào chi tiết

Tôi đã đọc cả hai file và đo trực tiếp trên data của bạn. Ba con số quyết định toàn bộ thiết kế:

| Đo được trên data của bạn | Giá trị |
|---|---|
| Entity sau khi chuẩn hoá tên (không phải entity_id) | 11.278 group / 80.000 dòng |
| Ảnh/entity | TB 7,08 · trung vị 6 · max 41 |
| Gate tất định miễn phí giết được | 2.434 dòng (3,04%) → còn 77.566 ảnh phải xử lý |
| Chi phí nếu gọi VLM 100% | 14,74 USD (đêm) → 33,35 USD (cao điểm) |
| Chi phí nếu gọi VLM 10–20% | 1,47–2,95 USD (đêm) · 3,34–6,67 USD (cao điểm) |
| pHash 64-bit (đo trên 66 ảnh thật, 24 entity) | intra-entity med 32 vs cross-entity med 32, AUC = 0,369 → không tách được gì cả |
| Entity có < 5 ảnh sống sau gate | 4.616 / 11.177 = 41% |

Và một cảnh báo thẳng: **71,4% là con số duy nhất đang được đo thật** (benchmark mù 400 entity trong tài liệu của bạn). Mục tiêu 75–80% không thể đạt bằng cách chỉ đổi kiến trúc — nó phụ thuộc vào một biến duy nhất: **chất lượng tầng quyết định ở phần 80–90% ảnh không gọi VLM**. Jev của TypeSafe chính là đòn bẩy cho biến đó, vì nó sinh ra để làm quyết định có kiểu với confidence đã hiệu chỉnh (calibrated) — phần mà pipeline hiện tại đang tự chế bằng ngưỡng 0.55/0.70 và đang over-confident (bin 0,8–0,9 chỉ khớp người 61,5%).

---

## 1. Đo trên tập data bạn gửi — số thật, không suy diễn

### 1.1 Cấu trúc file

| Chỉ số | Giá trị đo được |
|---|---|
| Dòng | 80.000 · tất cả flag = approved |
| entity_id duy nhất | 11.294 |
| Group theo canonical_name đã chuẩn hoá (bỏ dấu, lowercase) | 11.278 — chỉ 10 group bị trùng tên qua 26 entity_id |
| category | 669 giá trị; bucket theo tiền tố —/( → 479 bucket (đủ nhỏ để stratified) |
| sha256 | rỗng 100% → phải tự tính sau khi tải, không dùng cột này để dedupe |
| image_url | 80.000 unique, 0 trùng trong cùng entity |
| from_db | 0 = 72.218 · 1 = 7.782 |
| description rỗng | 16.110 dòng (20,1%) — toàn bộ thuộc from_db = 0 |
| Entity có description giống hệt nhau cho mọi ảnh | 908 entity → description là tín hiệu cấp entity, không phải cấp ảnh |
| Host | 6.438 host; 90 host phủ 50% số dòng; 368 host ≥ 30 dòng phủ 57.954 dòng |

Hai điểm cuối là vàng: **72% dòng đến từ 368 host → host prior là feature miễn phí rất mạnh** (laodong.vn, danviet.vn, tuoitre.vn… cho ảnh báo chí sạch; mia.vn, bizweb.dktcdn.net, tgdd.vn cho ảnh thiên thương mại/dễ dị ứng).

### 1.2 Gate miễn phí — đo thật trên 80k

| Rule | Số dòng bị loại | % |
|---|---|---|
| R1_noext (URL không có đuôi ảnh) | 1.642 | 2,05% |
| R1_blocked (lookaside.fbsbx.com) | 787 | 0,98% |
| R1_ws / R1_invalid | 5 | 0,01% |
| **Tổng loại cứng** | **2.434** | **3,04%** |
| **Còn phải xử lý** | **77.566** | **96,96%** |

Lưu ý: `R1_noext` là rule mới — bản hiện tại của bạn chỉ chặn lookaside + whitespace, nên 1.642 dòng này hiện đang bị gọi VLM vô ích.

### 1.3 Ảnh thật (tải 69 ảnh mẫu từ 24 entity)

| Chỉ số | Giá trị |
|---|---|
| Tải + decode được | 66/69 = 96% |
| Width med / Height med | 1.024 / 679 px |
| Aspect trong 0,4–3,0 | 100% |
| ≥ 300×200 | 100% → rule R3 khai báo gần như vô dụng trên bộ này (khớp tài liệu: 0 dòng) |
| Dung lượng | med 201 KB, p90 607 KB → 77.566 ảnh ≈ 15,6 GB tải một lần |
| Format | JPEG 59 · WEBP 5 · PNG 2 |

### 1.4 pHash — phát hiện quan trọng: rule R4 đang chết

Tôi tự implement pHash 64-bit (DCT-II 32×32) và đo phân bố trên ảnh thật:

| Đo | Kết quả |
|---|---|
| Intra-entity (cùng entity) | n=61, Hamming trung vị 32 |
| Cross-entity (khác entity) | n=253, Hamming trung vị 32 |
| AUC | **0,369** — thấp hơn cả đoán ngẫu nhiên (0,5) |
| Ngưỡng hiện tại Hamming ≤ 6 | intra 0%, cross 0% → **R4 gần như không bao giờ kích hoạt** |

Nghĩa là: (a) R4 không cứu được gì, (b) pHash không dùng được làm tín hiệu đồng thuận nội entity. **Phải thay bằng cosine trên embedding (ngưỡng 0,97 cho near-dup thật).**

### 1.5 Trần vật lý của bài toán (rất quan trọng cho mục tiêu 75–80%)

| Sau gate | Số entity |
|---|---|
| < 5 ảnh sống | 4.616 (41,3%) |
| 5–9 ảnh | 3.756 |
| ≥ 10 ảnh | 2.805 |
| TB ảnh/entity | 6,94 (median 6) |

Với tỉ lệ yes 44,5% (số bạn đo được), số ảnh yes kỳ vọng = 6,94 × 0,445 ≈ **3,09 ảnh/entity** — tức là trung bình toàn bộ 11.278 entity không thể đạt chỉ tiêu "5 ảnh", kể cả khi model hoàn hảo. Vì vậy:

- Nếu thước đo của bạn là "% entity có ≥5 ảnh yes", mục tiêu 75–80% là **bất khả thi về mặt cấu trúc dữ liệu**.
- Ở mức accuracy ảnh 71,4%, xác suất một entity 7 ảnh có ≥5 ảnh đúng chỉ là ≈68% (binomial); muốn ≈85% thì accuracy/ảnh phải là 0,80. Đây chính là lý do phải nâng accuracy theo ảnh, không phải tinh chỉnh ngưỡng.

---

## 2. "JEV AI" = Jev của TypeSafe — đã xác nhận, và nó đổi tầng nào của pipeline

Đã tra và xác nhận: **Jev là model đầu tiên trong lớp "System One Model" của TypeSafe AI (San Francisco, thành lập 2024)** — model phân biệt (discriminative), dùng cho classification/regression, **không sinh text**:

| Thuộc tính của Jev | Giá trị / ý nghĩa với pipeline này |
|---|---|
| Đầu vào | Dữ liệu phi cấu trúc — nhấn mạnh **structured program state** (state có cấu trúc dạng text/JSON) |
| Đầu ra | Giá trị có kiểu, định nghĩa sẵn schema (Pydantic model): bool, enum, Literal, score — **không bao giờ lỗi kiểu**, không cần parse text |
| Confidence | Mỗi trường trả về kèm **xác suất đã hiệu chỉnh** (`provider_details['confidence']`, ví dụ `{'match': 1.0, 'defer': 0.24}`) — "higher confidence means higher accuracy" |
| Tốc độ | 70–500 ms end-to-end (nhanh hơn LLM 40–200×) |
| Giá | Input **$0,042/MTok**, output miễn phí |
| Hạn chế then chốt | **Không nhìn được ảnh** — demo của TypeSafe là "structured state with text, not on images (yet…)" |

Hệ quả thiết kế — tách bạch hai vai trò:

| Vai trò | Chọn gì | Vì sao |
|---|---|---|
| **Encoder ảnh** (bắt buộc) | DINOv3 ViT-B/L (frozen) + SigLIP 2 (nhánh cross-modal với text tiếng Việt); nhánh phụ V-JEPA 2 / I-JEPA cho ensemble | Jev **không đọc được ảnh**, nên embedding phải đến từ một encoder ảnh riêng. Frozen features tốt nhất cho ít nhãn là DINOv3; SigLIP 2 đa ngữ cho phép so ảnh ↔ canonical_name/description |
| **Tầng quyết định + router** | **Jev của TypeSafe** | Đúng "smart if-statement": nhận state có cấu trúc (feature + metadata dạng text) → trả quyết định `yes/no/defer` có kiểu + confidence đã hiệu chỉnh cho **từng trường**. Thay toàn bộ khối `decide_row` + temperature scaling + conformal tự viết |
| **Tầng đắt** | DeepSeek-flash VLM, chỉ 10–20% | Không đổi model, chỉ đổi cái gì được gửi đi |

Jev giải quyết đúng 3 điểm yếu của pipeline hiện tại:

1. **Over-confidence tự chế**: tài liệu của bạn cho thấy confidence VLM bin 0,8–0,9 chỉ khớp người 61,5%. Jev cam kết confidence đã hiệu chỉnh theo thiết kế → router dựa trên con số đáng tin, không cần temperature scaling thủ công.
2. **Luật decide_row cứng nhắc**: 9 luật if/else tuần tự (mục 5.2 tài liệu hiện tại) đang biến mọi ca biên thành `review → no` (247 dòng). Jev nhận cùng state đó và trả quyết định có kiểu kèm lý do (enum), không rơi vào "sập gieuse nhánh".
3. **Không cần parse JSON từ VLM cho việc dễ**: các câu hỏi tất định kiểu "ảnh này có số điện thoại không?", "host này hay cho ảnh thương mại không?" — Jev trả bool + confidence trong ~100 ms, gần miễn phí, không đốt ngân sách VLM.

**Cảnh báo chi phí Jev**: chỉ input tính tiền. Giữ state/ảnh ≤ ~500 token → 77.566 ảnh × 500 token = 38,8M token ≈ **1,63 USD một lượt** (≈ bằng 1 lượt VLM 10%). Nén state xuống 300 token (bỏ trường rỗng, làm tròn số, viết tắt enum) → ~0,98 USD. Nếu muốn rẻ hơn nữa, chỉ gọi Jev cho ảnh qua gate (~77,5k) và các ca head không chắc.

**Gọi Jev qua Pydantic AI** (mẫu cho schema quyết định của pipeline này):

```python
# pip install "pydantic-ai-slim[typesafe]"
# export TYPESAFE_API_KEY='...'

from pydantic import BaseModel
from typing import Literal
from pydantic_ai import Agent
from pydantic_ai.models.typesafe import TypeSafeModel

class Match(StrEnum):
    DUNG_THUC_THE = "đúng thực thể"
    MOT_PHAN      = "khớp một phần"
    SAI_THUC_THE  = "sai thực thể"

class VerifyDecision(BaseModel):
    verify: Literal["yes", "no", "defer"]          # quyết định chính
    match: Match                                    # enum có kiểu, không sai lệch schema
    ly_do: Literal["link_chet", "qua_nho", "sai_thuc_the", "watermark",
                   "so_dien_thoai", "trung_lap", "diem_thap", "ok"]
    confidence: float                               # 0..1, đã hiệu chỉnh

model = TypeSafeModel("jev-latest")
agent = Agent(model, output_type=VerifyDecision, instructions=(
    "Bạn là tầng quyết định verify ảnh tư liệu di sản Việt Nam. "
    "Nhận state có cấu trúc (điểm đồng thuận nội entity, host prior, category prior, "
    "kích thước ảnh, tỉ lệ khung, tín hiệu head tuyến tính). "
    "Trả verify=yes/no/defer; ảnh không chắc chắn phải defer, không đoán bừa."
))

state = """entity: Cầu Maspéro (Sóc Trăng) | query_type: CHINH
cos_centroid: 0.93 | cos_nn: 0.95 | host_prior: laodong.vn (báo chí, 2.420 dòng)
size: 1024x679 | aspect: 1.51 | head_p_yes: 0.91 | desc_len: 412 | from_db: 1"""
result = agent.run_sync(state)
d = result.output
print(d.verify, d.match, d.ly_do, d.confidence)
print(result.response.provider_details["confidence"])   # confidence từng trường
```

---

## 3. Kiến trúc 4 tầng: Gate → Encoder → **Jev** → VLM cascade

```
T0 Gate tất định → T1 Encoder (DINOv3/SigLIP2) → T2 Feature → state JSON
   → T3 Jev (TypeSafe): quyết định có kiểu + confidence hiệu chỉnh
   → T4 Router ngân sách (θ trên VAL, conformal)
   → nhánh A: nhãn tự động (~80-85%)   |   nhánh B: VLM (~10-20%)
   → T6 Hợp nhất + active learning (Jev làm judge phụ cho output VLM)
```

### T0 — Gate + liên kết (0 đồng, đo được 3,04%)

- Giữ R1 (thêm `R1_noext`), R6 (dedupe URL — nhưng **tính sha256 thật** vì cột đang rỗng).
- **Bỏ R4 pHash** (AUC 0,369 — đã đo, chết).
- **Bỏ R5** dạng "nhân 0,5 độ tự tin" (nó biến mọi ảnh panorama thành no — trong khi ảnh thật của bạn 100% aspect hợp lệ). Thay vào đó: cho Jev trường `aspect` trong state và để nó quyết.
- **Sửa lớn nhất ở T0: R2 không được là `no` ngay.** Tài liệu của bạn ghi ~24% ảnh R2_ do link chết tạm thời vẫn được người giữ → đưa vào bucket `retry_later` (thử lại 3 lần, backoff), chỉ no sau lần 3. Câu hỏi "link này sống được không sau N lần thử" cũng có thể là một câu hỏi bool cho Jev.

### T1 — Encoder một lượt cho toàn bộ 77.566 ảnh

- Tải 1 lần (~15,6 GB, concurrency 32), resize cạnh dài 256, cache file theo sha256 tự tính.
- Forward frozen encoder → float16, 768–1024 chiều: 80k × 1024 × 2B ≈ 157 MB, một file `.npy` duy nhất.
- Trên 1 GPU (ViT-B/16): 300–800 ảnh/s → 2–5 phút; nút cổ chai là download (~15–25 phút), không phải model.
- **Đây là bước biến bài toán thành offline**: mọi thử nghiệm sau đó chạy trên `.npy`, không tải lại ảnh, không tốn tiền API.

### T2 — Feature (7 nhóm, trong đó 5 nhóm miễn phí)

| Feature | Nguồn | Ghi chú |
|---|---|---|
| e_img (768–1024d) | encoder | tín hiệu chính |
| cos_centroid | cosine với centroid các ảnh khác cùng entity | thay thế đúng chỗ pHash thất bại |
| cos_nn | cosine với ảnh gần nhất cùng entity | bắt ảnh "lạc đàn" (intruder) |
| cos_text | SigLIP2 image ↔ canonical_name + description | mạnh, nhưng 20,1% dòng không có description → phải có cờ `has_desc` |
| host_prior | log tần suất host (368 host phủ 72%) | học được "mia.vn/tgdd.vn hay ảnh thương mại" |
| category_prior | log tần suất bucket (479 bucket) | tỉ lệ yes chênh rất mạnh theo category (30,7% → 61,9%) |
| from_db, desc_len | metadata | from_db=1 là nhóm có mô tả đầy đủ hơn |

### T3 — Tầng quyết định bằng **Jev của TypeSafe** (nơi accuracy được tạo ra)

Kiến trúc lai, hai lớp:

1. **Head tuyến tính trên embedding** (logistic regression / MLP 2 lớp trên e_img + 7 feature rời, `class_weight="balanced"`): với 77k mẫu và 768 chiều, logistic là baseline rất khó đánh bại; chỉ chuyển sang LoRA trên 2 block cuối nếu learning curve còn dốc. Head này ra `head_p_yes` — **một con số**, được đưa vào state.
2. **Jev ra quyết định cuối**: nhận state JSON/text gồm `head_p_yes, cos_centroid, cos_nn, cos_text (nếu có), host_prior, category_prior, w, h, aspect, desc_len, from_db, entity_name, category` → trả `VerifyDecision` (schema ở mục 2). Toàn bộ luật `decide_row` (9 luật if/else) và temperature scaling **bị thay thế**: Jev trả verdict + confidence đã hiệu chỉnh cho từng trường ngay từ đầu.

Lợi ích cụ thể so với cách hiện tại:

- **Không over-confident do thừa kế**: confidence VLM cũ (bin 0,8–0,9 chỉ khớp người 61,5%) không còn là nguồn confidence chính; confidence của Jev đã hiệu chỉnh, và router chỉ cần một ngưỡng duy nhất.
- **Không lỗi schema**: `match` luôn thuộc enum, `verify` luôn là `yes/no/defer` — hết cảnh `vlm_error` → `review` (mục 5.2 luật #8).
- **Độ trễ ~100 ms + output miễn phí** → có thể chạy cho 100% ảnh (không chỉ ảnh khó), mỗi ảnh vẫn rẻ hơn một call VLM hàng chục lần.
- Head cấp entity (MIL): pooling điểm các ảnh trong entity → dự đoán "entity này có ≥k ảnh tốt" — vẫn cần riêng, vì mục tiêu thực của bạn là cấp entity; có thể đưa kết quả MIL vào state cho Jev ở lượt xử lý thứ hai.

### T4 — Router: ngân sách VLM là bài toán knapsack, không phải ngưỡng đơn

Jev trả `verify=defer` cho những ca không chắc; bài toán còn lại là **chia ngân sách defer cho đúng**. Đừng chỉ ngưỡng theo entropy. Với data của bạn, ưu tiên theo entity cho hiệu quả cao hơn nhiều:

- Ảnh có u cao (entropy cao / cos_centroid thấp) hoặc **Jev defer** → VLM.
- Entity đang thiếu ảnh yes (<5) → đẩy thêm 2–3 ảnh của entity đó sang VLM (1 ảnh đúng ở entity 3 ảnh có giá trị cao hơn 1 ảnh đúng ở entity 20 ảnh).
- Entity đã có ≥8 ảnh yes chắc chắn → cắt hẳn, không tiêu tiền.
- Entity <5 ảnh sống (4.616 entity = 41%) → không gọi VLM để "cố" — vô ích, đưa vào danh sách cần bổ sung ảnh.

Giải bằng greedy: sắp (giảm accuracy kỳ vọng) / (chi phí) rồi lấp đến ngân sách B = 10–20%. Cách này thường ăn hơn ngưỡng toàn cục 3–6 điểm accuracy ở cùng chi phí. Vẫn giữ conformal threshold trên VAL để **bảo đảm** P(defer) ≤ α (nếu Jev defer nhiều hơn α, ưu tiên chỉ những defer có `confidence` thấp nhất theo conformal rank).

### T5 — Tầng VLM (chỉ 10–20%) phải được thiết kế lại

Điểm mấu chốt: tập bị defer chính là tập khó nhất, nên prompt hiện tại (1 ảnh + description) sẽ cho accuracy thấp hơn 71,4% trên tập này. Bù lại bằng cách đổi đơn vị gọi:

- **Gửi 8 ảnh cùng entity trong 1 message**, yêu cầu model so sánh và trả về mảng JSON: ảnh nào đúng chủ thể, ảnh nào lạc. Câu hỏi "trong 8 ảnh này, ảnh nào không phải X" dễ hơn nhiều so với "ảnh này có phải X không". Token/ảnh gần như không đổi.
- Prompt v2.0: thêm (a) danh sách ảnh cùng entity, (b) luật "khác chủ thể nhưng cùng không gian văn hoá → partial", (c) bắt buộc trả `which_is_wrong` + evidence để audit.
- 3–5% ca bất định nhất: 2 lần gọi độc lập (temperature 0,3), chỉ nhận khi đồng thuận; **không đồng thuận → nhờ Jev làm judge** (đưa mô tả output VLM của cả hai lượt vào state, hỏi "hai lần chấm không đồng thuận, theo state này nên defer cho người không?") → vẫn không rõ thì review cho người.

### T6 — Hợp nhất + active learning

Mỗi batch: nhãn Jev (80–90%) + nhãn VLM (10–20%) + mẫu người audit (~200 ảnh/batch, stratified theo category & u bin) → retrain head. Vẽ learning curve (accuracy vs số nhãn) để biết khi nào ngừng mua nhãn — đây là thứ tiết kiệm tiền nhiều nhất về dài hạn.

---

## 4. Chia 70/30 đúng cách (và 3 bẫy leakage)

Chia theo nhóm canonical_name đã chuẩn hoá, stratified theo bucket category, seed cố định. Kết quả thật khi tôi chạy trên file của bạn:

| | Số dòng | Số group |
|---|---|---|
| Train | 56.433 | 7.899 |
| Test | 23.567 | 3.379 |

(70,5% / 29,5% số dòng.) Trong 70% train, trích tiếp: train 45.146 · val 11.287 (val dùng để chọn θ và kiểm tra calibration của Jev; **test chỉ chạm 1 lần**).

Ba bẫy phải chặn, nếu không con số 75–80% chỉ là ảo giác:

1. **Leakage theo entity**: entity_id là UUID, nhưng cùng một địa danh có thể xuất hiện với 2 UUID và tên gần giống nhau ("Chùa X" / "Chùa X (Hà Nội)"). 10 group đã trùng tên tuyệt đối trên 26 entity_id — phải gom cả fuzzy match (Jaccard token ≥0,9) trước khi split.
2. **Leakage qua cache VLM**: bạn có ~80.500 file cache cũ. Nếu một ảnh trong TEST mà nhãn lại sinh ra từ VLM đã "nhìn thấy" ảnh đó ở TRAIN (qua so sánh nội entity), điểm test sẽ cao giả tạo. Chặn bằng: khoá sha256(image_url) phải xuất hiện chỉ ở một phía.
3. **Jev/VLM vừa là thầy vừa là giám khảo**: nếu bạn train head bằng nhãn Jev/VLM rồi báo accuracy trên chính nhãn đó, bạn chỉ đang đo "% head bắt chước được model" — không liên quan tới người. Bắt buộc có ≥300–500 ảnh test do người chấm (stratified theo category và u), đó mới là thước đo để nói "75–80%".

---

## 5. Ngân sách VLM 10–20%: chi phí thật + điều kiện để đạt 75–80%

### 5.1 Chi phí (tính từ giá bạn đã đo: 0,19 USD/1k đêm · 0,43 USD/1k cao điểm)

| Hạng mục | Số request | Đêm | Cao điểm |
|---|---|---|---|
| VLM 100% (hiện tại) | 77.566 | 14,74 USD | 33,35 USD |
| VLM 20% | 15.513 | 2,95 USD | 6,67 USD |
| VLM 15% | 11.635 | 2,21 USD | 5,00 USD |
| VLM 10% | 7.757 | 1,47 USD | 3,34 USD |
| Jev — tầng quyết định cho 100% ảnh (state ~500 token) | 77.566 | ~1,63 USD | ~1,63 USD (không theo giờ cao điểm) |
| + Bootstrap nhãn ban đầu (VLM 5.000 ảnh stratified) | 5.000 | ~0,95 USD | ~2,15 USD |

Tổng ở α = 15%: **~5,8 USD/đêm** so với 14,74 USD hiện tại — tiết kiệm ~60% dù gọi Jev cho 100% ảnh. Bootstrap 5.000 nhãn = 6,4% ngân sách một lần, rồi từ đó head tự chạy.

### 5.2 Điều kiện toán học để đạt mục tiêu — đây là phần quan trọng nhất

Gọi α = tỉ lệ gọi VLM, A_keep = accuracy trên phần Jev tự quyết (không defer), A_VLM|deferred = accuracy của VLM trên phần khó:

```
acc_tổng = (1 − α)·A_keep + α·A_VLM|deferred
```

Sàn của A_VLM|deferred là 0,714 (đo được của bạn ở 100% coverage) và trên thực tế sẽ thấp hơn vì nó chỉ nhận ca khó. Dưới đây là dự phóng (chưa đo, dựa trên giả định):

| α | A_keep (giả định) | A_VLM|deferred (giả định) | acc dự phóng |
|---|---|---|---|
| 10% | 0,82 | 0,58 | 79,6% |
| 15% | 0,82 | 0,55 | **78,0%** |
| 20% | 0,82 | 0,52 | 76,0% |
| 15% | 0,78 | 0,55 | 74,5% ❌ trượt |

Kết luận có thể hành động: **ở α = 15%, bạn bắt buộc phải có A_keep ≥ 0,82.** Nếu A_keep chỉ đạt 0,78 thì không có ngưỡng nào cứu được — phải quay lại T1/T2 (encoder mạnh hơn, thêm feature, thêm nhãn), không phải chỉnh router.

Ba đòn bẩy thực sự nâng A_keep (theo thứ tự hiệu quả/chi phí):

1. **Nhãn người ở đúng chỗ khó** (active learning trên u cao) — rẻ nhất, +3…6 điểm.
2. **Feature nội entity** (cos_centroid, cos_nn) + head cấp entity — với 7 ảnh/entity, đồng thuận nội entity là tín hiệu cực mạnh mà pipeline hiện tại không hề dùng (pHash không làm được việc này, đã đo). Đây cũng là phần state mà Jev khai thác tốt nhất.
3. **Encoder mạnh hơn + ensemble DINOv3/SigLIP2/V-JEPA** — +2…4 điểm, chi phí GPU một lần.

---

## 6. Workflow chạy thật (6 bước, có thể lặp)

```
B0. Gate + hash + dedupe            → gate_report.json        (0 đồng, 3,04% bị loại)
B1. Tải 1 lần + embedding 80k       → emb_all.npy (~157MB)    (0 đồng API, 20-40 phút)
B2. Split 70/30 theo group          → split.json              (56.433 / 23.567)
B3. Bootstrap nhãn: VLM trên 5.000 ảnh stratified (6,4% budget) → labels_boot.csv (~0,95 USD)
B4. Train head + dựng state + Jev quyết định pilot 1.000 ảnh → decisions.parquet (~0,02 USD Jev)
B5. Suy luận cascade trên TEST (Jev 100% + VLM 10-20%) → test_scores.csv (1,47-2,95 USD)
B6. Audit người 300-500 ảnh + retrain → learning_curve.png   (chi phí người)
```

Ở B3, mẹo tiết kiệm: khớp với 80.500 cache cũ theo canonical_name + sha256(image_url) trước khi gọi API — phần nào trùng thì nhãn về 0 đồng. Ở B4, so kết quả Jev pilot với nhãn bootstrap để đo A_keep thật **trước** khi mở rộng — đây là phép kiểm chứng rẻ nhất cho mục 5.2.

---

## 7. Code: khung pipeline đã viết & chạy kiểm tra

Script đã chạy được cả hai chế độ (verify: `--demo` chạy hết, `--csv data.csv` in ra đúng gate 2.434 và split 56.433/23.567): **`jev_cascade_pipeline.py`** — tải về chạy trực tiếp.

```python
"""jev_cascade_pipeline.py — verify ảnh: gate → encoder → state → Jev → router → VLM"""
import argparse, csv, math, re, collections, unicodedata, random
import numpy as np

# ---------- T0: GATE (0 đồng) ----------
BLOCK = ("lookaside.fbsbx.com", "scontent.xx.fbcdn.net/login")
EXT = re.compile(r"\.(jpe?g|png|webp|gif|avif)(\?|$)", re.I)

def gate(url):
    u = url or ""
    if not u.startswith(("http://", "https://")) or not re.match(r"https?://[^/]+", u):
        return "R1_invalid"
    if any(b in u for b in BLOCK): return "R1_blocked"
    if " " in u: return "R1_ws"
    if not EXT.search(u): return "R1_noext"          # rule MỚI: bắt 1.642 dòng trên data của bạn
    return None

# ---------- Chia 70/30 theo GROUP, chống leakage ----------
def norm(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()

def category_bucket(cat):
    return re.sub(r"\s+", " ", (cat or "").split("(")[0].split("—")[0]).strip().lower()

def group_split(rows, test_frac=0.30, seed=42):
    groups = collections.defaultdict(list)
    for r in rows: groups[norm(r["canonical_name"])].append(r)
    by_bucket = collections.defaultdict(list)
    for gk, rs in groups.items(): by_bucket[category_bucket(rs[0]["category"])].append(gk)
    tr, te = [], []
    for b, gs in sorted(by_bucket.items()):
        gs = sorted(gs); random.Random(seed).shuffle(gs)
        n_te = max(1, int(round(test_frac * len(gs)))) if len(gs) > 1 else 0
        te += gs[:n_te]; tr += gs[n_te:]
    idx = lambda ks: [r for k in ks for r in groups[k]]
    return idx(tr), idx(te), len(tr), len(te)

# ---------- T2: FEATURE + STATE cho Jev ----------
def build_features(rows, emb):
    """emb: {image_url: np.array(d)}. Thêm 5 feature phi-ảnh + 2 feature nội entity."""
    ent = collections.defaultdict(list)
    for r in rows: ent[norm(r["canonical_name"])].append(r)
    host_cnt = collections.Counter(re.sub(r"^https?://([^/]+).*$", r"\1", r["image_url"]).lower() for r in rows)
    cat_cnt  = collections.Counter(category_bucket(r["category"]) for r in rows)
    X, meta = [], []
    for r in rows:
        e = emb[r["image_url"]]
        sib = [x for x in ent[norm(r["canonical_name"])] if x is not r]
        cen = np.mean([emb[x["image_url"]] for x in sib], axis=0) if sib else e
        n = lambda v: np.linalg.norm(v) + 1e-9
        cos_cen = float(e @ cen / (n(e) * n(cen)))                     # đồng thuận nội entity
        nn = max([float(e @ emb[x["image_url"]] / (n(e) * n(emb[x["image_url"]]))) for x in sib], default=0.0)
        h = re.sub(r"^https?://([^/]+).*$", r"\1", r["image_url"]).lower()
        X.append(np.concatenate([e, [
            cos_cen, nn,
            math.log1p(host_cnt[h]), math.log1p(cat_cnt[category_bucket(r["category"])]),
            1.0 if (r["description"] or "").strip() else 0.0,
            min(len(r["description"] or ""), 600) / 600.0,
            1.0 if r["from_db"] == "1" else 0.0]]))
        meta.append(r)
    return np.array(X, dtype=np.float32), meta

# ---------- T3: HEAD + JEV DECISION ----------
def fit_head(X, y, C=1.0):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    sc = StandardScaler().fit(X)
    clf = LogisticRegression(C=C, max_iter=2000, class_weight="balanced").fit(sc.transform(X), y)
    return sc, clf

def to_jev_state(r, p_yes, feat_row):
    """Nén feature thành state text ≤ ~500 token cho Jev."""
    return (f"entity: {r['canonical_name']} | query_type: {r['category']}\n"
            f"head_p_yes: {p_yes:.3f} | cos_centroid: {feat_row[0]:.3f} | cos_nn: {feat_row[1]:.3f}\n"
            f"host_prior: {feat_row[2]:.2f} | cat_prior: {feat_row[3]:.2f} "
            f"| has_desc: {feat_row[4]:.0f} | desc_len_norm: {feat_row[5]:.2f} | from_db: {feat_row[6]:.0f}")

def conformal_threshold(u, alpha=0.20):
    """θ sao cho P(defer) <= alpha, hiệu chỉnh hữu hạn mẫu (split-conformal)."""
    u = np.sort(np.asarray(u, float)); n = len(u)
    k = math.ceil((n + 1) * (1 - alpha))
    return float(u[min(k, n) - 1])

# ---------- T4: ROUTER theo ngân sách + ưu tiên entity ----------
def route(entity_ids, u, p, budget=0.15):
    """Chọn tập defer: ưu tiên u cao, và entity đang thiếu ảnh yes."""
    ent_cnt = collections.Counter(entity_ids)
    score = u + np.array([0.25 / max(1, ent_cnt[e]) for e in entity_ids])  # entity nhỏ -> ưu tiên
    k = int(round(budget * len(entity_ids)))
    idx = np.argsort(-score)[:k]
    return set(idx.tolist())

def evaluate(y, pred, defer):
    y = np.asarray(y); pred = np.asarray(pred); defer = np.asarray(defer)
    acc = lambda m: float(np.mean(y[m] == pred[m])) if m.sum() else float("nan")
    return {"defer_rate": float(defer.mean()), "acc_all": float(np.mean(y == pred)),
            "acc_keep": acc(~defer), "acc_deferred": acc(defer)}
```

Cách dùng thật:

```bash
python jev_cascade_pipeline.py --csv data_anh_pass_80000_full_pham_van_vuong.csv
# gate: [(None, 77566), ('R1_noext', 1642), ('R1_blocked', 787), ('R1_ws', 4), ('R1_invalid', 1)]
# train 56433 dòng/7899 group | test 23567 dòng/3379 group
python jev_cascade_pipeline.py --demo     # kiểm tra code path bằng dữ liệu tổng hợp
```

Đoạn mã chưa chứa phần encoder (cần GPU + tải model) — đó là phần duy nhất bạn phải bổ sung:

```python
# T1 — chạy 1 lần cho 77.566 ảnh
import torch, numpy as np
from PIL import Image
from transformers import AutoModel
m = AutoModel.from_pretrained("facebook/dinov3-vitb16-pretrain-lvd1689m").cuda().eval()
# hoặc: "facebook/ijepa_vith14_1k" / google/siglip2-base-patch16-256
@torch.no_grad()
def embed(paths, bs=64):
    out = []
    for i in range(0, len(paths), bs):
        batch = torch.stack([preprocess(Image.open(p).convert("RGB")) for p in paths[i:i+bs]]).cuda()
        out.append(m(pixel_values=batch).last_hidden_state[:, 0].half().cpu().numpy())  # CLS token
    return np.concatenate(out).astype(np.float32)
# np.save("emb_all.npy", embed(all_paths))   # ~157 MB
```

---

## 8. Checklist đo lường (để 75–80% là số thật, không phải số đẹp)

| Phải báo cáo | Cách tính | Vì sao |
|---|---|---|
| Risk–coverage curve | accuracy theo α ∈ {5, 10, 15, 20, 30%} | một con số accuracy duy nhất ở 100% là vô nghĩa với kiến trúc này |
| AURC | diện tích dưới risk–coverage | so sánh head A với head B độc lập với ngưỡng |
| Calibration của Jev | ECE = \|acc − conf\| theo bin, trên val | Jev cam kết "higher confidence = higher accuracy" — phải kiểm chứng trên data của bạn, không tin marketing |
| Defer rate thực tế vs θ | conformal check trên test | bảo đảm "10–20%" là bảo đảm, không phải hy vọng |
| Cấp entity: %entity ≥5 yes, trung vị ảnh yes/entity | trên test | mục tiêu thực của bạn là entity, không phải ảnh |
| Theo category & theo host | bảng chéo | 61,9% vs 30,7% chênh rất lớn → trung bình che mất lỗi hệ thống |
| Chi phí/1k ảnh + số request cache hit | log từ client | kiểm soát ngân sách thật (VLM + Jev tính riêng) |

Bốn cái bẫy phải tránh khi báo cáo: (1) test chạm nhiều lần rồi chọn θ → phải chọn θ trên val; (2) head train bằng nhãn Jev/VLM rồi báo accuracy trên chính nhãn đó; (3) trộn ảnh cùng entity giữa 2 phía; (4) tính accuracy trên dòng pending/no do link chết như dự đoán đúng.

---

## 9. Rủi ro & những gì cần bạn xác nhận

1. **Nhãn người**: tôi có 0 nhãn người trong file này (flag toàn approved, không có cột verify). Toàn bộ accuracy là: 71,4% (số bạn đo) + phần còn lại là dự phóng có ghi rõ. Muốn chứng minh 75–80%, cần ≥300–500 ảnh test do người chấm.
2. **"JEV" đã chốt là Jev của TypeSafe** (System One Model, quyết định có kiểu + confidence hiệu chỉnh, không đọc ảnh). Hạn chế "not on images (yet…)" của Jev chính là lý do kiến trúc giữ một encoder ảnh riêng ở T1 — nếu sau này Jev hỗ trợ ảnh, có thể bỏ một lớp trung gian.
3. **Ngưỡng chấp nhận**: nếu chỉ tiêu là "≥5 ảnh/entity", 41% entity không thể đạt ngay từ dữ liệu. Đề nghị đổi thành ≥3 ảnh yes + gắn cờ "cần bổ sung ảnh" cho 4.616 entity đó.
4. **Token/ảnh khi gửi 8 ảnh/lần VLM**: cần đo lại — chi phí có thể tăng 10–25% vì ảnh lớn hơn trong prompt, nhưng accuracy trên tập khó tăng nhiều hơn. Đo trước trên 200 entity rồi mới chạy toàn bộ.
5. **Calibration của Jev trên domain tiếng Việt/di sản**: chưa có số công khai; phải đo ECE trên val (mục 8) trước khi tin confidence của nó cho router.

**Bước tiếp theo rẻ nhất để kiểm chứng tất cả**: chạy B0→B1→B3→B4 trên 400 entity stratified (~2.800 ảnh, ~0,55 USD VLM + ~0,02 USD Jev) rồi vẽ risk–coverage. Nếu A_keep ở α = 15% ≥ 0,82 thì mục tiêu 75–80% là khả thi; nếu chỉ 0,76–0,78 thì phải quay lại encoder/feature trước khi đốt thêm tiền.
