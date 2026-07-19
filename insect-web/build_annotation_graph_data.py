#!/usr/bin/env python3
"""
Merge bay_area_butterfly_species.json + host_plant_annotations.json +
annotation_graph_photos.json into annotation_graph_data.json, the data
file for host-plant-annotations-graph.html.

Nodes = every Bay Area butterfly species (all 120, whether or not it
has a host-plant tag) + every host plant taxon that appears in a
"Host plant" annotation. Edges = butterfly -> host plant, weighted by
how many observations carry that tag.
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).parent

bay_species = json.loads((DATA_DIR / "bay_area_butterfly_species.json").read_text())
host_data = json.loads((DATA_DIR / "host_plant_annotations.json").read_text())
photos = json.loads((DATA_DIR / "annotation_graph_photos.json").read_text())

BFLY_FAMILY_IDS = {
    47223: "Papilionidae",
    48508: "Pieridae",
    47923: "Lycaenidae",
    47922: "Nymphalidae",
    47653: "Hesperiidae",
    59166: "Riodinidae",
}


def bfly_family(taxon_id):
    anc = set(photos.get(str(taxon_id), {}).get("ancestor_ids", []))
    for fid, name in BFLY_FAMILY_IDS.items():
        if fid in anc:
            return name
    return "Unknown"


def plant_family(taxon_id):
    info = photos.get(str(taxon_id), {})
    if info.get("rank") == "family":
        return info["name"]
    # walk ancestor chain from most specific to least, looking up each
    # ancestor's own rank via a second pass isn't available here, so
    # fall back to "Unknown" — family coloring is a nice-to-have, not
    # required for the plant nodes since they're colored uniformly.
    return "Unknown"


nodes = []
node_ids = set()

for tid_str, info in bay_species.items():
    tid = int(tid_str)
    p = photos.get(tid_str, {})
    nodes.append({
        "id": f"b{tid}",
        "taxon_id": tid,
        "type": "butterfly",
        "name": info["name"],
        "common_name": info.get("common_name") or p.get("common_name", ""),
        "family": bfly_family(tid),
        "bay_area_obs": info.get("obs_count", 0),
        "photo_url": p.get("photo_url", ""),
        "wikipedia_url": p.get("wikipedia_url", ""),
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
        "family": plant_family(tid) if tid else "Unknown",
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
print(f"Saved -> {outfile}")
