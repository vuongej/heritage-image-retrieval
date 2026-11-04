"""Multilingual metadata vectors. Image inputs use DeepSeek captions, not SigLIP.

Backend (`EMBED_BACKEND`):
- `torch` / `onnx_int8` — MiniLM chạy local (384d);
- `api` — endpoint tương thích OpenAI `/v1/embeddings` (EMBED_API_BASE, EMBED_API_KEY), hiện là
  `qwen3-embedding-4b` (2560d, qua OpenRouter; tên phía API đặt bằng EMBED_API_MODEL). Model instruction-aware: câu truy vấn có tiền tố
  `Instruct: ... / Query: ...` (2 dòng), metadata ảnh (document) gửi nguyên văn.
"""

from __future__ import annotations

import base64
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from functools import lru_cache

from storage import runtime

runtime.load_env()

EMBED_DIM = int(os.getenv("EMBED_DIM", "384"))
EMBED_MODEL = os.getenv(
    "EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
EMBED_BACKEND = os.getenv("EMBED_BACKEND", "torch")
# Tên model gửi lên endpoint, khi nhà cung cấp đặt tên khác (OpenRouter: `qwen/qwen3-embedding-4b`).
# EMBED_MODEL vẫn là định danh của index: cùng model ở nhà cung cấp khác không phải dựng lại index.
EMBED_API_MODEL = os.getenv("EMBED_API_MODEL") or EMBED_MODEL
# Độ dài input tối đa đưa vào manifest index: đổi -> index cũ không được dùng lại.
EMBED_MAX_SEQ = 128 if EMBED_BACKEND != "api" else int(os.getenv("EMBED_API_MAX_TOKENS", "8192"))
QUERY_INSTRUCTION = os.getenv(
    "EMBED_QUERY_INSTRUCTION",
    "Given a Vietnamese search query for travel and cultural heritage photos, "
    "retrieve the image descriptions that match the query",
)


class OnnxMetadataEncoder:
    """Published AVX2 int8 model with its original tokenizer and mean pooling."""

    def __init__(self, snapshot):
        import onnxruntime as ort
        from transformers import AutoTokenizer

        options = ort.SessionOptions()
        options.intra_op_num_threads = int(os.getenv("EMBED_THREADS", "4"))
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(snapshot / "onnx/model_quint8_avx2.onnx"),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self.tokenizer = AutoTokenizer.from_pretrained(str(snapshot), local_files_only=True)

    def encode(self, texts, batch_size=64, **kwargs):
        import numpy as np

        batches = []
        inputs = {item.name for item in self.session.get_inputs()}
        for start in range(0, len(texts), batch_size):
            tokens = self.tokenizer(
                texts[start : start + batch_size],
                padding=True,
                truncation=True,
                max_length=128,
                return_tensors="np",
            )
            if "token_type_ids" in inputs and "token_type_ids" not in tokens:
                tokens["token_type_ids"] = np.zeros_like(tokens["input_ids"])
            hidden = self.session.run(
                None, {k: v.astype("int64") for k, v in tokens.items() if k in inputs}
            )[0]
            mask = tokens["attention_mask"][:, :, None].astype("float32")
            pooled = (hidden * mask).sum(axis=1) / np.maximum(mask.sum(axis=1), 1)
            pooled /= np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)
            batches.append(pooled)
        return np.concatenate(batches)


@dataclass
class EmbedResponse:
    model: str
    dim: int
    vectors: list[list[float]]
    latency_ms: int


@lru_cache(maxsize=1)
def load_model(onnx_path: str | None = None):
    import torch
    from sentence_transformers import SentenceTransformer

    torch.set_num_threads(int(os.getenv("EMBED_THREADS", "4")))
    cache = runtime.data_dir() / "models"
    repo = cache / ("models--" + EMBED_MODEL.replace("/", "--"))
    ref = repo / "refs" / "main"
    snapshot = repo / "snapshots" / ref.read_text().strip() if ref.exists() else None
    offline_ready = snapshot is not None and all(
        (snapshot / f).exists()
        for f in ("model.safetensors", "tokenizer.json", "modules.json", "1_Pooling/config.json")
    )
    if EMBED_BACKEND == "onnx_int8":
        if not offline_ready or not (snapshot / "onnx/model_quint8_avx2.onnx").exists():
            raise RuntimeError("ONNX model not cached; run scripts.prepare_local_model first")
        return OnnxMetadataEncoder(snapshot)
    model = SentenceTransformer(
        str(snapshot) if offline_ready else EMBED_MODEL,
        cache_folder=str(cache),
        device="cuda" if torch.cuda.is_available() else "cpu",
        local_files_only=offline_ready,
    )
    model.max_seq_length = 128
    if model.get_embedding_dimension() != EMBED_DIM:
        raise ValueError("EMBED_DIM does not match the configured model")
    return model


class EmbeddingUnavailable(RuntimeError):
    """Endpoint embedding không trả lời / trả sai. Search suy giảm (bỏ nhánh dense), không 503."""


_api_lock = threading.Lock()
_api_client = None
_api_pool = ThreadPoolExecutor(
    max_workers=int(os.getenv("EMBED_API_WORKERS", "4")), thread_name_prefix="embed-api"
)


def _http():
    global _api_client
    import httpx

    with _api_lock:
        if _api_client is None:
            _api_client = httpx.Client(
                timeout=httpx.Timeout(float(os.getenv("EMBED_API_TIMEOUT_S", "60")), connect=5)
            )
        return _api_client


