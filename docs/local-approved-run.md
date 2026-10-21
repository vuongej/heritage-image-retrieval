# Chạy toàn bộ dữ liệu approved trên máy local

Luồng này đọc schema `data/data_anh_pass_master.csv`, nhập các URL HTTP(S) đã
`approved` vào SQLite, xây graph thực thể → nhóm, tạo vector cho metadata của
từng ảnh, rồi tìm kiếm bằng DeepSeek. Không cần Docker, S3, Redis hay deploy.

Đây là tìm kiếm trên tên, nhóm và mô tả có sẵn. Vector không phải embedding
pixel/SigLIP. Không tải lại ảnh hoặc chạy lại kiểm duyệt vì dữ liệu đã approved.
Những URL nội bộ như `x-raw-image:///...` được ghi vào báo cáo quarantine.
CSV chỉ có quan hệ nhóm; câu hỏi cần quan hệ gia đình/tổ chức trả cảnh báo
thiếu dữ liệu thay vì tự suy đoán.

Thiết lập môi trường (PowerShell):

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -r requirements-local.txt
.\.venv\Scripts\python.exe -m scripts.prepare_local_model
```

Điền key trong `.env`; không đưa key vào source hoặc câu lệnh:

```dotenv
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_BASE_URL=https://api.deepseek.com
EMBED_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
EMBED_DIM=384
RERANK_TOP_K=24
RETRIEVAL_BACKEND=local
```

Chạy:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pipeline --csv data/data_anh_pass_master.csv --mode approved
.\.venv\Scripts\python.exe -X utf8 -m evals.harness --goldset reports/approved_run/entity_smoke.jsonl --out reports/approved_run/evaluation.json
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -X utf8 -m scripts.verify_local_api
.\.venv\Scripts\python.exe -X utf8 -m scripts.report_approved_run
```

Chỉ chạy dữ liệu của một (hoặc nhiều) `username`, kèm audit Phần A trên mẫu ảnh —
xem bản ghi chi tiết lần chạy thật ở [pipeline-run-pham_van_vuong.md](pipeline-run-pham_van_vuong.md):

```powershell
.\.venv-gpu\Scripts\python.exe -X utf8 -m pipeline --csv data/data_anh_pass_master.csv --mode approved `
  --username pham_van_vuong --audit-sample 200 --out reports/pham_van_vuong
```

Lần đầu tải model và tạo vector; tiến độ lưu mỗi batch trong
`data/local/index.json`. Chạy lại lệnh để tiếp tục sau gián đoạn; chỉ dùng lại
checkpoint khi SHA-256 của CSV, model và số chiều đều khớp.

Kết quả lưu ở `reports/approved_run/pipeline_report.json`,
`search_results.json` và `quarantine.json`. Số token gọi DeepSeek thực lưu tại
`data/local/deepseek_usage.jsonl`, không chứa key. Kết quả LLM và tìm kiếm được
cache ở SQLite. Lần gọi đầu phụ thuộc độ trễ API; bản local này chưa cam kết
SLO p95 1500 ms. Eval tạo từ nhãn thực thể của CSV chỉ là smoke test, chưa thay
thế goldset đánh giá thủ công độc lập.

Chạy API local:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Xem `http://127.0.0.1:8000/docs`. Các endpoint hoạt động trong chế độ này:
health, search, embed, rerank, entities, graph. Nạp CSV bằng CLI; endpoint nạp
job ảnh mới chưa hỗ trợ trong chế độ approved local. Endpoint backfill vẫn
thuộc skeleton, không được dùng làm số liệu của lần chạy này.
