#!/usr/bin/env python3
"""
Refresh cached observation data from iNaturalist for all three species.
Run this script periodically to update the JSON files in data/.

Usage:
    python3 fetch-data.py

Requires Python 3.8+ and internet access. Rate-limits to ~1 req/sec.
If iNaturalist returns 503, wait a few minutes and retry.
"""

import urllib.request
import json
import time
import sys
import os

SF_PLACE_ID = 854  # San Francisco County, CA

SPECIES = [
    {
        "name": "Variable Checkerspot",
        "taxon_id": 50892,
        "output": "data/variable-checkerspot.json",
    },
    {
        "name": "Pipevine Swallowtail",
        "taxon_id": 49972,
        "output": "data/pipevine-swallowtail.json",
    },
    {
        "name": "Coastal Green Hairstreak",
        "taxon_id": 210423,
        "output": "data/coastal-green-hairstreak.json",
    },
    {
        "name": "California Pipevine (plant)",
        "taxon_id": 52950,   # Aristolochia californica on iNaturalist
        "output": "data/ca-pipevine-plant.json",
    },
]

LARVA_ATTR_ID  = 1  # Life Stage controlled attribute
LARVA_VALUE_ID = 6  # Larva controlled value


def fetch_page(taxon_id, page, retries=4):
    url = (
        f"https://api.inaturalist.org/v1/observations"
        f"?taxon_id={taxon_id}&place_id={SF_PLACE_ID}"
        f"&per_page=200&page={page}&order=asc&order_by=observed_on"
    )
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "nature-in-sf-map/1.0 (github.com/mertbozfakioglu/nature-in-sf)"}
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception as exc:
            if attempt < retries - 1:
                wait = 2 ** (attempt + 2)
                print(f"  Retry {attempt+1} after {wait}s ({exc})", flush=True)
                time.sleep(wait)
            else:
                raise


def fetch_species(spec):
    name     = spec["name"]
    taxon_id = spec["taxon_id"]
    outfile  = spec["output"]

    print(f"\nFetching {name} (taxon {taxon_id})…", flush=True)
    obs   = []
    page  = 1
    total = None

    while True:
        data = fetch_page(taxon_id, page)
        if total is None:
            total = data["total_results"]
        results = data["results"]

        for o in results:
            if not o.get("location") or not o.get("observed_on"):
                continue
            try:
                lat, lng = o["location"].split(",")
                lat, lng = float(lat), float(lng)
            except (ValueError, AttributeError):
                continue
            year = int(o["observed_on"][:4])
            if not (2000 <= year <= 2100):
                continue

            is_larva = any(
                a.get("controlled_attribute", {}).get("id") == LARVA_ATTR_ID
                and a.get("controlled_value", {}).get("id") == LARVA_VALUE_ID
                for a in (o.get("annotations") or [])
            )

            obs.append({
                "id":     o["id"],
                "lat":    lat,
                "lng":    lng,
                "year":   year,
                "isLarva": is_larva,
                "date":   o["observed_on"],
                "url":    o["uri"],
            })

        print(
            f"  Page {page}: {len(results)} results — {len(obs)}/{total} total",
            flush=True,
        )

        if len(results) < 200 or len(obs) >= total:
            break
        page += 1
        time.sleep(1.0)  # be polite to the API

    # Summary
    by_yr = {}
    for o in obs:
        by_yr.setdefault(o["year"], 0)
        by_yr[o["year"]] += 1
    larva_n = sum(1 for o in obs if o["isLarva"])
    print(f"  Done: {len(obs)} observations, {larva_n} larva")
    print(f"  Years: {dict(sorted(by_yr.items()))}")

    os.makedirs(os.path.dirname(outfile) or ".", exist_ok=True)
    with open(outfile, "w") as f:
        json.dump(obs, f)
    print(f"  Saved → {outfile}")
    return obs


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    targets = sys.argv[1:] or [s["name"].lower().split()[0] for s in SPECIES]

    for spec in SPECIES:
        key = spec["name"].lower().split()[0]
        if key in targets or spec["name"].lower() in " ".join(targets).lower():
            try:
                fetch_species(spec)
            except Exception as exc:
                print(f"  ERROR fetching {spec['name']}: {exc}", file=sys.stderr)
                sys.exit(1)

    print("\nAll done.")


if __name__ == "__main__":
    main()
