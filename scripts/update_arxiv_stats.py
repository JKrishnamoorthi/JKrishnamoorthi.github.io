#!/usr/bin/env python3

import json
import os
import time
from datetime import date, timedelta
from pathlib import Path

import arxiv


# ============================================================
# Configuration
# ============================================================

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

# arXiv API client settings
PAGE_SIZE = 100
REQUEST_DELAY = 3.0
NUM_RETRIES = 5


# ============================================================
# Date handling
# ============================================================

def parse_date(value):
    """Parse a date in YYYY-MM-DD format."""
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

    single_date = os.environ.get(
        "ARXIV_STATS_DATE", ""
    ).strip()

    start_date = os.environ.get(
        "ARXIV_STATS_START", ""
    ).strip()

    end_date = os.environ.get(
        "ARXIV_STATS_END", ""
    ).strip()

    # --------------------------------------------------------
    # Single-date mode
    # --------------------------------------------------------

    if single_date:

        if start_date or end_date:
            raise ValueError(
                "Use either ARXIV_STATS_DATE or "
                "ARXIV_STATS_START/ARXIV_STATS_END, "
                "not both."
            )

        return [parse_date(single_date)]

    # --------------------------------------------------------
    # Range mode
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Default: yesterday
    # --------------------------------------------------------

    yesterday = date.today() - timedelta(days=1)

    return [yesterday]


# ============================================================
# arXiv statistics
# ============================================================

def get_day_statistics(target_date):
    """
    Query arXiv for all submissions on target_date.

    A paper can contribute to multiple categories if it is
    cross-listed.
    """

    next_date = target_date + timedelta(days=1)

    start_string = target_date.strftime(
        "%Y%m%d0000"
    )

    end_string = next_date.strftime(
        "%Y%m%d0000"
    )

    query = (
        f"submittedDate:[{start_string} TO {end_string}]"
    )

    print()
    print(f"Processing {target_date}")
    print(f"Query: {query}")

    counts = {
        category: 0
        for category in CATEGORIES
    }

    total = 0

    # --------------------------------------------------------
    # arXiv Python client
    # --------------------------------------------------------

    client = arxiv.Client(
        page_size=PAGE_SIZE,
        delay_seconds=REQUEST_DELAY,
        num_retries=NUM_RETRIES,
    )

    search = arxiv.Search(
        query=query,
        max_results=None,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Ascending,
    )

    print("  Fetching submissions from arXiv...")

    try:

        results = client.results(search)

        for result in results:

            total += 1

            categories = set(result.categories)

            for category in CATEGORIES:

                if category in categories:
                    counts[category] += 1

            if total % PAGE_SIZE == 0:
                print(
                    f"  Processed {total} submissions..."
                )

    except Exception as exc:

        raise RuntimeError(
            f"Failed to query arXiv for "
            f"{target_date}: {exc}"
        ) from exc

    # --------------------------------------------------------
    # Build result
    # --------------------------------------------------------

    result = {
        "date": target_date.isoformat(),
        "total": total,
    }

    result.update(counts)

    print()
    print(
        f"  Total submissions: {total}"
    )

    for category in CATEGORIES:

        print(
            f"  {category:15s}: "
            f"{counts[category]}"
        )

    return result


# ============================================================
# JSON handling
# ============================================================

def load_daily_data():
    """Load existing daily statistics."""

    if not DAILY_FILE.exists():
        return []

    try:

        with DAILY_FILE.open(
            "r",
            encoding="utf-8",
        ) as f:

            data = json.load(f)

        if not isinstance(data, list):

            raise ValueError(
                "daily.json must contain a JSON list."
            )

        return data

    except json.JSONDecodeError as exc:

        raise RuntimeError(
            f"Could not parse {DAILY_FILE}: {exc}"
        ) from exc


def save_daily_data(data):
    """Save daily statistics."""

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Keep entries sorted chronologically.
    data.sort(
        key=lambda row: row["date"]
    )

    with DAILY_FILE.open(
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False,
        )

        f.write("\n")


def save_metadata():
    """Save metadata describing the dataset."""

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    metadata = {
        "updated": date.today().isoformat(),
        "categories": CATEGORIES,
        "description": (
            "Daily arXiv submission statistics for "
            "selected particle physics, astrophysics, "
            "and detector categories."
        ),
    }

    with METADATA_FILE.open(
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            metadata,
            f,
            indent=2,
            ensure_ascii=False,
        )

        f.write("\n")


# ============================================================
# Main
# ============================================================

def main():

    requested_dates = get_requested_dates()

    print("=" * 60)
    print("arXiv statistics updater")
    print("=" * 60)

    print()
    print("Dates to process:")

    for d in requested_dates:
        print(f"  {d}")

    # --------------------------------------------------------
    # Load existing data
    # --------------------------------------------------------

    daily_data = load_daily_data()

    # Convert existing entries into a dictionary.
    #
    # This ensures that if we process an existing date,
    # its old value is replaced rather than duplicated.
    existing = {
        row["date"]: row
        for row in daily_data
        if isinstance(row, dict)
        and "date" in row
    }

    # --------------------------------------------------------
    # Process requested dates
    # --------------------------------------------------------

    for index, target_date in enumerate(
        requested_dates
    ):

        result = get_day_statistics(
            target_date
        )

        existing[result["date"]] = result

        # Delay between different dates.
        if index < len(requested_dates) - 1:

            print(
                f"\nWaiting {REQUEST_DELAY} seconds "
                f"before next date..."
            )

            time.sleep(
                REQUEST_DELAY
            )

    # --------------------------------------------------------
    # Save results
    # --------------------------------------------------------

    updated_data = list(
        existing.values()
    )

    save_daily_data(
        updated_data
    )

    save_metadata()

    # --------------------------------------------------------
    # Done
    # --------------------------------------------------------

    print()
    print("=" * 60)
    print("Done.")
    print(
        f"Updated: {DAILY_FILE}"
    )
    print(
        f"Total dates in database: "
        f"{len(updated_data)}"
    )
    print("=" * 60)


if __name__ == "__main__":
    main()
