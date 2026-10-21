# Gold set

**Mục tiêu:** ≥ 300 query (100 single + 100 multi-intent + 100 multi-hop) + 50 set query.

## Cách xây (báo cáo được phương pháp)

1. **Stratified sampling** theo `branch × priority × query_type` để không thiên lệch về nhóm lớn
   (trong CSV nhóm 1: F chiếm 1.950/3.226, P1 chiếm 2.692/3.226).
2. Mỗi query gán tập relevant `R` = ảnh thoả đồng thời:
   - đúng `entity_id` (single / multi-hop), hoặc đúng `parent_class` (set query),
   - `decision = accept` sau pipeline Phần A,
   - `width >= 600`.
3. **Multi-hop:** `R` xác định bằng **graph traversal**, KHÔNG qua model retrieval (tránh circularity).
4. Tái dùng **927 ảnh `verify = no`** làm negative seed miễn phí.

## File

| File | Nội dung |
|---|---|
| `single_intent.jsonl` | `{"query": "...", "relevant": ["image_id", ...]}` |
| `multi_intent.jsonl` | kèm `sub_queries` |
| `multi_hop.jsonl` | kèm `hop_chain` |
| `set_query.jsonl` | kèm `parent_class` |
| `quality.json` | `image_id -> {passes_quality, width, watermark}` |

## Lưu ý về `|R|` nhỏ

CSV nhóm 1 có **242 entity 0 ảnh** và **478 entity dưới 5 ảnh** → với các entity này `|R| < 10`,
Recall@10 bị chặn trần. **Phải báo cáo Recall tách riêng cho nhóm thiếu ảnh**, không gộp chung.
