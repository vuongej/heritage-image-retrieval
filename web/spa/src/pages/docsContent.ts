import type { VerifyReport } from '@/api/metricsAdapter';
import { fmtInt } from '@/lib/format';

// Diagrams are grounded in the code surveyed on 21/10/2026 (docs/backend-inventory.md).
// "As-Is" = what runs now; "To-Be" = proposals, drawn dashed.

export const AS_IS = `flowchart LR
  U([Trình duyệt]) --> W["React SPA (web/spa)<br/>proxy /api gắn X-API-Key"]
  W -->|"/api/v1/*"| A["FastAPI api.main:app<br/>:8000"]
  W -.->|"image_url gốc — tải trực tiếp,<br/>không qua proxy"| EXT[(Host ảnh bên ngoài)]
  A --> P["Rule parser entity-first<br/>retrieval/rule_parser.py"]
  P -.->|"chỉ khi parse chưa chắc<br/>timeout 600 ms"| L["LLM parse<br/>(OpenRouter)"]
  A --> E["Embedding API<br/>qwen3-embedding-4b · 2560d"]
  A --> Q[("Qdrant · img_text<br/>cosine, HNSW m=16")]
  A --> S[("SQLite catalog.sqlite3<br/>images · entities · FTS5 · kg_* · cache")]
  A --> R["Rerank bge-reranker-v2-m3<br/>GPU local"]
  A --> H["Hop resolver<br/>retrieval/hop.py"]
  H --> S
  A --> VF["/v1/verify/* · /thumbs"]
  VF --> D[("data/verify/*.jsonl<br/>thumbs")]
  A --> RP["/v1/stats · /v1/reports"]
  RP --> F[("reports/*.json")]`;

export const TO_BE = `flowchart LR
  U([Trình duyệt]) --> N["Nginx<br/>SPA + proxy /api, /media"]
  N --> A["FastAPI"]
  N -.-> M["Media proxy<br/>chỉ ảnh approved, allowlist host"]
  M -.-> OBJ[("Object storage<br/>thumbnail WebP")]
  A --> Q[("Qdrant img_text")]
  A -.-> QV[("Qdrant img_visual<br/>SigLIP2 — tìm theo pixel")]
  A --> S[("SQLite catalog")]
  A -.-> KG["Duyệt người cho cạnh KG<br/>(kg_edge.reviewed) + bộ gold multi-hop"]
  A -.-> AUTH["Admin API + phân quyền reviewer<br/>audit trail"]
  W1["Worker pipeline verify<br/>hàng đợi + nhiều GPU"] -.-> S
  W1 -.-> QV
  K6["k6 loadtest/loadtest.js"] -.-> N
  classDef todo stroke-dasharray: 5 5,fill:#F8FAFC,color:#334155;
  class M,OBJ,QV,KG,AUTH,W1,K6 todo;`;

export function processingDiagram(r?: VerifyReport): string {
  const n = (v: number | null | undefined) => (v === null || v === undefined ? 'N/A' : fmtInt(v));
  return `flowchart TD
  CSV["CSV nguồn<br/>${n(r?.gate.source_rows)} dòng"] --> G["S0 · Gate rule"]
  G -->|"${n(r?.gate.live_rows)} sống"| SP["S2b · Split theo nhóm thực thể"]
  G -->|"${n(r?.gate.rejected_rows)} loại"| RJ[/"Loại theo rule"/]
  SP --> PI["Pilot ${n(r?.pilot_groups)} nhóm · ${n(r?.pilot_rows)} dòng"]
  PI --> FE["S1 · Tải ảnh + khử trùng sha256"]
  FE -->|"${n(r?.fetch.ok)} ok"| EM["SigLIP2 embedding"]
  FE -->|"${n(r?.fetch.dead)} dead · ${n(r?.fetch.dup_sha256)} trùng"| X[/"Loại"/]
  EM --> BS["S3 · Nhãn bootstrap VLM (thầy)"]
  BS --> HD["S4 · Head logistic + Jev"]
  HD -->|"quyết định"| OUT[("CSV đã verify")]
  HD -->|"không chắc"| RT{"T4 · Router α = ${r?.router.alpha ?? 'N/A'}"}
  RT -.->|"${n(r?.router.chosen)} ảnh"| VLM["T5 · VLM batch ≤ 8 ảnh"]
  VLM -.-> OUT
  RT -->|"ngoài ngân sách: giữ quyết định tầng chính"| OUT`;
}

