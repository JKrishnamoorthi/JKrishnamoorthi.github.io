#!/usr/bin/env python3

import json
import os
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path


API = "https://export.arxiv.org/api/query"

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

CATEGORIES = [
    "hep-ph",
    "hep-ex",
    "hep-th",
    "nucl-th",
    "astro-ph.HE",
    "astro-ph.CO",
    "physics.ins-det",
]

NS = {
    "a": "http://www.w3.org/2005/Atom"
}

PAGE_SIZE = 200

# arXiv asks clients to avoid excessive request rates.
REQUEST_DELAY = 5


def load_json(path, default):
    if not path.exists():
        return default

    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp = path.with_suffix(".tmp")

    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
        f.write("\n")

    tmp.replace(path)


def request_arxiv(query, start=0):

    params = urllib.parse.urlencode({
        "search_query": query,
        "start": start,
        "max_results": PAGE_SIZE,
        "sortBy": "submittedDate",
        "sortOrder": "ascending",
    })

    url = f"{API}?{params}"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(compatible; JKrishnamoorthi-ArxivStats/1.0; "
            "+https://jkrishnamoorthi.github.io/)"
        ),
        "Accept": "application/atom+xml",
    }

    request = urllib.request.Request(
        url,
        headers=headers,
        method="GET",
    )

    for attempt in range(5):

        try:

            print(f"Requesting: {url}")

            with urllib.request.urlopen(
                request,
                timeout=120
            ) as response:

                return response.read()

        except Exception as exc:

            print(
                f"Request failed "
                f"(attempt {attempt + 1}/5): {exc}",
                file=sys.stderr,
            )

            if attempt == 4:
                raise

            time.sleep(10 * (attempt + 1))


def day_query(day):

    start = f"{day}T00:00:00Z"

    end = (
        datetime.fromisoformat(day)
        .replace(tzinfo=timezone.utc)
        + timedelta(days=1)
    )

    end = end.strftime("%Y-%m-%dT00:00:00Z")

    return f"submittedDate:[{start} TO {end}]"


def parse_entries(xml_data):

    root = ET.fromstring(xml_data)

    entries = root.findall("a:entry", NS)

    return entries


def collect_day(day):

    query = day_query(day)

    total = 0
    category_counts = Counter()

    start = 0

    while True:

        xml_data = request_arxiv(
            query,
            start=start
        )

        entries = parse_entries(xml_data)

        if not entries:
            break

        total += len(entries)

        for entry in entries:

            categories = entry.findall(
                "a:category",
                NS
            )

            for category in categories:

                term = category.attrib.get("term")

                if term in CATEGORIES:
                    category_counts[term] += 1

        if len(entries) < PAGE_SIZE:
            break

        start += len(entries)

        time.sleep(REQUEST_DELAY)

    row = {
        "date": day,
        "total": total,
    }

    for category in CATEGORIES:
        row[category] = category_counts[category]

    return row


def get_target_date():

    override = os.environ.get(
        "ARXIV_STATS_DATE"
    )

    if override:
        datetime.fromisoformat(override)
        return override

    yesterday = (
        datetime.now(timezone.utc)
        - timedelta(days=1)
    )

    return yesterday.date().isoformat()


def main():

    day = get_target_date()

    print("=" * 60)
    print("arXiv statistics")
    print("=" * 60)
    print(f"Target date: {day}")
    print()

    path = DATA / "daily.json"

    rows = load_json(
        path,
        []
    )

    existing = {
        row["date"]: row
        for row in rows
        if "date" in row
    }

    print("Collecting data from arXiv...")

    row = collect_day(day)

    existing[day] = row

    output = [
        existing[d]
        for d in sorted(existing)
    ]

    save_json(
        path,
        output
    )

    metadata = {
        "description":
            "Daily arXiv submission counts by category.",

        "counting_basis":
            "v1 submission timestamp, UTC",

        "categories":
            CATEGORIES,

        "updated_for_date":
            day,

        "updated_at_utc":
            datetime.now(timezone.utc).isoformat(),
    }

    save_json(
        DATA / "metadata.json",
        metadata
    )

    print()
    print("Result:")
    print(json.dumps(
        row,
        indent=2
    ))


if __name__ == "__main__":

    try:
        main()

    except Exception as exc:

        print(
            f"ERROR: {exc}",
            file=sys.stderr
        )

        raise