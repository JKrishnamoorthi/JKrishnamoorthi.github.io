import json
import re
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDS_FILE = ROOT / "data" / "favourites.json"
OUT_FILE = ROOT / "data" / "favourites.json"
API = "https://export.arxiv.org/api/query"

NS = {"atom": "http://www.w3.org/2005/Atom"}

def get_ids():
    raw = json.loads(IDS_FILE.read_text())
    if not isinstance(raw, list):
        raise ValueError("data/favourites.json must contain a JSON list")
    ids = []
    for item in raw:
        if isinstance(item, str):
            ids.append(item.strip())
        elif isinstance(item, dict) and item.get("id"):
            ids.append(str(item["id"]).strip())
    return list(dict.fromkeys(i for i in ids if i))

def fetch(ids):
    query = " OR ".join(f"id:{i}" for i in ids)
    url = API + "?" + urllib.parse.urlencode({"search_query": query, "max_results": len(ids)})
    last = None
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "KrishnamoorthiJ-arxiv-dashboard/1.0"})
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.read()
        except Exception as exc:
            last = exc
            time.sleep(2 ** attempt)
    raise last

def main():
    ids = get_ids()
    if not ids:
        OUT_FILE.write_text("[]\n")
        return

    xml = fetch(ids)
    root = ET.fromstring(xml)

    papers = []
    for entry in root.findall("atom:entry", NS):
        def text(tag):
            node = entry.find(f"atom:{tag}", NS)
            return (node.text or "").strip() if node is not None else ""

        links = entry.findall("atom:link", NS)
        abs_link = next((x.attrib.get("href") for x in links if x.attrib.get("type") == "text/html"), text("id"))
        pdf_link = next((x.attrib.get("href") for x in links if x.attrib.get("title") == "pdf"), "")

        authors = ", ".join(
            (a.find("atom:name", NS).text or "").strip()
            for a in entry.findall("atom:author", NS)
            if a.find("atom:name", NS) is not None
        )
        categories = [
            c.attrib.get("term")
            for c in entry.findall("atom:category", NS)
            if c.attrib.get("term")
        ]

        papers.append({
            "id": re.sub(r"^https?://arxiv.org/abs/", "", text("id")),
            "title": re.sub(r"\s+", " ", text("title")),
            "authors": authors,
            "categories": categories,
            "published": text("published"),
            "summary": re.sub(r"\s+", " ", text("summary")),
            "absLink": abs_link,
            "pdfLink": pdf_link
        })

    order = {paper_id: i for i, paper_id in enumerate(ids)}
    papers.sort(key=lambda p: order.get(p["id"], 10**9))
    OUT_FILE.write_text(json.dumps(papers, indent=2, ensure_ascii=False) + "\n")

if __name__ == "__main__":
    main()
