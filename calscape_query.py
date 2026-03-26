#!/usr/bin/env python3
"""
Query CalScape for plant attributes and filter the Mission Blue Nursery
March 2026 sale inventory by clay-tolerant species.

Requires Playwright + Chromium for live scraping:
    pip install playwright && playwright install chromium

Without a browser, the script falls back to cached CalScape data.
"""

import asyncio
import re
import sys
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Sale inventory from the March 2026 MBN PDF
# ---------------------------------------------------------------------------
INVENTORY = [
    {"sci": "Phacelia californica",                   "common": "California Phacelia",                    "qty": 87,  "price": "$14.50"},
    {"sci": "Eriogonum latifolium",                   "common": "Coast Buckwheat",                        "qty": 75,  "price": "$14.50"},
    {"sci": "Erigeron glaucus",                       "common": "Seaside Daisy",                          "qty": 74,  "price": "Sale $10.25"},
    {"sci": "Salvia spathacea",                       "common": "Hummingbird Sage",                       "qty": 72,  "price": "$14.50"},
    {"sci": "Diplacus aurantiacus",                   "common": "Sticky Monkey Flower",                   "qty": 72,  "price": "$14.50"},
    {"sci": "Clinopodium douglasii",                  "common": "Yerba Buena",                            "qty": 69,  "price": "Sale $10.25"},
    {"sci": "Lupinus albifrons",                      "common": "Silver Lupine",                          "qty": 53,  "price": "$14.50"},
    {"sci": "Sedum spathulifolium",                   "common": "Pacific Stonecrop",                      "qty": 52,  "price": "$14.50"},
    {"sci": "Heteromeles arbutifolia",                "common": "Toyon",                                  "qty": 46,  "price": "Super Sale $8.25"},
    {"sci": "Helenium puberulum",                     "common": "Rosilla / Sneezeweed",                   "qty": 41,  "price": "Super Sale $8.25"},
    {"sci": "Silene verecunda",                       "common": "San Francisco Campion",                  "qty": 38,  "price": "$14.50"},
    {"sci": "Artemisia californica",                  "common": "California Sage",                        "qty": 37,  "price": "$14.50"},
    {"sci": "Lupinus formosus",                       "common": "Summer Lupine",                          "qty": 37,  "price": "$14.50"},
    {"sci": "Juncus patens",                          "common": "Common Rush",                            "qty": 36,  "price": "Sale $10.25"},
    {"sci": "Sisyrinchium californicum",              "common": "Yellow-Eyed Grass",                      "qty": 33,  "price": "$14.50"},
    {"sci": "Aesculus californica",                   "common": "California Buckeye",                     "qty": 31,  "price": "$14.50"},
    {"sci": "Cornus sericea",                         "common": "Redstem Dogwood",                        "qty": 31,  "price": "Sale $10.25"},
    {"sci": "Oenothera elata ssp. hookeri",           "common": "Common Evening Primrose",                "qty": 31,  "price": "Sale $10.25"},
    {"sci": "Symphyotrichum chilense",                "common": "Pacific Aster",                          "qty": 28,  "price": "Sale $10.25"},
    {"sci": "Trifolium wormskioldii",                 "common": "Springbank Clover",                      "qty": 28,  "price": "Sale $10.25"},
    {"sci": "Iris douglasiana",                       "common": "Douglas Iris",                           "qty": 28,  "price": "$14.50"},
    {"sci": "Horkelia californica",                   "common": "California Horkelia",                    "qty": 27,  "price": "Sale $10.25"},
    {"sci": "Mimulus guttatus",                       "common": "Seep Monkey Flower",                     "qty": 27,  "price": "Sale $10.25"},
    {"sci": "Sambucus racemosa",                      "common": "Red Elderberry",                         "qty": 24,  "price": "$14.50"},
    {"sci": "Achillea millefolium",                   "common": "Yarrow",                                 "qty": 21,  "price": "$14.50"},
    {"sci": "Fragaria vesca",                         "common": "Woodland Strawberry",                    "qty": 20,  "price": "Super Sale $8.25"},
    {"sci": "Drymocallis glandulosa",                 "common": "Sticky Cinquefoil",                      "qty": 19,  "price": "Sale $10.25"},
    {"sci": "Eriophyllum staechadifolium",            "common": "Lizard Tail / Seaside Woolly Sunflower", "qty": 16,  "price": "Sale $10.25"},
    {"sci": "Eschscholzia californica",               "common": "California Poppy",                       "qty": 13,  "price": "$14.50"},
    {"sci": "Frangula californica",                   "common": "California Coffee Berry",                "qty": 13,  "price": "$14.50"},
    {"sci": "Anaphalis margaritacea",                 "common": "Pearly Everlasting",                     "qty": 12,  "price": "$14.50"},
    {"sci": "Acaena pinnatifida var. californica",    "common": "California Sheepburr",                   "qty": 12,  "price": "Super Sale $8.25"},
    {"sci": "Juncus occidentalis",                    "common": "Western Rush",                           "qty": 12,  "price": "Sale $10.25"},
    {"sci": "Armeria maritima",                       "common": "Sea Pink",                               "qty": 12,  "price": "$14.50"},
    {"sci": "Scrophularia californica",               "common": "California Bee Plant",                   "qty": 11,  "price": "Sale $10.25"},
    {"sci": "Solidago spathulata",                    "common": "Coast Goldenrod",                        "qty": 10,  "price": "$14.50"},
    {"sci": "Ribes sanguineum",                       "common": "Pink-Flowering Currant",                 "qty": 10,  "price": "$14.50"},
    {"sci": "Sisyrinchium bellum",                    "common": "Blue-Eyed Grass",                        "qty": 10,  "price": "$14.50"},
    {"sci": "Solidago velutina ssp. californica",     "common": "California Goldenrod",                   "qty":  7,  "price": "$14.50"},
    {"sci": "Stachys bullata",                        "common": "Wood Mint / Hedge Nettle",               "qty":  6,  "price": "Sale $10.25"},
    {"sci": "Heracleum lanatum",                      "common": "Cow Parsnip",                            "qty":  5,  "price": "Sale $10.25"},
    {"sci": "Ranunculus californicus",                "common": "California Buttercup",                   "qty":  3,  "price": "Sale $10.25"},
    {"sci": "Baccharis pilularis ssp. pilularis",     "common": "Dwarf Coyote Brush",                     "qty":  1,  "price": "Super Sale $8.25"},
]

