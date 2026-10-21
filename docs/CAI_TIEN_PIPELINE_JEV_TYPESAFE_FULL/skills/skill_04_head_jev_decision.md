# Skill 04 — Head tuyến tính + Jev ra quyết định (T3)

## Mục đích
Tạo accuracy ở phần 80–90% ảnh KHÔNG gọi VLM: head tuyến tính chấm điểm thô → **Jev của TypeSafe** (System One Model, `jev-latest`) nhận state và trả quyết định có kiểu `yes/no/defer` kèm confidence **đã hiệu chỉnh** — thay toàn bộ khối `decide_row` 9 luật if/else và temperature scaling thủ công.

## Khi nào kích hoạt (Triggers)
- Sau khi có X (T2) và nhãn bootstrap (B3 trong workflow).
- Mỗi batch retrain hoặc khi ECE của Jev trên val vượt 0.05.

## Đầu vào / Đầu ra
| | Chi tiết |
|---|---|
| **Vào** | `X.npy`, `states.jsonl`, nhãn bootstrap (VLM 5.000 ảnh stratified) |
| **Ra** | `head.pkl` (scaler + logistic), `decisions.parquet` (verify/match/ly_do/confidence từng ảnh) |

## Quy trình từng bước
1. **Train head**: logistic regression (`C=1.0`, `max_iter=2000`, `class_weight="balanced"`) trên StandardScaler(X). Với 77k mẫu × 768 chiều, đây là baseline khó đánh bại; chỉ lên LoRA 2 block cuối nếu learning curve còn dốc.
2. Head ra `head_p_yes` cho từng ảnh → nạp vào state (skill 03).
3. **Định nghĩa schema quyết định cho Jev** (Pydantic — Jev không bao giờ lỗi kiểu, không cần parse text):
   ```python
   # pip install "pydantic-ai-slim[typesafe]" ; export TYPESAFE_API_KEY='...'
   from pydantic import BaseModel
   from typing import Literal
   from pydantic_ai import Agent
   from pydantic_ai.models.typesafe import TypeSafeModel

   class Match(StrEnum):
       DUNG_THUC_THE = "đúng thực thể"
       MOT_PHAN      = "khớp một phần"
       SAI_THUC_THE  = "sai thực thể"

   class VerifyDecision(BaseModel):
       verify: Literal["yes", "no", "defer"]
       match: Match
       ly_do: Literal["link_chet", "qua_nho", "sai_thuc_the", "watermark",
                      "so_dien_thoai", "trung_lap", "diem_thap", "ok"]
       confidence: float

   model = TypeSafeModel("jev-latest")
   agent = Agent(model, output_type=VerifyDecision, instructions=(
       "Bạn là tầng quyết định verify ảnh tư liệu di sản Việt Nam. "
       "Nhận state có cấu trúc (điểm đồng thuận nội entity, host prior, category prior, "
       "kích thước ảnh, tín hiệu head tuyến tính). Trả verify=yes/no/defer; "
       "ảnh không chắc chắn phải defer, không đoán bừa."))
   ```
4. **Đọc confidence từng trường** từ `result.response.provider_details['confidence']` (Jev trả ví dụ `{'match': 1.0, 'defer': 0.24}`) — đã hiệu chỉnh theo thiết kế.
5. **Kiểm calibration trên val** (KHÔNG phải tin marketing): tính ECE = |acc − conf| theo bin. Pipeline cũ over-confident (bin 0,8–0,9 chỉ khớp người 61,5%) — Jev phải tốt hơn điều đó trên val thì mới dùng làm nguồn confidence chính.
6. **Conformal threshold** trên val để bảo đảm P(defer) ≤ α:
   ```python
   def conformal_threshold(u, alpha=0.20):
       u = np.sort(np.asarray(u, float)); n = len(u)
       k = math.ceil((n + 1) * (1 - alpha))
       return float(u[min(k, n) - 1])
   ```
7. Ghi `decisions.parquet`.

## Ví dụ state → quyết định
```
state: head_p_yes 0.91 | cos_centroid 0.93 | host laodong.vn (báo chí) → verify=yes, confidence 0.96
state: head_p_yes 0.54 | cos_centroid 0.61 | host mia.vn (thương mại) → verify=defer, confidence 0.41
```

## Lỗi thường gặp & nhánh dự phòng
- Jev trả `defer` nhiều hơn α → dùng conformal rank để chỉ chuyển `defer` có confidence thấp nhất sang nhánh VLM.
- ECE trên val > 0.05 → thêm cặp (state → nhãn người) vào val và yêu cầu Jev chấm lại; nếu vẫn lệch, trở lại dùng conformal thay vì confidence raw.
- Jev chưa hỗ trợ ảnh ("not on images (yet…)") → **không bao giờ gửi ảnh cho Jev**, chỉ gửi state text. Ảnh chỉ đi vào VLM ở T5.
- Rate limit / lỗi tạm thời → retry backoff; Jev ~100ms/request nên 77.566 ảnh chạy song song 16 luồng xong trong ~10 phút.
