"""
Second-pass fetch: query GloBI for animal↔animal interactions
involving the insect species found in the SF plant interaction dataset.
"""
import json
import time
import sys
import requests
from collections import Counter
from pathlib import Path

DATA_DIR = Path(__file__).parent
RAW_FILE  = DATA_DIR / "raw_interactions.json"
OUT_FILE  = DATA_DIR / "raw_animal_interactions.json"
GLOBI_URL = "https://api.globalbioticinteractions.org/interaction"

ANIMAL_ITYPES = ["eats", "preysOn", "preyedUponBy", "parasiteOf", "parasitoidOf",
                 "hasParasite", "mutualistOf", "interactsWith"]

FIELDS = [
    "source_taxon_name", "source_taxon_path",
    "interaction_type",
    "target_taxon_name", "target_taxon_path",
]

def is_insect(path):
    return "Insecta" in (path or "")

def is_animal(path):
    return any(k in (path or "") for k in ("Insecta", "Arachnida", "Aves", "Mammalia", "Amphibia", "Reptilia"))

def query_globi(taxon: str, role: str, limit: int = 150) -> list[dict]:
    key = "sourceTaxon" if role == "source" else "targetTaxon"
    params = {key: taxon, "fields": ",".join(FIELDS), "limit": limit, "type": "json.v2"}
    try:
        r = requests.get(GLOBI_URL, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"  [warn] {taxon}: {e}", file=sys.stderr)
        return []

# load plant dataset to find insect species
plant_data = json.loads(RAW_FILE.read_text())
insect_counts: Counter = Counter()
for rec in plant_data:
    if is_insect(rec.get("source_taxon_path", "")):
        insect_counts[rec["source_taxon_name"]] += 1
    if is_insect(rec.get("target_taxon_path", "")):
        insect_counts[rec["target_taxon_name"]] += 1

# query top 100 most-interacting insect species
top_insects = [name for name, _ in insect_counts.most_common(100)]
print(f"Querying {len(top_insects)} top insect species for animal↔animal interactions…")

all_recs = []
seen_keys = set()

def add(records):
    for r in records:
        if not is_animal(r.get("source_taxon_path", "")) or not is_animal(r.get("target_taxon_path", "")):
            continue
        key = (r.get("source_taxon_name",""), r.get("interaction_type",""), r.get("target_taxon_name",""))
        if key not in seen_keys:
            seen_keys.add(key)
            all_recs.append(r)

for i, insect in enumerate(top_insects):
    sys.stdout.write(f"\r  {i+1}/{len(top_insects)}: {insect:<55}")
    sys.stdout.flush()
    add(query_globi(insect, "source", 150))
    add(query_globi(insect, "target", 150))
    time.sleep(0.15)

print(f"\nAnimal↔Animal interactions: {len(all_recs)}")
OUT_FILE.write_text(json.dumps(all_recs, indent=2))
print(f"Saved → {OUT_FILE}")
