"""Query parser rule-based — LUÔN chạy, không cần LLM, không cần key.

Entity-first (Phase 1.1): tìm tên thực thể trong truy vấn TRƯỚC, che các span đó, rồi mới xét
marker quan hệ / nhiều ý định / tập hợp trên phần còn lại. Nhờ vậy "Lăng Chủ tịch Hồ Chí Minh",
"Tượng đài Mẹ Việt Nam Anh hùng", "Chùa Diên Phúc (Đông Anh, Hà Nội)" không bị xếp multi_hop.

LLM (nếu có) chạy song song và chỉ override khi kết quả khác -> xem retrieval/speculative.py.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field

from retrieval.catalog import EMPTY, MAX_PHRASE, EntityCatalog, tokenize
from retrieval.places import is_place, trailing_place

MULTI_MARKERS = (" và ", " với ", " cùng ", ",", " & ")
HOP_MARKERS = ("con trai", "con gái", "vợ", "chồng", "chủ tịch", "giám đốc",
               "cha", "mẹ", "anh", "em", "sáng lập")  # fmt: skip
SET_MARKERS = ("những", "các", "tất cả", "danh sách", "loại", "họ", "mọi")


def _words_re(words) -> re.Pattern:
    alternation = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alternation})(?!\w)")


HOP_RE = _words_re(HOP_MARKERS)
SET_RE = _words_re(SET_MARKERS)
MULTI_RE = re.compile(r"\s*,\s*|\s+(?:và|với|cùng|&)\s+")


@dataclass
class ParsedQuery:
    raw: str
    normalized: str
    intent_type: str  # single | multi_intent | multi_hop | set_query
    sub_queries: list[dict] = field(default_factory=list)
    hop_chain: list[str] = field(default_factory=list)
    filters: dict = field(default_factory=dict)
    needs_graph: bool = False
    parser: str = "rule"
    entities: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFC", text.strip().lower())
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"^(ảnh|hình|hình ảnh|photo|picture)\s+(của|của |về)?\s*", "", t)
    return t.strip(" ?.!")


def _strip_prefix(text: str) -> str:
    return re.sub(r"^(cho tôi|cho mình|tìm|hiển thị|xem)\s+", "", text).strip()


class _Mask:
    """Phần nào của truy vấn thuộc về tên thực thể (marker ở đó không được tính)."""

    def __init__(self, text: str, catalog: EntityCatalog):
        self.tokens = tokenize(text)
        self.words = tuple(t for t, _, _ in self.tokens)
        self.spans = catalog.match_entity_spans(text)
        self.catalog = catalog
        self.in_entity = [False] * len(self.tokens)
        for span in self.spans:
            self.in_entity[span.start : span.end] = [True] * (span.end - span.start)

    def protected(self, start: int, end: int, both_sides: bool = False) -> bool:
        idx = [i for i, (_, a, b) in enumerate(self.tokens) if a < end and b > start]
        if not idx:  # dấu phẩy: chỉ được che khi nằm trong một tên đầy đủ
            return any(s.char_start <= start and end <= s.char_end for s in self.spans)
        if all(self.in_entity[i] for i in idx):
            return True
        lo, hi = idx[0], idx[-1] + 1
        # Cụm liên tiếp chứa marker + ít nhất 1 token khác, có trong tên thực thể nào đó.
        # Từ nối ("và", "với") cần ngữ cảnh cả hai phía: "mộ và đền thờ", không phải "an và".
        for size in range(hi - lo + 1, MAX_PHRASE + 1):
            for a in range(max(0, hi - size), min(lo, len(self.words) - size) + 1):
                if both_sides and (a == lo or a + size == hi):
                    continue
                if self.catalog.contains_phrase(self.words[a : a + size]):
                    return True
        return False

    def free(self, pattern: re.Pattern, text: str, both_sides: bool = False) -> list[re.Match]:
        return [
            m for m in pattern.finditer(text) if not self.protected(m.start(), m.end(), both_sides)
        ]


def _split_intents(text: str, cuts: list[re.Match], mask: _Mask | None = None) -> list[str]:
    parts, last = [], 0
    for m in cuts:
        parts.append(text[last : m.start()])
        last = m.end()
    parts.append(text[last:])
    merged: list[str] = []
    for part in (p.strip(" ,") for p in parts):
        if not part:
            continue
        # "chùa một cột, hà nội": địa danh sau dấu phẩy là modifier, không phải ý định mới.
        if merged and is_place(part) and not is_place(merged[-1]):
            merged[-1] = f"{merged[-1]} {part}"
        else:
            merged.append(part)
    place = trailing_place(merged[-1]) if len(merged) > 1 else None
    if place and mask is not None:
        # Địa danh nằm TRONG tên thực thể ("Lăng Chủ tịch Hồ Chí Minh") không phải modifier chung.
        end = len(text.rstrip(" ,"))
        if mask.protected(end - len(place), end):
            place = None
    if place:
        # "hồ bơi và công viên nước ở phú quốc": phú quốc là modifier của mọi sub-query.
        merged = [p if trailing_place(p) or is_place(p) else f"{p} {place}" for p in merged]
    return merged


def _hop_structure(n: str, mask: _Mask) -> bool:
    from retrieval.hop import plan

    hop = plan(n)
    if not hop.steps or not hop.seed_text or hop.unsupported:
        return False
    longest = max((s.end - s.start for s in mask.spans), default=0)
    return longest / max(1, len(mask.tokens)) < 0.6  # câu không phải chính một tên thực thể


# Chức danh cho biết phần sau từ quan hệ là MỘT NGƯỜI (bổ sung cho hop.TITLES).
PERSON_TITLES = ("hoàng hậu", "thái hậu", "hoàng thái hậu", "công chúa", "hoàng tử",
                 "tổng bí thư", "thủ tướng", "đại tướng", "tướng", "nhà thơ", "nhà văn",
                 "bác", "anh hùng", "danh nhân", "nghệ nhân")  # fmt: skip


def _relation_to_person(n: str, raw: str) -> bool:
    """Từ quan hệ có đứng đầu câu VÀ trỏ tới một người không.

    "con trâu cày ruộng", "con thuyền trên sông", "mẹ con cá voi", "chồng chén bát": "con"/"mẹ"/
    "chồng" ở đây là loại từ hoặc nghĩa thường -> KHÔNG phải multi-hop. Là người khi phần còn lại
    (sau mọi từ quan hệ và "của") bắt đầu bằng chức danh, là tên đã có trong KG, hoặc là tên riêng
    viết hoa trong câu người dùng gõ ("mộ mẹ của Hồ Chí Minh").
    """
    from retrieval import hop

    text = n.strip()
    for word, _ in hop.TARGETS:
        rest = hop._eat(text, word)
        if rest is not None:
            text = rest
            break
    relation_words = sorted(
        {w for w, *_ in hop.RELATIONS} | set(hop.UNSUPPORTED) | {"người", "trai", "gái"},
        key=len,
        reverse=True,
    )
    peeled = False
    while True:
        for word in relation_words:
            rest = hop._eat(text, word)
            if rest is not None and rest != text:
                text, peeled = rest, peeled or word not in {"người", "trai", "gái"}
                break
        else:
            break
    if not peeled or not text:
        return False
    if any(re.match(rf"{re.escape(t)}(?!\w)", text) for t in (*hop.TITLES, *PERSON_TITLES)):
        return True
    first = text.split()[0]
    words = raw.split()
    if any(w[:1].isupper() and w.lower().strip(".,;:!?") == first for w in words[1:]):
        return True  # tên riêng viết hoa (không tính chữ đầu câu)
    try:
        from storage.local import connect

        with connect() as conn:
            hop.ensure_schema(conn)
            return bool(hop.find_nodes(conn, hop.plan(n).seed_text))
    except Exception:  # không có DB (unit test parser): chỉ dùng chức danh / viết hoa
        return False


def parse(raw: str, catalog: EntityCatalog | None = None) -> ParsedQuery:
    n = _strip_prefix(normalize(raw))
    mask = _Mask(n, catalog or EMPTY)
    entities = [{"text": s.matched_text, "entity_ids": s.entity_ids} for s in mask.spans]

    def build(intent_type: str, subs: list[str], **kw) -> ParsedQuery:
        kind = "class" if intent_type == "set_query" else "text"
        return ParsedQuery(raw=raw, normalized=n, intent_type=intent_type,
                           sub_queries=[{"text": s, "type": kind} for s in subs],
                           entities=entities, **kw)  # fmt: skip

    # BƯỚC 2: marker quan hệ chỉ tính khi nằm NGOÀI tên thực thể — hoặc câu có CẤU TRÚC hỏi quan
    # hệ ([lăng/mộ/đền thờ…] + [con trai/cha/mẹ/vợ…] + người) mà không phải chính một tên thực thể
    # ("đền thờ cha của Hồ Chí Minh" vẫn là multi-hop dù "thờ cha" có trong "Nhà thờ Cha Tam").
    if (mask.free(HOP_RE, n) or _hop_structure(n, mask)) and _relation_to_person(n, raw):
        markers = "|".join(re.escape(m) for m in sorted(HOP_MARKERS, key=len, reverse=True))
        chain = [p.strip() for p in re.split(rf"(?:\s+(?:của|thuộc)\s+|(?<!\w)({markers})(?!\w))", n)
                 if p and p.strip()]  # fmt: skip
        return build("multi_hop", [n], hop_chain=chain or [n], needs_graph=True)

    # BƯỚC 3: tách ý định; địa danh sau dấu phẩy được gộp vào ý trước.
    subs = _split_intents(n, mask.free(MULTI_RE, n, both_sides=True), mask) or [n]
    if len(subs) > 1:
        return build("multi_intent", subs)

    # BƯỚC 4: marker tập hợp ("các", "những", "tất cả"...).
    if mask.free(SET_RE, n):
        return build("set_query", subs, needs_graph=True)

    return build("single", subs)


# Orientation only as a photo attribute ("ảnh ngang", "khổ dọc") or as the first word left
# after normalize() strips "ảnh"; never inside names like "Đèo Ngang" or "dọc sông Hương".
_ORIENTATION = re.compile(r"(?:^|(?<!\w)(?:ảnh|hình|khổ|chụp)\s+)(ngang|dọc)(?!\w)")
_QUALITY = re.compile(r"(?<!\w)(?:chất lượng cao|độ phân giải cao|sắc nét|độ nét cao)(?!\w)")


def extract_filters(n: str) -> dict:
    """Nhận diện 'ảnh ngang/dọc', 'chất lượng cao' -> filter. Tỉnh/thành giữ trong text."""
    filters: dict = {}
    if _QUALITY.search(n):
        filters["min_width"] = 1200
    match = _ORIENTATION.search(n)
    if match:
        filters["orientation"] = "landscape" if match.group(1) == "ngang" else "portrait"
    return filters
