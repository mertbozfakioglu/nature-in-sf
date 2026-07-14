#!/usr/bin/env python3
"""
Fetch butterfly -> host plant edges from iNaturalist annotation data
(the "Host plant" observation field, id 254) for Papilionoidea
observations in the SF Bay Area that are annotated Life Stage =
Larva / Pupa / Egg (the stages where a host plant tag is meaningful).

Unlike insect-web's GloBI-derived butterfly_web_data.json, this graph
is built purely from what Bay Area iNaturalist observers actually
tagged on their own observations, not from the wider GloBI literature.

Usage:
    python3 fetch_host_plant_annotations.py

Requires Python 3.8+ and internet access. Rate-limits to ~1 req/sec.
"""

import urllib.request
import json
import time
import os
from collections import defaultdict

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
TAXON_ID = 47224  # Papilionoidea
PLACE_ID = 54321  # SF Bay Area
HOST_FIELD_ID = 254  # standard "Host plant" observation field

LIFE_STAGES = [
    (6, "Larva"),
    (4, "Pupa"),
    (7, "Egg"),
]


def fetch_page(term_value_id, id_above, retries=5):
    url = (
        f"https://api.inaturalist.org/v1/observations"
        f"?taxon_id={TAXON_ID}&place_id={PLACE_ID}"
        f"&term_id=1&term_value_id={term_value_id}"
        f"&per_page=200&order=asc&order_by=id"
    )
    if id_above:
        url += f"&id_above={id_above}"
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
                print(f"  retry after {wait}s ({exc})", flush=True)
                time.sleep(wait)
            else:
                raise


def main():
    # edge_counts[(butterfly_taxon_id, host_taxon_id)] = observation count
    edge_counts = defaultdict(int)
    butterfly_taxa = {}  # taxon_id -> {"name", "common_name", "rank"}
    host_taxa = {}       # taxon_id -> {"name", "common_name", "rank"}
    total_obs = 0

    for value_id, label in LIFE_STAGES:
        print(f"=== {label} ===", flush=True)
        id_above = 0
        stage_total = 0
        while True:
            data = fetch_page(value_id, id_above)
            results = data["results"]
            if not results:
                break
            for o in results:
                total_obs += 1
                stage_total += 1
                taxon = o.get("taxon") or {}
                if taxon.get("rank") != "species":
                    continue
                b_id = taxon["id"]
                butterfly_taxa[b_id] = {
                    "name": taxon["name"],
                    "common_name": taxon.get("preferred_common_name", ""),
                }
                for ofv in (o.get("ofvs") or []):
                    if ofv.get("field_id") != HOST_FIELD_ID:
                        continue
                    host_taxon = ofv.get("taxon")
                    if not host_taxon or not host_taxon.get("id"):
                        continue
                    h_id = host_taxon["id"]
                    host_taxa[h_id] = {
                        "name": host_taxon["name"],
                        "common_name": host_taxon.get("preferred_common_name", ""),
                        "rank": host_taxon.get("rank"),
                    }
                    edge_counts[(b_id, h_id)] += 1
            id_above = results[-1]["id"]
            print(f"  ...{stage_total} fetched (id_above={id_above})", flush=True)
            if len(results) < 200:
                break
            time.sleep(1.0)

    edges = [
        {"butterfly_id": b, "host_id": h, "count": c}
        for (b, h), c in edge_counts.items()
    ]

    out = {
        "total_obs_scanned": total_obs,
        "butterfly_taxa": butterfly_taxa,
        "host_taxa": host_taxa,
        "edges": edges,
    }
    outfile = os.path.join(DATA_DIR, "host_plant_annotations.json")
    with open(outfile, "w") as f:
        json.dump(out, f, indent=2)

    print(f"\nScanned {total_obs} observations")
    print(f"Butterfly species with host-tagged obs: {len(butterfly_taxa)}")
    print(f"Distinct host plant taxa: {len(host_taxa)}")
    print(f"Edges (butterfly-host pairs): {len(edges)}")
    print(f"Saved -> {outfile}")


if __name__ == "__main__":
    main()
