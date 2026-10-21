# Load test (reproducible)

```bash
make loadtest   # docker compose --profile loadtest run --rm k6 run /scripts/loadtest.js
make report     # -> reports/report.html + reports/report.json
```

## Cách đo (phải ghi rõ trong báo cáo)

1. Warm-up **200 request** trước khi ghi số.
2. Đo **song song** server-side (`X-Response-Time`) và client-side (k6 `http_req_duration`) → báo cáo cả hai.
3. **10.000 request** mỗi loại query; chốt p50 / p95 / **p99**.
4. Tách bảng theo `single | multi_intent | multi_hop | set_query | embed | rerank`
   **và** theo `LLM_PROVIDER` (`none | local | gemini`).
5. Ghi rõ cấu hình máy, số ảnh trong index, model, batch size, cache state.

## Threshold

| Scenario | Threshold |
|---|---|
| single_intent | `p(95) < 1500 ms` |
| multi_intent | `p(95) < 1500 ms` |
| multi_hop | `p(95) < 1500 ms` |
| set_query | `p(95) < 1500 ms` |
| embed_only | `p(95) < 200 ms` |
| rerank_only | `p(95) < 400 ms` |
| errors | `rate < 0.01` |
