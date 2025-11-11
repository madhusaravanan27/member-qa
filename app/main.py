from __future__ import annotations
import os, re, logging
from typing import Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# -------------------
# Configuration & logging
# -------------------
logger = logging.getLogger("member-qa")
logging.basicConfig(level=logging.INFO)

APP_NAME = "member-qa"

# Env vars (safe defaults for local dev)
# Use HTTP base you successfully curl’d; code adds /messages/ and follows redirects.
MESSAGES_API_BASE = os.getenv("MESSAGES_API_BASE", "http://november7-730026606190.europe-west1.run.app")
TIMEOUT     = float(os.getenv("MESSAGES_API_TIMEOUT", "25"))   # generous while debugging
PAGE_LIMIT  = int(os.getenv("MESSAGES_API_LIMIT",   "50"))     # smaller pages return faster
MAX_PAGES   = int(os.getenv("MESSAGES_API_MAX_PAGES","20"))    # cap pages during dev; raise later

app = FastAPI(title=APP_NAME)

# -------------------
# I/O models
# -------------------
class AskRequest(BaseModel):
    question: str

class AskResponse(BaseModel):
    answer: str

# -------------------
# Robust upstream client
#  - trailing slash
#  - follow redirects
#  - try multiple header profiles (some gateways are picky)
#  - flip scheme http<->https on 400/401
# -------------------
def _flip_scheme(base: str) -> str:
    base = base.rstrip("/")
    if base.startswith("https://"):
        return "http://" + base[len("https://"):]
    if base.startswith("http://"):
        return "https://" + base[len("http://"):]
    return "https://" + base  # default to https if none

async def fetch_messages_page(skip: int = 0, limit: int = PAGE_LIMIT) -> Dict:
    bases = [MESSAGES_API_BASE.rstrip("/"), _flip_scheme(MESSAGES_API_BASE)]
    header_sets = [
        {},  # bare
        {"Accept": "application/json"},
        {
            "Accept": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        },
    ]

    last_exc: Optional[Exception] = None
    for base in bases:
        url = f"{base.rstrip('/')}/messages/"
        for hdr in header_sets:
            try:
                async with httpx.AsyncClient(
                    timeout=TIMEOUT,
                    follow_redirects=True,
                    trust_env=True,   # respect system proxy/VPN env if present
                    headers=hdr
                ) as client:
                    r = await client.get(url, params={"skip": int(skip), "limit": int(limit)})
                    if r.status_code >= 400:
                        snippet = r.text[:200]
                        logger.warning(
                            "Upstream %s for %s?skip=%s&limit=%s ; hdr=%s ; body=%s",
                            r.status_code, url, skip, limit, list(hdr.keys()), snippet
                        )
                        # On 400/401 try next header profile / scheme; else raise.
                        if r.status_code in (400, 401):
                            continue
                        r.raise_for_status()
                    return r.json()
            except Exception as e:
                last_exc = e
                logger.warning("Request error to %s with hdr=%s: %s", url, list(hdr.keys()), e)

    if isinstance(last_exc, httpx.HTTPError):
        raise last_exc
    raise httpx.RequestError(f"All attempts to fetch {MESSAGES_API_BASE}/messages/ failed", request=None)

