# syntax=docker/dockerfile:1.7
# Processing service — Pipeline A (upload CSV -> rule -> SigLIP2 -> LightGBM -> router -> VLM).
# Image riêng với API truy xuất (deploy/backend.Dockerfile, không torch): hai pipeline độc lập.
# torch bản CPU; có GPU thì chạy service ngoài Docker bằng .venv có CUDA (README §4).

############################  builder: venv đầy đủ  ############################
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.6.0
COPY deploy/processor.requirements.txt requirements.txt
RUN pip install -r requirements.txt

############################  runtime  ############################
FROM python:3.12-slim
# libgomp: OpenMP cho LightGBM.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* && useradd -m -u 1000 user
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/user \
    PROCESS_DIR=/home/user/work/process \
    LOCAL_DATA_DIR=/home/user/work/state \
    HF_HOME=/home/user/work/hf \
    PRELOAD_MODELS=true
WORKDIR /home/user/app
USER user
# Ảnh tải về, embedding, job và model SigLIP2 (cache tại work/local/models) nằm trong một volume.
RUN mkdir -p /home/user/work/process /home/user/work/state /home/user/work/local/models

COPY --chown=user processing/ processing/
COPY --chown=user pipeline/ pipeline/
COPY --chown=user storage/ storage/
COPY --chown=user retrieval/ retrieval/
COPY --chown=user api/__init__.py api/security.py api/
COPY --chown=user models/verify/ models/verify/

EXPOSE 8100
HEALTHCHECK --interval=15s --timeout=5s --retries=5 --start-period=60s \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8100/v1/process/health').status == 200 else 1)"]
CMD ["uvicorn", "processing.main:app", "--host", "0.0.0.0", "--port", "8100"]
