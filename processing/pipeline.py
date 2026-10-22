"""Luồng xử lý một file CSV: đọc -> gate -> tải ảnh -> SigLIP2 -> classifier -> router -> VLM -> tổng hợp.

Dùng lại đúng các stage của pipeline.verify (gate, fetch, encoder, features, router, vlm) và model
production ở processing.model, nên kết quả khớp benchmark (docs/verify-router-benchmark.md).
Cache ảnh / embedding nằm ở PROCESS_DIR (mặc định data/process) và dùng chung giữa các job:
xử lý lại cùng URL không tải / encode lại.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from storage.runtime import load_env

load_env()
PROCESS_DIR = Path(os.getenv("PROCESS_DIR", "data/process"))
if PROCESS_DIR.resolve() == Path("data/verify").resolve():
    raise SystemExit("PROCESS_DIR không được là data/verify (thư mục pilot của benchmark)")
# Các stage của pipeline.verify đọc thư mục làm việc từ VERIFY_DIR: chỉ trỏ vào PROCESS_DIR.
os.environ["VERIFY_DIR"] = str(PROCESS_DIR)

from pipeline.verify import encoder, features, fetch, gate, router, split, vlm  # noqa: E402
from pipeline.verify.common import read_jsonl, row_key, run_dir  # noqa: E402
from processing.model import load as load_model  # noqa: E402

STAGES = [
    ("parse", "Đọc CSV"),
    ("gate", "Gate URL"),
    ("fetch", "Tải ảnh"),
    ("embed", "SigLIP2"),
    ("classify", "Classifier"),
    ("route", "Router"),
    ("vlm", "VLM"),
    ("finalize", "Tổng hợp"),
]
ALIASES = {
    "image_url": ("image_url", "url", "img_url", "image", "anh"),
    "canonical_name": ("canonical_name", "entity_name", "name", "ten", "title"),
    "category": ("category", "leaf_label", "parent_class", "loai"),
    "entity_id": ("entity_id", "entity_slug", "slug"),
    "description": ("description", "desc", "mo_ta"),
    "label": ("verify", "label", "human_label", "flag"),
}
YES = {"yes", "y", "approved", "approve", "1", "true", "pass"}
NO = {"no", "n", "rejected", "reject", "0", "false", "fail"}
REASONS = {
    "R1_invalid": "URL không hợp lệ",
    "R1_blocked": "Host bị chặn",
    "R1_ws": "URL chứa khoảng trắng",
    "R1_noext": "URL không có đuôi ảnh",
    "R6_dup_url": "Trùng URL trong cùng entity",
    "dead": "Không tải / giải mã được ảnh",
    "too_small": "Ảnh nhỏ hơn 300×200",
    "dup_sha256": "Trùng nội dung ảnh trong cùng entity",
    "classifier_yes": "Classifier duyệt (p ≥ ngưỡng)",
    "classifier_no": "Classifier loại (p < ngưỡng)",
    "vlm_dung": "VLM: đúng chủ thể",
    "vlm_partial": "VLM: khác chủ thể, cùng không gian văn hoá",
    "vlm_sai": "VLM: sai chủ thể",
    "vlm_unsafe": "VLM: nội dung không an toàn",
    "vlm_error": "VLM lỗi, giữ quyết định classifier",
}
MAX_ROWS = int(os.getenv("PROCESS_MAX_ROWS", "50000"))
FETCH_WORKERS = int(os.getenv("PROCESS_FETCH_WORKERS", "32"))
VLM_WORKERS = int(os.getenv("PROCESS_VLM_WORKERS", "8"))
ENCODE_CHUNK = 256


class Cancelled(Exception):
    pass


class InvalidCsv(ValueError):
    pass


@dataclass
class Options:
    use_vlm: bool = True
    vlm_budget: float | None = None  # None = ngân sách của model card
    threshold: float | None = None  # None = ngưỡng của model card

    def to_dict(self) -> dict:
        return {"use_vlm": self.use_vlm, "vlm_budget": self.vlm_budget, "threshold": self.threshold}


Progress = Callable[[str, int, int], None]


def vlm_available() -> bool:
    return bool(os.getenv("DEEPSEEK_API_KEY", "").strip())


# ---------------------------------------------------------------- đọc CSV


def _label(value: str) -> str:
    v = (value or "").strip().lower()
    return "yes" if v in YES else "no" if v in NO else ""


def read_csv(data: bytes) -> tuple[list[dict], dict]:
    """CSV (UTF-8, có / không BOM, dấu phẩy hoặc chấm phẩy) -> dòng chuẩn hoá cho pipeline.verify."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InvalidCsv("File phải mã hoá UTF-8") from exc
    head = text[:4096]
    delimiter = ";" if head.count(";") > head.count(",") else ","
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter)
    fields = [f.strip() for f in reader.fieldnames or []]
    lower = {f.lower(): f for f in fields}
    mapping = {k: next((lower[a] for a in names if a in lower), None) for k, names in ALIASES.items()}
    missing = [k for k in ("image_url", "canonical_name") if not mapping[k]]
    if missing:
        raise InvalidCsv(
            "Thiếu cột bắt buộc: "
            + ", ".join(f"{k} (hoặc {'/'.join(ALIASES[k][1:3])})" for k in missing)
            + f". Cột hiện có: {', '.join(fields[:20])}"
        )
    rows = []
    for i, raw in enumerate(reader, start=2):
        raw = {(k or "").strip(): (v or "").strip() for k, v in raw.items() if k is not None}
        name = raw.get(mapping["canonical_name"], "")
        url = raw.get(mapping["image_url"], "")
        if not name and not url:
            continue
        eid = raw.get(mapping["entity_id"] or "", "") or "name:" + hashlib.sha1(
            name.lower().encode()).hexdigest()[:16]
        rows.append({
            "line": i,
            "entity_id": eid,
            "canonical_name": name,
            "category": raw.get(mapping["category"] or "", ""),
            "image_url": url,
            "description": raw.get(mapping["description"] or "", ""),
            "from_db": "0",
            "label": _label(raw.get(mapping["label"] or "", "")),
            "_raw": raw,
        })
        if len(rows) > MAX_ROWS:
            raise InvalidCsv(f"Tối đa {MAX_ROWS:,} dòng mỗi lần xử lý (PROCESS_MAX_ROWS)")
    if not rows:
        raise InvalidCsv("CSV không có dòng dữ liệu")
    info = {
        "rows": len(rows),
        "columns": fields,
        "mapping": {k: v for k, v in mapping.items() if v},
        "entities": len({r["entity_id"] for r in rows}),
        "labelled": sum(bool(r["label"]) for r in rows),
        "delimiter": delimiter,
    }
    return rows, info


