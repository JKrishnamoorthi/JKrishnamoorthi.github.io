#!/usr/bin/env python3

import json
import re
from pathlib import Path

import arxiv


# ============================================================
# Configuration
# ============================================================

ROOT = Path(__file__).resolve().parents[1]

FAVOURITES_FILE = ROOT / "data" / "favourites.json"
METADATA_FILE = ROOT / "data" / "favourites_metadata.json"

PAGE_SIZE = 100
REQUEST_DELAY = 3.0
NUM_RETRIES = 5


# ============================================================
# Read favourite arXiv IDs
# ============================================================

def normalize_arxiv_id(value):
    """
    Convert different arXiv ID formats into a plain ID.

    Examples:

        2604.16157
        arXiv:2604.16157
        https://arxiv.org/abs/2604.16157
        https://arxiv.org/pdf/2604.16157.pdf

    all become:

        2604.16157
    """

    paper_id = str(value).strip()

    paper_id = re.sub(
        r"^https?://arxiv\.org/(abs|pdf)/",
        "",
        paper_id,
        flags=re.IGNORECASE,
    )

    paper_id = re.sub(
        r"^arxiv:",
        "",
        paper_id,
        flags=re.IGNORECASE,
    )

    paper_id = re.sub(
        r"\.pdf$",
        "",
        paper_id,
        flags=re.IGNORECASE,
    )

    return paper_id.strip()


def get_ids():
    """
    Read favourite arXiv IDs from favourites.json.

    favourites.json must contain only IDs, for example:

    [
        "2604.16157",
        "2512.22632"
    ]
    """

    if not FAVOURITES_FILE.exists():
        raise FileNotFoundError(
            f"Favourite file not found: {FAVOURITES_FILE}"
        )

    try:
        raw = json.loads(
            FAVOURITES_FILE.read_text(
                encoding="utf-8"
            )
        )
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Could not parse {FAVOURITES_FILE}: {exc}"
        ) from exc

    if not isinstance(raw, list):
        raise ValueError(
            "data/favourites.json must contain "
            "a JSON list of arXiv IDs."
        )

    ids = []

    for item in raw:

        if not isinstance(item, str):
            raise ValueError(
                "data/favourites.json must contain "
                "only arXiv ID strings."
            )

        paper_id = normalize_arxiv_id(item)

        if paper_id:
            ids.append(paper_id)

    # Remove duplicates while preserving order.
    return list(dict.fromkeys(ids))


# ============================================================
# Fetch metadata from arXiv
# ============================================================

def fetch_papers(ids):
    """
    Fetch metadata for the requested arXiv IDs.
    """

    if not ids:
        return []

    query = " OR ".join(
        f"id:{paper_id}"
        for paper_id in ids
    )

    client = arxiv.Client(
        page_size=PAGE_SIZE,
        delay_seconds=REQUEST_DELAY,
        num_retries=NUM_RETRIES,
    )

    search = arxiv.Search(
        query=query,
        max_results=len(ids),
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Ascending,
    )

    try:
        return list(
            client.results(search)
        )

    except Exception as exc:
        raise RuntimeError(
            f"Failed to query arXiv: {exc}"
        ) from exc


# ============================================================
# Convert arXiv result to JSON
# ============================================================

def paper_to_dict(paper):
    """
    Convert arxiv.Result into the metadata format
    used by the website.
    """

    paper_id = paper.get_short_id()

    # Remove version suffix.
    #
    # 2604.16157v2 -> 2604.16157
    paper_id = re.sub(
        r"v\d+$",
        "",
        paper_id,
    )

    title = re.sub(
        r"\s+",
        " ",
        paper.title or "",
    ).strip()

    summary = re.sub(
        r"\s+",
        " ",
        paper.summary or "",
    ).strip()

    authors = [
        author.name.strip()
        for author in paper.authors
        if author.name
    ]

    categories = list(
        paper.categories
    )

    abs_link = (
        f"https://arxiv.org/abs/{paper_id}"
    )

    pdf_link = (
        f"https://arxiv.org/pdf/{paper_id}"
    )

    published = ""

    if paper.published:
        published = paper.published.isoformat()

    return {
        "id": paper_id,
        "title": title,
        "authors": authors,
        "categories": categories,
        "published": published,
        "summary": summary,
        "absLink": abs_link,
        "pdfLink": pdf_link,
    }


# ============================================================
# Save metadata
# ============================================================

def save_metadata(papers):
    """
    Save fetched favourite-paper metadata.
    """

    METADATA_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    METADATA_FILE.write_text(
        json.dumps(
            papers,
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )


# ============================================================
# Main
# ============================================================

def main():

    print("=" * 60)
    print("arXiv favourite papers updater")
    print("=" * 60)

    # --------------------------------------------------------
    # Read favourite IDs
    # --------------------------------------------------------

    ids = get_ids()

    print()
    print(
        f"Favourite paper IDs: {len(ids)}"
    )

    if not ids:

        print(
            "No favourite papers found."
        )

        save_metadata([])

        return

    for paper_id in ids:
        print(f"  {paper_id}")

    # --------------------------------------------------------
    # Fetch metadata
    # --------------------------------------------------------

    print()
    print(
        "Fetching paper metadata from arXiv..."
    )

    results = fetch_papers(ids)

    papers = [
        paper_to_dict(result)
        for result in results
    ]

    # --------------------------------------------------------
    # Preserve favourites.json order
    # --------------------------------------------------------

    order = {
        paper_id: index
        for index, paper_id in enumerate(ids)
    }

    papers.sort(
        key=lambda paper: order.get(
            paper["id"],
            10**9,
        )
    )

    # --------------------------------------------------------
    # Check for missing papers
    # --------------------------------------------------------

    found_ids = {
        paper["id"]
        for paper in papers
    }

    missing_ids = [
        paper_id
        for paper_id in ids
        if paper_id not in found_ids
    ]

    if missing_ids:

        print()
        print(
            "WARNING: The following papers were "
            "not returned by arXiv:"
        )

        for paper_id in missing_ids:
            print(f"  {paper_id}")

    # --------------------------------------------------------
    # Save metadata
    # --------------------------------------------------------

    save_metadata(papers)

    print()
    print(
        f"Fetched: {len(papers)} / {len(ids)} papers"
    )

    print(
        f"Updated: {METADATA_FILE}"
    )

    print("=" * 60)


if __name__ == "__main__":
    main()