def _api_batch(texts: list[str]) -> list[list[float]]:
    import httpx

    base = os.getenv("EMBED_API_BASE", "").rstrip("/")
    key = os.getenv("EMBED_API_KEY", "").strip()
    if not base or not key:
        raise EmbeddingUnavailable("EMBED_API_BASE / EMBED_API_KEY chưa cấu hình")
    last = "unknown"
    for attempt in range(3):
        try:
            from retrieval import ratelimit

            ratelimit.acquire()  # dùng chung hạn mức 100 request/phút/key với rerank
            response = _http().post(
                base + "/embeddings",
                json={"model": EMBED_API_MODEL, "input": texts},
                headers={"Authorization": "Bearer " + key},
            )
        except httpx.HTTPError as exc:
            last = type(exc).__name__
        else:
            if response.status_code in {401, 403}:
                raise EmbeddingUnavailable(
                    f"embedding HTTP {response.status_code}: key không hợp lệ"
                )
            if response.is_success:
                data = sorted(response.json()["data"], key=lambda d: d["index"])
                vectors = [d["embedding"] for d in data]
                if len(vectors) != len(texts) or any(len(v) != EMBED_DIM for v in vectors):
                    raise EmbeddingUnavailable(
                        f"embedding trả {len(vectors)} vector, cần {len(texts)} x {EMBED_DIM}d"
                    )
                return vectors
            last = f"HTTP {response.status_code}"
            if response.status_code < 500 and response.status_code != 429:
                break  # lỗi phía request: thử lại vô ích
            if response.status_code == 429:  # endpoint giới hạn tốc độ: chờ theo Retry-After
                time.sleep(min(float(response.headers.get("retry-after") or 2**attempt), 5))
                continue
        time.sleep(0.5 * 2**attempt)
    raise EmbeddingUnavailable(f"embedding endpoint lỗi sau 3 lần ({last})")


def _api_embed(texts: list[str]) -> list[list[float]]:
    import numpy as np

    size = int(os.getenv("EMBED_API_BATCH", "128"))
    chunks = [texts[i : i + size] for i in range(0, len(texts), size)]
    if len(chunks) == 1:
        vectors = _api_batch(chunks[0])
    else:
        vectors = [v for part in _api_pool.map(_api_batch, chunks) for v in part]
    matrix = np.asarray(vectors, dtype="float32")
    matrix /= np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)
    return matrix.tolist()


def embed_text(texts: list[str]) -> list[list[float]]:
    """Vector của DOCUMENT (metadata ảnh, caption)."""
    if not texts:
        return []
    if EMBED_BACKEND == "api":
        return _api_embed(texts)
    return (
        load_model()
        .encode(
            texts,
            batch_size=int(os.getenv("EMBED_BATCH_SIZE", "64")),
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        .tolist()
    )


_query_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="embed-query")


def embed_query(texts: list[str]) -> list[list[float]]:
    """Vector của CÂU TRUY VẤN. Model instruction-aware thêm tiền tố nhiệm vụ; MiniLM thì không.

    Endpoint embedding có hạn chờ EMBED_QUERY_DEADLINE_S (mặc định 2 s; đã đo một lần 5,9 s), trong
    hạn chờ tổng của request (retrieval/budget.py): quá hạn -> EmbeddingUnavailable, local_search bỏ nhánh dense và vẫn trả kết quả FTS + khớp tên.
    Timeout 60 s của _http() chỉ còn áp cho dựng index (embed_text theo lô lớn).
    """
    if EMBED_BACKEND == "api" and QUERY_INSTRUCTION:
        texts = [f"Instruct: {QUERY_INSTRUCTION}\nQuery: {t}" for t in texts]
    if EMBED_BACKEND != "api" or not texts:
        return embed_text(texts)
    from retrieval import budget, ratelimit

    # Phần còn lại của hạn chờ request, chừa ~0,6 s cho retrieve + rerank phía sau.
    deadline = budget.remaining(float(os.getenv("EMBED_QUERY_DEADLINE_S", "2.0")), reserve=0.6)
    if deadline < 0.2:
        raise EmbeddingUnavailable("hết thời gian của request trước khi embedding truy vấn")

    def run():
        with ratelimit.deadline(deadline):  # hết hạn mức -> không xếp hàng chờ
            return embed_text(texts)

    future = _query_pool.submit(run)
    try:
        return future.result(timeout=deadline)
    except FutureTimeout:
        raise EmbeddingUnavailable(f"embedding truy vấn quá hạn {deadline:g} s") from None
    except ratelimit.QuotaExhausted as exc:
        raise EmbeddingUnavailable(str(exc)) from None


def embed_text_visual(texts: list[str]) -> list[list[float]]:
    """Câu truy vấn trong không gian ảnh SigLIP2 (text tower của encoder Phần A, 768d)."""
    if not texts:
        return []
    from pipeline.verify.encoder import embed_texts

    return embed_texts(texts).tolist()


def embed_images(images: list[bytes | str]) -> list[list[float]]:
    """Caption with DeepSeek vision, then embed the caption in the metadata space.

    URLs are fetched locally and sent as base64: DeepSeek's own downloader is refused
    by many image hosts.
    """
    from pipeline.stage3_vlm import downscale
    from retrieval.deepseek import json_chat
    from storage.images import fetch_image

    captions = []
    for image in images:
        data = fetch_image(image) if isinstance(image, str) else image
        url = "data:image/jpeg;base64," + base64.b64encode(downscale(data)).decode()
        result = json_chat(
            'Describe the image in Vietnamese. Return JSON {"caption":"..."}.',
            [
                {
                    "type": "text",
                    "text": "Mô tả chủ thể và đặc điểm nhìn thấy. Không đoán địa danh.",
                },
                {"type": "image_url", "image_url": {"url": url, "detail": "low"}},
            ],
            max_tokens=512,
        )
        caption = result.get("caption")
        if not isinstance(caption, str) or not caption.strip():
            raise ValueError("Missing image caption from DeepSeek")
        captions.append(caption)
    return embed_text(captions)