export const SEQ_SINGLE = `sequenceDiagram
  autonumber
  participant UI as SPA
  participant API as /v1/search
  participant C as Cache (SQLite)
  participant E as Embedding API
  participant Q as Qdrant img_text
  participant S as SQLite FTS5 + tên
  participant R as bge-reranker
  UI->>API: POST {query, top_k}
  API->>C: tra cache (khoá: index, pipeline, model)
  alt trúng cache
    C-->>API: response đã lưu
  else không có cache
    API->>API: rule parse entity-first (LLM chỉ khi chưa chắc)
    API->>E: embed truy vấn
    API->>Q: ANN top 200
    API->>S: BM25 + khớp tên thực thể
    API->>API: RRF (text 1 · lexical 1 · tên 3)
    API->>R: rerank pool ≥ 24
    API->>API: xếp tầng: thực thể trùng tên trước (khi parse chắc)
    API->>C: lưu cache nếu không suy giảm
  end
  API-->>UI: hits · timings_ms · total_ms · warnings`;

export const SEQ_MULTI = `sequenceDiagram
  autonumber
  participant UI as SPA
  participant API as /v1/search
  participant P as Rule parser
  participant Q as Qdrant + FTS5 + tên
  participant R as bge-reranker
  UI->>API: "hồ bơi và công viên nước ở Phú Quốc"
  API->>P: tách theo "và" / dấu phẩy ngoài tên thực thể
  Note over P: địa danh cuối là điều kiện chung,<br/>gộp vào MỌI sub-query:<br/>q0 "hồ bơi ở phú quốc"<br/>q1 "công viên nước ở phú quốc"
  par mỗi sub-query
    API->>Q: truy xuất riêng q0
  and
    API->>Q: truy xuất riêng q1
  end
  par rerank riêng
    API->>R: rerank q0 bằng text của q0
  and
    API->>R: rerank q1 bằng text của q1
  end
  API->>API: chỉ giữ ảnh có bằng chứng thuộc sub-query
  API->>API: allocate_fair — xen kẽ (OR theo nhóm, KHÔNG phải AND)
  API-->>UI: hits[].matched_subqueries · sub_queries[].coverage`;

export const SEQ_HOP = `sequenceDiagram
  autonumber
  participant UI as SPA
  participant API as /v1/search
  participant H as hop.resolve
  participant KG as SQLite kg_*
  participant ON as kg_online (Gemini + web search)
  UI->>API: "lăng của con trai vua Gia Long"
  API->>API: rule parser: [lăng] + [con trai] + [người] → multi_hop (LLM không được bỏ)
  API->>H: plan: PARENT_OF xuôi · nam → BURIED_AT · seed "gia long"
  H->>KG: kg_alias(seed, bỏ chức danh) → node
  alt seed không có trong KG
    H->>ON: tìm nguồn cho seed (ngân sách 2,5 s)
    alt không có nguồn kiểm chứng được
      H-->>API: seed_not_linked
    end
  end
  loop mỗi bước quan hệ
    H->>KG: kg_edge (verified=1 hoặc reviewed=1), lọc giới tính
    alt KG thiếu cạnh người–người
      H->>ON: web search exa → kiểm câu trích nguyên văn trong trang nguồn
      alt quá ngân sách
        H-->>API: pending_online_lookup (chạy nền, hỏi lại sau)
      else ghi cạnh source_type=online
        H->>KG: đọc lại cạnh vừa kiểm chứng
      end
    end
    alt vẫn không có cạnh
      H-->>API: no_evidence (≠ quan hệ không tồn tại)
    end
  end
  H->>KG: kg_link(node → entity_id)
  alt đích là người (catalog không có ảnh người)
    H-->>API: target_not_in_catalog + related_places
    API-->>UI: hits = [] · resolution.target_nodes
  else
    H-->>API: resolved · cạnh kèm câu trích + URL
    API-->>UI: ảnh các entity đích · resolution.steps
  end`;

