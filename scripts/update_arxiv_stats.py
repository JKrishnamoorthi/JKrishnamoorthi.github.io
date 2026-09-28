#!/usr/bin/env python3
"""
Daily arXiv submission counts for selected categories.

Request handling follows the version that ran successfully on GitHub
Actions (bot commit 1e2086f): one honest User-Agent, plain paging over
the date query, and a LONG exponential backoff, because arXiv's edge
answers 406/403/429/503 to CI egress IPs as a throttle signal. Short
retries (a few seconds) never outlast it.
"""

import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path


API = "https://export.arxiv.org/api/query"

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DAILY_FILE = DATA / "daily.json"
METADATA_FILE = DATA / "metadata.json"

CATEGORIES = [
    "hep-ph",
    "hep-ex",
    "hep-th",
    "nucl-th",
    "astro-ph.HE",
    "astro-ph.CO",
    "physics.ins-det",
]

NS = {"a": "http://www.w3.org/2005/Atom"}

PAGE_SIZE = 100
REQUEST_DELAY = 3.0          # polite delay between pages / days

MAX_ATTEMPTS = 8
BACKOFF_CAP = 300            # seconds
THROTTLE_CODES = (403, 406, 429, 503)

HEADERS = {
    "User-Agent": (
        "JKrishnamoorthi-arxiv-dashboard/1.0 "
        "(https://jkrishnamoorthi.github.io/)"
    ),
    "Accept": "application/atom+xml",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}


# ---------------------------------------------------------------- dates

def utc_today():
    return datetime.now(timezone.utc).date()


def parse_day(value):
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()


def get_requested_dates():
    """
    ARXIV_STATS_DATE=2026-09-24                       single day
    ARXIV_STATS_START=... and ARXIV_STATS_END=...     inclusive range
    nothing set                                       yesterday (UTC)
    """
    single = os.environ.get("ARXIV_STATS_DATE", "").strip()
    start = os.environ.get("ARXIV_STATS_START", "").strip()
    end = os.environ.get("ARXIV_STATS_END", "").strip()

    if single:
        if start or end:
            raise ValueError(
                "Use either ARXIV_STATS_DATE or START/END, not both."
            )
        return [parse_day(single)]

    if start or end:
        if not (start and end):
            raise ValueError("Both ARXIV_STATS_START and ARXIV_STATS_END needed.")
        first, last = parse_day(start), parse_day(end)
        if first > last:
            raise ValueError(f"START ({first}) is after END ({last}).")
        days = []
        current = first
        while current <= last:
            days.append(current)
            current += timedelta(days=1)
        return days

    return [utc_today() - timedelta(days=1)]


def make_query(day):
    """submittedDate:[YYYYMMDDHHMM TO YYYYMMDDHHMM] (UTC, one day)."""
    begin = datetime(day.year, day.month, day.day)
    finish = begin + timedelta(days=1)
    return (
        f"submittedDate:[{begin.strftime('%Y%m%d%H%M')} "
        f"TO {finish.strftime('%Y%m%d%H%M')}]"
    )


# -------------------------------------------------------------- network

def decode_body(raw, encoding):
    enc = (encoding or "").lower()
    if enc == "gzip":
        return gzip.decompress(raw)
    if enc == "deflate":
        try:
            return zlib.decompress(raw)
        except zlib.error:
            return zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw


def request_arxiv(query, start=0):
    params = urllib.parse.urlencode({
        "search_query": query,
        "start": start,
        "max_results": PAGE_SIZE,
        "sortBy": "submittedDate",
        "sortOrder": "ascending",
    })
    request = urllib.request.Request(
        f"{API}?{params}", headers=HEADERS, method="GET"
    )

    for attempt in range(MAX_ATTEMPTS):
        last = attempt == MAX_ATTEMPTS - 1
        print(
            f"  Requesting start={start} "
            f"(attempt {attempt + 1}/{MAX_ATTEMPTS})"
        )

        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                raw = response.read()
                return decode_body(
                    raw, response.headers.get("Content-Encoding")
                )

        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                body = ""

            print(
                f"  HTTP {exc.code} {exc.reason} "
                f"(attempt {attempt + 1}/{MAX_ATTEMPTS})",
                file=sys.stderr,
            )
            if body:
                print(f"  Response body (truncated): {body}", file=sys.stderr)

            if last:
                raise

            if exc.code in THROTTLE_CODES:
                delay = min(20 * (2 ** attempt), BACKOFF_CAP)  # 20,40,80,...
            else:
                delay = 10 * (attempt + 1)

        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(
                f"  Network error (attempt {attempt + 1}/{MAX_ATTEMPTS}): {exc}",
                file=sys.stderr,
            )
            if last:
                raise
            delay = 10 * (attempt + 1)

        print(f"  Sleeping {delay}s before retrying...", file=sys.stderr)
        time.sleep(delay)