async def fetch_all_messages(max_pages: int = MAX_PAGES) -> List[Dict]:
    items: List[Dict] = []
    skip = 0
    for _ in range(max_pages):
        page = await fetch_messages_page(skip=skip, limit=PAGE_LIMIT)
        batch = page.get("items", []) or []
        if not batch:
            break
        items.extend(batch)
        if len(batch) < PAGE_LIMIT:
            break
        skip += PAGE_LIMIT
    logger.info("Fetched %d messages (pages=%d, page_size=%d)", len(items), (skip // PAGE_LIMIT) + 1, PAGE_LIMIT)
    return items

# -------------------
# Intent detection (regex)
# -------------------
# Tightened city capture: capitalized words to end, optional trailing '?'
TRIP_Q_RE = re.compile(
    r"(?i)when\s+is\s+(.+?)\s+planning\s+(?:her|his|their)?\s*trip\s+to\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)\s*\??\s*$"
)
CARS_Q_RE = re.compile(r"(?i)how\s+many\s+cars\s+does\s+(.+?)\s+have\??")
FAV_Q_RE  = re.compile(r"(?i)what\s+are\s+(.+?)['’]s\s+favorite\s+restaurants\??")

NAME_NORM = lambda s: re.sub(r"\s+", " ", (s or "").strip().lower())
DATE_WORDS = r"(?:on|around|in|by|this|next|coming|on the)"

TRIP_PATTERNS = [
    re.compile(
        rf"(?i)\b(trip|travel|fly|flight|going)\b.*\bto\b\s*(?P<city>[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)[^\n]*\b{DATE_WORDS}\b\s*(?P<when>[A-Za-z0-9 ,./-]+)"
    ),
    re.compile(
        r"(?i)\bto\s+(?P<city>[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)\b[^\n]*\b(on|around|in|by)\b\s*(?P<when>[A-Za-z0-9 ,./-]+)"
    ),
    # extra leniency for phrasing like "headed to London next Friday"
    re.compile(
        rf"(?i)\b(?:to|headed to|off to)\s+(?P<city>[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)\b.*?\b{DATE_WORDS}\b\s*(?P<when>[A-Za-z0-9 ,./-]+)"
    ),
]

CARS_PATTERNS = [
    re.compile(r"(?i)\b(?P<count>\d+)\s+cars?\b"),
    re.compile(r"(?i)\b(has|own(?:s)?)\b[^\n]*\b(?P<count>\d+)\s+cars?\b"),
]

FAV_PATTERNS = [
    re.compile(r"(?i)favorite\s+restaurants?\s*:?\s*(?P<list>.+)$"),
    re.compile(
        r"(?i)\b(love|loves|like|likes)\s+(?P<list>(?:[A-Z][\w'&]+(?:\s+[A-Z][\w'&]+)*)(?:\s*,\s*(?:and\s+)?[A-Z][\w'&]+(?:\s+[A-Z][\w'&]+)*)*)"
    ),
]

# -------------------
# Extraction helpers
# -------------------
def normalize_city(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()

def messages_for_user(all_msgs: List[Dict], name_query: str) -> List[str]:
    target = NAME_NORM(name_query)
    out: List[str] = []
    for m in all_msgs:
        uname = m.get("user_name") or ""
        if target in NAME_NORM(uname):
            msg = m.get("message") or ""
            if msg.strip():
                out.append(msg)
    return out

def extract_trip_when_to_city(texts: List[str], city: str) -> Optional[str]:
    city_norm = normalize_city(city)
    for t in texts:
        for pat in TRIP_PATTERNS:
            m = pat.search(t)
            if not m:
                continue
            det_city = (m.groupdict().get("city") or "").strip()
            when = (m.groupdict().get("when") or "").strip()
            if det_city and normalize_city(det_city) != city_norm:
                continue
            if when:
                return when
    return None

def extract_car_count(texts: List[str]) -> Optional[str]:
    best = None
    for t in texts:
        for pat in CARS_PATTERNS:
            m = pat.search(t)
            if m:
                try:
                    c = int(m.group("count"))
                    best = c if best is None or c > best else best
                except Exception:
                    pass
    return str(best) if best is not None else None

def extract_favorite_restaurants(texts: List[str]) -> Optional[str]:
    for t in texts:
        for pat in FAV_PATTERNS:
            m = pat.search(t)
            if m:
                raw = m.group("list")
                items = re.split(r"\s*,\s*|\s+and\s+", raw)
                items = [i.strip().strip(". ") for i in items if i.strip()]
                seen, ordered = set(), []
                for i in items:
                    k = i.lower()
                    if k not in seen:
                        seen.add(k)
                        ordered.append(i)
                return ", ".join(ordered)
    return None

# -------------------
# API endpoints
# -------------------
@app.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    q = (req.question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Question must not be empty")

    # Fetch messages with robust fallbacks; surface upstream issues in the response
    try:
        all_msgs = await fetch_all_messages()
    except httpx.HTTPStatusError as e:
        body = ""
        try:
            body = e.response.text[:300]
        except Exception:
            pass
        code = e.response.status_code if e.response is not None else "unknown"
        return AskResponse(answer=f"Upstream API error ({code}): {body or 'no details'}")
    except httpx.RequestError as e:
        return AskResponse(answer=f"Upstream API request failed (network/timeout): {e}")
    except Exception as e:
        logger.exception("Unexpected error fetching messages: %s", e)
        return AskResponse(answer="Unexpected error fetching messages. Please try again.")

    # Intent 1: Trip timing to a city
    m = TRIP_Q_RE.search(q)
    if m:
        name = m.group(1).strip().rstrip("?.!,")
        city = m.group(2).strip().rstrip("?.!,")
        logger.info("Parsed trip intent → name=%r city=%r", name, city)
        texts = messages_for_user(all_msgs, name)
        if not texts:
            return AskResponse(answer=f"I couldn't find any messages for {name}.")
        when = extract_trip_when_to_city(texts, city)
        return AskResponse(answer= when or f"No trip to {city} found for {name}.")

    # Intent 2: Car count
    m = CARS_Q_RE.search(q)
    if m:
        name = m.group(1).strip().rstrip("?.!,")
        texts = messages_for_user(all_msgs, name)
        if not texts:
            return AskResponse(answer=f"I couldn't find any messages for {name}.")
        count = extract_car_count(texts)
        return AskResponse(answer= count or f"I couldn't infer car ownership for {name}.")

    # Intent 3: Favorite restaurants
    m = FAV_Q_RE.search(q)
    if m:
        name = m.group(1).strip().rstrip("?.!,")
        texts = messages_for_user(all_msgs, name)
        if not texts:
            return AskResponse(answer=f"I couldn't find any messages for {name}.")
        favs = extract_favorite_restaurants(texts)
        return AskResponse(answer= favs or f"No favorite restaurants found for {name}.")

    # Fallback
    return AskResponse(answer="I couldn't understand the question. Ask about trips to a city, car counts, or favorite restaurants.")

@app.get("/")
async def root():
    return {"service": APP_NAME, "endpoints": ["/ask"], "status": "ok"}
