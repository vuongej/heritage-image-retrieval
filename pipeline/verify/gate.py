"""S0 — deterministic gate (skill_01). Costs nothing; runs before any download or API call.

Rules, first match wins: R1_invalid, R1_blocked, R1_ws, R1_noext. R4 (pHash) and R5
(aspect penalty) are intentionally gone: pHash did not separate entities and aspect is
passed to the decision layer as a feature instead.
"""

from __future__ import annotations

import re
from collections import Counter

from pipeline.verify.common import norm

BLOCK = ("lookaside.fbsbx.com", "scontent.xx.fbcdn.net/login")
EXT = re.compile(r"\.(jpe?g|png|webp|gif|avif)(\?|$)", re.I)
VALID = re.compile(r"^https?://[^/\s]+")


def gate(url: str, noext_policy: str = "reject") -> str | None:
    u = url or ""
    if not VALID.match(u):
        return "R1_invalid"
    if any(b in u for b in BLOCK):
        return "R1_blocked"
    if any(c.isspace() for c in u):
        return "R1_ws"
    if not EXT.search(u) and noext_policy == "reject":
        return "R1_noext"
    return None


def run(rows: list[dict], noext_policy: str = "reject") -> tuple[list[dict], dict]:
    """Return live rows (deduped per entity) and the gate report."""
    reasons: Counter = Counter()
    live: list[dict] = []
    rejected: list[dict] = []
    seen: set[tuple[str, str]] = set()
    noext_live = 0
    for row in rows:
        url = row["image_url"]
        code = gate(url, noext_policy)
        if code is None:
            key = (row["entity_id"], url.strip())
            if key in seen:
                code = "R6_dup_url"
            else:
                seen.add(key)
        if code:
            reasons[code] += 1
            rejected.append({"line": row["line"], "image_url": url, "gate": code})
            continue
        if not EXT.search(url):
            noext_live += 1
        live.append(row)
    groups = {norm(r["canonical_name"]) for r in live}
    report = {
        "source_rows": len(rows),
        "live_rows": len(live),
        "rejected_rows": len(rows) - len(live),
        "rejected_share": round((len(rows) - len(live)) / max(1, len(rows)), 4),
        "by_rule": dict(reasons.most_common()),
        "noext_policy": noext_policy,
        "noext_kept_for_download": noext_live,
        "entities": len({r["entity_id"] for r in live}),
        "name_groups": len(groups),
        "rejected": rejected,
    }
    return live, report