# ----------------------------------------------------------- statistics

def get_day_statistics(day):
    query = make_query(day)
    print(f"\nProcessing {day}")
    print(f"Query: {query}")

    total = 0
    counts = Counter()
    start = 0

    while True:
        xml_data = request_arxiv(query, start=start)

        try:
            root = ET.fromstring(xml_data)
        except ET.ParseError as exc:
            raise RuntimeError(
                f"Could not parse arXiv response for {day}: {exc}"
            ) from exc

        entries = root.findall("a:entry", NS)
        print(f"  Received {len(entries)} entries")

        if not entries:
            break

        total += len(entries)

        for entry in entries:
            terms = {
                c.attrib.get("term") for c in entry.findall("a:category", NS)
            }
            for category in CATEGORIES:
                if category in terms:
                    counts[category] += 1

        if len(entries) < PAGE_SIZE:
            break

        start += len(entries)
        time.sleep(REQUEST_DELAY)

    row = {"date": day.isoformat(), "total": total}
    for category in CATEGORIES:
        row[category] = counts[category]

    print(f"  Total submissions: {total}")
    for category in CATEGORIES:
        print(f"  {category:15s}: {counts[category]}")

    return row


# ---------------------------------------------------------------- files

def load_rows():
    if not DAILY_FILE.exists():
        return []
    try:
        with DAILY_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Could not parse {DAILY_FILE}: {exc}") from exc
    if not isinstance(data, list):
        raise RuntimeError("daily.json must contain a JSON list.")
    return data


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.replace(path)


def save_metadata(days):
    now = datetime.now(timezone.utc)
    save_json(METADATA_FILE, {
        "description": "Daily arXiv submission counts.",
        "counting_basis": "v1 submission timestamp",
        "timezone": "UTC",
        "categories": CATEGORIES,
        "updated": now.date().isoformat(),
        "updated_for_date": ", ".join(d.isoformat() for d in days),
        "updated_at_utc": now.isoformat(),
    })


# ----------------------------------------------------------------- main

def main():
    days = get_requested_dates()

    print("=" * 60)
    print("arXiv statistics updater")
    print("=" * 60)
    print("Dates to process: " + ", ".join(d.isoformat() for d in days))

    existing = {
        row["date"]: row
        for row in load_rows()
        if isinstance(row, dict) and "date" in row
    }

    saved, skipped, failed = [], [], []

    for index, day in enumerate(days):
        try:
            row = get_day_statistics(day)
        except Exception as exc:
            print(f"  ERROR for {day}: {exc}", file=sys.stderr)
            failed.append(day)
        else:
            if row["total"] == 0:
                # arXiv's API only lists papers once they are announced,
                # so very recent days (and weekends) can come back empty.
                # Don't overwrite/record a misleading all-zero row.
                print(
                    f"  WARNING: no entries returned for {day}; "
                    "not saving (not announced yet?)."
                )
                skipped.append(day)
            else:
                existing[row["date"]] = row
                saved.append(day)

        if index < len(days) - 1:
            time.sleep(REQUEST_DELAY)

    if saved:
        save_json(DAILY_FILE, [existing[d] for d in sorted(existing)])
        save_metadata(saved)

    print("\n" + "=" * 60)
    print(f"Saved:   {', '.join(map(str, saved)) or '-'}")
    print(f"Skipped: {', '.join(map(str, skipped)) or '-'}")
    print(f"Failed:  {', '.join(map(str, failed)) or '-'}")
    print(f"Total dates in database: {len(existing)}")
    print("=" * 60)

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
