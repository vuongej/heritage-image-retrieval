"""Hybrid retrieval: rule parse entity-first + LLM speculative; mỗi sub-query gộp RRF 4 nguồn:
dense metadata (img_text), dense ảnh SigLIP2 (img_visual), FTS5 BM25, khớp tên thực thể."""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from itertools import zip_longest

from retrieval import budget, llm_router, speculative, vector_store
from retrieval import rerank as reranking
from retrieval.catalog import for_index
from retrieval.embed import EmbeddingUnavailable, embed_query, embed_text_visual
from retrieval.fusion import rrf
from retrieval.local_index import manifest
from retrieval.query_parser import parse
from storage.local import cache_get, cache_put, connect, image_rows, lexical_candidates, plain

ALLOWED_FILTERS = {"entity_id", "entity_slug", "parent_class", "min_width", "orientation"}
DENSE_TOP_K = 200
# Trọng số RRF (dense text, dense ảnh, FTS, tên thực thể): giữ 1/1/1/3 tới khi có goldset (Phase 4).
RRF_WEIGHTS = {"text": 1.0, "visual": 1.0, "lexical": 1.0, "exact": 3.0}
_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="dense")


def _retrieve(
    subs: list[str],
    conn,
    entities,
    timings: dict,
    suffix: str = "",
    warnings: list | None = None,
    anchors: list | None = None,
) -> list[list[str]]:
    """Một danh sách xếp hạng (rownum dạng chuỗi) cho mỗi sub-query.

    `anchors` (nếu truyền) nhận, cho mỗi sub-query, tập entity_id khớp TÊN với sub-query đó
    (trùng hẳn hoặc khớp một phần) — bằng chứng "ảnh này thuộc ý định này" cho multi-intent.

    `entities`: [(entity_id, tên đã bỏ dấu)] — tính sẵn trong catalog, không plain() mỗi truy vấn.
    """
    visual = vector_store.has_visual()
    t = time.perf_counter()
    try:
        vectors = embed_query(subs)
    except EmbeddingUnavailable as exc:
        # Endpoint embedding lỗi: vẫn trả kết quả từ FTS + khớp tên, không 503.
        vectors = []
        if warnings is not None:
            warnings.append(f"embedding_failed: {exc}; dense text branch skipped")
    timings["embed_query" + suffix] = (time.perf_counter() - t) * 1000
    if visual:
        t = time.perf_counter()
        visual_vectors = embed_text_visual(subs)
        timings["embed_visual" + suffix] = (time.perf_counter() - t) * 1000
    t = time.perf_counter()
    # Hai collection được truy vấn song song cho mọi sub-query.
    jobs = [_pool.submit(vector_store.search, vector_store.TEXT, v, DENSE_TOP_K) for v in vectors]
    visual_jobs = (
        [
            _pool.submit(vector_store.search, vector_store.VISUAL, v, DENSE_TOP_K)
            for v in visual_vectors
        ]
        if visual
        else []
    )
    dense_text = [[str(n) for n, _ in job.result()] for job in jobs] or [[] for _ in subs]
    dense_visual = [[str(n) for n, _ in job.result()] for job in visual_jobs] or [[] for _ in subs]
    timings["dense" + suffix] = (time.perf_counter() - t) * 1000
    t = time.perf_counter()
    ranks = []
    for i, text in enumerate(subs):
        lexical = [str(n) for n in lexical_candidates(text)]
        normalized = plain(text)
        matching = [
            e
            for e in entities
            if len(e[1]) >= 4
            and (e[1] in normalized or (len(normalized) >= 8 and normalized in e[1]))
        ]
        # The entity named exactly by the query keeps all its images first; the other
        # matches are interleaved so one of them cannot fill the whole rerank pool
        # (e.g. "Văn Miếu" matches Văn Miếu Huế, Bắc Ninh, Hà Tĩnh, ...).
        identical = [e for e in matching if e[1] == normalized]
        partial = [e for e in matching if e[1] != normalized][:20]
        if anchors is not None:
            anchors.append(
                {"exact": {e[0] for e in identical}, "all": {e[0] for e in [*identical, *partial]}}
            )
        per_entity = [
            [
                str(r[0])
                for r in conn.execute(
                    "SELECT rownum FROM images WHERE entity_id=? ORDER BY rownum LIMIT 30",
                    (e[0],),
                )
            ]
            for e in [*identical, *partial]
        ]
        exact = [doc for docs in per_entity[: len(identical)] for doc in docs]
        exact += [
            doc
            for row in zip_longest(*per_entity[len(identical) :])
            for doc in row
            if doc is not None
        ]
        merged = rrf(
            [dense_text[i], dense_visual[i], lexical, exact],
            weights=[
                RRF_WEIGHTS["text"],
                RRF_WEIGHTS["visual"],
                RRF_WEIGHTS["lexical"],
                RRF_WEIGHTS["exact"] if exact else 0.0,
            ],
        )
        ranks.append([doc for doc, _ in merged])
    timings["retrieve" + suffix] = (time.perf_counter() - t) * 1000
    return ranks


