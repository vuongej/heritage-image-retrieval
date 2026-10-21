"""Stage 1 — heuristics trên CPU. Chạy TRƯỚC khi tốn GPU.

Gate: độ phân giải, aspect ratio, độ nét (Laplacian variance), entropy,
dedup bằng pHash (Hamming <= 6), mật độ cạnh vùng 4 góc (nghi watermark).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageOps

# Lấy từ config/cascade.yaml
DEFAULTS = dict(
    min_width=600,
    min_height=400,
    aspect_ratio=(0.4, 3.0),
    blur_laplacian_var_min=60.0,
    entropy_min=3.0,
    phash_hamming_max=6,
    watermark_zone_edge_density_max=0.18,
)


@dataclass
class Stage1Result:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    width: int = 0
    height: int = 0
    phash64: int = 0
    metrics: dict = field(default_factory=dict)


ANALYSIS_MAX_SIDE = 1024
EDGE_MAGNITUDE_MIN = 200.0


def to_gray(img: Image.Image, max_side: int = ANALYSIS_MAX_SIDE) -> np.ndarray:
    """Grayscale float array, downscaled so gate values are comparable across sizes."""
    gray = ImageOps.exif_transpose(img).convert("L")
    gray.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return np.asarray(gray, dtype=np.float64)


def laplacian_variance(gray: np.ndarray) -> float:
    """Variance of the 4-neighbour Laplacian (same kernel as cv2.Laplacian ksize=1)."""
    if gray.shape[0] < 3 or gray.shape[1] < 3:
        return 0.0
    lap = gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:] - 4 * gray[1:-1, 1:-1]
    return float(lap.var())


def shannon_entropy(gray: np.ndarray) -> float:
    hist = np.bincount(np.clip(gray, 0, 255).astype(np.uint8).ravel(), minlength=256)
    p = hist[hist > 0] / hist.sum()
    return float(-(p * np.log2(p)).sum())


def _edge_map(gray: np.ndarray) -> np.ndarray:
    """Sobel + non-maximum suppression; a dependency-free stand-in for thin Canny edges."""
    g = np.pad(gray, 1, mode="edge")
    gx = (g[:-2, 2:] + 2 * g[1:-1, 2:] + g[2:, 2:]) - (g[:-2, :-2] + 2 * g[1:-1, :-2] + g[2:, :-2])
    gy = (g[2:, :-2] + 2 * g[2:, 1:-1] + g[2:, 2:]) - (g[:-2, :-2] + 2 * g[:-2, 1:-1] + g[:-2, 2:])
    mag = np.hypot(gx, gy)
    m = np.pad(mag, 1, mode="constant")
    horizontal = np.abs(gx) >= np.abs(gy)
    peak_x = (mag >= m[1:-1, :-2]) & (mag >= m[1:-1, 2:])
    peak_y = (mag >= m[:-2, 1:-1]) & (mag >= m[2:, 1:-1])
    return (mag >= EDGE_MAGNITUDE_MIN) & np.where(horizontal, peak_x, peak_y)


def corner_edge_density(gray: np.ndarray, ratio: float = 0.15) -> float:
    """Highest edge density among the 4 corner zones (where watermarks/logos sit)."""
    edges = _edge_map(gray)
    h, w = edges.shape
    ch, cw = max(1, int(h * ratio)), max(1, int(w * ratio))
    zones = [edges[:ch, :cw], edges[:ch, -cw:], edges[-ch:, :cw], edges[-ch:, -cw:]]
    return float(max(z.mean() for z in zones))


def phash64(img: Image.Image) -> int:
    import imagehash

    return int(str(imagehash.phash(img.convert("RGB"), hash_size=8)), 16)


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def run(
    img: Image.Image, cfg: dict | None = None, seen_hashes: set[int] | None = None
) -> Stage1Result:
    c = {**DEFAULTS, **(cfg or {})}
    reasons: list[str] = []
    w, h = img.size

    if w < c["min_width"]:
        reasons.append(f"width {w} < {c['min_width']}")
    if h < c["min_height"]:
        reasons.append(f"height {h} < {c['min_height']}")
    ar = w / h if h else 0
    if not (c["aspect_ratio"][0] <= ar <= c["aspect_ratio"][1]):
        reasons.append(f"aspect {ar:.2f} ngoài [{c['aspect_ratio'][0]}, {c['aspect_ratio'][1]}]")

    gray = to_gray(img)
    metrics = {
        "laplacian_var": laplacian_variance(gray),
        "entropy": shannon_entropy(gray),
        "corner_edge_density": corner_edge_density(gray),
    }
    if metrics["laplacian_var"] < c["blur_laplacian_var_min"]:
        reasons.append(
            f"blur laplacian_var {metrics['laplacian_var']:.1f} < {c['blur_laplacian_var_min']}"
        )
    if metrics["entropy"] < c["entropy_min"]:
        reasons.append(f"entropy {metrics['entropy']:.2f} < {c['entropy_min']}")
    if metrics["corner_edge_density"] > c["watermark_zone_edge_density_max"]:
        reasons.append(
            f"watermark_zone edge_density {metrics['corner_edge_density']:.3f} > "
            f"{c['watermark_zone_edge_density_max']}"
        )
    ph = phash64(img)
    if seen_hashes is not None:
        near = min((hamming(ph, other) for other in seen_hashes), default=64)
        if near <= c["phash_hamming_max"]:
            reasons.append(f"near_duplicate phash hamming {near} <= {c['phash_hamming_max']}")
        seen_hashes.add(ph)

    return Stage1Result(
        passed=not reasons, reasons=reasons, width=w, height=h, phash64=ph, metrics=metrics
    )


def expected_reject_share() -> float:
    """Từ dữ liệu thật: 318/3226 ảnh < 600px => tối thiểu ~9,9% bị loại ở gate độ phân giải."""
    return 318 / 3226
