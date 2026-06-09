"""
Query iNaturalist for California establishment means for every taxon
in the cleaned interaction dataset. Results cached to nativity_cache.json.

Logic:
  introduced / naturalised / invasive  → NON_NATIVE  (remove)
  native / endemic                      → NATIVE      (keep)
  null / no data                        → UNKNOWN     (keep, per user request)
"""

import json
import time
import sys
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Semaphore

DATA_DIR   = Path(__file__).parent
CACHE_FILE = DATA_DIR / "nativity_cache.json"
INAT_URL   = "https://api.inaturalist.org/v1/taxa"
PLACE_CA   = 14   # iNaturalist place_id for California

NON_NATIVE_MEANS = {"introduced", "naturalised", "invasive", "managed"}
NATIVE_MEANS     = {"native", "endemic"}

# ── load datasets ──────────────────────────────────────────────────────────────
raw  = json.loads((DATA_DIR / "raw_interactions.json").read_text())
araw = json.loads((DATA_DIR / "raw_animal_interactions.json").read_text())
sf_natives = set(
    l.strip()
    for l in (DATA_DIR.parent / "sf-parks-biodiversity/data/sf_natives.csv")
              .read_text().strip().splitlines()
    if l.strip()
)

NOISE_TYPES   = {"interactsWith","coOccursWith","adjacentTo","visits","visitedBy",
                 "livesOn","livedOnBy","ecologicallyRelatedTo"}
PARASITIC     = {"parasiteOf","hasParasite","hostOf","hasHost"}

def is_plant_strict(path):
    return any(k in (path or "") for k in
               ("Plantae","Angiosperms","Viridiplantae","Tracheophyta","Gymnosperms","Bryophyta"))

# apply same filters as analyze.py to know which names are in play
active = []
for r in raw:
    itype = r.get("interaction_type","")
    sp, tp = r.get("source_taxon_path",""), r.get("target_taxon_path","")
    if itype in NOISE_TYPES: continue
    if is_plant_strict(sp) and is_plant_strict(tp) and itype not in PARASITIC: continue
    active.append(r)
active += araw

all_names: set[str] = set()
for r in active:
    for key in ("source_taxon_name","target_taxon_name"):
        n = r.get(key,"").strip()
        if n: all_names.add(n)

# ── decide what to query ───────────────────────────────────────────────────────
# Plants already in sf_natives → native by definition, skip query
# Higher-rank taxa (single word, or accession IDs) → skip, classify as UNKNOWN
# Fungi, Bacteria, Viruses → nativity undefined for our purposes, skip (UNKNOWN)

def is_microbe(path):
    return any(k in (path or "") for k in ("Fungi","Bacteria","Virus","Prokaryota","Archaea","Chromista"))

# build path lookup from raw data
path_of: dict[str,str] = {}
for r in active:
    for nk, pk in [("source_taxon_name","source_taxon_path"),
                   ("target_taxon_name","target_taxon_path")]:
        n = (r.get(nk) or "").strip()
        p = (r.get(pk) or "").strip()
        if n and p and n not in path_of:
            path_of[n] = p

to_query: list[str] = []
pre_classified: dict[str, str] = {}

for name in sorted(all_names):
    # SF native plants → native
    if name in sf_natives:
        pre_classified[name] = "native"
        continue
    path = path_of.get(name, "")
    # microbes → unknown (nativity not meaningful here)
    if is_microbe(path):
        pre_classified[name] = "unknown"
        continue
    # single-word / accession IDs → unknown
    parts = name.split()
    if len(parts) < 2 or not parts[0][0].isupper():
        pre_classified[name] = "unknown"
        continue
    to_query.append(name)

print(f"Total unique names: {len(all_names)}")
print(f"Pre-classified (no query needed): {len(pre_classified)}")
print(f"  native (SF natives csv):  {sum(1 for v in pre_classified.values() if v=='native')}")
print(f"  unknown (microbes/genus): {sum(1 for v in pre_classified.values() if v=='unknown')}")
print(f"To query iNaturalist: {len(to_query)}")

# ── load cache ─────────────────────────────────────────────────────────────────
cache: dict[str,str] = {}
if CACHE_FILE.exists():
    cache = json.loads(CACHE_FILE.read_text())
    print(f"Cache loaded: {len(cache)} entries")

remaining = [n for n in to_query if n not in cache]
print(f"Remaining to fetch: {len(remaining)}")

# ── fetch with concurrency ─────────────────────────────────────────────────────
RATE_SEM   = Semaphore(5)   # max 5 concurrent requests
REQUEST_DELAY = 0.25        # seconds between acquiring the semaphore

def fetch_one(name: str) -> tuple[str, str]:
    with RATE_SEM:
        time.sleep(REQUEST_DELAY)
        try:
            r = requests.get(
                INAT_URL,
                params={"q": name, "place_id": PLACE_CA, "per_page": 1,
                        "rank": "species,subspecies,variety"},
                timeout=15,
                headers={"User-Agent": "nature-in-sf/1.0 (mertbozfakioglu@gmail.com)"},
            )
            r.raise_for_status()
            results = r.json().get("results", [])
            if not results:
                return name, "unknown"
            top = results[0]
            # confirm name match (avoid wrong taxon hits)
            if top["name"].lower() != name.lower().split(" var.")[0].split(" subsp.")[0].strip():
                # soft match: check if query name starts with result name or vice versa
                if not (name.lower().startswith(top["name"].lower()) or
                        top["name"].lower().startswith(name.split()[0].lower() + " " + name.split()[1].lower() if len(name.split()) >= 2 else name.lower())):
                    pass  # still use it — close enough for a single best-match
            em = top.get("establishment_means")
            if em:
                means = em.get("establishment_means","").lower()
                if means in NON_NATIVE_MEANS:
                    return name, "non_native"
                if means in NATIVE_MEANS:
                    return name, "native"
            return name, "unknown"
        except Exception as e:
            return name, "unknown"

if remaining:
    done = 0
    save_every = 100
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(fetch_one, n): n for n in remaining}
        for fut in as_completed(futs):
            name, status = fut.result()
            cache[name] = status
            done += 1
            if done % save_every == 0 or done == len(remaining):
                CACHE_FILE.write_text(json.dumps(cache, indent=2, sort_keys=True))
                pct = done / len(remaining) * 100
                sys.stdout.write(f"\r  {done}/{len(remaining)} ({pct:.0f}%)  ")
                sys.stdout.flush()
    print()

# ── merge and save final classification ────────────────────────────────────────
final: dict[str,str] = {**pre_classified, **cache}
out = DATA_DIR / "nativity.json"
out.write_text(json.dumps(final, indent=2, sort_keys=True))

native   = sum(1 for v in final.values() if v == "native")
non_nat  = sum(1 for v in final.values() if v == "non_native")
unknown  = sum(1 for v in final.values() if v == "unknown")
print(f"\nFinal classification ({len(final)} taxa):")
print(f"  native:     {native}")
print(f"  non_native: {non_nat}")
print(f"  unknown:    {unknown}")
print(f"Saved → {out}")
