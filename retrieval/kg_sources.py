"""Tài liệu nguồn cho KG multi-hop: tải trang an toàn, tách văn bản, kiểm tra câu trích.

Nguyên tắc: một quan hệ chỉ "đã kiểm chứng" khi CÂU TRÍCH xuất hiện nguyên văn trong văn bản của
trang nguồn mà CHÍNH HỆ THỐNG tải về — không tin lời model rằng nguồn nói vậy.

An toàn khi tải (§10.4): chỉ http(s), host phải phân giải ra IP công khai (kiểm lại mỗi redirect),
tối đa 5 redirect, tối đa 3 MB, chỉ nhận text/html hoặc text/plain. Văn bản cache trên đĩa theo URL.
"""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import httpx

from storage.images import FetchError, _check_public
from storage.runtime import data_dir

MAX_BYTES = 3 * 1024 * 1024
MAX_REDIRECTS = 5
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; heritage-image-retrieval-kg/0.2)",
    "Accept": "text/html,text/plain;q=0.9,*/*;q=0.1",
    "Accept-Language": "vi,en;q=0.8",
}
SKIP_TAGS = {"script", "style", "noscript", "svg", "head", "nav", "footer", "form", "iframe"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self.skip += 1
        elif tag in {"p", "br", "div", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(raw: str) -> str:
    parser = _Text()
    parser.feed(raw)
    text = html.unescape("".join(parser.parts))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def _cache_path(url: str) -> Path:
    path = data_dir() / "kg" / "docs" / (hashlib.sha256(url.encode()).hexdigest() + ".txt")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def fetch_text(url: str, timeout: float = 15.0) -> tuple[str, str]:
    """(final_url, văn bản). Lỗi -> FetchError. Có cache trên đĩa (dòng đầu = final_url)."""
    cached = _cache_path(url)
    if cached.exists():
        final, _, text = cached.read_text(encoding="utf-8").partition("\n")
        return final, text
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        _check_public(current)
        try:
            with httpx.stream(
                "GET",
                current,
                headers=HEADERS,
                timeout=httpx.Timeout(timeout, connect=8),
                follow_redirects=False,
            ) as response:
                if response.is_redirect:
                    current = urljoin(current, response.headers.get("location", ""))
                    continue
                if not response.is_success:
                    raise FetchError(f"http_{response.status_code}")
                kind = response.headers.get("content-type", "").lower()
                if kind and not kind.startswith(("text/html", "text/plain", "application/xhtml")):
                    raise FetchError(f"not_text:{kind.split(';')[0]}")
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise FetchError("too_large")
                    chunks.append(chunk)
                raw = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
                text = html_to_text(raw) if "html" in kind or "<html" in raw[:2000].lower() else raw
                cached.write_text(f"{current}\n{text}", encoding="utf-8")
                return current, text
        except httpx.HTTPError as exc:
            raise FetchError(type(exc).__name__) from exc
    raise FetchError("too_many_redirects")


def normalize(text: str) -> str:
    """So khớp câu trích: NFC, thường, gộp khoảng trắng, bỏ dấu nháy/ngoặc kép kiểu chữ."""
    text = unicodedata.normalize("NFC", text).lower()
    text = re.sub(r"[\"“”‘’«»`']", "", text)
    text = text.replace("…", "...")
    return re.sub(r"\s+", " ", text).strip()


def quote_in(text: str, quote: str, min_chars: int = 25) -> bool:
    """Câu trích (đủ dài để có nghĩa) có nằm nguyên văn trong văn bản không.

    Cho phép model rút gọn bằng "..." / "(...)": mọi đoạn giữa các dấu rút gọn phải có mặt theo
    đúng thứ tự trong văn bản.
    """
    q = normalize(quote)
    if len(q) < min_chars:
        return False
    body = normalize(text)
    pieces = [p.strip() for p in re.split(r"\(?\.\.\.\)?", q) if p.strip()]
    position = 0
    for piece in pieces:
        found = body.find(piece, position)
        if found < 0:
            return False
        position = found + len(piece)
    return bool(pieces)


def quote_context(text: str, quote: str, radius: int = 400) -> str | None:
    """Đoạn văn bản (đã chuẩn hoá) quanh vị trí câu trích trong trang, hoặc None nếu không có.
    Câu trích ≥ 15 ký tự (vd ô infobox "Thân phụ | Gia Long"): tên các bên được kiểm ở đoạn quanh."""
    if not quote_in(text, quote, min_chars=15):
        return None
    body = normalize(text)
    first = [p.strip() for p in re.split(r"\(?\.\.\.\)?", normalize(quote)) if p.strip()][0]
    at = body.find(first)
    return body[max(0, at - radius) : at + len(normalize(quote)) + radius]


def window(text: str, needles: list[str], radius: int = 2500, limit: int = 9000) -> str:
    """Các đoạn văn bản quanh tên cần quan tâm (giữ chi phí Gemini nhỏ)."""
    low = normalize(text)
    spans = []
    for needle in needles:
        n = normalize(needle)
        for m in re.finditer(re.escape(n), low):
            spans.append((max(0, m.start() - radius), m.end() + radius))
    if not spans:
        return text[:limit]
    spans.sort()
    merged = [list(spans[0])]
    for a, b in spans[1:]:
        if a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    # Vị trí trên `low` (đã gộp khoảng trắng) xấp xỉ vị trí trên văn bản gốc: lấy từ bản đã chuẩn hoá.
    return "\n...\n".join(low[a:b] for a, b in merged)[:limit]
