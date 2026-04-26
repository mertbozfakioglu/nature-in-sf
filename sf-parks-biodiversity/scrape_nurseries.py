#!/usr/bin/env python3
"""
Scrapes nursery websites and updates data/nursery_inventory.json.
Run from any directory; paths are resolved relative to this script.
"""

import html as html_lib
import json
import re
import urllib.request
from datetime import date
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


def parse_species_name(raw: str) -> str:
    name = html_lib.unescape(raw).strip()
    name = re.sub(r"\s*'[^']*'.*$", "", name)   # strip cultivar names
    name = re.sub(r"\s+var\.\s+\S+.*$", "", name)  # strip var. designations
    return name.strip()


def genus_species(name: str) -> str:
    parts = name.split()
    return " ".join(parts[:2]) if len(parts) >= 2 else name


def scrape_oaktown(url: str) -> list:
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 nature-in-sf/nursery-scraper"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        content = r.read().decode("utf-8")

    raw_names = re.findall(r'<td class="species"><a[^>]*>([^<]+)</a>', content)
    seen = set()
    result = []
    for raw in raw_names:
        name = parse_species_name(raw)
        if not name or len(name.split()) < 2:
            continue
        gs = genus_species(name)
        if gs not in seen:
            seen.add(gs)
            result.append(gs)
    return result


SCRAPERS = {
    "oaktown": scrape_oaktown,
}


def main():
    with open(DATA_DIR / "nurseries.json") as f:
        nurseries = json.load(f)

    with open(DATA_DIR / "sf_natives.csv") as f:
        sf_natives = {line.strip() for line in f if line.strip()}

    by_species = {}

    for nursery_id, info in nurseries.items():
        scraper = SCRAPERS.get(nursery_id)
        if not scraper or "inventoryUrl" not in info:
            continue
        print(f"Scraping {info['name']} ...", flush=True)
        try:
            species = scraper(info["inventoryUrl"])
            matched = 0
            for gs in species:
                if gs in sf_natives:
                    by_species.setdefault(gs, []).append(nursery_id)
                    matched += 1
            print(f"  {len(species)} unique species, {matched} SF native matches")
        except Exception as exc:
            print(f"  ERROR: {exc}")

    inventory = {
        "lastUpdated": date.today().isoformat(),
        "bySpecies": dict(sorted(by_species.items())),
    }

    out = DATA_DIR / "nursery_inventory.json"
    with open(out, "w") as f:
        json.dump(inventory, f, indent=2)
    print(f"Wrote {len(by_species)} species to {out}")


if __name__ == "__main__":
    main()