# ---------------------------------------------------------------- các stage


def _fetch(live: list[dict], progress: Progress, check: Callable[[], None]) -> dict[str, dict]:
    manifest = run_dir() / "fetch.jsonl"
    state = {r["key"]: r for r in read_jsonl(manifest)} if manifest.exists() else {}

    def usable(rec: dict | None) -> bool:
        if not rec:
            return False
        return rec["status"] == "too_small" or (
            rec["status"] == "ok" and fetch.thumb_path(rec["key"]).exists())

    unique = {}
    for r in live:
        unique.setdefault(row_key(r), r)
    todo = [r for k, r in unique.items() if not usable(state.get(k))]
    total, done = len(unique), len(unique) - len(todo)
    progress("fetch", done, total)
    new: list[dict] = []
    for attempt in (1, 2):
        if not todo:
            break
        if attempt == 2:
            time.sleep(5)
        failed = []
        with ThreadPoolExecutor(FETCH_WORKERS) as pool:
            futures = {pool.submit(fetch._fetch_one, r): r for r in todo}
            try:
                for fut in as_completed(futures):
                    check()
                    rec = fut.result()
                    if rec["status"] == "error" and attempt == 1:
                        failed.append(futures[fut])
                        continue
                    if rec["status"] == "error":
                        rec["status"] = "dead"
                        rec["errors"] = [rec.pop("error")]
                    rec["attempts"] = attempt
                    state[rec["key"]] = rec
                    new.append(rec)
                    done += 1
                    progress("fetch", done, total)
            except Cancelled:
                pool.shutdown(cancel_futures=True)
                raise
        todo = failed
    if new:
        with manifest.open("a", encoding="utf-8") as fh:
            fh.writelines(json.dumps(rec) + "\n" for rec in new)
    return state


