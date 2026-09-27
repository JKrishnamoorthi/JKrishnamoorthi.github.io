#!/usr/bin/env python3

import json
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path


API_URL = "https://export.arxiv.org/api/query"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DAILY_FILE = DATA_DIR / "daily.json"
METADATA_FILE = DATA_DIR / "metadata.json"

CATEGORIES = [
    "hep-ph",
    "hep-ex",
    "hep-th",
    "nucl-th",
    "astro-ph.HE",
    "astro-ph.CO",
    "physics.ins-det",
]

PAGE_SIZE = 100
REQUEST_DELAY = 3.0


def parse_date(value):
    """Parse YYYY-MM-DD."""
    return date.fromisoformat(value)


def get_requested_dates():
    """
    Supported modes:

    1. Single date:
       ARXIV_STATS_DATE=2026-09-23

    2. Date range:
       ARXIV_STATS_START=2026-09-01
       ARXIV_STATS_END=2026-09-23

    3. No environment variables:
       defaults to yesterday.
    """

    single_date = os.environ.get("ARXIV_STATS_DATE", "").strip()
    start_date = os.environ.get("ARXIV_STATS_START", "").strip()
    end_date = os.environ.get("ARXIV_STATS_END", "").strip()

    # Single-date mode
    if single_date:
        if start_date or end_date:
            raise ValueError(
                "Use either ARXIV_STATS_DATE or "
                "ARXIV_STATS_START/ARXIV_STATS_END, not both."
            )

        return [parse_date(single_date)]

    # Range mode
    if start_date or end_date:
        if not start_date or not end_date:
            raise ValueError(
                "Both ARXIV_STATS_START and ARXIV_STATS_END "
                "must be provided for range mode."
            )

        start = parse_date(start_date)
        end = parse_date(end_date)

        if start > end:
            raise ValueError(
                f"ARXIV_STATS_START ({start}) is after "
                f"ARXIV_STATS_END ({end})."
            )

        dates = []
        current = start

        while current <= end:
            dates.append(current)
            current += timedelta(days=1)

        return dates

    # Default: yesterday
    yesterday = date.today() - timedelta(days=1)
    return [yesterday]


def arxiv_date_string(d):
    """
    arXiv API date format.

    Example:
    2026-09-23 -> 202609230000
    """
    return d.strftime("%Y%m%d0000")


def get_day_statistics(target_date):
    """
    Query arXiv for all submissions on target_date and count
    papers belonging to each selected category.

    Cross-listed papers can contribute to more than one category.
    """

    next_date = target_date + timedelta(days=1)

    start_string = arxiv_date_string(target_date)
    end_string = arxiv_date_string(next_date)

    query = (
        f"submittedDate:[{start_string} TO {end_string}]"
    )

    print(f"\nProcessing {target_date}")
    print(f"Query: {query}")

    counts = {
        category: 0
        for category in CATEGORIES
    }

    total = 0
    start = 0

    while True:
        params = {
            "search_query": query,
            "start": str(start),
            "max_results": str(PAGE_SIZE),
            "sortBy": "submittedDate",
            "sortOrder": "ascending",
        }

        url = API_URL + "?" + urllib.parse.urlencode(params)

        print(f"  Fetching records {start} - {start + PAGE_SIZE - 1}")

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                "KrishnamoorthiJ-ArXiv-Stats/1.0 "
                "(GitHub Pages statistics; mailto:krishalphabet@gmail.com)"
            ),
            "Accept": "application/atom+xml, application/xml;q=0.9, */*;q=0.8",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                xml_data = response.read()
        except Exception as exc:
            raise RuntimeError(
                f"Failed to query arXiv for {target_date}: {exc}"
            ) from exc

        root = ET.fromstring(xml_data)

        namespace = {
            "atom": "http://www.w3.org/2005/Atom",
            "arxiv": "http://arxiv.org/schemas/atom",
        }

        entries = root.findall("atom:entry", namespace)

        if not entries:
            break

        for entry in entries:
            total += 1

            categories = {
                category.attrib.get("term")
                for category in entry.findall(
                    "atom:category",
                    namespace,
                )
            }

            for category in CATEGORIES:
                if category in categories:
                    counts[category] += 1

        # If fewer than PAGE_SIZE entries were returned,
        # this was the final page.
        if len(entries) < PAGE_SIZE:
            break

        start += PAGE_SIZE

        # Respect arXiv API request rate.
        time.sleep(REQUEST_DELAY)

    result = {
        "date": target_date.isoformat(),
        "total": total,
    }

    result.update(counts)

    print(f"  Total submissions: {total}")

    for category in CATEGORIES:
        print(
            f"  {category:15s}: {counts[category]}"
        )

    return result


def load_daily_data():
    if not DAILY_FILE.exists():
        return []

    try:
        with DAILY_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            raise ValueError("daily.json must contain a JSON list.")

        return data

    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Could not parse {DAILY_FILE}: {exc}"
        ) from exc


def save_daily_data(data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    data.sort(key=lambda row: row["date"])

    with DAILY_FILE.open("w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False,
        )
        f.write("\n")


def save_metadata():
    metadata = {
        "updated": date.today().isoformat(),
        "categories": CATEGORIES,
        "description": (
            "Daily arXiv submission statistics for selected "
            "particle physics, astrophysics, and detector categories."
        ),
    }

    with METADATA_FILE.open("w", encoding="utf-8") as f:
        json.dump(
            metadata,
            f,
            indent=2,
            ensure_ascii=False,
        )
        f.write("\n")


def main():
    requested_dates = get_requested_dates()

    print("=" * 60)
    print("arXiv statistics updater")
    print("=" * 60)

    print("\nDates to process:")

    for d in requested_dates:
        print(f"  {d}")

    daily_data = load_daily_data()

    # Convert existing entries into a dictionary so that
    # dates are replaced rather than duplicated.
    existing = {
        row["date"]: row
        for row in daily_data
        if isinstance(row, dict) and "date" in row
    }

    for index, target_date in enumerate(requested_dates):

        result = get_day_statistics(target_date)

        # Replace existing value for this date.
        existing[result["date"]] = result

        # Avoid unnecessary delay after the final date.
        if index < len(requested_dates) - 1:
            time.sleep(REQUEST_DELAY)

    updated_data = list(existing.values())

    save_daily_data(updated_data)
    save_metadata()

    print("\n" + "=" * 60)
    print("Done.")
    print(f"Updated: {DAILY_FILE}")
    print(f"Total dates in database: {len(updated_data)}")
    print("=" * 60)


if __name__ == "__main__":
    main()