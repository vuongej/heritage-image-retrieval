# syntax=docker/dockerfile:1.7
# Image backend cho Hugging Face Space (cpu-basic: 2 vCPU / 16 GB RAM).
# `python -m deploy.hf_deploy push-space` đặt file này thành Dockerfile ở gốc repo Space.
FROM python:3.12-slim

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN useradd -m -u 1000 user
WORKDIR /home/user/app

# Layer phụ thuộc tách riêng: đổi code không phải cài lại torch.
COPY deploy/hf/requirements.txt requirements.txt
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

USER user
ENV HOME=/home/user \
    LOCAL_DATA_DIR=/home/user/data \
    HF_HOME=/home/user/.cache/huggingface \
    VECTOR_BACKEND=numpy \
    PRELOAD_MODELS=true

# Nạp sẵn BGE reranker vào image: Space thức dậy sau khi ngủ không phải tải lại ~2,3 GB.
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-reranker-v2-m3', cache_dir='/home/user/data/models', allow_patterns=['*.json', '*.safetensors', '*.model', '*.txt'])"

COPY --chown=user . .

EXPOSE 7860
CMD ["sh", "deploy/hf/start.sh"]