def _embed(ok: list[dict], progress: Progress, check: Callable[[], None]) -> tuple[dict, dict]:
    cache_path = run_dir() / "img_emb.npz"
    cache: dict[str, np.ndarray] = {}
    if cache_path.exists():
        with np.load(cache_path) as z:
            if str(z["encoder"]) == encoder.ENCODER:
                cache = dict(zip(z["keys"].tolist(), z["img"], strict=True))
    keys = [row_key(r) for r in ok]
    todo = list(dict.fromkeys(k for k in keys if k not in cache))
    names = list(dict.fromkeys(r["canonical_name"] for r in ok))
    descs = list(dict.fromkeys(r["description"] or r["canonical_name"] for r in ok))
    total = len(todo) + len(names) + len(descs)
    done = 0
    progress("embed", done, total)
    _, _, device, _ = encoder.loaded()  # nạp SigLIP2 (lần đầu) ngoài phần đo tốc độ encode
    started = time.perf_counter()
    for s in range(0, len(todo), ENCODE_CHUNK):
        check()
        part = todo[s : s + ENCODE_CHUNK]
        vecs = encoder.embed_images([fetch.thumb_path(k) for k in part], log=lambda _m: None)
        cache.update(zip(part, vecs.astype(np.float16), strict=True))
        done += len(part)
        progress("embed", done, total)
    image_s = time.perf_counter() - started
    text: dict[str, np.ndarray] = {}
    for group in (names, descs):
        for s in range(0, len(group), ENCODE_CHUNK):
            check()
            part = [t for t in group[s : s + ENCODE_CHUNK] if t not in text]
            if part:
                text.update(zip(part, encoder.embed_texts(part), strict=True))
            done += len(group[s : s + ENCODE_CHUNK])
            progress("embed", done, total)
    if todo:
        all_keys = list(cache)
        np.savez(cache_path, keys=np.array(all_keys), encoder=np.array(encoder.ENCODER),
                 img=np.stack([cache[k] for k in all_keys]))
    emb = {
        "img": np.stack([cache[k] for k in keys]).astype(np.float32),
        "name": np.stack([text[r["canonical_name"]] for r in ok]).astype(np.float32),
        "desc": np.stack([text[r["description"] or r["canonical_name"]] for r in ok]).astype(np.float32),
    }
    return emb, {
        "encoded_images": len(todo),
        "cached_images": len(set(keys)) - len(todo),
        "device": device,
        "image_seconds": round(image_s, 2),
        "images_per_second": round(len(todo) / image_s, 1) if todo and image_s else None,
    }