export const ER = `erDiagram
  entities ||--o{ images : "entity_id"
  images ||--|| image_fts : "rownum = rowid"
  images ||--o| qdrant_img_text : "point id = rownum"
  kg_node ||--o{ kg_edge : "subject / object"
  kg_node ||--o{ kg_alias : "node_id"
  kg_node ||--o{ kg_link : "node_id"
  entities ||--o{ kg_link : "entity_id"
  entities {
    TEXT entity_id PK
    TEXT entity_name
    TEXT entity_slug
    TEXT parent_class
  }
  images {
    INTEGER rownum PK
    TEXT image_id UK "uuid5(url)"
    TEXT entity_id FK
    TEXT image_url
    TEXT description
    TEXT metadata_text
    TEXT verify "yes | no | NULL"
    INTEGER width
    INTEGER height
    INTEGER has_watermark
    TEXT fetch_status
  }
  image_fts {
    TEXT text "metadata bỏ dấu"
  }
  qdrant_img_text {
    VECTOR v "2560d cosine"
  }
  kg_node {
    TEXT node_id PK "person:slug | place:entity_id"
    TEXT kind "person | place"
    TEXT label
    TEXT gender
    TEXT created_by
  }
  kg_edge {
    TEXT subject PK
    TEXT predicate PK "PARENT_OF SPOUSE_OF BURIED_AT WORSHIPPED_AT MEMORIAL_AT"
    TEXT object PK
    TEXT source_url PK "URL | catalog:entity/id"
    TEXT source_type "catalog_name gemini_doc manual_claim online"
    TEXT evidence "câu trích nguyên văn"
    INTEGER verified
    INTEGER reviewed
    TEXT verifier
  }
  kg_alias {
    TEXT alias_norm PK
    TEXT node_id PK
  }
  kg_link {
    TEXT node_id PK
    TEXT entity_id PK
    TEXT method
  }
  kg_lookup {
    TEXT lookup_key PK
    TEXT status "found | no_evidence"
    TEXT detail
  }`;

export const MD_ASIS = `**Truy xuất đang chạy là truy xuất dựa trên metadata văn bản**: tên thực thể, nhóm (category) và mô tả trong CSV đã được người duyệt (\`flag=approved\`). Mỗi sub-query được hợp nhất bằng RRF từ ba nguồn đang bật:

1. **Vector văn bản** — \`qwen3-embedding-4b\` (2560 chiều) nhúng metadata, tìm ANN trên Qdrant \`img_text\`.
2. **FTS5/BM25** — văn bản bỏ dấu, lọc hư từ tiếng Việt (giữ "chợ", "đền", "cổ").
3. **Khớp tên thực thể** — trọng số 3, ảnh của thực thể trùng tên được đưa lên trước.

Nhánh **thị giác** (SigLIP2, collection \`img_visual\`) có trong code nhưng **chưa bật**: \`img_visual\` không tồn tại. Vì vậy UI không bao giờ ghi "tìm theo nội dung ảnh".

Rerank: \`BAAI/bge-reranker-v2-m3\` chạy local; lỗi sẽ rơi về độ tương đồng embedding rồi thứ tự RRF, ghi vào \`warnings\`. LLM parse chạy **song song**, chỉ khi rule parser chưa chắc, và bị cắt ở 600 ms để không nằm trên đường găng.`;

export const MD_PART_A = `Pipeline verify (\`python -m pipeline.verify\`) lọc ảnh sau crawl theo nhiều tầng, đi từ rẻ đến đắt:

- **S0 gate** chạy rule trên metadata cho **toàn bộ** CSV (không tải ảnh).
- Các stage tải ảnh, SigLIP2, head và Jev chạy trên **pilot** gồm các nhóm thực thể được lấy mẫu.
- **Router** chỉ chuyển một tỉ lệ α ảnh khó nhất sang VLM. Đây là **nhánh phụ**, không phải bước mọi ảnh đều đi qua.

Giới hạn hiện tại:

- Lần chạy trong báo cáo dùng lại cache nên **thông lượng và chi phí không đại diện**.
- Nhãn người duy nhất là cột \`flag\` (toàn approved), nên chỉ đo được **tỉ lệ loại nhầm**.
- Các chỉ số "agreement" là đồng thuận với VLM thầy, **không phải accuracy**.

Để lên 10–100 triệu ảnh cần: thông lượng duy trì đo không cache, chi phí/1.000 ảnh có phạm vi rõ, rồi ngoại suy theo nút cổ chai (tải ảnh, GPU encode, quota API VLM), có gắn nhãn ƯỚC LƯỢNG.`;