def _order(ranks: list[list[str]]) -> list[str]:
    """Xen kẽ các sub-query (mỗi ý định đều có mặt ở đầu pool), phần còn lại theo RRF."""
    if not ranks:
        return []
    ordered = (
        list(dict.fromkeys(doc for items in zip(*ranks, strict=False) for doc in items))
        if len(ranks) > 1
        else list(ranks[0])
    )
    seen = set(ordered)
    for doc, _ in rrf(ranks):
        if doc not in seen:
            ordered.append(doc)
            seen.add(doc)
    return ordered


CUTOFF_MODE = os.getenv("RERANK_CUTOFF_MODE", "none")  # none | legacy_llm_0.2


def min_relevance() -> float:
    """Ngưỡng điểm gốc cross-encoder để một ảnh được coi là liên quan (scripts/calibrate_relevance.py).

    Chỉ áp cho ảnh có `relevance` (local_ce / api); ảnh khớp ĐÚNG tên thực thể được miễn (bằng chứng
    tên mạnh hơn điểm mô hình). 0 = tắt. Mặc định 0,2 (reports/v2/relevance_calibration.json, bge-
    reranker-v2-m3): ảnh đúng silver thấp nhất 0,53; truy vấn ngoài phạm vi cao nhất 0,128.
    """
    return float(os.getenv("RERANK_MIN_RELEVANCE", "0.2"))


def _passes(hit, exempt: set[str], entity_of) -> bool:
    floor = min_relevance()
    return (
        floor <= 0
        or hit.relevance is None
        or hit.relevance >= floor
        or entity_of(hit.image_id) in exempt
    )


def _size_ok(row: dict, size: dict) -> bool | None:
    """True/False khi biết kích thước; None khi chưa biết (chính sách quyết định giữ hay bỏ)."""
    w, h = row.get("width"), row.get("height")
    if w is None or h is None:
        return None
    if w < size.get("min_width", 0):
        return False
    if size.get("orientation") == "landscape" and not w > h:
        return False
    if size.get("orientation") == "portrait" and not h > w:
        return False
    return True


def _rerank(text: str, pool: list[dict], mode: str, warnings: list[str]):
    """Rerank có 2 tầng dự phòng; lỗi không bao giờ làm hỏng request."""
    if not pool:
        return []
    try:
        ranked = reranking.rerank(text, pool, keep=len(pool), mode=mode)
    except (RuntimeError, ValueError) as exc:
        prefix = "llm_rerank_failed" if mode == "llm" else "rerank_failed"
        # Rerank qua endpoint lỗi / quá hạn: dự phòng cosine cũng gọi chính endpoint đó (embed
        # ứng viên, chung hạn mức) nên giữ thẳng thứ tự RRF để không vượt SLO.
        fallback = "fusion order" if mode == "api" else "embedding similarity"
        warnings.append(f"{prefix}: {exc}; used {fallback}")
        try:
            if mode == "api":
                raise RuntimeError("skip embedding fallback")
            ranked = reranking.rerank(text, pool, keep=len(pool), mode="embedding")
        except (RuntimeError, ValueError):
            # Cả embedding cũng lỗi (vd endpoint 429): giữ thứ tự RRF, điểm giảm dần.
            ranked = [
                reranking.RerankHit(r["image_id"], 1 - i / len(pool), "fusion_order")
                for i, r in enumerate(pool)
            ]
    if CUTOFF_MODE == "legacy_llm_0.2" and ranked and ranked[0].reason == "llm_metadata_rerank":
        ranked = [h for h in ranked if h.score >= 0.2]
    return ranked


