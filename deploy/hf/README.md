---
title: Heritage Image Retrieval API
emoji: 🏛️
colorFrom: yellow
colorTo: red
sdk: docker
app_port: 7860
startup_duration_timeout: 1h
pinned: false
short_description: Backend FastAPI truy xuất ảnh di sản Việt Nam
---

# Heritage Image Retrieval — backend

Backend FastAPI của dự án (Phần B: truy xuất single / multi-intent / multi-hop trên 130.428 ảnh).
Repo này được GitHub Actions đồng bộ tự động; không sửa trực tiếp ở đây.

- Web demo: chạy trên Vercel, gọi API này qua proxy có gắn `X-API-Key`.
- Mọi endpoint `/v1/*` trừ `/v1/health` đều yêu cầu `X-API-Key`.
- Dữ liệu index nằm trong dataset private, được tải về khi Space khởi động.
