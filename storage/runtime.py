"""Local configuration; environment values and API keys are never logged."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> None:
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_env()


def source_csv() -> str:
    """Bộ dữ liệu nguồn DUY NHẤT cho mọi luồng (Phần A verify, Phần B import/index, đo lường).

    Mặc định `data_anh_pass_master.csv`: 130.429 ảnh đã được người dùng verify tay 100%.
    """
    return os.getenv("SOURCE_CSV", "data/data_anh_pass_master.csv")


def data_dir() -> Path:
    path = Path(os.getenv("LOCAL_DATA_DIR", str(ROOT / "data" / "local")))
    path.mkdir(parents=True, exist_ok=True)
    return path
