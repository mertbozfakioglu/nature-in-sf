#!/usr/bin/env python3
"""
Merge bay_area_butterfly_species.json + host_plant_annotations.json +
annotation_graph_photos.json + annotation_graph_nativity.json into
annotation_graph_data.json, the data file for
host-plant-annotations-graph.html.

Nodes = every Bay Area butterfly species (all 120, whether or not it
has a host-plant tag) + every host plant taxon that appears in a host
plant annotation. Edges = butterfly -> host plant, weighted by how
many observations carry that tag. Every node carries a native_status
("native" / "introduced" / "unknown", per iNaturalist's California
checklist) instead of a taxonomic family.
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).parent

bay_species = json.loads((DATA_DIR / "bay_area_butterfly_species.json").read_text())
host_data = json.loads((DATA_DIR / "host_plant_annotations.json").read_text())
photos = json.loads((DATA_DIR / "annotation_graph_photos.json").read_text())
nativity = json.loads((DATA_DIR / "annotation_graph_nativity.json").read_text())
sf_presence = json.loads((DATA_DIR / "annotation_graph_sf_presence.json").read_text())
quality = json.loads((DATA_DIR / "annotation_graph_quality.json").read_text())


def native_status(taxon_id):
    if taxon_id is None:
        return "unknown"
    return nativity.get(str(taxon_id), "unknown")


def sf_observed(taxon_id):
    # Unresolved free-text host mentions have no taxon id to check against;
    # treat as not confirmed in SF rather than guessing.
    if taxon_id is None:
        return False
    return bool(sf_presence.get(str(taxon_id), False))


# Display-only overrides, keyed by species-level taxon id. The graph tracks
# butterflies at species rank (see fetch_host_plant_annotations.py's
# subspecies rollup), but the species-level identity isn't always what's
# actually flying in SF -- Icaricia icarioides (Boisduval's Blue) locally
# means the subspecies I. i. missionensis, Mission Blue. This only swaps
# what's displayed (name/common name/photo/Wikipedia link); taxon_id stays
# the species id so it still lines up with the nativity/sf_presence/quality
# lookups and the host-plant edges, all keyed at species rank.
DISPLAY_OVERRIDES = {
    520457: {
        "name": "Icaricia icarioides ssp. missionensis",
        "common_name": "Mission Blue",
        "photo_url": "https://inaturalist-open-data.s3.amazonaws.com/photos/486126130/medium.jpeg",
        "wikipedia_url": "http://en.wikipedia.org/wiki/Mission_blue_butterfly",
    },
}

# Species-level taxa excluded from the butterfly node set entirely (as
# opposed to DISPLAY_OVERRIDES, which just renames/re-photos a node).
# 520456 = Icaricia acmon (Acmon Blue): per user, SF's local population is
# a distinct subspecies, so the species-level node is excluded rather than
# risk representing it as a generic Acmon Blue.
EXCLUDED_BUTTERFLY_TAXA = {520456}


nodes = []
node_ids = set()

for tid_str, info in bay_species.items():
    tid = int(tid_str)
    if tid in EXCLUDED_BUTTERFLY_TAXA:
        continue
    p = photos.get(tid_str, {})
    q = quality.get(tid_str, {})
    override = DISPLAY_OVERRIDES.get(tid, {})
    nodes.append({
        "id": f"b{tid}",
        "taxon_id": tid,
        "type": "butterfly",
        "name": override.get("name", info["name"]),
        "common_name": override.get("common_name") or info.get("common_name") or p.get("common_name", ""),
        "native_status": native_status(tid),
        "sf_observed": sf_observed(tid),
        "research_grade_sf": q.get("research_grade_sf", False),
        "geoprivacy_obscured": q.get("geoprivacy_obscured", False),
        "bay_area_obs": info.get("obs_count", 0),
        "photo_url": override.get("photo_url") or p.get("photo_url", ""),
        "wikipedia_url": override.get("wikipedia_url") or p.get("wikipedia_url", ""),
    })
    node_ids.add(tid)

host_node_id = {}  # host_taxa key (str) -> node id used in edges

for tid_str, info in host_data["host_taxa"].items():
    is_unresolved_text = not tid_str.isdigit()
    if is_unresolved_text:
        tid = None
        node_id = f"h_{tid_str.split(':', 1)[-1]}"
        photo_key = None
    else:
        tid = int(tid_str)
        node_id = f"h{tid}"
        photo_key = tid_str
        if tid in node_ids:
            host_node_id[tid_str] = f"h{tid}"
            continue
    p = photos.get(photo_key, {}) if photo_key else {}
    nodes.append({
        "id": node_id,
        "taxon_id": tid,
        "type": "plant",
        "name": info["name"],
        "common_name": info.get("common_name") or p.get("common_name", ""),
        "native_status": native_status(tid),
        "sf_observed": sf_observed(tid),
        "bay_area_obs": 0,
        "photo_url": p.get("photo_url", ""),
        "wikipedia_url": p.get("wikipedia_url", ""),
        "unresolved_text": is_unresolved_text,
    })
    if tid:
        node_ids.add(tid)
    host_node_id[tid_str] = node_id

bfly_node_ids = {n["id"] for n in nodes if n["type"] == "butterfly"}
edges = []
for e in host_data["edges"]:
    source = f"b{e['butterfly_id']}"
    if source not in bfly_node_ids:
        # Butterfly taxon isn't in bay_area_butterfly_species.json (e.g. an
        # observation whose current identification is coarser than species
        # despite carrying a stray min_species_taxon_id) -- drop the edge
        # rather than reference a node that doesn't exist.
        print(f"  Skipping edge: butterfly taxon {e['butterfly_id']} not in Bay Area species list")
        continue
    edges.append({
        "source": source,
        "target": host_node_id[str(e['host_id'])],
        "count": e["count"],
    })

deg = {}
for e in edges:
    deg[e["source"]] = deg.get(e["source"], 0) + 1
    deg[e["target"]] = deg.get(e["target"], 0) + 1
for n in nodes:
    n["degree"] = deg.get(n["id"], 0)

out = {
    "nodes": nodes,
    "edges": edges,
    "meta": {
        "total_obs_scanned": host_data["total_obs_scanned"],
        "bay_area_butterfly_species": len(bay_species),
        "species_with_host_tags": len(host_data["butterfly_taxa"]),
        "host_plant_taxa": len(host_data["host_taxa"]),
    },
}

outfile = DATA_DIR / "annotation_graph_data.json"
outfile.write_text(json.dumps(out))
print(f"Nodes: {len(nodes)} ({sum(1 for n in nodes if n['type']=='butterfly')} butterflies, "
      f"{sum(1 for n in nodes if n['type']=='plant')} plants)")
print(f"Edges: {len(edges)}")
print(f"Nodes with photos: {sum(1 for n in nodes if n['photo_url'])}/{len(nodes)}")
ns = {"native": 0, "introduced": 0, "unknown": 0}
for n in nodes:
    ns[n["native_status"]] += 1
print(f"Native status: {ns}")
print(f"Observed in SF: {sum(1 for n in nodes if n['sf_observed'])}/{len(nodes)}")
bflies = [n for n in nodes if n["type"] == "butterfly"]
print(f"Butterflies research-grade in SF: {sum(1 for n in bflies if n['research_grade_sf'])}/{len(bflies)}")
print(f"Butterflies geoprivacy-obscured: {sum(1 for n in bflies if n['geoprivacy_obscured'])}/{len(bflies)}")
print(f"Saved -> {outfile}")
