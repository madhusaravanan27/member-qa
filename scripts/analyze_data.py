import os, re, asyncio, httpx

BASE = os.getenv("MESSAGES_API_BASE", "https://november7-730026606190.europe-west1.run.app")

async def fetch(skip=0, limit=100):
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{BASE}/messages", params={"skip": skip, "limit": limit})
        r.raise_for_status()
        return r.json()

async def main():
    skip, limit = 0, 100
    users = {}
    inconsistencies = []
    seen_ids = set()
    for _ in range(50):  # safety cap ~5k
        page = await fetch(skip, limit)
        items = page.get("items", [])
        if not items:
            break
        for m in items:
            mid = m.get("id")
            if mid in seen_ids:
                inconsistencies.append({"issue": "duplicate message id", "id": mid})
            else:
                seen_ids.add(mid)

            name = (m.get("user_name") or "").strip().lower()
            msg  = m.get("message") or ""
            users.setdefault(name, {"cars": set(), "dates": 0, "empty": 0})

            for x in re.findall(r"(?i)(\d+)\s+cars?", msg):
                try: users[name]["cars"].add(int(x))
                except: pass

            if re.search(r"(?i)\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2}\b", msg):
                users[name]["dates"] += 1

            if not msg.strip():
                users[name]["empty"] += 1

        if len(items) < limit:
            break
        skip += limit

    print("Potential issues:")
    for n, agg in users.items():
        display = n or "<missing user_name>"
        if len(agg["cars"]) > 1:
            print(f" - {display}: conflicting car counts {sorted(agg['cars'])}")
        if agg["empty"] > 0:
            print(f" - {display}: {agg['empty']} empty messages")
    for inc in inconsistencies[:20]:
        print(" -", inc)

if __name__ == "__main__":
    asyncio.run(main())
