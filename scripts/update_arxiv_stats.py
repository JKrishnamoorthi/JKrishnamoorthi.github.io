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

PAGE_SIZE = 100


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


def make_query(day):
    """
    arXiv API submittedDate format:

        YYYYMMDDHHMM

    Example:

        submittedDate:[202609260000 TO 202609270000]
    """

    start = datetime.strptime(
        day,
        "%Y-%m-%d"
    )

    end = start + timedelta(days=1)

    start_string = start.strftime("%Y%m%d%H%M")
    end_string = end.strftime("%Y%m%d%H%M")

    return (
        f"submittedDate:[{start_string} TO {end_string}]"
    )


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
        "User-Agent":
            "JKrishnamoorthi-arxiv-dashboard/1.0 "
            "(https://jkrishnamoorthi.github.io/)",
        "Accept":
            "application/atom+xml",
        "Accept-Language":
            "en-US,en;q=0.9",
        "Accept-Encoding":
            "gzip, deflate",
        "Connection":
            "keep-alive",
    }

    request = urllib.request.Request(
        url,
        headers=headers,
        method="GET",
    )

    max_attempts = 8

    for attempt in range(max_attempts):

        try:

            print(
                f"Requesting page "
                f"start={start} "
                f"(attempt {attempt + 1}/{max_attempts})"
            )

            with urllib.request.urlopen(
                request,
                timeout=120
            ) as response:

                return response.read()

        except urllib.error.HTTPError as exc:

            # arXiv's edge has recently started returning 406
            # (and sometimes 403) as a load-shedding/throttle
            # signal against cloud/CI egress IPs, rather than
            # a genuine content-negotiation failure. Treat it
            # like 429/503 and retry with a long, growing
            # backoff instead of failing fast.
            body = ""

            try:
                body = exc.read().decode(
                    "utf-8",
                    errors="replace"
                )[:500]
            except Exception:
                pass

            print(
                f"Request failed "
                f"(attempt {attempt + 1}/{max_attempts}): "
                f"HTTP {exc.code} {exc.reason}",
                file=sys.stderr,
            )

            if body:
                print(
                    f"Response body (truncated): {body}",
                    file=sys.stderr,
                )

            if attempt == max_attempts - 1:
                raise

            if exc.code in (403, 406, 429, 503):
                # Longer, steeper backoff for throttle-like
                # responses: 20, 40, 80, ... seconds, capped.
                delay = min(
                    20 * (2 ** attempt),
                    300
                )
            else:
                delay = 10 * (attempt + 1)

            print(
                f"Sleeping {delay}s before retrying...",
                file=sys.stderr,
            )

            time.sleep(delay)

        except Exception as exc:

            print(
                f"Request failed "
                f"(attempt {attempt + 1}/{max_attempts}): {exc}",
                file=sys.stderr,
            )

            if attempt == max_attempts - 1:
                raise

            time.sleep(
                10 * (attempt + 1)
            )


def collect_day(day):

    query = make_query(day)

    print()
    print("Query:")
    print(query)
    print()

    total = 0

    category_counts = Counter()

    start = 0

    while True:

        xml_data = request_arxiv(
            query,
            start=start
        )

        root = ET.fromstring(xml_data)

        entries = root.findall(
            "a:entry",
            NS
        )

        print(
            f"Received {len(entries)} entries"
        )

        if not entries:
            break

        total += len(entries)

        for entry in entries:

            categories = entry.findall(
                "a:category",
                NS
            )

            for category in categories:

                term = category.attrib.get(
                    "term"
                )

                if term in CATEGORIES:
                    category_counts[term] += 1

        if len(entries) < PAGE_SIZE:
            break

        start += len(entries)

        # Be polite to arXiv.
        time.sleep(3)

    row = {
        "date": day,
        "total": total,
    }

    for category in CATEGORIES:

        row[category] = category_counts[
            category
        ]

    return row


def get_target_date():

    manual_date = os.environ.get(
        "ARXIV_STATS_DATE"
    )

    if manual_date:

        datetime.strptime(
            manual_date,
            "%Y-%m-%d"
        )

        return manual_date

    yesterday = (
        datetime.now(timezone.utc)
        - timedelta(days=1)
    )

    return yesterday.strftime(
        "%Y-%m-%d"
    )


def main():

    print("=" * 60)
    print("arXiv statistics collector")
    print("=" * 60)

    day = get_target_date()

    print(
        f"Target date: {day}"
    )

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
            "Daily arXiv submission counts.",

        "counting_basis":
            "v1 submission timestamp",

        "timezone":
            "UTC",

        "categories":
            CATEGORIES,

        "updated_for_date":
            day,

        "updated_at_utc":
            datetime.now(
                timezone.utc
            ).isoformat(),
    }

    save_json(
        DATA / "metadata.json",
        metadata
    )

    print()
    print("=" * 60)
    print("Result")
    print("=" * 60)

    print(
        json.dumps(
            row,
            indent=2
        )
    )


if __name__ == "__main__":

    try:
        main()

    except Exception as exc:

        print(
            f"ERROR: {exc}",
            file=sys.stderr
        )

        raise