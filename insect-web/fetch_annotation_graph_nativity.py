#!/usr/bin/env python3
"""
Fetch California establishment means (native / introduced / unknown)
for every taxon in the annotation-based host-plant graph -- both the
butterfly species and their host plants.

iNaturalist only computes establishment_means against places with a
curated checklist; the custom "San Francisco Bay Area" place (54321)
used elsewhere in this graph has none, so this queries against
California (place_id 14) instead, same convention as
insect-web/fetch_nativity.py.

Outputs annotation_graph_nativity.json: {taxon_id: status}
where status is "native", "introduced", or "unknown".

Usage:
    python3 fetch_annotation_graph_nativity.py
"""

import json
import sys
import time
import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).parent
INAT_TAXA = "https://api.inaturalist.org/v1/taxa"
CA_PLACE_ID = 14

NATIVE_MEANS = {"native", "endemic"}
NON_NATIVE_MEANS = {"introduced", "naturalised", "naturalized", "invasive", "managed"}

bay_species = json.loads((DATA_DIR / "bay_area_butterfly_species.json").read_text())
host_data = json.loads((DATA_DIR / "host_plant_annotations.json").read_text())

all_ids = set(int(k) for k in bay_species.keys())
all_ids |= set(int(k) for k in host_data["host_taxa"].keys() if k.isdigit())
all_ids |= set(int(k) for k in host_data["butterfly_taxa"].keys())
all_ids = sorted(all_ids)
print(f"Total taxa needing nativity: {len(all_ids)}")

BATCH = 30
result = {}

for i in range(0, len(all_ids), BATCH):
    batch = all_ids[i:i + BATCH]
    url = f"{INAT_TAXA}?id={','.join(map(str, batch))}&place_id={CA_PLACE_ID}&per_page={BATCH}"
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
        em = (t.get("establishment_means") or {}).get("establishment_means", "")
        em = (em or "").lower()
        if em in NATIVE_MEANS:
            status = "native"
        elif em in NON_NATIVE_MEANS:
            status = "introduced"
        else:
            status = "unknown"
        result[t["id"]] = status
    time.sleep(0.5)
    sys.stdout.write(f"\r  {min(i+BATCH, len(all_ids))}/{len(all_ids)}")
    sys.stdout.flush()

print()
counts = {"native": 0, "introduced": 0, "unknown": 0}
for v in result.values():
    counts[v] += 1
print(f"native: {counts['native']}  introduced: {counts['introduced']}  unknown: {counts['unknown']}")

outfile = DATA_DIR / "annotation_graph_nativity.json"
outfile.write_text(json.dumps(result, indent=2))
print(f"Saved -> {outfile}")
