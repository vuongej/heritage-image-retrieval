# Tài liệu

## Bộ tài liệu rà soát ngày 21/10/2026

- [Tài liệu kỹ thuật](technical-report.vi.md): kiến trúc thực tế, pipeline dữ liệu, bốn loại query, lựa chọn giải pháp và hạn chế.
- [Báo cáo performance và benchmark](performance-benchmark.vi.md): metric từ JSON nguồn, các lượt đạt/chưa đạt SLO, A/B reranker, verify và khoảng trống kiểm chứng.
- [Test case và hướng dẫn tái lập](test-cases.vi.md): ma trận chức năng, kiểm tra đã chạy, quy trình benchmark và nghiệm thu.
- [244 ca benchmark dạng CSV](../reports/project_review/benchmark-cases.csv), [evidence có hash nguồn](../reports/project_review/evidence.json).

Ưu tiên bộ tài liệu trên khi đọc hiện trạng. Các tài liệu bên dưới gồm thiết kế ban đầu và các snapshot lịch sử; tham số, số lượng dữ liệu và tính năng có thể khác mã hiện tại.

## Tài liệu thiết kế và lịch sử

| File | Nội dung |
|---|---|
| `architecture.md` | Kiến trúc tổng thể + Mermaid + ánh xạ thư mục |
| `data-pipeline.md` | Cascade 3 tầng, cost model 10M/100M, throughput |
| `retrieval.md` | 3 loại query + set query + speculative parse + graph |
| `performance.md` | Ngân sách latency 1,5 s, cách đo, chỉ số chất lượng |
| `diagrams/*.mmd` | Sơ đồ Mermaid rời (render bằng mermaid-cli hoặc dán vào mermaid.live) |