def _vlm(chosen_rows: list[dict], progress: Progress, check: Callable[[], None]) -> tuple[dict, dict]:
    from retrieval.deepseek import BudgetExhausted
    from storage.runtime import data_dir

    by_entity: dict[str, list[dict]] = defaultdict(list)
    for r in chosen_rows:
        by_entity[r["entity_id"]].append(r)
    batches = [rs[s : s + vlm.BATCH_MAX] for rs in by_entity.values()
               for s in range(0, len(rs), vlm.BATCH_MAX)]
    usage_path = data_dir() / "deepseek_usage.jsonl"
    offset = len(usage_path.read_text("utf-8").splitlines()) if usage_path.exists() else 0
    results: dict[str, dict] = {}
    errors: list[str] = []
    stop = {"reason": None}
    done = 0
    progress("vlm", 0, len(chosen_rows))

    def job(part):
        if stop["reason"]:
            return part, None, "skipped"
        images = [(row_key(r), fetch.thumb_path(row_key(r)).read_bytes()) for r in part]
        t = time.perf_counter()
        try:
            res = vlm.judge_batch(part[0], images)
        except BudgetExhausted as exc:
            stop["reason"] = str(exc)
            return part, None, str(exc)
        except Exception as exc:  # một lô lỗi không làm hỏng cả job
            return part, None, f"{type(exc).__name__}: {str(exc)[:160]}"
        return part, {k: {**v, "batch_ms": round((time.perf_counter() - t) * 1000)}
                      for k, v in res.items()}, None

    started = time.perf_counter()
    with ThreadPoolExecutor(VLM_WORKERS) as pool:
        futures = [pool.submit(job, b) for b in batches]
        try:
            for fut in as_completed(futures):
                check()
                part, res, err = fut.result()
                if err and err != "skipped":
                    errors.append(err)
                if res:
                    results.update(res)
                done += len(part)
                progress("vlm", done, len(chosen_rows))
        except Cancelled:
            pool.shutdown(cancel_futures=True)
            raise
    wall = time.perf_counter() - started
    events = []
    if usage_path.exists():
        events = [json.loads(x) for x in usage_path.read_text("utf-8").splitlines()[offset:] if x]
    events = [e for e in events if str(e.get("tag", "")).startswith("vlm_batch")]
    prompt = sum(e["usage"].get("prompt_tokens", 0) for e in events)
    hit = sum(e["usage"].get("prompt_cache_hit_tokens", 0) for e in events)
    out = sum(e["usage"].get("completion_tokens", 0) for e in events)
    usd = ((prompt - hit) * float(os.getenv("DEEPSEEK_PRICE_INPUT_PER_MTOK", "0.3"))
           + hit * float(os.getenv("DEEPSEEK_PRICE_CACHE_HIT_PER_MTOK", "0.006"))
           + out * float(os.getenv("DEEPSEEK_PRICE_OUTPUT_PER_MTOK", "1.2"))) / 1e6
    lat = sorted(e.get("latency_ms", 0) for e in events)
    return results, {
        "images": len(chosen_rows),
        "judged": len(results),
        "batches": len(batches),
        "requests": len(events),
        "errors": len(errors),
        "error_samples": errors[:3],
        "stopped": stop["reason"],
        "prompt_tokens": prompt,
        "completion_tokens": out,
        "usd": round(usd, 4),
        "seconds": round(wall, 1),
        "images_per_second": round(len(results) / wall, 1) if results and wall else None,
        "latency_ms_p95": lat[int(len(lat) * 0.95)] if lat else None,
    }


# ---------------------------------------------------------------- chấm theo nhãn người


def evaluate(labels: list[str], decisions: list[str], entities: list[str]) -> dict | None:
    """Lớp dương = no. Chỉ trên dòng có nhãn yes/no trong CSV."""
    pairs = [(h, d, e) for h, d, e in zip(labels, decisions, entities, strict=True) if h]
    if not pairs or len({h for h, _, _ in pairs}) < 2:
        return None
    c = Counter((h, d) for h, d, _ in pairs)
    tp, fp, fn, tn = c[("no", "no")], c[("yes", "no")], c[("no", "yes")], c[("yes", "yes")]
    r_no, r_yes = tp / max(1, tp + fn), tn / max(1, tn + fp)
    p_no, p_yes = tp / max(1, tp + fp), tn / max(1, tn + fn)
    good = {e for h, _, e in pairs if h == "yes"}
    kept = {e for h, d, e in pairs if h == "yes" and d == "yes"}
    return {
        "n": len(pairs),
        "accuracy": round((tp + tn) / len(pairs), 4),
        "recall_no": round(r_no, 4),
        "precision_no": round(p_no, 4),
        "f1_no": round(2 * p_no * r_no / max(1e-9, p_no + r_no), 4),
        "precision_yes": round(p_yes, 4),
        "recall_yes": round(r_yes, 4),
        "balanced_accuracy": round((r_no + r_yes) / 2, 4),
        "entity_retention": round(len(kept) / max(1, len(good)), 4),
        "confusion": {"no→no": tp, "yes→no": fp, "no→yes": fn, "yes→yes": tn},
    }


# ---------------------------------------------------------------- chạy cả luồng


