"""
Fetch iNaturalist default_photo square_url for each taxon in the web data.
Uses taxon IDs already cached in common_names_cache.json, batches 30 at a time.
Updates butterfly_web_data.json with a photo_url field on each node.
"""
import json, time, sys, requests
from pathlib import Path

DATA_DIR  = Path(__file__).parent
INAT_TAXA = "https://api.inaturalist.org/v1/taxa"

cache = json.loads((DATA_DIR / "common_names_cache.json").read_text())
id_to_name = {v["id"]: k for k, v in cache.items() if v.get("id")}
print(f"Taxa with IDs: {len(id_to_name)}")

photo_map: dict[str, str] = {}
ids       = list(id_to_name.keys())
BATCH     = 30

for i in range(0, len(ids), BATCH):
    batch = ids[i : i + BATCH]
    try:
        r = requests.get(
            INAT_TAXA,
            params={"id": ",".join(map(str, batch)), "per_page": BATCH},
            timeout=20,
            headers={"User-Agent": "nature-in-sf/1.0 (mertbozfakioglu@gmail.com)"},
        )
        r.raise_for_status()
        for res in r.json().get("results", []):
            name  = id_to_name.get(res["id"])
            photo = res.get("default_photo") or {}
            if name and photo.get("square_url"):
                photo_map[name] = photo["square_url"]
    except Exception as e:
        print(f"\n  Error batch {i//BATCH}: {e}")
    time.sleep(0.3)
    sys.stdout.write(f"\r  {min(i+BATCH, len(ids))}/{len(ids)}")
    sys.stdout.flush()

print(f"\nPhotos found: {len(photo_map)}/{len(id_to_name)}")

data = json.loads((DATA_DIR / "butterfly_web_data.json").read_text())
hits = 0
for node in data["nodes"]:
    url = photo_map.get(node["id"], "")
    node["photo_url"] = url
    if url:
        hits += 1
print(f"Nodes with photos: {hits}/{len(data['nodes'])}")
(DATA_DIR / "butterfly_web_data.json").write_text(json.dumps(data))
print("Saved butterfly_web_data.json")
