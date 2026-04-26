#!/usr/bin/env python3
"""
Scrapes nursery websites and updates data/nursery_inventory.json.
Run from any directory; paths are resolved relative to this script.
"""

import html as html_lib
import json
import re
import time
import urllib.request
from datetime import date
from pathlib import Path

try:
    import requests as _requests
except ImportError:
    _requests = None

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


def scrape_sutro(url: str) -> list:
    """Return list of genus+species strings from Sutro Stewards shop (Wix).
    Product names embed the scientific name in parentheses, e.g.
    'Yarrow (Achillea millefolium) Short Tree Pot potted plant'."""
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 nature-in-sf/nursery-scraper"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        content = r.read().decode("utf-8", errors="replace")

    # Scientific names appear in parentheses inside product name strings in the
    # embedded Wix JSON: "name":"Common Name (Genus species) pot description"
    raw_names = re.findall(
        r'"name":"[^"]*\(([A-Z][a-z]+(?: [a-z]+)+(?:\s+(?:ssp|subsp|var)\.[^)]*)?)\)',
        content,
    )
    seen = set()
    result = []
    for name in raw_names:
        gs = genus_species(name.strip())
        if gs not in seen:
            seen.add(gs)
            result.append(gs)
    return result


def scrape_heronshead(url: str) -> list:
    """Return in-stock genus+species from Heron's Head Nursery (Shopify).
    Uses the Shopify /products.json API; filters to variants with available=true."""
    collection_base = re.sub(r'\?.*$', '', url.rstrip('/'))
    seen = set()
    result = []
    page = 1
    while True:
        api_url = f"{collection_base}/products.json?limit=250&page={page}"
        req = urllib.request.Request(
            api_url, headers={"User-Agent": "Mozilla/5.0 nature-in-sf/nursery-scraper"}
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            products = json.load(r)["products"]
        if not products:
            break
        for p in products:
            if not any(v.get("available") for v in p.get("variants", [])):
                continue
            name = p["title"]
            name = re.sub(r"\s*'[^']*'.*$", "", name)     # strip cultivars
            name = re.sub(r'\s*\([^)]*\).*$', '', name)   # strip descriptors like (seed grown)
            name = re.sub(r'\s+var\.\s+\S+.*$', '', name) # strip var.
            name = name.strip()
            gs = genus_species(name)
            if len(gs.split()) >= 2 and gs not in seen:
                seen.add(gs)
                result.append(gs)
        if len(products) < 250:
            break
        page += 1
        time.sleep(1)
    return result


def scrape_missionblue(url: str) -> list:
    """Return in-stock genus+species from Mission Blue Nursery (Squarespace).
    Scientific names appear in parentheses in product titles.
    Sold-out items carry a 'sold-out' CSS class on their <a> element."""
    if _requests is None:
        raise RuntimeError("requests library required for Mission Blue scraper")
    r = _requests.get(url, headers={"User-Agent": "Mozilla/5.0 nature-in-sf/nursery-scraper"}, timeout=30)
    r.raise_for_status()
    content = r.text

    blocks = re.findall(
        r'<a href="/mbn-menu/[^"]+" class="([^"]+)"[^>]*>.*?<div class="product-title">([^<]+)</div>',
        content, re.DOTALL,
    )
    seen = set()
    result = []
    for cls, title in blocks:
        if "sold-out" in cls:
            continue
        m = re.search(
            r'\(([A-Z][a-z]+(?: [a-z]+)+(?:\s+(?:ssp|subsp|var)\.[^)]*)?)\)', title
        )
        if not m:
            continue
        gs = genus_species(m.group(1).strip())
        if gs not in seen:
            seen.add(gs)
            result.append(gs)
    return result


def scrape_larnerseeds(url: str) -> list:
    """Return in-stock genus+species from Larner Seeds (Shopify).
    Titles begin with the scientific name: 'Genus species[, Common Name]'.
    Uses the Shopify /products.json API with pagination."""
    collection_base = re.sub(r'\?.*$', '', url.rstrip('/'))
    seen = set()
    result = []
    page = 1
    while True:
        api_url = f"{collection_base}/products.json?limit=250&page={page}"
        req = urllib.request.Request(
            api_url, headers={"User-Agent": "Mozilla/5.0 nature-in-sf/nursery-scraper"}
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            products = json.load(r)["products"]
        if not products:
            break
        for p in products:
            if not any(v.get("available") for v in p.get("variants", [])):
                continue
            title = p["title"]
            # Titles start with scientific name; common name follows a comma
            name = title.split(",")[0].strip()
            name = re.sub(r"\s*'[^']*'.*$", "", name)   # strip cultivar names
            name = re.sub(r"\s+var\.\s+\S+.*$", "", name)  # strip var.
            name = name.strip()
            gs = genus_species(name)
            if len(gs.split()) >= 2 and gs not in seen:
                seen.add(gs)
                result.append(gs)
        if len(products) < 250:
            break
        page += 1
        time.sleep(1)
    return result


SCRAPERS = {
    "oaktown":      scrape_oaktown,
    "sutro":        scrape_sutro,
    "heronshead":   scrape_heronshead,
    "missionblue":  scrape_missionblue,
    "larnerseeds":  scrape_larnerseeds,
}


def main():
    with open(DATA_DIR / "nurseries.json") as f:
        nurseries = json.load(f)

    with open(DATA_DIR / "sf_natives.csv") as f:
        sf_natives = {line.strip() for line in f if line.strip()}

    # Load previous inventory so failed nurseries keep their last-known data
    inv_path = DATA_DIR / "nursery_inventory.json"
    prev_by_species: dict = {}
    if inv_path.exists():
        with open(inv_path) as f:
            prev_by_species = json.load(f).get("bySpecies", {})

    # Build a reverse index: nursery_id → set of species it contributed previously
    prev_by_nursery: dict[str, set] = {}
    for gs, ids in prev_by_species.items():
        for nid in ids:
            prev_by_nursery.setdefault(nid, set()).add(gs)

    succeeded: set[str] = set()
    new_by_nursery: dict[str, set] = {}

    for nursery_id, info in nurseries.items():
        scraper = SCRAPERS.get(nursery_id)
        if not scraper or "inventoryUrl" not in info:
            continue
        print(f"Scraping {info['name']} ...", flush=True)
        try:
            species = scraper(info["inventoryUrl"])
            matched = {gs for gs in species if gs in sf_natives}
            new_by_nursery[nursery_id] = matched
            succeeded.add(nursery_id)
            print(f"  {len(species)} unique species, {len(matched)} SF native matches")
        except Exception as exc:
            print(f"  ERROR: {exc} — keeping previous data")
            new_by_nursery[nursery_id] = prev_by_nursery.get(nursery_id, set())

    # Rebuild bySpecies index
    by_species: dict[str, list] = {}
    for nursery_id, species_set in new_by_nursery.items():
        for gs in species_set:
            by_species.setdefault(gs, []).append(nursery_id)

    inventory = {
        "lastUpdated": date.today().isoformat(),
        "bySpecies": dict(sorted(by_species.items())),
    }

    with open(inv_path, "w") as f:
        json.dump(inventory, f, indent=2)
    print(f"Wrote {len(by_species)} species to {inv_path}")


if __name__ == "__main__":
    main()
