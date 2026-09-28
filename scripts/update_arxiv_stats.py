#!/usr/bin/env python3

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path


# Tried in order; on a 406/403 the next host is used.
API_URLS = [
    "https://export.arxiv.org/api/query",
    "https://arxiv.org/api/query",
]

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

# Delay between arXiv API requests (arXiv asks for >= 3 s).
REQUEST_DELAY = 3.0

# Number of attempts for a failed request.
MAX_RETRIES = 6

OPENSEARCH_NS = "http://a9.com/-/spec/opensearch/1.1/"

USER_AGENT = (
    "JKrishnamoorthi.github.io arXiv statistics updater "
    "(https://jkrishnamoorthi.github.io/; "
    "https://github.com/JKrishnamoorthi)"
)

# Header profiles tried in rotation when the server answers 406.
# A 406 means the server disliked our Accept / Accept-Encoding /
# User-Agent, so retrying the identical request is pointless.
HEADER_PROFILES = [
    {
        "User-Agent": USER_AGENT,
        "Accept": "application/atom+xml, application/xml;q=0.9, */*;q=0.8",
    },
    {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
    },
    {
        "User-Agent": "Mozilla/5.0 (compatible; " + USER_AGENT + ")",
        "Accept": "*/*",
    },
    {
        "User-Agent": "curl/8.5.0",
        "Accept": "*/*",
    },
]

# Statuses worth retrying (with backoff / different headers).
RETRYABLE = {403, 406, 429, 500, 502, 503, 504}


def parse_date(value):
    """Parse YYYY-MM-DD."""
    return date.fromisoformat(value)


def get_requested_dates():
    """
    Supported modes:

    1. Single date:   ARXIV_STATS_DATE=2026-09-23
    2. Date range:    ARXIV_STATS_START=... ARXIV_STATS_END=...
    3. Nothing set:   defaults to yesterday.
    """
    single_date = os.environ.get("ARXIV_STATS_DATE", "").strip()
    start_date = os.environ.get("ARXIV_STATS_START", "").strip()
    end_date = os.environ.get("ARXIV_STATS_END", "").strip()

    if single_date:
        if start_date or end_date:
            raise ValueError(
                "Use either ARXIV_STATS_DATE or "
                "ARXIV_STATS_START/ARXIV_STATS_END, not both."
            )
        return [parse_date(single_date)]

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

    return [date.today() - timedelta(days=1)]


def arxiv_date_string(d):
    """2026-09-23 -> 202609230000"""
    return d.strftime("%Y%m%d0000")


def fetch_arxiv(search_query, target_date, max_results=1):
    """
    Query the arXiv API with retries.

    On 406/403 the header profile and API host are rotated, because
    the same request will be rejected again. On 429/5xx the request is
    retried with increasing delays.
    """
    # Keep ':' '[' ']' '(' ')' '*' literal (as in the curl requests that
    # work) instead of percent-encoding them; spaces become '+'.
    params = urllib.parse.urlencode(
        {
            "search_query": search_query,
            "start": "0",
            "max_results": str(max_results),
        },
        safe=":[]()*",
    )

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        # Rotate through header profiles and hosts on each attempt.
        headers = HEADER_PROFILES[(attempt - 1) % len(HEADER_PROFILES)]
        base = API_URLS[(attempt - 1) % len(API_URLS)]
        url = f"{base}?{params}"

        request = urllib.request.Request(url, headers=headers, method="GET")

        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()

        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code} {exc.reason}"
            print(
                f"  arXiv HTTP error {exc.code} "
                f"(attempt {attempt}/{MAX_RETRIES}, host={base}, "
                f"profile={(attempt - 1) % len(HEADER_PROFILES)})"
            )

            if attempt == 1:
                try:
                    body = exc.read().decode("utf-8", "replace")[:300]
                except Exception:
                    body = ""
                print(f"    request url: {url}")
                print(f"    response body: {body!r}")
                print(f"    response headers: {dict(exc.headers)}")

            if exc.code not in RETRYABLE:
                raise RuntimeError(
                    f"Failed to query arXiv for {target_date}: {last_error}"
                ) from exc

        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = str(exc)
            print(
                f"  Network error (attempt {attempt}/{MAX_RETRIES}): {exc}"
            )

        if attempt < MAX_RETRIES:
            delay = 5 * attempt
            print(f"  Retrying in {delay} seconds...")
            time.sleep(delay)

    raise RuntimeError(
        f"Failed to query arXiv for {target_date} "
        f"after {MAX_RETRIES} attempts: {last_error}"
    )


