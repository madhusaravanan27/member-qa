# scripts/analyze_data.py
from __future__ import annotations

import os
import logging
from typing import Dict, List, Any
from collections import Counter
from datetime import datetime

import httpx


logger = logging.getLogger("analyze-data")
logging.basicConfig(level=logging.INFO)

# Same config as main.py
MESSAGES_API_BASE = os.getenv(
    "MESSAGES_API_BASE",
    "https://november7-730026606190.europe-west1.run.app",
)
TIMEOUT = float(os.getenv("MESSAGES_API_TIMEOUT", "25"))
PAGE_LIMIT = int(os.getenv("MESSAGES_API_LIMIT", "50"))
MAX_PAGES = int(os.getenv("MESSAGES_API_MAX_PAGES", "20"))

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "member-qa-analyze/1.0",
}


async def fetch_messages_page(skip: int = 0, limit: int = PAGE_LIMIT) -> Dict:
    """
    Fetch one page from the upstream /messages endpoint.

    Mirrors the logic from app.main: defensive about base URL and handles
    both .../messages and bare host.
    """
    base = MESSAGES_API_BASE.rstrip("/")
    if base.endswith("/messages"):
        url = base
    else:
        url = f"{base}/messages"

    async with httpx.AsyncClient(
        timeout=TIMEOUT,
        follow_redirects=True,
        headers=HEADERS,
    ) as client:
        r = await client.get(url, params={"skip": int(skip), "limit": int(limit)})
        if r.status_code >= 400:
            logger.error(
                "Upstream error %s for %s?skip=%s&limit=%s ; body=%s",
                r.status_code,
                url,
                skip,
                limit,
                r.text[:300],
            )
        r.raise_for_status()
        return r.json()