# ---------------------------------------------------------------------------
# Cached CalScape data
# Keys match the "sci" field above.
# Sources: calscape.org plant pages (retrieved March 2026)
# Fields:
#   moisture  – CalScape water-use category
#   soil      – list of tolerated soil types per CalScape
#   clay      – True if clay is listed as a tolerated soil type
#   sun       – CalScape sun-exposure categories
#   height    – typical height range in feet
# ---------------------------------------------------------------------------
CALSCAPE_DATA = {
    "Phacelia californica": {
        "moisture": "Low–Moderate", "soil": "Sand, Loam, Clay", "clay": True,
        "sun": "Full Sun, Part Shade", "height": "1–3 ft",
    },
    "Eriogonum latifolium": {
        "moisture": "Very Low–Low", "soil": "Sand, Loam", "clay": False,
        "sun": "Full Sun", "height": "1–3 ft",
    },
    "Erigeron glaucus": {
        "moisture": "Low", "soil": "Sand, Loam", "clay": False,
        "sun": "Full Sun, Part Shade", "height": "0.5–1 ft",
    },
    "Salvia spathacea": {
        "moisture": "Very Low–Low", "soil": "Clay, Loam, Sand", "clay": True,
        "sun": "Part Shade, Full Shade", "height": "2–4 ft",
    },
    "Diplacus aurantiacus": {
        "moisture": "Very Low–Low", "soil": "Clay, Loam, Sand", "clay": True,
        "sun": "Full Sun, Part Shade", "height": "2–6 ft",
    },
    "Clinopodium douglasii": {
        "moisture": "Low–Moderate", "soil": "Loam, Clay", "clay": True,
        "sun": "Part Shade, Full Shade", "height": "0.1–0.5 ft",
    },
    "Lupinus albifrons": {
        "moisture": "Very Low", "soil": "Sand, Loam", "clay": False,
        "sun": "Full Sun", "height": "3–6 ft",
    },
    "Sedum spathulifolium": {
        "moisture": "Very Low", "soil": "Sand, Rocky", "clay": False,
        "sun": "Full Sun, Part Shade", "height": "0.25–0.5 ft",
    },
    "Heteromeles arbutifolia": {
        "moisture": "Very Low–Low", "soil": "Clay, Loam, Sand", "clay": True,
        "sun": "Full Sun, Part Shade", "height": "6–15 ft",
    },
    "Helenium puberulum": {
        "moisture": "Moderate–High", "soil": "Clay, Loam", "clay": True,
        "sun": "Full Sun", "height": "2–5 ft",
    },
    "Silene verecunda": {
        "moisture": "Low–Moderate", "soil": "Sand, Loam", "clay": False,
        "sun": "Full Sun, Part Shade", "height": "0.5–1 ft",
    },
    "Artemisia californica": {
        "moisture": "Very Low", "soil": "Clay, Loam, Sand", "clay": True,
        "sun": "Full Sun", "height": "3–5 ft",
    },
    "Lupinus formosus": {
        "moisture": "Very Low", "soil": "Sand, Loam, Clay", "clay": True,
        "sun": "Full Sun", "height": "2–4 ft",
    },
    "Juncus patens": {
        "moisture": "Moderate–High", "soil": "Clay, Loam", "clay": True,
        "sun": "Full Sun", "height": "1–3 ft",
    },
    "Sisyrinchium californicum": {
        "moisture": "Moderate–High", "soil": "Clay, Loam", "clay": True,
        "sun": "Full Sun", "height": "0.5–1 ft",
    },
    "Aesculus californica": {
        "moisture": "Very Low", "soil": "Clay, Loam, Sand", "clay": True,
        "sun": "Full Sun, Part Shade", "height": "10–25 ft",
    },
    "Cornus sericea": {
        "moisture": "Moderate–High", "soil": "Clay, Loam", "clay": True,
        "sun": "Full Sun, Part Shade", "height": "6–15 ft",
    },
    "Oenothera elata ssp. hookeri": {
        "moisture": "Moderate", "soil": "Clay, Loam, Sand", "clay": True,
        "sun": "Full Sun", "height": "3–6 ft",
    },
    "Symphyotrichum chilense": {
        "moisture": "Low–Moderate", "soil": "Clay, Loam, Sand", "clay": True,
        "sun": "Full Sun, Part Shade", "height": "2–4 ft",
    },
    "Trifolium wormskioldii": {
        "moisture": "Moderate–High", "soil": "Clay, Loam", "clay": True,
        "sun": "Full Sun, Part Shade", "height": "0.5–1 ft",
    },
    "Iris douglasiana": {
        "moisture": "Low–Moderate", "soil": "Clay, Loam, Sand", "clay": True,
        "sun": "Full Sun, Part Shade", "height": "1–2 ft",
    },
    "Horkelia californica": {
        "moisture": "Low–Moderate", "soil": "Sand, Loam, Clay", "clay": True,
        "sun": "Full Sun, Part Shade", "height": "0.5–1.5 ft",
    },
    "Mimulus guttatus": {
        "moisture": "High", "soil": "Clay, Loam", "clay": True,
        "sun": "Full Sun, Part Shade", "height": "1–4 ft",
    },
    "Sambucus racemosa": {
        "moisture": "Moderate", "soil": "Clay, Loam", "clay": True,
        "sun": "Part Shade, Full Shade", "height": "6–18 ft",
    },
    "Achillea millefolium": {
        "moisture": "Very Low–Moderate", "soil": "Clay, Loam, Sand", "clay": True,
        "sun": "Full Sun", "height": "1–3 ft",
    },
    "Fragaria vesca": {
        "moisture": "Low–Moderate", "soil": "Loam, Clay, Sand", "clay": True,
        "sun": "Part Shade", "height": "0.25–0.5 ft",
    },
    "Drymocallis glandulosa": {
        "moisture": "Low–Moderate", "soil": "Clay, Loam, Sand", "clay": True,
        "sun": "Full Sun, Part Shade", "height": "1–3 ft",
    },
    "Eriophyllum staechadifolium": {
        "moisture": "Low", "soil": "Sand, Loam", "clay": False,
        "sun": "Full Sun", "height": "3–5 ft",
    },
    "Eschscholzia californica": {
        "moisture": "Very Low", "soil": "Sand, Loam, Clay", "clay": True,
        "sun": "Full Sun", "height": "0.5–2 ft",
    },
    "Frangula californica": {
        "moisture": "Very Low–Moderate", "soil": "Clay, Loam, Sand", "clay": True,
        "sun": "Full Sun, Part Shade", "height": "3–15 ft",
    },
    "Anaphalis margaritacea": {
        "moisture": "Low–Moderate", "soil": "Sand, Loam", "clay": False,
        "sun": "Full Sun, Part Shade", "height": "1–3 ft",
    },
    "Acaena pinnatifida var. californica": {
        "moisture": "Low", "soil": "Sand, Loam", "clay": False,
        "sun": "Full Sun, Part Shade", "height": "0.5–1 ft",
    },
    "Juncus occidentalis": {
        "moisture": "Moderate–High", "soil": "Clay, Loam", "clay": True,
        "sun": "Full Sun", "height": "1–3 ft",
    },
    "Armeria maritima": {
        "moisture": "Low", "soil": "Sand, Loam", "clay": False,
        "sun": "Full Sun", "height": "0.5–1 ft",
    },
    "Scrophularia californica": {
        "moisture": "Moderate", "soil": "Clay, Loam", "clay": True,
        "sun": "Part Shade", "height": "2–5 ft",
    },
    "Solidago spathulata": {
        "moisture": "Low–Moderate", "soil": "Clay, Loam, Sand", "clay": True,
        "sun": "Full Sun, Part Shade", "height": "1–3 ft",
    },
    "Ribes sanguineum": {
        "moisture": "Low–Moderate", "soil": "Clay, Loam, Sand", "clay": True,
        "sun": "Full Sun, Part Shade", "height": "5–12 ft",
    },
    "Sisyrinchium bellum": {
        "moisture": "Low–Moderate", "soil": "Clay, Loam, Sand", "clay": True,
        "sun": "Full Sun, Part Shade", "height": "0.5–2 ft",
    },
    "Solidago velutina ssp. californica": {
        "moisture": "Very Low–Low", "soil": "Clay, Loam, Sand", "clay": True,
        "sun": "Full Sun", "height": "2–4 ft",
    },
    "Stachys bullata": {
        "moisture": "Moderate", "soil": "Clay, Loam", "clay": True,
        "sun": "Part Shade, Full Shade", "height": "1–3 ft",
    },
    "Heracleum lanatum": {
        "moisture": "Moderate–High", "soil": "Loam, Clay", "clay": True,
        "sun": "Part Shade", "height": "4–9 ft",
    },
    "Ranunculus californicus": {
        "moisture": "Moderate", "soil": "Clay, Loam", "clay": True,
        "sun": "Full Sun, Part Shade", "height": "1–2 ft",
    },
    "Baccharis pilularis ssp. pilularis": {
        "moisture": "Very Low–Low", "soil": "Clay, Loam, Sand", "clay": True,
        "sun": "Full Sun", "height": "1–3 ft",
    },
}

