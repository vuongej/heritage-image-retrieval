# Seed từ CSV

```bash
docker compose run --rm api python -m db.seed_entities_from_csv \
  --csv data/bo_sung_anh_cho_entities_nhom_1_Vuong_ent1-500.csv
```

Kết quả mong đợi (đã đối chiếu file thật):

| Chỉ số | Giá trị |
|---|---|
| Dòng dữ liệu | 3.226 |
| Entity duy nhất | 500 |
| Ảnh / entity (trung bình) | 6,45 |
| Entity 0 ảnh (`so_anh_pass_master = 0`) | 242 |
| Entity dưới 5 ảnh (`entity_duoi_5_master = yes`) | 478 |
| Ảnh `verify = no` | 927 (28,7%) |
| Ảnh < 600 px chiều ngang | 318 |
