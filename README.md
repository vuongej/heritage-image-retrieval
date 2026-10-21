# Heritage Image Retrieval — Repo Skeleton

> **Bộ tài liệu rà soát 21/10/2026:** [Tài liệu kỹ thuật](docs/technical-report.vi.md) · [Performance và benchmark](docs/performance-benchmark.vi.md) · [Test case](docs/test-cases.vi.md).
> Các tài liệu này đối chiếu mã hiện tại với dữ liệu master, phân biệt kết quả đo, giả định thiết kế và phần còn là stub. Nội dung skeleton bên dưới là hướng dẫn từ giai đoạn đầu của dự án.

> **Deploy + CI/CD** (Vercel cho web, VM Oracle Always Free cho API, GitHub Actions): [docs/deploy.md](docs/deploy.md).
> Chạy local với dữ liệu approved và DeepSeek: xem [hướng dẫn](docs/local-approved-run.md).
> Bản ghi lần chạy full pipeline cho `username = pham_van_vuong`: [docs/pipeline-run-pham_van_vuong.md](docs/pipeline-run-pham_van_vuong.md).
> Giao diện local (http://127.0.0.1:8000/) + 18 test case: [docs/ui-testcases.md](docs/ui-testcases.md).
> Pipeline verify ảnh Phần A (gate → SigLIP2 → head → Jev qua OpenRouter → VLM 15%): [docs/verify-pipeline-jev.md](docs/verify-pipeline-jev.md).

Pipeline lọc ảnh tự động (**Phần A**) + hệ thống truy xuất ảnh (**Phần B**) cho kho ảnh di sản Việt Nam.
**Chạy được hoàn toàn KHÔNG cần API key** — key chỉ là tầng tăng chất lượng, bật thêm khi có.

---

## 1. Chạy nhanh (không cần key)

```bash
cp .env.example .env        # LLM_PROVIDER=none là mặc định
make up                     # docker compose up -d --build
make seed                   # nạp CSV entity nhóm 1 (500 entity / 3.226 ảnh) lên S3
open http://localhost:3000  # web demo
```

Kiểm tra nhanh:

```bash
curl http://localhost:8000/v1/health

curl -X POST http://localhost:8000/v1/search \
  -H 'X-API-Key: gsk_test_dev_only' \
  -H 'Content-Type: application/json' \
  -d '{"query":"Quần thể Tràng An","top_k":10}'
```

---

## 2. Ba mode LLM (`LLM_PROVIDER`)

| Mode | Cần key | Query parser | Stage 3 VLM | Chi phí API |
|---|---|---|---|---|
| `none` **(mặc định)** | Không | Rule-based (regex + alias + slot) | Tắt → human review queue | **$0** |
| `local` | Không | Qwen3.5-2B/4B qua Ollama | Qwen3-VL-4B / SmolVLM2 | $0 |
| `gemini` | **Có** | Gemini 3.5 Flash-Lite | Gemini 3.5 Flash-Lite (Batch) | theo cost model |

Bật mode `gemini` khi bạn đã có key:

```bash
sed -i 's/^LLM_PROVIDER=.*/LLM_PROVIDER=gemini/' .env
printf 'GEMINI_API_KEY=<key-cua-ban>\n' >> .env
make up
```

> Không có key vẫn chạy đủ 3 loại truy vấn. Chỉ **multi-hop** ở mode `none` bị giảm recall
> (rule-based parser không tách được hop chain) — xem `docs/retrieval.md`.

---

## 3. Cấu trúc repo

```text
heritage-image-retrieval/
├── .github/
│   └── workflows/
│       ├── ci.yml
│       └── nightly-eval.yml
├── api/
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── backfill.py
│   │   ├── embed.py
│   │   ├── entities.py
│   │   ├── graph.py
│   │   ├── health.py
│   │   ├── ingest.py
│   │   ├── rerank.py
│   │   └── search.py
│   ├── __init__.py
│   ├── deps.py
│   ├── main.py
│   ├── schemas.py
│   └── security.py
├── config/
│   ├── cascade.yaml
│   ├── latency_budget.yaml
│   └── models.yaml
├── data/
│   ├── .gitkeep
│   └── README.md
├── db/
│   ├── migrations/
│   │   └── 001_init.sql
│   ├── schema.dbml
│   ├── seed_entities_from_csv.md
│   └── seed_entities_from_csv.py
├── docs/
│   ├── diagrams/
│   │   ├── architecture.mmd
│   │   ├── cascade.mmd
│   │   ├── ci-cd.mmd
│   │   └── retrieval.mmd
│   ├── architecture.md
│   ├── data-pipeline.md
│   ├── performance.md
│   ├── README.md
│   └── retrieval.md
├── evals/
│   ├── goldset/
│   │   ├── multi_hop.jsonl
│   │   ├── multi_intent.jsonl
│   │   ├── quality.json
│   │   ├── README.md
│   │   ├── set_query.jsonl
│   │   └── single_intent.jsonl
│   ├── __init__.py
│   └── harness.py
├── loadtest/
│   ├── loadtest.js
│   ├── make_report.py
│   └── README.md
├── pipeline/
│   ├── __init__.py
│   ├── __main__.py
│   ├── routing.py
│   ├── stage1_heuristics.py
│   ├── stage2_classifier.py
│   ├── stage3_vlm.py
│   └── worker_loop.py
├── reports/
│   └── .gitkeep
├── retrieval/
│   ├── __init__.py
│   ├── backfill.py
│   ├── embed.py
│   ├── fusion.py
│   ├── graph.py
│   ├── query_parser.py
│   ├── rerank.py
│   ├── rule_parser.py
│   ├── search.py
│   └── speculative.py
├── scripts/
│   ├── bench_stage3_cost.py
│   ├── issue_test_key.py
│   └── seed_from_csv.py
├── storage/
│   ├── __init__.py
│   ├── redis_cache.py
│   └── s3.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_api_contract.py
│   ├── test_backfill.py
│   ├── test_fusion.py
│   ├── test_metrics.py
│   ├── test_routing.py
│   ├── test_rule_parser.py
│   └── test_stage1_gates.py
├── web/
│   ├── app/
│   │   ├── globals.css
│   │   ├── layout.tsx
│   │   └── page.tsx
│   ├── components/
│   │   ├── FacetChips.tsx
│   │   ├── ResultGrid.tsx
│   │   └── SearchBar.tsx
│   ├── lib/
│   │   └── api.ts
│   ├── public/
│   │   └── .gitkeep
│   ├── next.config.mjs
│   ├── package.json
│   ├── README.md
│   └── tsconfig.json
├── .env.example
├── .gitignore
├── docker-compose.yml
├── Dockerfile.api
├── Dockerfile.web
├── Dockerfile.worker
├── Makefile
├── pyproject.toml
├── README.md
├── requirements-worker.txt
└── requirements.txt
```

---

## 4. SLO đã chốt

| Chỉ số | Ngưỡng |
|---|---|
| Retrieval p95 | **< 1500 ms** trên 80.000 ảnh |
| Retrieval p50 | ≈ 400 ms |
| Graph build (offline) | **< 5 s** |
| Recall@10 | ≥ 0,70 |
| Hit@10 | ≥ 0,95 |

Ngân sách chi tiết: `config/latency_budget.yaml`.
LLM parse **không** nằm đồng bộ trên critical path — xem `docs/retrieval.md` mục *Speculative parse*.

---

## 5. Endpoint

| Endpoint | Method | Auth | Mô tả |
|---|---|---|---|
| `/v1/health` | GET | không | Healthcheck |
| `/v1/search` | POST | có | Pipeline đầy đủ |
| `/v1/embed` | POST | có | **Chỉ** embedding (text/image → vector) |
| `/v1/rerank` | POST | có | **Chỉ** rerank danh sách ứng viên |
| `/v1/entities` | GET | có | Entity + facet để drill-down |
| `/v1/graph` | GET/POST | có | Truy vấn / rebuild graph |
| `/v1/ingest` | POST | có | Nạp batch ảnh mới |
| `/v1/backfill` | POST | có | Queue bổ sung ảnh thiếu |

---

## 6. Đo lường

```bash
make test        # pytest
make eval        # Recall@10 / Hit@10 / nDCG / MRR trên goldset
make loadtest    # k6, threshold p95 < 1500 ms
make report      # sinh reports/report.html
```

---

## 7. Tài liệu

- `docs/architecture.md` — kiến trúc tổng thể + Mermaid
- `docs/data-pipeline.md` — cascade 3 tầng Phần A + cost model
- `docs/retrieval.md` — 3 loại query + set query + speculative parse
- `docs/performance.md` — ngân sách latency + cách đo
- `docs/diagrams/*.mmd` — sơ đồ rời

---

## 8. Trạng thái skeleton

Đây là **khung repo**: cấu trúc thư mục, schema, config, sơ đồ và stub code đã khớp kiến trúc.
Các hàm đánh dấu `TODO(impl)` là chỗ cần cài đặt thật.