def get_total_results(search_query, target_date):
    """
    Return the number of matching papers using opensearch:totalResults.

    Only one entry is requested, so no pagination is needed.
    """
    xml_data = fetch_arxiv(search_query, target_date, max_results=1)

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as exc:
        raise RuntimeError(
            f"Could not parse arXiv response for {target_date}: {exc}"
        ) from exc

    node = root.find(f"{{{OPENSEARCH_NS}}}totalResults")
    if node is None or node.text is None:
        raise RuntimeError(
            f"arXiv response for {target_date} has no totalResults field."
        )

    return int(node.text.strip())


def get_day_statistics(target_date):
    """
    Count arXiv submissions on target_date, overall and per category.

    Cross-listed papers count towards every category they appear in
    (same behaviour as matching against each entry's category terms).
    """
    next_date = target_date + timedelta(days=1)
    date_range = (
        f"submittedDate:[{arxiv_date_string(target_date)} "
        f"TO {arxiv_date_string(next_date)}]"
    )

    print(f"\nProcessing {target_date}")
    print(f"Date filter: {date_range}")

    if target_date >= date.today():
        print(
            "  WARNING: this date is not finished yet (UTC); "
            "counts will be incomplete."
        )

    total = get_total_results(date_range, target_date)
    time.sleep(REQUEST_DELAY)

    counts = {}
    for category in CATEGORIES:
        query = f"cat:{category} AND {date_range}"
        counts[category] = get_total_results(query, target_date)
        time.sleep(REQUEST_DELAY)

    if total == 0 and any(counts.values()):
        union = "(" + " OR ".join(f"cat:{c}" for c in CATEGORIES) + ")"
        total = get_total_results(f"{union} AND {date_range}", target_date)
        time.sleep(REQUEST_DELAY)
        print(
            "  NOTE: date-only query returned 0, so 'total' is the number "
            "of papers in the tracked categories (deduplicated)."
        )

    result = {"date": target_date.isoformat(), "total": total}
    result.update(counts)

    print(f"  Total submissions: {total}")
    for category in CATEGORIES:
        print(f"  {category:15s}: {counts[category]}")

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
        raise RuntimeError(f"Could not parse {DAILY_FILE}: {exc}") from exc


def save_daily_data(data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data.sort(key=lambda row: row["date"])

    with DAILY_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
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
        json.dump(metadata, f, indent=2, ensure_ascii=False)
        f.write("\n")


def main():
    requested_dates = get_requested_dates()

    print("=" * 60)
    print("arXiv statistics updater")
    print("=" * 60)

    print("\nDates to process:")
    for d in requested_dates:
        print(f"  {d}")

    # Trivial query that works from a normal machine. If this fails,
    # arXiv is rejecting this host/IP, not our date query.
    print("\nPreflight check (cat:hep-ph, 1 result)...")
    try:
        get_total_results("cat:hep-ph", "preflight")
        print("  Preflight OK")
    except RuntimeError as exc:
        print(f"  Preflight FAILED: {exc}")
        print(
            "  arXiv rejects even a trivial query from this machine; "
            "this points to an IP-level block (e.g. GitHub runner)."
        )
        sys.exit(1)

    daily_data = load_daily_data()

    # Dict keyed by date so entries are replaced, not duplicated.
    existing = {
        row["date"]: row
        for row in daily_data
        if isinstance(row, dict) and "date" in row
    }

    failed = []

    for index, target_date in enumerate(requested_dates):
        try:
            result = get_day_statistics(target_date)
            existing[result["date"]] = result
        except RuntimeError as exc:
            # Keep going so one bad day doesn't discard the others.
            print(f"  ERROR: {exc}")
            failed.append(target_date)

        if index < len(requested_dates) - 1:
            time.sleep(REQUEST_DELAY)

    updated_data = list(existing.values())

    if updated_data:
        save_daily_data(updated_data)
        save_metadata()

    print("\n" + "=" * 60)
    print("Done." if not failed else "Done with errors.")
    print(f"Updated: {DAILY_FILE}")
    print(f"Total dates in database: {len(updated_data)}")

    if failed:
        print("Failed dates: " + ", ".join(d.isoformat() for d in failed))

    print("=" * 60)

    # Non-zero exit so the workflow still shows the failure.
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
