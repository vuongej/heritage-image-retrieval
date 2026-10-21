# syntax=docker/dockerfile:1.7
# Image backend production (VM Oracle ARM, chạy qua deploy/oracle/compose.yml). ~400 MB.
#
# Không có torch / BGE: server không có GPU; BGE-v2-m3 local mất ~26 s cho 24 ứng viên trên
# 2 vCPU (đo bằng container --cpus 2), còn jina-reranker-v2 qua endpoint ~150–300 ms.
FROM python:3.12-slim

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN useradd -m -u 1000 user
WORKDIR /home/user/app

# Layer phụ thuộc tách riêng: đổi code không phải cài lại package.
COPY deploy/requirements.txt requirements.txt
RUN pip install -r requirements.txt

USER user
# SQLite cần ghi WAL/journal cạnh catalog: thư mục dữ liệu phải thuộc user 1000.
RUN mkdir -p /home/user/data
# HOP_ONLINE_BUDGET_MS: 600 ms chờ LLM + 1,8 s tra KG online < 3 s; quá hạn trả pending_online_lookup.
# Mọi giá trị ở đây có thể ghi đè bằng .env của server.
ENV HOME=/home/user \
    LOCAL_DATA_DIR=/home/user/data \
    HF_HOME=/home/user/.cache/huggingface \
    VECTOR_BACKEND=numpy \
    RERANK_BACKEND=api \
    HOP_ONLINE_BUDGET_MS=1800 \
    PRELOAD_MODELS=true

COPY --chown=user api/ api/
COPY --chown=user retrieval/ retrieval/
COPY --chown=user storage/ storage/
COPY --chown=user pipeline/ pipeline/
COPY --chown=user config/ config/
COPY --chown=user deploy/__init__.py deploy/hf_data.py deploy/start.sh deploy/
COPY --chown=user reports/ reports/

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 --start-period=15m \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/v1/health').status == 200 else 1)"]
CMD ["sh", "deploy/start.sh"]
