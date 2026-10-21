"""Giai đoạn 3 — online fallback cho multi-hop: tìm web + KIỂM CHỨNG, không đoán.

Gemini (OpenRouter, plugin web search) chỉ ĐỀ XUẤT: tên người + câu trích. Hệ thống tự tải các URL
trích dẫn do CÔNG CỤ TÌM KIẾM trả về (annotations, không dùng URL model tự viết), rồi chỉ chấp nhận
khi câu trích có nguyên văn trong trang tải về VÀ nhắc tên cả hai phía của quan hệ. Không đủ bằng
chứng -> lưu `no_evidence` (cache, không gọi lại tốn tiền trong KG_ONLINE_NEGATIVE_TTL_DAYS ngày).

Chạy nền với ngân sách HOP_ONLINE_BUDGET_MS cho mỗi request: hết ngân sách -> trả `pending`, luồng
nền vẫn chạy tiếp và ghi KG; lần hỏi sau dùng cạnh đã ghi.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import httpx

from retrieval import hop
from retrieval.kg_quality import direction_ok, has_cue, person_node
from retrieval.kg_sources import FetchError, fetch_text, normalize, quote_context
from storage.local import connect, plain

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="kg-online")
_running: dict[str, object] = {}
_lock = threading.Lock()

ASK = {
    ("PARENT_OF", "forward"): "các người con của {x}",
    ("PARENT_OF", "reverse"): "cha và mẹ của {x}",
    ("SPOUSE_OF", "any"): "vợ hoặc chồng của {x}",
}
GENDER_WORDS = {
    "male": ("con trai", "hoàng tử", "thân phụ", "cha ", "bố ", "chồng", "ông "),
    "female": ("con gái", "công chúa", "thân mẫu", "mẹ ", "vợ", "hoàng hậu", "bà "),
}


def enabled() -> bool:
    from retrieval import llm_router

    return os.getenv("HOP_ONLINE", "on").lower() == "on" and llm_router.enabled()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def web_search(question: str) -> tuple[dict, list[str], dict]:
    """(JSON model trả, URL trích dẫn của công cụ tìm kiếm, usage)."""
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    body = {
        "model": os.getenv("KG_ONLINE_MODEL", "google/gemini-3.5-flash-lite"),
        # engine exa: kết quả tìm kiếm được đưa vào ngữ cảnh nên LUÔN có URL nguồn thật; engine
        # native (Google grounding) bỏ trích dẫn khi buộc trả JSON (đo 2026-10-21: 0/15 lần).
        "plugins": [
            {
                "id": "web",
                "engine": os.getenv("KG_ONLINE_ENGINE", "exa"),
                "max_results": int(os.getenv("KG_ONLINE_RESULTS", "4")),
            }
        ],
        "messages": [
            {
                "role": "system",
                "content": (
                    "Bạn tra cứu quan hệ gia đình của nhân vật lịch sử/công chúng Việt Nam trên web. "
                    "Chỉ nêu điều các nguồn tìm được NÓI RÕ. Mỗi người kèm MỘT câu trích NGUYÊN VĂN "
                    "(copy đúng từng chữ, 40-300 ký tự) có nhắc tên cả hai người. Không biết thì để "
                    'danh sách rỗng. Trả DUY NHẤT JSON: {"people":[{"name":"...","gender":'
                    '"male|female|unknown","quote":"..."}]}'
                ),
            },
            {"role": "user", "content": question},
        ],
        "max_tokens": 800,
        "temperature": 0,
        "reasoning": {"effort": "minimal"},
        "usage": {"include": True},
    }
    response = httpx.post(
        os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
        + "/chat/completions",
        json=body,
        headers={"Authorization": "Bearer " + key},
        timeout=40,
    )
    response.raise_for_status()
    data = response.json()
    message = data["choices"][0]["message"]
    sources, seen = [], set()
    for a in message.get("annotations") or []:
        cite = a.get("url_citation") or {}
        if a.get("type") == "url_citation" and cite.get("url") and cite["url"] not in seen:
            seen.add(cite["url"])
            # `content` = đoạn trang do CÔNG CỤ TÌM KIẾM đọc (không phải model viết).
            sources.append(
                {
                    "url": cite["url"],
                    "title": cite.get("title") or "",
                    "content": cite.get("content") or "",
                }
            )
    match = re.search(r"\{.*\}", message.get("content") or "", re.S)
    parsed = json.loads(match.group(0)) if match else {}
    return parsed, sources, data.get("usage") or {}


def _names_in(context: str, parties: list[list[str]]) -> bool:
    text = plain(context)
    return all(any(plain(name) in text for name in names if name) for names in parties)


def verify_quote(
    quote: str, parties: list[list[str]], sources: list[dict], predicate: str | None = None
) -> tuple[str, str, str] | None:
    """(url, câu trích, cách kiểm) khi câu trích có NGUYÊN VĂN trong văn bản nguồn và đoạn quanh nó
    (±400 ký tự) nhắc mọi bên (theo bất kỳ tên gọi nào). Văn bản nguồn, theo thứ tự:
      1. đoạn trang do công cụ tìm kiếm trả (annotation.content) — không do model viết;
      2. trang do chính hệ thống tải về (nhiều trang chặn bot: Wikipedia 403, trang cần JS…).
    `parties`: mỗi bên là danh sách tên gọi (nhãn + bí danh)."""
    if not quote or not any(plain(n) in plain(quote) for names in parties for n in names if n):
        return None  # câu trích phải nhắc ít nhất một bên
    if not has_cue(quote, predicate):
        return None  # câu trích không nói lên quan hệ
    for source in sources:
        snippet = f"{source.get('title', '')}\n{source.get('content', '')}"
        context = quote_context(snippet, quote) if source.get("content") else None
        if context and _names_in(context, parties):
            return source["url"], quote, "quote_in_search_snippet"
    for source in sources:
        try:
            final, text = fetch_text(source["url"])
        except FetchError:
            continue
        context = quote_context(text, quote)
        if context and _names_in(context, parties):
            return final, quote, "quote_in_fetched_page"
    return None


def aliases(conn, node: str | None, fallback: str) -> list[str]:
    names = [r[0] for r in conn.execute("SELECT alias_norm FROM kg_alias WHERE node_id=?", (node,))]
    return names or [fallback]


def _gender(person: dict, quote: str) -> str | None:
    """Chỉ nhận giới tính khi câu trích có từ chỉ giới tính tương ứng."""
    g = person.get("gender")
    if g in GENDER_WORDS and any(w in normalize(quote) + " " for w in GENDER_WORDS[g]):
        return g
    return None


def lookup(subject_node: str | None, subject_text: str, predicate: str, direction: str) -> dict:
    """Tìm + kiểm chứng + ghi KG. Trả {status: found|no_evidence|error, edges, usd}."""
    with connect() as conn:
        hop.ensure_schema(conn)
        label = hop.node_info(conn, subject_node).get("label") if subject_node else subject_text
        subject_names = aliases(conn, subject_node, label)
    question = ASK[(predicate, direction)].format(x=label)
    try:
        parsed, urls, usage = web_search(question)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return {"status": "error", "detail": type(exc).__name__}
    edges = []
    with connect() as conn:
        hop.ensure_schema(conn)
        for person in (parsed.get("people") or [])[:6]:
            name = (person.get("name") or "").strip()
            quote = (person.get("quote") or "").strip()
            if not name or not quote or plain(name) == plain(label):
                continue
            checked = verify_quote(quote, [subject_names, [name]], urls, predicate)
            if not checked:
                continue
            final_url, quote, how = checked
            subject = subject_node or person_node(conn, label, None, "online")
            other = person_node(conn, name, _gender(person, quote), "online")
            if subject is None or other is None:
                continue
            s, o = (subject, other) if direction in {"forward", "any"} else (other, subject)
            conn.commit()  # judge ghi cache qua kết nối khác
            if predicate == "PARENT_OF" and not direction_ok(conn, quote, s, o):
                continue  # câu trích không nói đúng chiều cha/mẹ -> con
            conn.execute(
                "INSERT OR IGNORE INTO kg_edge VALUES (?,?,?,?,?,?,1,0,?,?,?)",
                (
                    s,
                    predicate,
                    o,
                    "online",
                    final_url,
                    quote,
                    "web_search+" + how,
                    None,
                    _now(),
                ),
            )
            edges.append({"subject": s, "object": o, "source": final_url})
    return {
        "status": "found" if edges else "no_evidence",
        "edges": edges,
        "citations": len(urls),
        "usd": usage.get("cost"),
    }


def verify_claim(
    subject_label: str,
    predicate: str,
    object_label: str,
    subject_names: list[str] | None = None,
    object_names: list[str] | None = None,
) -> dict:
    """Kiểm chứng một khẳng định của seed thủ công: {verified, source_url, evidence, verifier}."""
    phrase = {"PARENT_OF": "là cha hoặc mẹ của", "SPOUSE_OF": "là vợ hoặc chồng của"}[predicate]
    question = (
        f"Tìm nguồn nói rõ {subject_label} {phrase} {object_label}. Trong JSON, mục people gồm "
        f"{object_label} với câu trích nguyên văn thể hiện quan hệ này."
    )
    parties = [subject_names or [subject_label], object_names or [object_label]]
    try:
        parsed, urls, usage = web_search(question)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return {"verified": False, "detail": type(exc).__name__}
    for person in parsed.get("people") or []:
        quote = (person.get("quote") or "").strip()
        checked = verify_quote(quote, parties, urls, predicate)
        if checked:
            return {
                "verified": True,
                "source_url": checked[0],
                "evidence": checked[1],
                "verifier": "web_search+" + checked[2],
                "usd": usage.get("cost"),
            }
    return {"verified": False, "citations": len(urls), "usd": usage.get("cost")}


def callback(budget_ms: int | None = None):
    """Hàm `online(conn, node, seed_text, step)` cho hop.resolve: cache + chạy nền + ngân sách."""
    budget = (
        budget_ms if budget_ms is not None else int(os.getenv("HOP_ONLINE_BUDGET_MS", "2500"))
    ) / 1000
    ttl = timedelta(days=int(os.getenv("KG_ONLINE_NEGATIVE_TTL_DAYS", "7")))

    def online(conn, node, seed_text, step):
        if (step.predicate, step.direction) not in ASK:
            return {"status": "unsupported"}
        key = f"{node or 'text:' + plain(seed_text)}|{step.predicate}|{step.direction}"
        row = conn.execute(
            "SELECT status, detail, created_at FROM kg_lookup WHERE lookup_key=?", (key,)
        ).fetchone()
        if row and (row[0] == "found" or datetime.fromisoformat(row[2]) > datetime.now(UTC) - ttl):
            result = {**json.loads(row[1] or "{}"), "status": row[0], "cached": True}
            if node is None and row[0] == "found":
                result["seed_nodes"] = hop.find_nodes(conn, seed_text)
            return result
        with _lock:
            future = _running.get(key)
            if future is None:

                def job():
                    result = lookup(node, seed_text or "", step.predicate, step.direction)
                    if result["status"] in {"found", "no_evidence"}:
                        with connect() as c:
                            hop.ensure_schema(c)
                            c.execute(
                                "INSERT OR REPLACE INTO kg_lookup VALUES (?,?,?,?)",
                                (key, result["status"], json.dumps(result), _now()),
                            )
                    with _lock:
                        _running.pop(key, None)
                    return result

                future = _executor.submit(job)
                _running[key] = future
        started = time.perf_counter()
        try:
            result = future.result(timeout=budget)
        except TimeoutError:
            return {"status": "pending", "key": key, "budget_ms": round(budget * 1000)}
        except Exception as exc:  # tra cứu online lỗi không làm hỏng request
            return {"status": "error", "detail": type(exc).__name__}
        result = {**result, "wait_ms": round((time.perf_counter() - started) * 1000)}
        if node is None and result["status"] == "found":
            result["seed_nodes"] = hop.find_nodes(conn, seed_text)
        return result

    return online
