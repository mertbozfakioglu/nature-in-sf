#!/usr/bin/env python3
"""
For every butterfly species in the graph, check (within San Francisco,
place_id 854, matching the display scope) whether it has at least one
research-grade observation, and whether the taxon is geoprivacy-obscured
(iNaturalist hides/randomizes true coordinates for sensitive species,
e.g. Mission Blue -- Icaricia icarioides missionensis -- and other
locally-sensitive butterflies).

One request per species tells us both: quality_grade=research already
narrows to research-grade observations, and each result's own
taxon_geoprivacy field reports the taxon's global sensitivity flag
directly, no separate query needed. taxon_geoprivacy is a property of
the taxon (consistent across all its observations), unlike the
observation-level "obscured"/"geoprivacy" fields, which also reflect
an individual observer's own privacy choice on that one observation --
e.g. Vanessa atalanta (Red Admiral, common and unlisted) came back
"obscured": true on a sampled observation purely because that
observer chose to obscure it personally, while taxon_geoprivacy was
"open". Using taxon_geoprivacy avoids that false positive.

Outputs annotation_graph_quality.json:
    {taxon_id: {"research_grade_sf": bool, "geoprivacy_obscured": bool}}

Usage:
    python3 fetch_annotation_graph_quality.py
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
ids = sorted(int(k) for k in bay_species.keys())
print(f"Checking {len(ids)} butterfly species")


def fetch_one(taxon_id, retries=5):
    url = (f"{INAT_OBS}?taxon_id={taxon_id}&place_id={SF_PLACE_ID}"
           f"&quality_grade=research&per_page=1")
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "nature-in-sf-map/1.0 (github.com/mertbozfakioglu/nature-in-sf)"}
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except Exception as exc:
            if attempt < retries - 1:
                wait = 2 ** (attempt + 2)
                print(f"\n  retry after {wait}s ({exc})")
                time.sleep(wait)
            else:
                raise


result = {}
for i, tid in enumerate(ids):
    data = fetch_one(tid)
    results = data.get("results", [])
    if results:
        o = results[0]
        result[tid] = {
            "research_grade_sf": True,
            "geoprivacy_obscured": o.get("taxon_geoprivacy") in ("obscured", "private"),
        }
    else:
        result[tid] = {"research_grade_sf": False, "geoprivacy_obscured": False}
    time.sleep(0.3)
    sys.stdout.write(f"\r  {i+1}/{len(ids)}")
    sys.stdout.flush()

print()
rg = sum(1 for v in result.values() if v["research_grade_sf"])
obs = sum(1 for v in result.values() if v["geoprivacy_obscured"])
print(f"Research-grade in SF: {rg}/{len(result)}")
print(f"Geoprivacy-obscured: {obs}/{len(result)}")
for tid, v in result.items():
    if v["geoprivacy_obscured"]:
        print(f"  obscured: {tid} ({bay_species[str(tid)]['name']})")

outfile = DATA_DIR / "annotation_graph_quality.json"
outfile.write_text(json.dumps(result, indent=2))
print(f"Saved -> {outfile}")
