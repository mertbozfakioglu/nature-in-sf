#!/usr/bin/env python3
"""
Fetch butterfly -> host plant edges from iNaturalist annotation data
for Papilionoidea observations in the SF Bay Area that are annotated
Life Stage = Larva / Pupa / Egg (the stages where a host plant tag is
meaningful).

Unlike insect-web's GloBI-derived butterfly_web_data.json, this graph
is built purely from what Bay Area iNaturalist observers actually
tagged on their own observations, not from the wider GloBI literature.

Pulls from five observation fields:
  - 254  "Host plant"                          (taxon)
  - 6586 "Host Plant ID"                       (taxon)
  - 499  "Insect Host Plant"                   (taxon)
  - 9324 "Larval plant"                        (free text)
  - 4513 "Caterpillar host plant (text field)" (free text)

("Insect-Host Plant Interaction", field 1673, is deliberately excluded:
despite its name it records the insect's activity/stage when observed
-- e.g. "Ovipositing", "Late Instar" -- not the host plant's identity.)

Free-text fields are resolved to iNaturalist taxa via a name search,
cached in text_host_taxon_cache.json across runs. Unresolvable text
(no confident Plantae match) still gets a node, keyed by its text
value instead of a taxon id, so the tag isn't silently dropped.

Usage:
    python3 fetch_host_plant_annotations.py

Requires Python 3.8+ and internet access. Rate-limits to ~1 req/sec.
"""

import urllib.request
import urllib.parse
import json
import re
import time
import os
from collections import defaultdict

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
TAXON_ID = 47224  # Papilionoidea
PLACE_ID = 54321  # SF Bay Area
TEXT_CACHE_FILE = os.path.join(DATA_DIR, "text_host_taxon_cache.json")

TAXON_FIELD_IDS = {254, 6586, 499}
TEXT_FIELD_IDS = {9324, 4513}

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
    return fetch_json(url, retries)


def fetch_json(url, retries=5):
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


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def resolve_text_to_taxon(raw_text, cache):
    key = raw_text.strip().lower()
    if key in cache:
        return cache[key]
    url = f"https://api.inaturalist.org/v1/taxa?q={urllib.parse.quote(raw_text)}&per_page=10"
    data = fetch_json(url)
    result = None
    plant_results = [
        t for t in data.get("results", [])
        if t.get("iconic_taxon_name") == "Plantae" and t.get("rank_level", 100) <= 20
    ]
    for t in plant_results:
        if t["name"].lower() == key or t.get("preferred_common_name", "").lower() == key:
            result = t
            break
    if result is None and plant_results:
        result = plant_results[0]
    if result:
        cache[key] = {
            "taxon_id": result["id"],
            "name": result["name"],
            "common_name": result.get("preferred_common_name", ""),
            "rank": result.get("rank"),
        }
    else:
        cache[key] = None
    time.sleep(0.5)
    return cache[key]


def main():
    # edge_counts[(butterfly_taxon_id, host_key)] = observation count
    # host_key is an int taxon id, or a "text:<slug>" string for
    # unresolved free-text host plant mentions.
    edge_counts = defaultdict(int)
    butterfly_taxa = {}  # taxon_id -> {"name", "common_name"}
    host_taxa = {}       # host_key -> {"name", "common_name", "rank"}
    total_obs = 0
    rolled_up = 0
    pending_text = []  # (b_id, raw_text)

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
                # Many Bay Area butterflies (e.g. Battus philenor hirsuta,
                # the California Pipevine Swallowtail) are identified to
                # subspecies/variety, not bare species. min_species_taxon_id
                # is the nearest species-or-finer ancestor's id, which equals
                # the taxon's own id when it's already species rank -- so
                # this rolls subspecies/variety/form up to their species
                # without dropping genuinely coarse (genus/family) IDs,
                # which have no min_species_taxon_id at all.
                b_id = taxon.get("min_species_taxon_id")
                if not b_id:
                    continue
                if b_id != taxon.get("id"):
                    rolled_up += 1
                butterfly_taxa.setdefault(b_id, {
                    "name": taxon["name"],
                    "common_name": taxon.get("preferred_common_name", ""),
                })
                for ofv in (o.get("ofvs") or []):
                    field_id = ofv.get("field_id")
                    if field_id in TAXON_FIELD_IDS:
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
                    elif field_id in TEXT_FIELD_IDS:
                        raw = (ofv.get("value") or "").strip()
                        if raw:
                            pending_text.append((b_id, raw))
            id_above = results[-1]["id"]
            print(f"  ...{stage_total} fetched (id_above={id_above})", flush=True)
            if len(results) < 200:
                break
            time.sleep(1.0)

    # ── resolve free-text host mentions to taxa ────────────────────────────
    cache = {}
    if os.path.exists(TEXT_CACHE_FILE):
        cache = json.loads(open(TEXT_CACHE_FILE).read())

    resolved_n = unresolved_n = 0
    for b_id, raw in pending_text:
        match = resolve_text_to_taxon(raw, cache)
        if match:
            h_id = match["taxon_id"]
            host_taxa[h_id] = {
                "name": match["name"],
                "common_name": match["common_name"],
                "rank": match["rank"],
            }
            resolved_n += 1
        else:
            h_id = f"text:{slug(raw)}"
            host_taxa[h_id] = {"name": raw, "common_name": "", "rank": "unresolved_text"}
            unresolved_n += 1
        edge_counts[(b_id, h_id)] += 1

    with open(TEXT_CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2, sort_keys=True)

    print(f"\nFree-text host mentions: {len(pending_text)} "
          f"({resolved_n} resolved to a taxon, {unresolved_n} kept as unresolved text)")

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

    print(f"\nScanned {total_obs} observations ({rolled_up} rolled up from subspecies/variety to species)")
    print(f"Butterfly species with host-tagged obs: {len(butterfly_taxa)}")
    print(f"Distinct host plant taxa: {len(host_taxa)}")
    print(f"Edges (butterfly-host pairs): {len(edges)}")
    print(f"Saved -> {outfile}")


if __name__ == "__main__":
    main()
