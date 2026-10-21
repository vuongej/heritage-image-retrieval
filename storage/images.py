"""Bounded public-image download for the audit stages and /v1/embed.

Only http(s), only hosts that resolve to public addresses (re-checked on every
redirect), size-capped, and decoded with Pillow before anything trusts the bytes.
"""

from __future__ import annotations

import ipaddress
import socket
from io import BytesIO
from urllib.parse import urljoin, urlsplit

import httpx
from PIL import Image

MAX_BYTES = 15 * 1024 * 1024
MAX_REDIRECTS = 3
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; heritage-image-retrieval-audit/0.1)",
    "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*;q=0.8",
}


class FetchError(Exception):
    pass


def _check_public(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise FetchError("only absolute http(s) image URLs are allowed")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or None)
    except socket.gaierror as exc:
        raise FetchError("dns_failed") from exc
    if not all(ipaddress.ip_address(info[4][0]).is_global for info in infos):
        raise FetchError("host does not resolve to a public address")


def fetch_image(url: str, timeout: float = 20.0) -> bytes:
    for _ in range(MAX_REDIRECTS + 1):
        _check_public(url)
        try:
            with httpx.stream(
                "GET",
                url,
                headers=HEADERS,
                timeout=httpx.Timeout(timeout, connect=10),
                follow_redirects=False,
            ) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers.get("location", ""))
                    continue
                if not response.is_success:
                    raise FetchError(f"http_{response.status_code}")
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise FetchError("too_large")
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.HTTPError as exc:
            raise FetchError(type(exc).__name__) from exc
    raise FetchError("too_many_redirects")


def decode(data: bytes) -> Image.Image:
    try:
        img = Image.open(BytesIO(data))
        img.load()
    except Exception as exc:
        raise FetchError("not_a_decodable_image") from exc
    return img
