"""Stage 2 — classifier nhỏ trên GPU/ONNX.

Multi-head trên SigLIP2-B/16 fine-tuned:
    relevance(entity), watermark, nsfw, violence, politics
Xuất xác suất để routing quyết định (accept / reject / uncertain).
"""

from __future__ import annotations

from dataclasses import dataclass

HEADS = ["relevance", "watermark", "nsfw", "violence", "politics"]


@dataclass
class Stage2Result:
    probs: dict[str, float]
    decision: str  # accept | reject | uncertain
    model_version: str


def load_session(onnx_path: str):
    """TODO(impl): onnxruntime.InferenceSession(providers=['CUDAExecutionProvider','CPUExecutionProvider'])"""
    raise NotImplementedError


def preprocess(img, size: int = 384):
    """TODO(impl): resize + normalize theo config của SigLIP2"""
    raise NotImplementedError


def predict_batch(session, batch, batch_size: int = 128) -> list[dict[str, float]]:
    """TODO(impl): chạy fp16, batch 128. Kỳ vọng ~1500 ảnh/s trên 1x L4."""
    raise NotImplementedError


def route(probs: dict[str, float], accept_p: float = 0.70, reject_p: float = 0.35) -> str:
    """Dải bất định là hạt nhân tiết kiệm chi phí: chỉ ~8% ảnh rơi vào đây."""
    rel = probs.get("relevance", 0.0)
    unsafe = max(
        probs.get("watermark", 0),
        probs.get("nsfw", 0),
        probs.get("violence", 0),
        probs.get("politics", 0),
    )
    if unsafe >= 0.5 or rel <= reject_p:
        return "reject"
    if rel >= accept_p:
        return "accept"
    return "uncertain"


def calibrate(probs: list[float], labels: list[int]) -> dict:
    """TODO(impl): Platt scaling / isotonic; trả ECE + curve để báo cáo."""
    raise NotImplementedError