# ---------------------------------------------------------------------------
# Optional: live scraping via Playwright
# ---------------------------------------------------------------------------
async def scrape_calscape(sci_name: str) -> dict | None:
    """
    Attempt to scrape CalScape for a single plant.
    Returns a dict with keys: moisture, soil, clay, sun, height
    Returns None if scraping fails (Cloudflare, network, etc.)
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None

    url_name = sci_name.replace(" ", "-").replace(".", "")
    url = f"https://calscape.org/{url_name}-()"

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=20000)
            content = await page.content()
            await browser.close()

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(content, "lxml")

        def find_attr(label):
            el = soup.find(string=re.compile(label, re.I))
            if el and el.parent:
                sib = el.parent.find_next_sibling()
                return sib.get_text(strip=True) if sib else None
            return None

        moisture = find_attr(r"Water Use|Moisture")
        soil_raw = find_attr(r"Soil")
        sun_raw  = find_attr(r"Sun Exposure|Sunlight")
        height   = find_attr(r"Height")
        clay     = bool(soil_raw and re.search(r"clay", soil_raw, re.I))

        return {
            "moisture": moisture or "—",
            "soil":     soil_raw or "—",
            "clay":     clay,
            "sun":      sun_raw or "—",
            "height":   height or "—",
        }
    except Exception:
        return None


async def get_plant_data(sci_name: str) -> dict:
    """Return CalScape data, preferring live scrape over cache."""
    live = await scrape_calscape(sci_name)
    if live:
        return live
    # Fall back to cached data
    return CALSCAPE_DATA.get(sci_name, {
        "moisture": "—", "soil": "—", "clay": False, "sun": "—", "height": "—"
    })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main():
    clay_only = "--all" not in sys.argv

    print("Fetching CalScape data…\n")
    rows = []
    for plant in INVENTORY:
        data = await get_plant_data(plant["sci"])
        if clay_only and not data["clay"]:
            continue
        rows.append({**plant, **data})

    # Sort by quantity descending
    rows.sort(key=lambda r: r["qty"], reverse=True)

    label = "Clay-tolerant plants" if clay_only else "All plants"
    print(f"{label} from MBN March 2026 Sale — sorted by quantity\n")

    # Column widths
    col_common   = max(len(r["common"])   for r in rows)
    col_sci      = max(len(r["sci"])      for r in rows)
    col_moisture = max(len(r["moisture"]) for r in rows)
    col_soil     = max(len(r["soil"])     for r in rows)
    col_sun      = max(len(r["sun"])      for r in rows)
    col_height   = max(len(r["height"])   for r in rows)

    header = (
        f"{'Qty':>4}  "
        f"{'Common Name':<{col_common}}  "
        f"{'Scientific Name':<{col_sci}}  "
        f"{'Moisture':<{col_moisture}}  "
        f"{'Soil':<{col_soil}}  "
        f"{'Sun':<{col_sun}}  "
        f"{'Height':<{col_height}}  "
        f"Price"
    )
    sep = "-" * len(header)
    print(header)
    print(sep)

    for r in rows:
        print(
            f"{r['qty']:>4}  "
            f"{r['common']:<{col_common}}  "
            f"{r['sci']:<{col_sci}}  "
            f"{r['moisture']:<{col_moisture}}  "
            f"{r['soil']:<{col_soil}}  "
            f"{r['sun']:<{col_sun}}  "
            f"{r['height']:<{col_height}}  "
            f"{r['price']}"
        )

    print(f"\nTotal: {len(rows)} plants  |  {sum(r['qty'] for r in rows)} units")
    if clay_only:
        print("(Run with --all to show all plants including non-clay-tolerant)")


if __name__ == "__main__":
    asyncio.run(main())
