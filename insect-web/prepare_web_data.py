"""
Prepare butterfly × plant interaction data for the web explorer.
Fetches common names from iNaturalist, extracts plant families,
outputs butterfly_web_data.json.
"""
import json, time, sys, requests
from pathlib import Path
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Semaphore

DATA_DIR   = Path(__file__).parent
INAT_TAXA  = "https://api.inaturalist.org/v1/taxa"
CACHE_FILE = DATA_DIR / "common_names_cache.json"

# ── load ───────────────────────────────────────────────────────────────────────
raw      = json.load(open(DATA_DIR / "raw_interactions.json"))
nat      = json.load(open(DATA_DIR / "nativity.json"))
bfly_sf  = json.load(open(DATA_DIR / "butterfly_sf_obs_cache.json"))
sf_obs_p = json.load(open(DATA_DIR / "sf_obs_cache.json"))

def to_species(name: str) -> str:
    parts = name.split()
    return " ".join(parts[:2]) if len(parts) >= 2 else name

EXCLUDE       = {to_species(k) for k, v in nat.items() if v in ("non_native", "no_ca_obs")}

# iNaturalist synonymizes these with a CA species, inflating their SF obs counts
# Papilio polyxenes (Black Swallowtail, eastern US) → returns P. zelicaon obs
SF_OBS_FALSE_POSITIVES = {"Papilio polyxenes"}

SF_BUTTERFLIES = {to_species(n) for n, c in bfly_sf.items() if c > 0} - SF_OBS_FALSE_POSITIVES

# ── interaction categorization ─────────────────────────────────────────────────
# eats/eatenBy = adult feeding on plant (nectaring), not larval host
HOST_TYPES   = {"hostOf","hasHost","laysEggsOn","hasEggsLayedOnBy"}
NECTAR_TYPES = {"flowersVisitedBy","visitsFlowersOf","pollinates","pollinatedBy","visits","visitedBy","eats","eatenBy"}

# ── taxonomy helpers ────────────────────────────────────────────────────────────
FAMILY_KW = {
    "Papilionidae": ["Papilionidae"],
    "Pieridae":     ["Pieridae"],
    "Lycaenidae":   ["Lycaenidae", "Polyommatini"],
    "Nymphalidae":  ["Nymphalidae"],
    "Hesperiidae":  ["Hesperiidae"],
    "Riodinidae":   ["Riodinidae"],
}
BUTTERFLY_KW = [kw for kws in FAMILY_KW.values() for kw in kws] + ["Papilionoidea"]

def is_butterfly(p): return any(k in (p or "") for k in BUTTERFLY_KW)
def is_plant(p): return any(k in (p or "") for k in (
    "Plantae","Angiosperms","Viridiplantae","Tracheophyta","Spermatophytes",
    "Gymnosperms","Bryophyta","Fagales","Poales","Caryophyllales","Lamiales",
    "Asterales","Rosales","Fabales","Malpighiales","Ericales","Solanales",
    "Apiales","Ranunculales","Myrtales","Malvales","lamiids","Equisetopsida",
))

def butterfly_family(path):
    for fam, kws in FAMILY_KW.items():
        if any(k in (path or "") for k in kws):
            return fam
    return "Unknown"

def plant_family(path):
    for seg in (path or "").split("|"):
        s = seg.strip()
        if s.endswith("aceae"):
            return s
    return "Unknown"

# ── build pairs ────────────────────────────────────────────────────────────────
path_of = {}
pairs   = defaultdict(lambda: {"host": False, "nectar": False, "other": False})

for r in raw:
    sn    = to_species((r.get("source_taxon_name") or "").strip())
    tn    = to_species((r.get("target_taxon_name") or "").strip())
    sp    = r.get("source_taxon_path") or ""
    tp    = r.get("target_taxon_path") or ""
    itype = r.get("interaction_type", "")
    if sn: path_of[sn] = sp
    if tn: path_of[tn] = tp
    if sn in EXCLUDE or tn in EXCLUDE:
        continue
    b = p = None
    if is_butterfly(sp) and is_plant(tp) and sn in SF_BUTTERFLIES:
        b, p = sn, tn
    elif is_plant(sp) and is_butterfly(tp) and tn in SF_BUTTERFLIES:
        b, p = tn, sn
    if b and p and len(b.split()) == 2 and len(p.split()) == 2:
        key = (b, p)
        if itype in HOST_TYPES:    pairs[key]["host"]   = True
        elif itype in NECTAR_TYPES: pairs[key]["nectar"] = True
        else:                       pairs[key]["other"]  = True

# ── degree filter (min 2, 3 passes) ───────────────────────────────────────────
MIN_DEG = 2

def filter_deg(ps, md):
    bd = Counter(b for b, _ in ps)
    pd = Counter(p for _, p in ps)
    return {(b, p) for b, p in ps if bd[b] >= md and pd[p] >= md}

