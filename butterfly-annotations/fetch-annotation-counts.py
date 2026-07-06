#!/usr/bin/env python3
"""
Count iNaturalist annotations on butterfly (Papilionoidea) observations
in the San Francisco Bay Area.

Uses per_page=0 requests to let the iNaturalist API return total_results
counts directly, instead of downloading all ~200k observations.

Usage:
    python3 fetch-annotation-counts.py

Requires Python 3.8+ and internet access. Rate-limits to ~1 req/sec.
"""

import urllib.request
import json
import time
import os

TAXON_ID = 47224  # Papilionoidea (Butterflies)
PLACE_ID = 54321  # San Francisco Bay Area, CA, US

# Controlled terms that apply to animal observations generally (and thus
# to butterflies): Life Stage, Sex, Alive or Dead, Evidence of Presence.
# ("Leaves", "Flowers and Fruits", "Established" only apply to plants /
# specific taxa and are skipped.)
TERMS = [
    {"id": 17, "label": "Alive or Dead", "values": [
        (18, "Alive"), (19, "Dead"), (20, "Cannot Be Determined"),
    ]},
    {"id": 1, "label": "Life Stage", "values": [
        (2, "Adult"), (3, "Teneral"), (4, "Pupa"), (5, "Nymph"),
        (6, "Larva"), (7, "Egg"), (8, "Juvenile"), (16, "Subimago"),
    ]},
    {"id": 9, "label": "Sex", "values": [
        (10, "Female"), (11, "Male"), (20, "Cannot Be Determined"),
    ]},
    {"id": 22, "label": "Evidence of Presence", "values": [
        (23, "Feather"), (24, "Organism"), (25, "Scat"), (29, "Gall"),
        (26, "Track"), (27, "Bone"), (28, "Molt"), (30, "Egg"),
        (31, "Hair"), (32, "Leafmine"), (35, "Construction"),
    ]},
]


def fetch_count(term_id=None, value_id=None, retries=5):
    url = (
        f"https://api.inaturalist.org/v1/observations"
        f"?taxon_id={TAXON_ID}&place_id={PLACE_ID}&per_page=0"
    )
    if term_id is not None:
        url += f"&term_id={term_id}&term_value_id={value_id}"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "nature-in-sf-map/1.0 (github.com/mertbozfakioglu/nature-in-sf)"}
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())["total_results"]
        except Exception as exc:
            if attempt < retries - 1:
                wait = 2 ** (attempt + 2)
                print(f"  Retry after {wait}s ({exc})", flush=True)
                time.sleep(wait)
            else:
                raise


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    total = fetch_count()
    print(f"Total butterfly (Papilionoidea) observations in SF Bay Area: {total}\n")

    results = {"total_observations": total, "terms": []}

    for term in TERMS:
        term_result = {"term": term["label"], "term_id": term["id"], "values": []}
        print(f"== {term['label']} (term_id={term['id']}) ==")
        for value_id, value_label in term["values"]:
            count = fetch_count(term["id"], value_id)
            print(f"  {value_label:30s} (value_id={value_id}): {count}")
            term_result["values"].append({"value": value_label, "value_id": value_id, "count": count})
            time.sleep(1.0)
        results["terms"].append(term_result)
        print()

    os.makedirs("data", exist_ok=True)
    with open("data/annotation-counts.json", "w") as f:
        json.dump(results, f, indent=2)
    print("Saved -> data/annotation-counts.json")


if __name__ == "__main__":
    main()