async def fetch_all_messages(max_pages: int = MAX_PAGES) -> List[Dict]:
    """
    Fetch multiple pages, but stop gracefully on 400/401/404/405 instead of blowing up.
    This way, we still use whatever data we got from earlier pages.
    """
    items: List[Dict] = []
    skip = 0

    for page_idx in range(max_pages):
        try:
            page = await fetch_messages_page(skip=skip, limit=PAGE_LIMIT)
        except httpx.HTTPStatusError as e:
            code = e.response.status_code if e.response is not None else None
            if code in (400, 401, 404, 405):
                logger.warning(
                    "Stopping pagination at skip=%s due to upstream %s",
                    skip,
                    code,
                )
                break
            raise

        batch = page.get("items", []) or []
        if not batch:
            break

        items.extend(batch)

        if len(batch) < PAGE_LIMIT:
            break

        skip += PAGE_LIMIT

    logger.info(
        "Fetched %d messages (pages=%d, page_size=%d)",
        len(items),
        (skip // PAGE_LIMIT) + 1 if items else 0,
        PAGE_LIMIT,
    )
    return items


def compute_dataset_insights(msgs: List[Dict]) -> Dict[str, Any]:
    """
    Lightweight anomaly / quality analysis over the messages dataset.
    This is *offline* tooling used for README / debugging, not part of the API.
    """
    total = len(msgs)

    missing_user = sum(1 for m in msgs if not (m.get("user_name") or "").strip())
    missing_text = sum(1 for m in msgs if not (m.get("message") or "").strip())
    missing_id = sum(1 for m in msgs if not m.get("id"))

    ids = [m.get("id") for m in msgs if m.get("id") is not None]
    dup_ids = len(ids) - len(set(ids))

    # Message length distribution
    lengths = [len((m.get("message") or "")) for m in msgs]
    very_short = sum(1 for L in lengths if L <= 5)
    ultra_short = sum(1 for L in lengths if 0 < L <= 20)
    very_long = sum(1 for L in lengths if L >= 500)

    # Users
    users = [m.get("user_name") or "" for m in msgs]
    user_counts = Counter(u for u in users if u.strip())
    top_users = user_counts.most_common(5)

    # Timestamp sanity check
    bad_ts = 0
    min_ts = None
    max_ts = None
    for m in msgs:
        ts = m.get("timestamp")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            bad_ts += 1
            continue
        if min_ts is None or dt < min_ts:
            min_ts = dt
        if max_ts is None or dt > max_ts:
            max_ts = dt

    return {
        "total_messages": total,
        "missing_user_name": missing_user,
        "missing_message_text": missing_text,
        "missing_id": missing_id,
        "duplicate_ids": dup_ids,
        "very_short_messages_<=5_chars": very_short,
        "ultra_short_messages_<=20_chars": ultra_short,
        "very_long_messages_>=500_chars": very_long,
        "top_users_by_message_count": top_users,
        "bad_timestamps": bad_ts,
        "min_timestamp": min_ts.isoformat() if min_ts else None,
        "max_timestamp": max_ts.isoformat() if max_ts else None,
    }


def format_insights_for_readme(ins: Dict[str, Any]) -> str:
    """
    Turn raw stats into a human-readable summary you can paste into README.
    """
    total = ins["total_messages"] or 0
    if total == 0:
        return "No messages were retrieved from the upstream API."

    def pct(x: int) -> str:
        return f"{(x / total) * 100:.1f}%" if total else "0.0%"

    missing_user = ins["missing_user_name"]
    missing_text = ins["missing_message_text"]
    missing_id = ins["missing_id"]
    dup_ids = ins["duplicate_ids"]
    very_short = ins["very_short_messages_<=5_chars"]
    ultra_short = ins["ultra_short_messages_<=20_chars"]
    very_long = ins["very_long_messages_>=500_chars"]
    bad_ts = ins["bad_timestamps"]
    min_ts = ins["min_timestamp"]
    max_ts = ins["max_timestamp"]
    top_users = ins["top_users_by_message_count"]

    lines = []
    lines.append("**Data quality & anomalies**")
    lines.append(
        f"- Total messages fetched: **{total}**"
    )
    lines.append(
        f"- Missing `user_name`: **{missing_user}** ({pct(missing_user)})"
    )
    lines.append(
        f"- Missing/empty `message` text: **{missing_text}** ({pct(missing_text)})"
    )
    lines.append(
        f"- Missing `id`: **{missing_id}** ({pct(missing_id)})"
    )
    lines.append(
        f"- Duplicate IDs: **{dup_ids}**"
    )
    lines.append(
        f"- Very short messages (≤ 5 chars): **{very_short}** ({pct(very_short)})"
    )
    lines.append(
        f"- Ultra-short messages (1–20 chars): **{ultra_short}** ({pct(ultra_short)})"
    )
    lines.append(
        f"- Very long messages (≥ 500 chars): **{very_long}** ({pct(very_long)})"
    )

    if min_ts or max_ts:
        lines.append(
            f"- Timestamp range (valid ISO): **{min_ts}** → **{max_ts}**, "
            f"with **{bad_ts}** malformed timestamps"
        )
    else:
        lines.append(
            f"- Timestamps: could not parse any valid timestamps, "
            f"{bad_ts} entries failed parsing."
        )

    if top_users:
        top_str = ", ".join(
            f"{name or 'Unknown'} ({count})" for name, count in top_users
        )
        lines.append(f"- Top active users by message count: {top_str}")

    lines.append(
        "\nThese findings influenced the design of the QA service: "
        "empty or malformed messages are skipped when building the embedding index, "
        "extremely short commands are down-weighted, and user names are treated as "
        "soft hints rather than strict keys to avoid brittle matching."
    )

    return "\n".join(lines)


async def main() -> None:
    msgs = await fetch_all_messages()
    if not msgs:
        print("No messages fetched; cannot compute insights.")
        return

    ins = compute_dataset_insights(msgs)

    print("========== RAW INSIGHTS ==========")
    for k, v in ins.items():
        print(f"{k}: {v}")

    print("\n========== README SNIPPET ==========\n")
    print(format_insights_for_readme(ins))


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