def run(rows: list[dict], options: Options, out_dir: Path, progress: Progress,
        check: Callable[[], None]) -> dict:
    model = load_model()
    timings: dict[str, float] = {}

    def timed(stage: str):
        class _T:
            def __enter__(self):
                self.t = time.perf_counter()

            def __exit__(self, *exc):
                timings[stage] = round(time.perf_counter() - self.t, 3)

        return _T()

    progress("parse", len(rows), len(rows))
    with timed("gate"):
        live, gate_report = gate.run(rows, noext_policy="download")
        rejected = {r["line"]: r["gate"] for r in gate_report["rejected"]}
        progress("gate", len(rows), len(rows))
    check()
    with timed("fetch"):
        state = _fetch(live, progress, check)
    # Trùng nội dung trong cùng entity: giữ ảnh đầu (như fetch.mark_sha_duplicates).
    seen: set[tuple[str, str]] = set()
    rule_of: dict[int, str] = dict(rejected)
    ok: list[dict] = []
    for r in live:
        rec = state.get(row_key(r), {})
        status = rec.get("status", "dead")
        if status == "ok":
            sig = (r["entity_id"], rec["sha256"])
            status = "dup_sha256" if sig in seen else "ok"
            seen.add(sig)
        if status == "ok":
            ok.append(r)
        else:
            rule_of[r["line"]] = status if status in REASONS else "dead"

    t = options.threshold if options.threshold is not None else model.threshold
    budget = model.alpha if options.vlm_budget is None else options.vlm_budget
    use_vlm = options.use_vlm and budget > 0 and vlm_available()
    p = np.zeros(0)
    chosen: set[int] = set()
    vlm_results: dict[str, dict] = {}
    embed_info: dict = {}
    vlm_info: dict = {"skipped": "tắt" if not options.use_vlm or budget <= 0
                      else "thiếu DEEPSEEK_API_KEY" if not vlm_available() else None}
    if ok:
        with timed("embed"):
            emb, embed_info = _embed(ok, progress, check)
        with timed("classify"):
            group_of = split.split(rows)["group_of_url"]  # như benchmark: nhóm tên trên mọi dòng
            groups = [group_of[r["image_url"]] for r in ok]
            X, _ = features.build(ok, [state[row_key(r)] for r in ok], emb, groups, model.priors)
            p = model.predict(X.astype(np.float32))
            progress("classify", len(ok), len(ok))
        with timed("route"):
            pred = np.where(p >= t, "yes", "no")
            if use_vlm:
                conf = 0.5 + 0.5 * np.abs(p - t) / max(t, 1 - t)
                chosen, route_report = router.select(groups, list(pred), conf, [False] * len(ok), budget)
            else:
                route_report = {"alpha": 0.0, "chosen": 0}
            progress("route", len(ok), len(ok))
        check()
        if chosen:
            with timed("vlm"):
                vlm_results, vlm_info = _vlm([ok[j] for j in sorted(chosen)], progress, check)
        else:
            progress("vlm", 0, 0)
    else:
        route_report = {"alpha": 0.0, "chosen": 0}
        for s in ("embed", "classify", "route", "vlm"):
            progress(s, 0, 0)

    with timed("finalize"):
        pos = {r["line"]: j for j, r in enumerate(ok)}
        records = []
        for r in rows:
            rec = state.get(row_key(r), {})
            j = pos.get(r["line"])
            item = {
                "line": r["line"], "key": row_key(r), "entity_id": r["entity_id"],
                "entity_name": r["canonical_name"], "category": r["category"],
                "image_url": r["image_url"], "label": r["label"],
                "width": rec.get("w"), "height": rec.get("h"), "fetch_ms": rec.get("ms"),
                "p_yes": None, "routed": False, "vlm": None,
            }
            if j is None:
                code = rule_of.get(r["line"], "dead")
                item.update(decision="no", stage="rule", reason=code)
            else:
                item["p_yes"] = round(float(p[j]), 4)
                cls = "yes" if p[j] >= t else "no"
                item.update(decision=cls, stage="classifier", reason=f"classifier_{cls}")
                if j in chosen:
                    item["routed"] = True
                    v = vlm_results.get(item["key"])
                    if v is None:
                        item["reason"] = "vlm_error"
                    else:
                        lab = vlm_label(v, model.vlm_rule)
                        item.update(decision=lab, stage="vlm",
                                    reason="vlm_unsafe" if v["unsafe"] else f"vlm_{v['subject']}",
                                    vlm={k: v.get(k) for k in ("subject", "watermark", "unsafe",
                                                               "evidence", "batch_ms")})
            item["reason_text"] = REASONS.get(item["reason"], item["reason"])
            records.append(item)
        write_results(out_dir, rows, records)
        summary = summarize(rows, records, timings, embed_info, vlm_info, route_report,
                            {"threshold": t, "budget": budget if use_vlm else 0.0,
                             "use_vlm": use_vlm, "vlm_rule": model.vlm_rule}, model)
        progress("finalize", 1, 1)
    summary["timings"] = timings
    return summary