export const MD_METHOD = `**Latency** (\`scripts/eval_latency.py\`): gọi \`search()\` trong cùng process, đo bằng \`perf_counter\`.

- Cache kết quả bị tắt (\`warm_uncached\`); tải đầu vào giới hạn theo \`offered_rpm\`.
- Báo cáo p50/p95/p99/max và tỉ lệ \`< 3.000 ms\` (so sánh **nhỏ hơn hẳn**).
- Số đo **không gồm HTTP và mạng**. UI hiển thị riêng \`total_ms\` của backend, \`X-Response-Time\` và thời gian trình duyệt quan sát.

**Quy tắc SLA trên UI**: PASS chỉ khi n > 0 và 100% request < 3.000 ms. p95 đạt chưa đủ để kết luận PASS.

**Chất lượng** (\`scripts/eval_quality.py\`): nhãn **silver**, sinh tự động từ \`entity_id\`/category của catalog.

- Recall vì vậy là recall ước lượng trên tập liên quan tự sinh.
- Bộ test UI gồm 18 case trong \`evals/ui_testcases.json\` (tên chính xác, không dấu, mô tả, multi-intent, set, multi-hop, mơ hồ, tiếng Anh, vô nghĩa, cache, lỗi API).

**Đếm dữ liệu** (\`scripts/check_index_counts.py\`): đối chiếu CSV ↔ SQLite ↔ Qdrant theo ID; không bao giờ lấy số dòng CSV làm số ảnh index.`;

export const GAPS: Array<[string, string]> = [
  ['Dữ liệu ≥ 80.000', 'Đạt: SQLite = vectors.npy = Qdrant img_text = 130.428, không lệch ID (reports/v2/index_counts.json, 21/10/2026).'],
  ['SLA < 3 s', 'Trên index 130.428: concurrency 4 đạt 100% < 3.000 ms; concurrency 1 có 5/244 request vi phạm (max 3.669 ms). Nút cổ chai là embed_query qua endpoint embedding từ xa (p50 1.042 ms, trước đây 140 ms), không phải Qdrant (dense p50 36 ms).'],
  ['Phân loại truy vấn', 'LLM parse có thể trả intent_type "single" kèm 2 sub-query (vd. “hồ bơi và công viên nước ở Phú Quốc”); backend vẫn truy xuất theo 2 nhóm. UI nhóm theo bằng chứng và cảnh báo lệch nhãn.'],
  ['Ngưỡng liên quan', 'Ảnh chỉ được trả khi điểm gốc bge-reranker-v2-m3 ≥ 0,2 hoặc khớp đúng tên thực thể (scripts/calibrate_relevance.py: ảnh đúng silver thấp nhất 0,53; 57/57 truy vấn ngoài phạm vi về 0 ảnh). Còn lọt ca catalog thiếu thực thể phù hợp nhưng điểm cao: “công viên nước ở Phú Quốc” → Nhà tù Phú Quốc (0,52). Ngưỡng hiệu chỉnh trên nhãn silver, chưa có gold người.'],
  ['Multi-hop', 'KG 3 giai đoạn (seed thủ công → Gemini đọc tài liệu → tra cứu trực tuyến), 333 cạnh máy kiểm chứng (docs/multihop-kg.md). Chưa có người duyệt cạnh (reviewed) và chưa có bộ gold multi-hop; phạm vi 43 người / 200 nơi chốn; quan hệ anh/em, cháu, chức vụ chưa hỗ trợ.'],
  ['Tìm theo pixel', 'img_visual (SigLIP2) chưa có; truy xuất chỉ dựa trên metadata.'],
  ['Media', 'Không có media proxy: trình duyệt tải ảnh trực tiếp từ host gốc (có thể chặn hotlink/chết link).'],
  ['Phân quyền', 'Một API key dev chung, chưa có vai trò reviewer ⇒ thao tác duyệt trên UI bị tắt.'],
  ['Benchmark', 'Thiếu mẫu raw từng request, latency MULTI_HOP, k6 chưa chạy, không có git SHA.'],
  ['Phần A', 'Chưa có thông lượng/chi phí đo không cache, chưa có precision/recall theo lớp lỗi với nhãn người.'],
  ['Triển khai', 'docker-compose.yml vẫn là skeleton cũ (Postgres/MinIO/Next.js) — chưa khớp runtime local.'],
];
