#!/usr/bin/env python3
"""
Fetch iNaturalist default_photo (square_url) and Wikipedia summary for
every taxon that will appear in the annotation-based host plant graph:
all Bay Area butterfly species + every host plant taxon tagged on
their observations. Also verifies/refreshes common names.

Outputs annotation_graph_photos.json: {taxon_id: {photo_url, common_name}}

Usage:
    python3 fetch_annotation_graph_photos.py
"""

import json
import time
import sys
import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).parent
INAT_TAXA = "https://api.inaturalist.org/v1/taxa"

bay_species = json.loads((DATA_DIR / "bay_area_butterfly_species.json").read_text())
host_data = json.loads((DATA_DIR / "host_plant_annotations.json").read_text())

all_ids = set(int(k) for k in bay_species.keys())
all_ids |= set(int(k) for k in host_data["host_taxa"].keys())
all_ids |= set(int(k) for k in host_data["butterfly_taxa"].keys())
all_ids = sorted(all_ids)
print(f"Total taxa needing photos: {len(all_ids)}")

BATCH = 30
result = {}

for i in range(0, len(all_ids), BATCH):
    batch = all_ids[i:i + BATCH]
    url = f"{INAT_TAXA}?id={','.join(map(str, batch))}&per_page={BATCH}"
    for attempt in range(5):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "nature-in-sf-map/1.0 (github.com/mertbozfakioglu/nature-in-sf)"}
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
            break
        except Exception as exc:
            if attempt < 4:
                wait = 2 ** (attempt + 2)
                print(f"\n  retry after {wait}s ({exc})")
                time.sleep(wait)
            else:
                raise
    for t in data.get("results", []):
        photo = t.get("default_photo") or {}
        result[t["id"]] = {
            "name": t.get("name"),
            "common_name": t.get("preferred_common_name", ""),
            "rank": t.get("rank"),
            "iconic_taxon_name": t.get("iconic_taxon_name"),
            "ancestor_ids": t.get("ancestor_ids", []),
            "photo_url": (photo.get("medium_url") or photo.get("square_url") or ""),
            "wikipedia_url": t.get("wikipedia_url", ""),
        }
    time.sleep(0.5)
    sys.stdout.write(f"\r  {min(i+BATCH, len(all_ids))}/{len(all_ids)}")
    sys.stdout.flush()

print()
with_photo = sum(1 for v in result.values() if v["photo_url"])
print(f"Taxa with photos: {with_photo}/{len(result)}")

outfile = DATA_DIR / "annotation_graph_photos.json"
outfile.write_text(json.dumps(result, indent=2))
print(f"Saved -> {outfile}")