def allocate_fair(queues: list[list[str]], top_k: int) -> list[str]:
    """Round-robin giữa các sub-query trên tập ứng viên ĐÃ có bằng chứng; không lấp bằng ảnh khác.

    (RETRIEVAL_PIPELINE_V2 §5.4) — không dùng quota max(top_k//n, 3) vì có thể vượt top_k.
    """
    result: list[str] = []
    used: set[str] = set()
    queues = [list(q) for q in queues]
    while len(result) < top_k:
        advanced = False
        for queue in queues:
            while queue and queue[0] in used:
                queue.pop(0)
            if queue and len(result) < top_k:
                item = queue.pop(0)
                result.append(item)
                used.add(item)
                advanced = True
        if not advanced:
            break
    return result


def run(query: str, top_k: int = 10, filters: dict | None = None, use_cache: bool = True):
    """Một request /v1/search, trong hạn chờ tổng SEARCH_DEADLINE_S (retrieval/budget.py)."""
    with budget.request():
        return _run(query, top_k, filters, use_cache)


def _run(query: str, top_k: int = 10, filters: dict | None = None, use_cache: bool = True):
    from retrieval.search import PIPELINE_VERSION, SearchHit, SearchResponse, build_facets

    if not query.strip() or not 1 <= top_k <= 100:
        raise ValueError("query must be nonempty and top_k must be between 1 and 100")
    if set(filters or {}) - ALLOWED_FILTERS:
        raise ValueError(f"Unsupported local filters: {sorted(set(filters) - ALLOWED_FILTERS)}")
    started = time.perf_counter()
    state = manifest()
    rerank_mode = reranking.backend()
    with connect() as conn:
        row = conn.execute("SELECT value FROM metadata WHERE key='dimensions_known'").fetchone()
    dims_known = int(row[0]) if row else 0  # ghi bởi scripts.migrate_images_v2
    with connect() as conn:  # KG đổi (seed / Gemini / online) -> kết quả multi-hop cache cũ hết hạn
        try:
            kg_stamp = list(
                conn.execute(
                    "SELECT count(*), max(created_at) FROM kg_edge WHERE verified=1 OR reviewed=1"
                ).fetchone()
            )
        except Exception:  # bảng KG chưa tạo
            kg_stamp = None
    cache_id = (
        "search:v7:"
        + hashlib.sha256(
            json.dumps(
                {
                    "q": query,
                    "k": top_k,
                    "f": filters,
                    "index": state,
                    "index_version": state.get("index_version"),
                    "pipeline_version": PIPELINE_VERSION,
                    "vectors": [
                        vector_store.backend(),
                        vector_store.visual_manifest().get("points"),
                    ],
                    "dims_known": dims_known,
                    "kg": kg_stamp,
                    "parse": [
                        llm_router.model() if llm_router.enabled() else None,
                        speculative.mode(),
                        speculative.POLICY_VERSION,
                    ],
                    "rerank": [
                        rerank_mode,
                        reranking.model_name(rerank_mode),
                        CUTOFF_MODE,
                        min_relevance(),
                    ],
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
    )
    cached = cache_get(cache_id) if use_cache else None
    if cached:
        cached["hits"] = [SearchHit(**h) for h in cached["hits"]]
        cached["request_id"] = str(uuid.uuid4())
        cached["total_ms"] = int((time.perf_counter() - started) * 1000)
        cached["timings_ms"] = {"cache_lookup": cached["total_ms"]}
        return SearchResponse(**cached)
    timings: dict = {}
    warnings: list[str] = []

    t = time.perf_counter()
    catalog = for_index(state.get("csv_sha256"))
    timings["catalog"] = (time.perf_counter() - t) * 1000
    t = time.perf_counter()
    rule = parse(query, catalog)
    conf = speculative.confidence(rule, catalog)
    timings["parse"] = (time.perf_counter() - t) * 1000
    # LLM chỉ chạy khi rule chưa chắc (LLM_PARSE_MODE=ambiguous_only), song song, không chặn retrieve.
    handle = speculative.start(query, catalog) if speculative.should_call(conf) else None
    skipped = (
        handle is None
        and llm_router.enabled()
        and speculative.mode() != "off"
        and not speculative.should_call(conf)
    )

    # Filter: tham số API là BẮT BUỘC (strict: ảnh chưa biết kích thước bị loại); filter suy ra từ
    # câu ("ảnh ngang") là gợi ý (permissive: chỉ loại ảnh ĐÃ BIẾT là sai, giữ ảnh chưa biết).
    explicit = dict(filters or {})
    inferred = {k: v for k, v in (rule.get("filters") or {}).items() if k in ALLOWED_FILTERS}
    active = {**inferred, **explicit}
    size = {k: active.pop(k) for k in ("min_width", "orientation") if k in active}
    strict = any(k in explicit for k in size)
    if size and not dims_known:
        warnings += [f"filter {k} ignored: catalog has no image dimensions yet" for k in size]
        size = {}

    tail: list[str] = []
    anchors: list[dict] = []
    with connect() as conn:
        entities = catalog.plain_names
        ranks = []
        if rule["intent_type"] != "multi_hop":
            ranks = _retrieve(
                [s["text"] for s in rule["sub_queries"]],
                conn,
                entities,
                timings,
                "",
                warnings,
                anchors,
            )
        t = time.perf_counter()
        llm, status = speculative.wait(handle)
        if skipped:
            status = "skipped_confident"
        timings["llm_wait"] = (time.perf_counter() - t) * 1000
        parsed, action = speculative.decide(rule, llm, conf)
        if parsed is not rule:
            # LLM khác rule: retrieve theo LLM, ứng viên của rule xếp sau để không mất.
            tail = _order(ranks)
            anchors = []
            ranks = _retrieve(
                [s["text"] for s in parsed["sub_queries"]],
                conn,
                entities,
                timings,
                "_llm",
                warnings,
                anchors,
            )
    outcome = status if status != "ok" else action
    if status != "disabled":
        llm_router.log_event(
            {"kind": "outcome", "outcome": outcome, "wait_ms": timings["llm_wait"], "conf": conf}
        )
    if status.startswith("error"):
        warnings.append(f"llm_parse_failed: {status[7:]}; used rule parser")
    if parsed.get("parser") == "llm":
        parser = "llm"
    elif status == "ok":
        parser = "rule+llm"  # LLM về kịp; giữ rule (đồng ý, hoặc bị guard chặn)
    elif status in {"disabled", "skipped_confident"}:
        parser = "rule"
    else:
        parser = f"rule (llm {status.split(':')[0]})"  # timeout | error

    def respond(hits, subq_info=None, extra_warnings=(), resolution=None):
        return SearchResponse(
            str(uuid.uuid4()),
            parsed["intent_type"],
            parser,
            hits,
            build_facets(hits),
            timings,
            int((time.perf_counter() - started) * 1000),
            [*warnings, *extra_warnings],
            sub_queries=subq_info or [],
            parse_confidence=conf,
            pipeline_version=PIPELINE_VERSION,
            resolution=resolution,
        )

    resolution = None
    if parsed["intent_type"] == "multi_hop":
        # Chỉ đi theo cạnh có nguồn trong KG (retrieval/hop.py); không fallback sang ảnh cùng nhóm.
        from retrieval import hop, kg_online

        t = time.perf_counter()
        online = kg_online.callback() if kg_online.enabled() else None
        resolution = hop.resolve(rule["normalized"], online=online).to_dict()
        timings["hop_resolve"] = (time.perf_counter() - t) * 1000
        if resolution["status"] != "resolved":
            messages = {
                "pending_online_lookup": "KG has no verified edge yet; online evidence lookup is "
                "running in the background — ask again in a few seconds",
                "target_not_in_catalog": "relation chain verified, but the target has no images "
                "in the catalog (see resolution.target_nodes / related_places)",
            }
            return respond(
                [],
                extra_warnings=[
                    f"multi_hop {resolution['status']}: "
                    + messages.get(
                        resolution["status"],
                        "no verified relation chain to an entity with images in the catalog",
                    )
                ],
                resolution=resolution,
            )

    subs = [s["text"] for s in parsed["sub_queries"]]
    pool_size = max(top_k, int(os.getenv("RERANK_TOP_K", "24")))
    t = time.perf_counter()
    unknown_size = 0

    def eligible(ordered: list[str]) -> list[dict]:
        nonlocal unknown_size
        out = []
        for row in image_rows([int(n) for n in ordered[:400]]):
            if any(
                row.get(key) != active[key]
                for key in ("entity_id", "entity_slug", "parent_class")
                if key in active
            ):
                continue
            if size:
                verdict = _size_ok(row, size)
                if verdict is False:
                    continue
                if verdict is None:
                    unknown_size += 1
                    if strict:
                        continue
            out.append(row)
        return out

    if resolution:
        # Ảnh của thực thể đích (đã xác minh), xen kẽ giữa các entity_id trùng tên.
        with connect() as conn:
            per_entity = [
                [
                    str(r[0])
                    for r in conn.execute(
                        "SELECT rownum FROM images WHERE entity_id=? ORDER BY rownum", (e,)
                    )
                ]
                for e in resolution["mapped_target_entity_ids"]
            ]
        merged = [d for row in zip_longest(*per_entity) for d in row if d is not None]
        pools = [eligible(merged)[:pool_size]]
    elif len(subs) == 1:
        merged = _order(ranks)
        seen = set(merged)
        merged += [doc for doc in tail if doc not in seen]
        pools = [eligible(merged)[:pool_size]]
    else:
        pools = [eligible(rank)[:pool_size] for rank in ranks]
    timings["metadata_filter"] = (time.perf_counter() - t) * 1000
    if unknown_size:
        policy = "excluded (strict API filter)" if strict else "kept (filter inferred from query)"
        warnings.append(f"size filter: {unknown_size} candidates with unknown dimensions {policy}")

    t = time.perf_counter()
    lookup = {r["image_id"]: r for pool in pools for r in pool}

    def entity_of(image_id: str) -> str | None:
        return lookup[image_id]["entity_id"]

    if resolution:
        chosen = [
            (r["image_id"], 1 - i / len(pools[0]), ["q0"], None) for i, r in enumerate(pools[0])
        ]
        chosen = chosen[:top_k]
        subq_info = [
            {
                "id": "q0",
                "text": subs[0],
                "coverage": "covered" if chosen else "none",
                "returned": len(chosen),
                "evidence": "verified_relation_chain",
            }
        ]
    elif len(subs) == 1:
        ranked = _rerank(query, pools[0], rerank_mode, warnings)
        if conf == "high" and anchors and anchors[0]["all"]:
            # Entity-first (V2 §6.3): truy vấn neo chắc vào tên -> ảnh của thực thể trùng đúng tên,
            # rồi thực thể khớp một phần, rồi phần còn lại; reranker chỉ xếp TRONG từng tầng.
            # (A/B trên pool đóng băng: reranker xếp tự do làm nDCG@10 tên thực thể 1,00 -> 0,95.)
            exact, partial = anchors[0]["exact"], anchors[0]["all"]

            def tier(hit):
                entity = lookup[hit.image_id]["entity_id"]
                return 0 if entity in exact else 1 if entity in partial else 2

            ranked = sorted(ranked, key=tier)  # sort ổn định: giữ thứ tự reranker trong tầng
        exempt = anchors[0]["exact"] if anchors else set()
        pooled = len(ranked)
        ranked = [h for h in ranked if _passes(h, exempt, entity_of)]
        if pooled and not ranked:
            warnings.append(
                f"no_relevant_results: no candidate reached relevance {min_relevance():g}"
                " (cross-encoder) and none matches an entity name"
            )
        ranked = ranked[:top_k]
        chosen = [(h.image_id, h.score, ["q0"], h.relevance) for h in ranked]
        subq_info = [
            {
                "id": "q0",
                "text": subs[0],
                "coverage": "covered" if chosen else "none",
                "returned": len(chosen),
            }
        ]
    else:
        # Multi-intent: rerank RIÊNG từng sub-query bằng chính text của nó (song song), chỉ giữ
        # ảnh có bằng chứng thuộc sub-query (thực thể khớp tên, nếu sub-query có tên), rồi chia slot.
        jobs = [
            # copy_context: thread rerank thấy hạn chờ tổng của request (retrieval/budget.py)
            _pool.submit(contextvars.copy_context().run, _rerank, text, pool, rerank_mode, warnings)
            for text, pool in zip(subs, pools, strict=True)
        ]
        per_sub = [job.result() for job in jobs]
        anchor_sets = (
            [a["all"] for a in anchors] if len(anchors) == len(subs) else [set()] * len(subs)
        )
        queues, scores, subq_info = [], {}, []
        for i, (ranked_i, anchor) in enumerate(zip(per_sub, anchor_sets, strict=True)):
            # Có tên thực thể: bằng chứng = khớp tên. Không có: phải đạt ngưỡng liên quan.
            supported = [
                h
                for h in ranked_i
                if (entity_of(h.image_id) in anchor if anchor else _passes(h, set(), entity_of))
            ]
            queues.append([h.image_id for h in supported])
            for h in supported:
                scores.setdefault(h.image_id, (h.score, [], h.relevance))[1].append(f"q{i}")
            subq_info.append(
                {
                    "id": f"q{i}",
                    "text": subs[i],
                    "evidence": "entity_name" if anchor else "retrieval_rank",
                    "supported_candidates": len(supported),
                }
            )
        selected = allocate_fair(queues, top_k)
        chosen = [(i, scores[i][0], scores[i][1], scores[i][2]) for i in selected]
        for info in subq_info:
            got = sum(info["id"] in m for _, _, m, _ in chosen)
            info["coverage"] = "covered" if got else "none"
            info["returned"] = got
            if not got:
                warnings.append(f"sub_query_no_coverage: {info['id']} ({info['text']})")
        if subq_info and not chosen:
            warnings.append(
                f"no_relevant_results: no sub-query has a candidate with relevance"
                f" >= {min_relevance():g} or an entity-name match"
            )
        if top_k < len(subs):
            warnings.append(
                f"top_k={top_k} < {len(subs)} sub-queries: not every intent can be shown"
            )
    timings["rerank"] = (time.perf_counter() - t) * 1000

    hits = []
    for image_id, score, matched, relevance in chosen:
        row = lookup[image_id]
        hits.append(
            SearchHit(
                image_id=image_id,
                image_url=row["image_url"],
                score=score,
                entity_id=row["entity_id"],
                entity_slug=row["entity_slug"],
                leaf_label=row["entity_name"],
                parent_class=row["parent_class"],
                query_type="approved_metadata",
                description=row["description"] or None,
                matched_subqueries=matched,
                relevance=None if relevance is None else round(relevance, 4),
                quality={
                    "width": row.get("width"),
                    "height": row.get("height"),
                    "verify": row.get("verify") or "unknown",
                    "verify_source": row.get("verify_source"),
                    "watermark": {1: "yes", 0: "no"}.get(row.get("has_watermark"), "unknown"),
                    "pixel_checked": False,
                },
            )
        )
    response = respond(hits, subq_info, resolution=resolution)
    # Không ghim câu trả lời suy giảm: rerank/embedding lỗi, hoặc LLM parse chưa kịp về (lần sau
    # parse LLM đã nằm trong cache nên sẽ được dùng).
    degraded = any(w.startswith(("deepseek_", "llm_", "embedding_", "rerank_")) for w in warnings)
    if not degraded and status in {"disabled", "ok", "skipped_confident"}:
        cache_put(cache_id, asdict(response))
    return response
