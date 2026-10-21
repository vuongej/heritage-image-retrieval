"""Chặn truy vấn khiếm nhã / nhạy cảm TRƯỚC khi vào pipeline (parse, embedding, rerank, LLM).

Chạy ở tầng API nên không thể vượt qua bằng cách gọi thẳng endpoint, và truy vấn bị chặn không
tốn quota embedding/LLM. Không phụ thuộc thư viện ngoài, ~0,1 ms / truy vấn.

Cách khớp: tách truy vấn thành token rồi so khớp CẢ CỤM TỪ (không so chuỗi con), nên "Dâm Đàm",
"du lịch", "buổi sáng", "đeo kính" không bị chặn nhầm vì có chứa chữ cái của từ cấm.
Chống lách luật phổ biến:
  - hoa/thường, Unicode dựng sẵn/tổ hợp, ký tự toàn chiều rộng, ký tự rộng 0, chữ Cyrillic giống Latin;
  - kéo dài chữ ("đụụụ", "fuuuck"), chèn ký tự ("đ.ụ", "d i t", "đ_m");
  - leetspeak ("l0n", "d1t", "sh!t", "f@ck").
Hai chế độ khớp cho mỗi từ (xem LEXICON):
  - strict: chỉ khớp khi GÕ ĐỦ DẤU. Dùng cho từ mà bản bỏ dấu trùng từ thường ngày
    (đụ ≈ du lịch, đéo ≈ đeo, lồn ≈ lon, buồi ≈ buổi, đĩ ≈ đi, phản động ≈ phần đông).
  - folded: khớp cả khi gõ không dấu. Dùng cho từ không có nghĩa thường ngày.
Danh sách cố ý ngắn và chỉ chứa từ không có nghĩa trong ngữ cảnh tìm ảnh di sản; sửa ở LEXICON.
Tắt tạm thời (ví dụ khi chạy đánh giá): QUERY_GUARD=off.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from typing import NamedTuple

log = logging.getLogger("query_guard")

# category -> {"strict": [...], "folded": [...]}; mỗi mục là một cụm từ (token cách nhau bằng dấu cách).
LEXICON: dict[str, dict[str, list[str]]] = {
    "profanity": {
        "strict": [
            "đụ", "đéo", "lồn", "cặc", "buồi", "cứt", "đĩ", "đm", "đmm", "đcm", "đkm",
            "mẹ mày", "thằng chó", "đồ chó", "chó đẻ", "đồ khốn", "khốn nạn", "mất dạy",
            "súc sinh", "thằng ngu", "đồ ngu",
        ],
        "folded": [
            "địt", "dit me", "vcl", "vkl", "clmm", "cmm", "dcm", "dkm", "dmm",
            "fuck", "fucking", "fucker", "motherfucker", "fck", "fuk", "fcuk", "shit", "bullshit", "bitch",
            "asshole", "bastard", "cunt", "dick", "pussy",
        ],
    },
    "sexual": {
        "strict": [
            "ảnh nóng", "clip nóng", "lộ hàng", "lộ clip", "khỏa thân", "khoả thân",
            "hiếp dâm", "dâm ô", "dâm đãng", "dâm dục", "đồi trụy", "làm tình", "tình dục",
            "mại dâm", "gái gọi", "ngực trần", "thủ dâm", "chịch",
        ],
        "folded": [
            "sex", "porn", "porno", "pornhub", "hentai", "jav", "nude", "nudes", "naked",
            "nsfw", "erotic", "blowjob", "khiêu dâm", "phim sex", "phim người lớn",
        ],
    },
    "violence": {
        "strict": [
            "chặt đầu", "xác chết", "máu me", "mổ bụng", "tự tử", "cách giết người",
            "chế bom", "chế tạo bom", "làm bom",
        ],
        "folded": ["gore", "snuff"],
    },
    "hate": {
        "strict": ["đồ mọi", "mọi đen"],
        "folded": ["nigger", "nigga", "faggot"],
    },
    "political": {
        "strict": [
            "phản động", "việt tân", "lật đổ chế độ", "lật đổ chính quyền",
            "chống phá nhà nước",
        ],
        "folded": ["cờ vàng ba sọc"],
    },
}

# Mẫu không biểu diễn được bằng cụm từ cố định.
_REGEX_TERMS: tuple[tuple[str, re.Pattern[str]], ...] = (("sexual", re.compile(r"^x{3,}$")),)

MESSAGES = {
    "profanity": "Truy vấn chứa ngôn từ thô tục nên không được xử lý.",
    "sexual": "Hệ thống không hỗ trợ tìm kiếm nội dung khiêu dâm hoặc nhạy cảm.",
    "violence": "Hệ thống không hỗ trợ tìm kiếm nội dung bạo lực hoặc gây hại.",
    "hate": "Truy vấn chứa ngôn từ miệt thị nên không được xử lý.",
    "political": "Hệ thống không hỗ trợ tìm kiếm nội dung chính trị nhạy cảm.",
}
HINT = " Hãy nhập tên địa danh, di tích hoặc mô tả ảnh di sản, ví dụ “Chùa Một Cột”."

_HOMOGLYPH = str.maketrans("аеорсхуіѕјοι", "aeopcxyisjoi")  # Cyrillic/Greek trông giống Latin
_LEET = str.maketrans("013457@$!", "oieastasi")
_LEET_CHARS = set("013457@$!")
# Chữ + số Unicode; ký hiệu @ $ ! chỉ thuộc token khi nằm GIỮA hai ký tự chữ-số ("sh!t", "c4c").
_TOKEN = re.compile(r"(?:[^\W_]|(?<=[^\W_])[@$!](?=[^\W_]))+")
_RUN = re.compile(r"(.)\1+")


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFD", text).replace("đ", "d")
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def _squeeze(token: str) -> str:
    return _RUN.sub(r"\1", token)


def _tokens(text: str) -> tuple[list[str], list[bool]]:
    """Token đã chuẩn hóa (CÒN dấu tiếng Việt) và cờ "đã bị che giấu" cho từng token.

    Token bị che giấu = đã đổi leet ("l0n") hoặc ghép từ các chữ rời ("d i t"): người gõ đang cố
    lách, nên bộ so khớp được phép so cả dạng không dấu ngay cả với từ strict.
    """
    s = unicodedata.normalize("NFKC", text)
    s = "".join(c for c in s if unicodedata.category(c) != "Cf")  # ký tự rộng 0, điều khiển hướng chữ
    s = unicodedata.normalize("NFC", s.lower().translate(_HOMOGLYPH))
    tokens: list[str] = []
    flags: list[bool] = []
    for t in _TOKEN.findall(s):
        leet = (
            len(t) >= 3
            and any(c.isalpha() for c in t)
            and any(c in _LEET_CHARS for c in t)
        )
        tokens.append(t.translate(_LEET) if leet else t)
        flags.append(leet)
    # "d i t" / "đ.ụ" -> các chữ đơn liên tiếp được ghép lại thành một token.
    out: list[str] = []
    out_flags: list[bool] = []
    run: list[str] = []
    for t, f in [*zip(tokens, flags, strict=True), ("", False)]:
        if len(t) == 1 and t.isalpha():
            run.append(t)
            continue
        if len(run) >= 2:
            out.append("".join(run))
            out_flags.append(True)
        else:
            out.extend(run)
            out_flags.extend([False] * len(run))
        run = []
        if t:
            out.append(t)
            out_flags.append(f)
    return out, out_flags


@dataclass(frozen=True)
class _Pattern:
    category: str
    phrase: str
    strict: bool
    exact: tuple[str, ...]
    squeezed: tuple[str | None, ...]  # None: từ quá ngắn sau khi nén chữ lặp -> chỉ so khớp chính xác


def _compile() -> tuple[_Pattern, ...]:
    patterns = []
    for category, modes in LEXICON.items():
        for mode, phrases in modes.items():
            strict = mode == "strict"
            for phrase in phrases:
                words = tuple(w if strict else _fold(w) for w in phrase.split())
                patterns.append(
                    _Pattern(
                        category,
                        phrase,
                        strict,
                        words,
                        tuple(_squeeze(w) if len(_squeeze(w)) >= 2 else None for w in words),
                    )
                )
    return tuple(patterns)


_PATTERNS = _compile()


class _View(NamedTuple):
    """Một truy vấn đã chuẩn hóa, tính sẵn các dạng so khớp để dùng chung cho mọi mẫu."""

    tokens: list[str]
    squeezed: list[str]
    folded: list[str]
    folded_squeezed: list[str]
    obfuscated: list[bool]

    @classmethod
    def of(cls, text: str) -> _View:
        tokens, flags = _tokens(text)
        folded = [_fold(t) for t in tokens]
        return cls(tokens, [_squeeze(t) for t in tokens], folded, [_squeeze(t) for t in folded], flags)


def _word_ok(view: _View, i: int, pattern: _Pattern, j: int) -> bool:
    text, text_sq = (
        (view.tokens[i], view.squeezed[i]) if pattern.strict else (view.folded[i], view.folded_squeezed[i])
    )
    word = pattern.exact[j]
    # Nén chữ lặp chỉ để bắt "đụụụ"; token phải dài ít nhất bằng từ cấm, nếu không "cm" (centimet)
    # sẽ khớp "cmm" vì cả hai cùng nén về "cm".
    if text == word or (
        pattern.squeezed[j] is not None and text_sq == pattern.squeezed[j] and len(text) >= len(word)
    ):
        return True
    if view.obfuscated[i] and pattern.strict:  # "l0n" không có dấu nhưng rõ ràng là "lồn" bị che
        plain = _fold(word)
        return view.folded[i] == plain or (
            len(_squeeze(plain)) >= 2
            and view.folded_squeezed[i] == _squeeze(plain)
            and len(view.folded[i]) >= len(plain)
        )
    return False


def _matches(view: _View, pattern: _Pattern) -> bool:
    n = len(pattern.exact)
    for i in range(len(view.tokens) - n + 1):
        if all(_word_ok(view, i + j, pattern, j) for j in range(n)):
            return True
    if n > 1:  # "d i t m e": chữ rời đã ghép thành MỘT token, so với cụm từ viết liền
        compact = "".join(_fold(w) for w in pattern.exact)
        compact_sq = _squeeze(compact)
        return any(
            f
            and (
                view.folded[i] == compact
                or (view.folded_squeezed[i] == compact_sq and len(view.folded[i]) >= len(compact))
            )
            for i, f in enumerate(view.obfuscated)
        )
    return False


@dataclass(frozen=True)
class Verdict:
    blocked: bool
    category: str | None = None
    term: str | None = None  # từ khóa trong LEXICON đã khớp; chỉ để ghi log, không trả cho client


def enabled() -> bool:
    return os.getenv("QUERY_GUARD", "on").lower() not in {"off", "0", "false"}


def check(text: str) -> Verdict:
    view = _View.of(text)
    for pattern in _PATTERNS:
        if _matches(view, pattern):
            return Verdict(True, pattern.category, pattern.phrase)
    for category, regex in _REGEX_TERMS:
        if any(regex.match(t) for t in view.folded):
            return Verdict(True, category, regex.pattern)
    return Verdict(False)


class QueryBlocked(Exception):
    def __init__(self, category: str):
        self.category = category
        self.message = MESSAGES[category] + HINT
        super().__init__(self.message)


def ensure_allowed(*texts: str | None) -> None:
    """Ném QueryBlocked nếu một trong các chuỗi vi phạm. api/main.py đổi thành HTTP 400."""
    if not enabled():
        return
    for text in texts:
        if not text:
            continue
        verdict = check(text)
        if verdict.blocked:
            digest = hashlib.sha256(text.encode()).hexdigest()[:10]
            log.warning(
                "query_blocked category=%s term=%r chars=%d sha=%s",
                verdict.category, verdict.term, len(text), digest,
            )
            raise QueryBlocked(verdict.category or "profanity")
