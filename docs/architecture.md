# Kiến trúc tổng thể

## 1. Sơ đồ

```mermaid
flowchart TB
  subgraph SRC["① Nguồn"]
    CR[Crawler HTML/API] --> RAW[(S3 bronze/raw)]
    CSV[CSV entity nhóm 1] --> RAW
  end

  subgraph PART_A["② PHẦN A — Pipeline lọc ảnh tự động (offline, batch)"]
    RAW --> S1["Stage 1 · Heuristics CPU<br/>resolution · aspect · blur<br/>pHash dedup · watermark-zone"]
    S1 -->|pass| S2["Stage 2 · Small classifier GPU<br/>SigLIP2-B/16 fine-tuned<br/>5 head: relevance/watermark/NSFW/violence/politics"]
    S1 -->|fail| REJ[(S3 rejects/)]
    S2 -->|"p >= 0.70"| GOLD
    S2 -->|"p <= 0.35"| REJ
    S2 -->|"0.35 < p < 0.70<br/>~8% ảnh"| S3["Stage 3 · VLM<br/>Gemini 3.5 Flash-Lite / local Qwen3-VL<br/>Batch API + JSON schema"]
    S3 --> GOLD
    S2 -.->|"khi LLM_PROVIDER=none"| HRQ[(human_review_queue)]
    GOLD["S3 gold/ · Parquet + manifest"]
  end

  subgraph PART_B["③ PHẦN B — Retrieval (online, KHÔNG agent)"]
    Q[Người dùng nhập query] --> API[API Gateway<br/>X-API-Key]
    API --> QP["Query Parser<br/>rule-based fast path<br/>+ LLM speculative"]
    QP -->|single| VEC
    QP -->|multi_intent| VEC
    QP -->|multi_hop| GR["Graph traversal<br/>entity -> relation -> entity"]
    QP -->|set_query| GR
    GR --> VEC["Query Encoder<br/>SigLIP2 text tower"]
    VEC --> ANN["ANN search HNSW<br/>top-200"]
    ANN --> FLT["Metadata filter<br/>branch · priority · query_type · min-res"]
    FLT --> RR["Reranker cross-encoder<br/>100 -> 10"]
    RR --> OUT[Top-10 ảnh + facet entity]
  end

  GOLD --> IDX[(Vector index + Metadata)]
  IDX --> ANN
  GOLD --> GRAPH[(Entity Graph)]
  GRAPH --> GR
```

## 2. Nguyên tắc bất di bất dịch

Nhánh retrieval chỉ có `encode → ANN → filter → rerank`. **Không tool-calling, không vòng lặp suy luận,
không agent chọn ảnh.** LLM chỉ xuất hiện ở *trước* index (query parsing) — và ở đó nó chạy
**speculative**, không đồng bộ trên critical path (xem `docs/retrieval.md`).

## 3. Ánh xạ thành phần → thư mục

| Thành phần | Thư mục |
|---|---|
| Pipeline lọc ảnh (Phần A) | `pipeline/` |
| Retrieval (Phần B) | `retrieval/` |
| API gateway + middleware | `api/` |
| S3 bronze/silver/gold | `storage/` |
| Schema + migration | `db/` |
| Ngân sách latency + cascade config | `config/` |
| Đo chất lượng | `evals/` |
| Load test | `loadtest/` |
| Web demo | `web/` |
| CI/CD | `.github/workflows/` |
| Sơ đồ rời | `docs/diagrams/` |

## 4. Ba mode LLM

```mermaid
flowchart LR
  E[LLM_PROVIDER] -->|none| N["Không cần key<br/>rule parser + 2 tầng cascade<br/>uncertain -> human review"]
  E -->|local| L["Không cần key<br/>Ollama Qwen3.5-2B/4B<br/>+ Qwen3-VL-4B"]
  E -->|gemini| G["Cần GEMINI_API_KEY<br/>Gemini 3.5 Flash-Lite<br/>+ Batch API"]
```

Key của bên thứ ba là **tuỳ chọn**; `X-API-Key` là key nội bộ cho auto test, luôn có.