def vlm_label(v: dict, rule: str) -> str:
    if v["unsafe"]:
        return "no"
    if rule == "bo_watermark":
        return "yes" if v["subject"] == "dung" else "no"
    if rule == "partial_yes":
        return "yes" if v["subject"] in ("dung", "partial") and not v["watermark"] else "no"
    if rule == "chi_sai":
        return "no" if v["subject"] == "sai" else "yes"
    return v["label"]  # goc: đúng chủ thể và không watermark


OUT_COLUMNS = ["decision", "stage", "reason", "reason_text", "p_yes", "routed", "width", "height",
               "vlm_subject", "vlm_watermark", "vlm_evidence"]


def write_results(out_dir: Path, rows: list[dict], records: list[dict]) -> None:
    with (out_dir / "results.jsonl").open("w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(x, ensure_ascii=False) + "\n" for x in records)
    raw_cols = list(dict.fromkeys(k for r in rows for k in r["_raw"]))
    with (out_dir / "results.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(raw_cols + [c for c in OUT_COLUMNS if c not in raw_cols])
        for r, x in zip(rows, records, strict=True):
            v = x["vlm"] or {}
            extra = {**x, "vlm_subject": v.get("subject", ""), "vlm_watermark": v.get("watermark", ""),
                     "vlm_evidence": v.get("evidence", ""), "routed": int(x["routed"])}
            w.writerow([r["_raw"].get(c, "") for c in raw_cols]
                       + ["" if extra.get(c) is None else extra[c] for c in OUT_COLUMNS
                          if c not in raw_cols])


def summarize(rows, records, timings, embed_info, vlm_info, route_report, decision, model) -> dict:
    n = len(records)
    approved = sum(x["decision"] == "yes" for x in records)
    entities = {x["entity_id"] for x in records}
    kept = {x["entity_id"] for x in records if x["decision"] == "yes"}
    fetched = sum(1 for x in records if x["fetch_ms"] is not None)
    fetch_s = timings.get("fetch", 0)
    total_s = sum(timings.values())
    usd = (vlm_info or {}).get("usd", 0) or 0
    return {
        "rows": n,
        "approved": approved,
        "rejected": n - approved,
        "approved_share": round(approved / max(1, n), 4),
        "entities": len(entities),
        "entities_with_approved": len(kept),
        "by_stage": dict(Counter(x["stage"] for x in records)),
        "by_reason": dict(Counter(x["reason"] for x in records).most_common()),
        "routed": sum(x["routed"] for x in records),
        "decision": decision,
        "router": {k: v for k, v in route_report.items() if isinstance(v, (int, float, str))},
        "embedding": embed_info,
        "vlm": vlm_info,
        "cost_usd": round(usd, 4),
        "cost_usd_per_1000": round(usd / max(1, n) * 1000, 4),
        "throughput": {
            "rows_per_second": round(n / total_s, 2) if total_s else None,
            "fetch_images_per_second": round(fetched / fetch_s, 2) if fetch_s and fetched else None,
        },
        "metrics": evaluate([x["label"] for x in records], [x["decision"] for x in records],
                            [x["entity_id"] for x in records]),
        "model": model.summary(),
    }
