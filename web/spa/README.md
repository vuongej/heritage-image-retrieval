# Kho Ảnh Thông Minh — web UI (Vite + React 18)

UI cho Capstone, theo `docs/UI_Capstone_v2/SKILL.md`, gồm 4 route:

- `/`: tìm kiếm ảnh (SINGLE, MULTI_INTENT, MULTI_HOP, SET_QUERY)
- `/moderation`: Phần A
- `/benchmark`: bằng chứng đo lường
- `/docs`: kiến trúc và phương pháp

Dữ liệu thật lấy từ FastAPI (`api.main:app`). Hợp đồng dữ liệu nằm ở `docs/backend-inventory.md`.

## Chạy local

```powershell
# 1. Backend (từ thư mục gốc repo)
.\.venv-gpu\Scripts\python.exe -X utf8 -m uvicorn api.main:app --host 127.0.0.1 --port 8000

# 2. Web
cd web\spa
npm ci
npm run dev        # http://localhost:5173 (hot reload)
# hoặc bản production:
npm run build; npm run preview   # http://localhost:4173
```

Dev server và preview proxy `/api/*` → `BACKEND_URL` (mặc định `http://127.0.0.1:8000`). Proxy tự gắn header `X-API-Key` từ `TEST_API_KEY` trong `.env` ở thư mục gốc. Key này đọc **không có** tiền tố `VITE_` nên không bao giờ nằm trong bundle trình duyệt.

## Chế độ dữ liệu

| `VITE_DATA_MODE` | Ý nghĩa |
|---|---|
| `live` (mặc định) | Gọi backend thật. Lỗi API hiển thị là lỗi, **không** fallback sang mock. |
| `mock` | Chỉ dùng để dựng giao diện. Mọi trang có băng rôn "DỮ LIỆU MINH HỌA"; trang Kiểm duyệt và Benchmark không hiển thị số. |

## Kiểm tra

```powershell
npm run typecheck   # tsc
npm test            # vitest: adapter, SLA, contract trên payload thật (src/api/__samples__)
npm run build
```

## Cấu trúc

```text
src/api/         backendClient (timeout, phân loại lỗi), validators (zod), searchAdapter, metricsAdapter
src/types/       type chuẩn hoá cho UI (SKILL.md §4.1)
src/components/  shared · search · grid · trace · moderation · benchmark · docs
src/pages/       Search, Moderation, Benchmark, Docs (+ docsContent: sơ đồ Mermaid)
src/mocks/       fixture chỉ dùng cho DATA_MODE=mock
```

## Chưa làm (P8/P9)

- Dockerfile cho Nginx và cập nhật `docker-compose.yml`. Compose hiện tại vẫn là skeleton Next.js/Postgres cũ.
- Playwright, Lighthouse.
- Media proxy chỉ phục vụ ảnh approved.
- Phân quyền reviewer.
