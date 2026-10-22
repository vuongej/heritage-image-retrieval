# Tài liệu

## Bộ tài liệu bàn giao (22/10/2026)

| Tài liệu | Nội dung |
|---|---|
| [Tài liệu kỹ thuật](technical-report.vi.md) | Kiến trúc hai pipeline, schema, pipeline xử lý data, cách retrieve từng loại query, lý do chọn, hạn chế |
| [Performance và benchmark](performance-benchmark.vi.md) | Chất lượng + latency + throughput + chi phí của cả hai pipeline, load test k6, cách đo |
| [Test case](test-cases.vi.md) | Phương pháp dựng 82 test case Phần B, bộ nhãn người Phần A, kết quả từng ca, test tự động |
| [Tối ưu Pipeline A](verify-router-benchmark.md) | Classifier, ngân sách VLM 5–20%, chọn cấu hình production |
| [Benchmark Phần A trên nhãn người](verify-human-benchmark.md) | Chẩn đoán tầng rẻ và VLM so với nhãn người |
| [Deploy & CI/CD](deploy.md) | Vercel + HF Space + GitHub Actions |
| [Schema](../db/schema.dbml) | DBML của SQLite và artifact Pipeline A |

Ưu tiên bộ tài liệu trên khi đọc hiện trạng. Các tài liệu bên dưới là thiết kế ban đầu và snapshot lịch sử (gồm bản rà soát 21/10); tham số, số liệu và tính năng có thể khác mã hiện tại.

## Tài liệu thiết kế và lịch sử

| File | Nội dung |
|---|---|
| `architecture.md` | Kiến trúc tổng thể + Mermaid + ánh xạ thư mục |
| `data-pipeline.md` | Cascade 3 tầng, cost model 10M/100M, throughput |
| `retrieval.md` | 3 loại query + set query + speculative parse + graph |
| `performance.md` | Ngân sách latency 1,5 s, cách đo, chỉ số chất lượng |
| `diagrams/*.mmd` | Sơ đồ Mermaid rời (render bằng mermaid-cli hoặc dán vào mermaid.live) |
