"""S1b — frozen SigLIP2 image + text embeddings (skill_02).

DINOv3 (the doc's first choice) is a gated Hugging Face repo (HTTP 401 without an
accepted licence + token), so the default is SigLIP2, which is open, multilingual and
gives the cross-modal image<->name/description score in the same embedding space.
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

from pipeline.verify.common import run_dir

ENCODER = os.getenv("VERIFY_ENCODER", "google/siglip2-base-patch16-256")
TEXT_LEN = 64


def _load():
    import torch
    from transformers import AutoModel, AutoProcessor

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    cache = str(run_dir().parent / "local" / "models")
    model = AutoModel.from_pretrained(ENCODER, cache_dir=cache, dtype=dtype).to(device).eval()
    processor = AutoProcessor.from_pretrained(ENCODER, cache_dir=cache)
    return model, processor, device, dtype


def _pooled(out):
    """transformers>=5 returns a ModelOutput from get_*_features."""
    return out if hasattr(out, "shape") else out.pooler_output


def _normalize(x: np.ndarray) -> np.ndarray:
    return x / np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-12)


_loaded = None


def loaded():
    """Model dùng chung trong một tiến trình (Phần A encode, Phần B encode ảnh + câu truy vấn)."""
    global _loaded
    if _loaded is None:
        _loaded = _load()
    return _loaded


def embed_images(paths: list, batch: int = 64, log=print) -> np.ndarray:
    """L2-normalized float32 image embeddings, rows aligned with paths."""
    import torch

    model, processor, device, dtype = loaded()
    img_out = []

    def load(chunk):  # PIL decode + resize release the GIL: threads keep the GPU fed
        return processor(images=[Image.open(p).convert("RGB") for p in chunk], return_tensors="pt")[
            "pixel_values"
        ]

    chunks = [paths[i : i + batch] for i in range(0, len(paths), batch)]
    with torch.inference_mode(), ThreadPoolExecutor(int(os.getenv("VERIFY_LOADERS", "6"))) as pool:
        for n, px in enumerate(pool.map(load, chunks)):
            px = px.to(device, dtype)
            img_out.append(_pooled(model.get_image_features(pixel_values=px)).float().cpu().numpy())
            if n % 20 == 0:
                log(f"[encode] images {min((n + 1) * batch, len(paths))}/{len(paths)}")
    return _normalize(np.concatenate(img_out)) if img_out else np.zeros((0, 0), np.float32)


def embed_texts(texts: list[str]) -> np.ndarray:
    """L2-normalized float32 text-tower embeddings (cùng tiền xử lý với tên/mô tả ở Phần A)."""
    import torch

    if not texts:
        return np.zeros((0, 0), np.float32)
    model, processor, device, _ = loaded()
    out = []
    with torch.inference_mode():
        for i in range(0, len(texts), 256):
            tok = processor(
                text=[t.lower() for t in texts[i : i + 256]],
                padding="max_length",
                max_length=TEXT_LEN,
                truncation=True,
                return_tensors="pt",
            ).to(device)
            out.append(_pooled(model.get_text_features(**tok)).float().cpu().numpy())
    return _normalize(np.concatenate(out))


def embed(
    paths: list, texts_name: list[str], texts_desc: list[str], batch: int = 64, log=print
) -> dict:
    """Return float16 L2-normalized arrays: img, name, desc (rows aligned with paths)."""
    model, processor, device, dtype = loaded()
    started = time.perf_counter()
    img = embed_images(paths, batch, log)
    img_seconds = time.perf_counter() - started

    name = embed_texts(texts_name)
    desc = embed_texts(texts_desc)
    return {
        "img": img.astype(np.float16),
        "name": name.astype(np.float16),
        "desc": desc.astype(np.float16),
        "stats": {
            "encoder": ENCODER,
            "device": device,
            "images": len(paths),
            "dim": int(img.shape[1]),
            "image_seconds": round(img_seconds, 2),
            "images_per_second": round(len(paths) / max(img_seconds, 1e-9), 1),
            "total_seconds": round(time.perf_counter() - started, 2),
        },
    }