edge_set = set(pairs.keys())
for _ in range(3):
    edge_set = filter_deg(edge_set, MIN_DEG)

# Add confirmed host-plant pairs that the degree filter dropped:
# butterfly already survives the filter, plant has ≥5 SF iNat observations
base_bflies = {b for b, _ in edge_set}
host_bonus = {
    (b, p) for (b, p), v in pairs.items()
    if v["host"] and b in base_bflies
    and sf_obs_p.get(p, 0) >= 5
    and (b, p) not in edge_set
}
edge_set |= host_bonus
print(f"Host-plant bonus edges added: {len(host_bonus)}")

butterflies = {b for b, _ in edge_set}
plants      = {p for _, p in edge_set}
print(f"Network: {len(butterflies)} butterflies, {len(plants)} plants, {len(edge_set)} edges")

# ── fetch common names from iNaturalist ────────────────────────────────────────
cache: dict = {}
if CACHE_FILE.exists():
    cache = json.loads(CACHE_FILE.read_text())

all_names = butterflies | plants
to_fetch  = [n for n in all_names if n not in cache]
print(f"Common names: {len(cache)} cached, fetching {len(to_fetch)} …")

SEM   = Semaphore(5)
DELAY = 0.25

def fetch_name(name: str) -> tuple[str, dict]:
    # use first two words (genus + species) for lookup
    parts = name.split()
    query = " ".join(parts[:2]) if len(parts) >= 2 else name
    with SEM:
        time.sleep(DELAY)
        try:
            r = requests.get(
                INAT_TAXA,
                params={"q": query, "rank": "species,subspecies,variety", "per_page": 5},
                timeout=15,
                headers={"User-Agent": "nature-in-sf/1.0 (mertbozfakioglu@gmail.com)"},
            )
            r.raise_for_status()
            results = r.json().get("results", [])
            # prefer exact name match
            for res in results:
                if res["name"].lower() == query.lower():
                    return name, {"common": res.get("preferred_common_name", ""), "id": res.get("id")}
            if results:
                return name, {"common": results[0].get("preferred_common_name", ""), "id": results[0].get("id")}
            return name, {"common": "", "id": None}
        except Exception:
            return name, {"common": "", "id": None}

if to_fetch:
    done = 0
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(fetch_name, n): n for n in to_fetch}
        for fut in as_completed(futs):
            name, info = fut.result()
            cache[name] = info
            done += 1
            if done % 30 == 0 or done == len(to_fetch):
                CACHE_FILE.write_text(json.dumps(cache, indent=2, sort_keys=True))
                sys.stdout.write(f"\r  {done}/{len(to_fetch)} ({done/len(to_fetch)*100:.0f}%)  ")
                sys.stdout.flush()
    print()
    CACHE_FILE.write_text(json.dumps(cache, indent=2, sort_keys=True))

# ── build output ───────────────────────────────────────────────────────────────
deg = Counter()
for b, p in edge_set:
    deg[b] += 1; deg[p] += 1

nodes = []
for b in butterflies:
    info = cache.get(b, {})
    nodes.append({
        "id":          b,
        "type":        "butterfly",
        "family":      butterfly_family(path_of.get(b, "")),
        "common_name": info.get("common", "") or "",
        "sf_obs":      bfly_sf.get(b, 0),
        "degree":      deg[b],
    })

for p in plants:
    info = cache.get(p, {})
    nodes.append({
        "id":          p,
        "type":        "plant",
        "family":      plant_family(path_of.get(p, "")),
        "common_name": info.get("common", "") or "",
        "sf_obs":      sf_obs_p.get(p, 0),
        "degree":      deg[p],
    })

edges = [
    {"source": b, "target": p,
     "host": pairs[(b,p)]["host"],
     "nectar": pairs[(b,p)]["nectar"],
     "other": pairs[(b,p)]["other"]}
    for b, p in edge_set
]

out = {"nodes": nodes, "edges": edges}
(DATA_DIR / "butterfly_web_data.json").write_text(json.dumps(out))
print(f"Saved butterfly_web_data.json  ({len(nodes)} nodes, {len(edges)} edges)")

# ── quick summary ──────────────────────────────────────────────────────────────
host_only   = sum(1 for e in edges if e["host"] and not e["nectar"])
nectar_only = sum(1 for e in edges if e["nectar"] and not e["host"])
both        = sum(1 for e in edges if e["host"] and e["nectar"])
other_only  = sum(1 for e in edges if not e["host"] and not e["nectar"])
print(f"  host only: {host_only}  nectar only: {nectar_only}  both: {both}  other only: {other_only}")
common_filled = sum(1 for n in nodes if n["common_name"])
print(f"  common names filled: {common_filled}/{len(nodes)}")
