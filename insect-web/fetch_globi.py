"""
Fetch GloBI interactions for SF native plants.
Queries both plant↔insect and insect↔animal interactions.
Writes raw_interactions.json with all results.
"""
import json
import time
import requests
import csv
import sys
from pathlib import Path

GLOBI_URL = "https://api.globalbioticinteractions.org/interaction"
DATA_DIR = Path(__file__).parent
NATIVES_CSV = DATA_DIR.parent / "sf-parks-biodiversity/data/sf_natives.csv"
OUT_FILE = DATA_DIR / "raw_interactions.json"

# GloBI interaction types we care about
INTERACTION_TYPES = [
    "pollinates",
    "parasiteOf",
    "parasitoidOf",
    "hostOf",
    "eats",
    "preysOn",
    "flowersVisitedBy",
    "visitsFlowersOf",
    "mutualistOf",
    "preyedUponBy",
    "hasParasite",
    "hasHost",
    "laysEggsOn",
]

FIELDS = [
    "source_taxon_name",
    "source_taxon_path",
    "source_taxon_path_ids",
    "interaction_type",
    "target_taxon_name",
    "target_taxon_path",
    "target_taxon_path_ids",
    "latitude",
    "longitude",
    "study_citation",
]


def read_plants(csv_path: Path) -> list[str]:
    plants = []
    with open(csv_path) as f:
        for line in f:
            name = line.strip()
            if name:
                plants.append(name)
    seen = set()
    unique = []
    for p in plants:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def query_globi(taxon: str, taxon_role: str = "source", limit: int = 200) -> list[dict]:
    """Query GloBI for one taxon. taxon_role: 'source' or 'target'."""
    param_key = "sourceTaxon" if taxon_role == "source" else "targetTaxon"
    params = {
        param_key: taxon,
        "fields": ",".join(FIELDS),
        "limit": limit,
        "type": "json.v2",  # returns flat list of objects
    }
    try:
        r = requests.get(GLOBI_URL, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        # json.v2 returns a list directly
        if isinstance(data, list):
            return data
        # fallback: columnar format {"columns": [...], "data": [[...]]}
        if isinstance(data, dict) and "columns" in data:
            cols = data["columns"]
            return [dict(zip(cols, row)) for row in data.get("data", [])]
        return []
    except Exception as e:
        print(f"  [warn] {taxon}: {e}", file=sys.stderr)
        return []


def main():
    plants = read_plants(NATIVES_CSV)
    print(f"Loaded {len(plants)} unique SF native plants")

    # Use a prioritised sample for speed; include iconic & well-studied taxa
    priority = [
        "Quercus agrifolia",
        "Artemisia californica",
        "Eschscholzia californica",
        "Salvia spathacea",
        "Lupinus arboreus",
        "Ceanothus thyrsiflorus",
        "Baccharis pilularis",
        "Eriogonum latifolium",
        "Heteromeles arbutifolia",
        "Achillea millefolium",
        "Sidalcea malviflora",
        "Castilleja miniata",
        "Iris douglasiana",
        "Fragaria chiloensis",
        "Rosa californica",
        "Sambucus nigra",
        "Rubus ursinus",
        "Lonicera hispidula",
        "Solidago spathulata",
        "Stipa pulchra",
        "Deschampsia cespitosa",
        "Festuca californica",
        "Carex obnupta",
        "Juncus effusus",
        "Typha latifolia",
        "Lupinus bicolor",
        "Lupinus nanus",
        "Phacelia californica",
        "Gilia capitata",
        "Clarkia amoena",
        "Delphinium californicum",
        "Trillium chloropetalum",
        "Calystegia purpurata",
        "Cornus sericea",
        "Salix lasiolepis",
        "Prunus ilicifolia",
        "Umbellularia californica",
        "Morella californica",
        "Garrya elliptica",
        "Arbutus menziesii",
        "Arctostaphylos manzanita",
        "Toxicodendron diversilobum",
        "Urtica dioica",
        "Cirsium occidentale",
        "Hemizonia congesta",
        "Layia platyglossa",
        "Lasthenia californica",
        "Madia elegans",
        "Monardella villosa",
        "Erysimum capitatum",
    ]

    # add the rest of the plants list (capped to keep runtime reasonable)
    remaining = [p for p in plants if p not in priority]
    target_species = priority + remaining[:150]  # total ~200

    all_interactions = []
    seen_keys = set()

    def add_records(records: list[dict]):
        for rec in records:
            key = (
                rec.get("source_taxon_name", ""),
                rec.get("interaction_type", ""),
                rec.get("target_taxon_name", ""),
            )
            if key not in seen_keys:
                seen_keys.add(key)
                all_interactions.append(rec)

    print(f"Querying GloBI for {len(target_species)} taxa …")
    for i, plant in enumerate(target_species):
        sys.stdout.write(f"\r  {i+1}/{len(target_species)}: {plant:<55}")
        sys.stdout.flush()

        # Plant as TARGET (insects using the plant)
        records = query_globi(plant, taxon_role="target", limit=200)
        add_records(records)

        # Plant as SOURCE (plant interacts with something)
        records = query_globi(plant, taxon_role="source", limit=200)
        add_records(records)

        time.sleep(0.15)  # polite rate-limiting

    print(f"\nTotal unique interactions: {len(all_interactions)}")

    OUT_FILE.write_text(json.dumps(all_interactions, indent=2))
    print(f"Saved → {OUT_FILE}")


if __name__ == "__main__":
    main()
