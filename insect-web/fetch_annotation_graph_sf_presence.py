#!/usr/bin/env python3
"""
Check which taxa in the annotation-based host-plant graph (built
against the wider Bay Area place) have actually been observed within
San Francisco County itself (place_id 854, same place used by
checkerspot-map/fetch-data.py).

This does not change the underlying Bay Area relationship data at
all -- it just produces a per-taxon boolean lookup so the graph page
can filter its display down to SF-local nodes without deleting or
re-fetching anything else.

Outputs annotation_graph_sf_presence.json: {taxon_id: true/false}

Usage:
    python3 fetch_annotation_graph_sf_presence.py
"""

import json
import sys
import time
import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).parent
INAT_OBS = "https://api.inaturalist.org/v1/observations"
SF_PLACE_ID = 854  # San Francisco County, CA

bay_species = json.loads((DATA_DIR / "bay_area_butterfly_species.json").read_text())
host_data = json.loads((DATA_DIR / "host_plant_annotations.json").read_text())

all_ids = set(int(k) for k in bay_species.keys())
all_ids |= set(int(k) for k in host_data["host_taxa"].keys() if k.isdigit())
all_ids |= set(int(k) for k in host_data["butterfly_taxa"].keys())
all_ids = sorted(all_ids)
print(f"Total taxa to check for SF presence: {len(all_ids)}")


def fetch_count(taxon_id, retries=5):
    url = f"{INAT_OBS}?taxon_id={taxon_id}&place_id={SF_PLACE_ID}&per_page=0"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "nature-in-sf-map/1.0 (github.com/mertbozfakioglu/nature-in-sf)"}
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())["total_results"]
        except Exception as exc:
            if attempt < retries - 1:
                wait = 2 ** (attempt + 2)
                print(f"\n  retry after {wait}s ({exc})")
                time.sleep(wait)
            else:
                raise


result = {}
for i, tid in enumerate(all_ids):
    count = fetch_count(tid)
    result[tid] = count > 0
    time.sleep(0.3)
    sys.stdout.write(f"\r  {i+1}/{len(all_ids)}")
    sys.stdout.flush()

print()
sf_yes = sum(1 for v in result.values() if v)
print(f"Observed in SF: {sf_yes}/{len(result)}")

outfile = DATA_DIR / "annotation_graph_sf_presence.json"
outfile.write_text(json.dumps(result, indent=2))
print(f"Saved -> {outfile}")
