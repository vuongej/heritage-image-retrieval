"""Chỉ mục tên thực thể cho parse entity-first (Phase 1.2).

- `match_entity_spans`: span tên đầy đủ / alias, longest-match-first, không chồng lấn.
- `contains_phrase`: cụm 2..6 token liên tiếp có xuất hiện trong tên thực thể nào không. Dùng để
  che marker nằm *bên trong* một tên mà truy vấn chỉ nhắc một phần ("Hòn Chồng Nha Trang" khi
  catalog chỉ có "Biệt thự cổ Bảo Đại Hòn Chồng (Nha Trang)").
- `suggest`: ứng viên tên thực thể (IDF theo token) gửi kèm cho LLM parse.

Không giới hạn span tên đầy đủ ở 6 token: 2.386/4.481 tên trong catalog dài hơn 6 token.
Chuẩn hoá hai phía bằng `storage.local.plain` (bỏ dấu, lowercase, đ -> d).
"""

from __future__ import annotations

import logging
import math
import re
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field

from storage.local import plain

log = logging.getLogger(__name__)

TOKEN = re.compile(r"\w+")
MAX_PHRASE = 6
MIN_NAME_CHARS = 4
_PAREN_TAIL = re.compile(r"\s*\([^()]*\)\s*$")
_SEGMENT = re.compile(r"\s+[–—/]\s+")


def tokenize(text: str) -> list[tuple[str, int, int]]:
    """[(token không dấu, vị trí đầu, vị trí cuối)] trên chuỗi gốc."""
    return [(plain(m.group()), m.start(), m.end()) for m in TOKEN.finditer(text)]


def aliases(name: str) -> set[str]:
    """Tên đầy đủ, tên bỏ ngoặc đơn cuối, và từng đoạn ngăn bởi ' – ' / ' — ' / ' / '."""
    out = {name}
    base = name
    while _PAREN_TAIL.search(base):
        base = _PAREN_TAIL.sub("", base)
    out.add(base)
    out.update(part for part in _SEGMENT.split(base) if len(TOKEN.findall(part)) >= 2)
    return {a.strip() for a in out if len(plain(a).strip()) >= MIN_NAME_CHARS}


@dataclass
class Span:
    start: int  # chỉ số token
    end: int  # không bao gồm
    char_start: int
    char_end: int
    entity_ids: list[str]
    matched_text: str


@dataclass
class EntityCatalog:
    names: dict[tuple[str, ...], set[str]] = field(default_factory=dict)
    phrases: set[tuple[str, ...]] = field(default_factory=set)
    display: dict[str, str] = field(default_factory=dict)
    postings: dict[str, list[str]] = field(default_factory=dict)
    idf: dict[str, float] = field(default_factory=dict)
    plain_names: list[tuple[str, str]] = field(default_factory=list)  # (entity_id, tên bỏ dấu)
    max_len: int = 0
    build_ms: float = 0.0

    @classmethod
    def build(cls, entities: list[tuple[str, str]]) -> EntityCatalog:
        started = time.perf_counter()
        names: dict[tuple[str, ...], set[str]] = defaultdict(set)
        phrases: set[tuple[str, ...]] = set()
        postings: dict[str, set[str]] = defaultdict(set)
        display = {}
        for entity_id, name in entities:
            if not name:
                continue
            display[entity_id] = name
            for alias in aliases(name):
                key = tuple(t for t, _, _ in tokenize(alias))
                if key:
                    names[key].add(entity_id)
            words = [t for t, _, _ in tokenize(name)]
            for word in set(words):
                postings[word].add(entity_id)
            for size in range(2, MAX_PHRASE + 1):
                phrases.update(tuple(words[i : i + size]) for i in range(len(words) - size + 1))
        total = max(1, len(display))
        catalog = cls(
            names=dict(names),
            phrases=phrases,
            display=display,
            postings={w: sorted(ids) for w, ids in postings.items()},
            idf={w: math.log(1 + total / len(ids)) for w, ids in postings.items()},
            plain_names=[(entity_id, plain(name)) for entity_id, name in display.items()],
            max_len=max((len(k) for k in names), default=0),
        )
        catalog.build_ms = (time.perf_counter() - started) * 1000
        log.info(
            "entity catalog: %d entities, %d name keys, %d phrases, build %.0f ms",
            len(display), len(names), len(phrases), catalog.build_ms,
        )  # fmt: skip
        return catalog

    def match_entity_spans(self, text: str) -> list[Span]:
        tokens = tokenize(text)
        words = [t for t, _, _ in tokens]
        found = []
        for i in range(len(words)):
            for j in range(min(len(words), i + self.max_len), i, -1):
                ids = self.names.get(tuple(words[i:j]))
                if ids:
                    found.append((i, j, ids))
                    break  # dài nhất tại vị trí i
        found.sort(key=lambda s: (-(s[1] - s[0]), s[0]))
        taken = [False] * len(words)
        spans = []
        for i, j, ids in found:
            if any(taken[i:j]):
                continue
            taken[i:j] = [True] * (j - i)
            start, end = tokens[i][1], tokens[j - 1][2]
            spans.append(Span(i, j, start, end, sorted(ids), text[start:end]))
        return sorted(spans, key=lambda s: s.start)

    def contains_phrase(self, words: tuple[str, ...]) -> bool:
        return words in self.phrases

    def suggest(self, query: str, k: int = 20) -> list[str]:
        scores: dict[str, float] = defaultdict(float)
        for word in {t for t, _, _ in tokenize(query)}:
            for entity_id in self.postings.get(word, ()):
                scores[entity_id] += self.idf[word]
        best = sorted(scores.items(), key=lambda kv: (-kv[1], self.display[kv[0]]))[:k]
        return [self.display[entity_id] for entity_id, _ in best]


EMPTY = EntityCatalog()
_lock = threading.Lock()
_loaded: dict[str, EntityCatalog] = {}


def for_index(csv_sha256: str | None) -> EntityCatalog:
    """Catalog của chỉ mục hiện tại; build 1 lần cho mỗi fingerprint CSV, giữ trong RAM."""
    if not csv_sha256:
        return EMPTY
    with _lock:
        if csv_sha256 not in _loaded:
            from storage.local import connect

            with connect() as conn:
                rows = conn.execute("SELECT entity_id, entity_name FROM entities").fetchall()
            _loaded.clear()
            _loaded[csv_sha256] = EntityCatalog.build([(r[0], r[1]) for r in rows])
        return _loaded[csv_sha256]
