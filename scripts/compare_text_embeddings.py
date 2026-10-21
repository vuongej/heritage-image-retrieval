"""So sánh nhánh dense text: MiniLM (backup) vs qwen3-embedding-4b (index hiện tại).

Chỉ so top-10 của riêng nhánh dense (không FTS, không khớp tên, không rerank), để thấy model
embedding thay đổi gì. Kết quả là danh sách thực thể để người đọc tự đánh giá — chưa có goldset.

python -X utf8 -m scripts.compare_text_embeddings
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np

from storage.local import connect
from storage.runtime import data_dir

ROOT = Path(__file__).resolve().parents[1]
QUERIES = [
    "chùa cổ mái ngói rêu phong",
    "bãi biển cát trắng nước trong xanh",
    "món ăn đường phố Hà Nội",
    "lễ hội đua thuyền trên sông",
    "nhà thờ kiến trúc Gothic",
    "ruộng bậc thang mùa lúa chín",
    "đặc sản làm quà từ miền Tây",
    "di tích chiến tranh",
    "thủ đô Việt Nam",
    "nơi thờ vua Hùng",
]


def top(vectors, query_vec, k=10):
    scores = np.asarray(vectors) @ np.asarray(query_vec, dtype=np.float32)
    idx = np.argpartition(-scores, k)[:k]
    return [int(i) + 1 for i in idx[np.argsort(-scores[idx])]]


def describe(rownums, conn):
    rows = {
        r[0]: r[1]
        for r in conn.execute(
            f"SELECT i.rownum, e.entity_name FROM images i JOIN entities e USING(entity_id)"
            f" WHERE i.rownum IN ({','.join('?' * len(rownums))})",
            rownums,
        )
    }
    names = [rows[r] for r in rownums]
    return list(dict.fromkeys(names))  # thực thể khác nhau, giữ thứ tự


def main() -> None:
    from retrieval import embed as qwen

    new_vectors = np.load(data_dir() / "vectors.npy", mmap_mode="r")
    old_vectors = np.load(data_dir() / "backup_minilm_80k" / "vectors.npy", mmap_mode="r")
    os.environ["EMBED_BACKEND"] = "torch"
    from sentence_transformers import SentenceTransformer

    minilm = SentenceTransformer(
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        cache_folder=str(data_dir() / "models"),
    )
    old_q = minilm.encode(QUERIES, normalize_embeddings=True)
    new_q = qwen.embed_query(QUERIES)
    report = []
    with connect() as conn:
        for q, oq, nq in zip(QUERIES, old_q, new_q, strict=True):
            item = {
                "query": q,
                "minilm": describe(top(old_vectors, oq), conn),
                "qwen3": describe(top(new_vectors, nq), conn),
            }
            report.append(item)
            print(f"\n## {q}\n  MiniLM: {item['minilm'][:5]}\n  Qwen3 : {item['qwen3'][:5]}")
    out = ROOT / "reports" / "phase2" / "compare_text_embeddings.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
