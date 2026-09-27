#!/usr/bin/env python3
import json, os, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = "https://export.arxiv.org/api/query"
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CATEGORIES = ["hep-ph","hep-ex","hep-th","nucl-th","astro-ph.HE","astro-ph.CO","physics.ins-det"]
NS = {"a": "http://www.w3.org/2005/Atom"}
PAGE_SIZE = 200
REQUEST_DELAY = 3.0

def load(path, default):
    if not path.exists(): return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default

def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=2) + "\n")
    tmp.replace(path)

def request(q, start=0):
    params = urllib.parse.urlencode({
        "search_query": q, "start": start, "max_results": PAGE_SIZE,
        "sortBy": "submittedDate", "sortOrder": "ascending"
    })
    req = urllib.request.Request(
        f"{API}?{params}",
        headers={"User-Agent": "JKrishnamoorthi.github.io arXiv statistics bot"}
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception:
            if attempt == 4: raise
            time.sleep(5 * (attempt + 1))

def count(q):
    total, start = 0, 0
    while True:
        root = ET.fromstring(request(q, start))
        entries = root.findall("a:entry", NS)
        n = root.find("a:totalResults", NS)
        known = int(n.text or 0) if n is not None else None
        total += len(entries)
        if not entries or (known is not None and start + len(entries) >= known):
            return total
        start += len(entries)
        time.sleep(REQUEST_DELAY)

def day_query(day, cat=None):
    start = f"{day}T00:00:00Z"
    end = (datetime.fromisoformat(day).replace(tzinfo=timezone.utc) + timedelta(days=1))
    q = f"submittedDate:[{start} TO {end.strftime('%Y-%m-%dT00:00:00Z')}]"
    return q + (f" AND cat:{cat}" if cat else "")

def main():
    day = os.getenv("ARXIV_STATS_DATE") or (
        datetime.now(timezone.utc) - timedelta(days=1)
    ).date().isoformat()

    path = DATA / "daily.json"
    rows = load(path, [])
    existing = {r["date"]: r for r in rows if "date" in r}
    row = existing.get(day, {"date": day})

    print("Counting total:", day)
    row["total"] = count(day_query(day))
    for cat in CATEGORIES:
        print("Counting:", cat)
        row[cat] = count(day_query(day, cat))

    existing[day] = row
    save(path, [existing[d] for d in sorted(existing)])
    save(DATA/"metadata.json", {
        "description": "Daily arXiv submission counts by selected category.",
        "counting_basis": "v1 submission timestamp, UTC",
        "categories": CATEGORIES,
        "updated_for_date": day,
        "updated_at_utc": datetime.now(timezone.utc).isoformat()
    })
    print(json.dumps(row, indent=2))

if __name__ == "__main__":
    try: main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise
