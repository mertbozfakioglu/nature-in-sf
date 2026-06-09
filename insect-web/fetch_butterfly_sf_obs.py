"""
Query iNaturalist for SF (place_id=854) observation counts
for every butterfly species in the dataset. Results cached to
butterfly_sf_obs_cache.json.
"""
import json, time, sys, requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Semaphore
from pathlib import Path

DATA_DIR   = Path(__file__).parent
SPECIES    = json.loads((DATA_DIR / "butterfly_species.json").read_text())
CACHE_FILE = DATA_DIR / "butterfly_sf_obs_cache.json"
INAT_OBS   = "https://api.inaturalist.org/v1/observations"
PLACE_SF   = 854

cache: dict[str, int] = {}
if CACHE_FILE.exists():
    cache = json.loads(CACHE_FILE.read_text())

remaining = [n for n in SPECIES if n not in cache]
print(f"Total butterfly species: {len(SPECIES)}")
print(f"Already cached: {len(SPECIES) - len(remaining)}")
print(f"To query: {len(remaining)}")

SEM   = Semaphore(5)
DELAY = 0.25

def fetch_count(name: str) -> tuple[str, int]:
    with SEM:
        time.sleep(DELAY)
        try:
            r = requests.get(
                INAT_OBS,
                params={"taxon_name": name, "place_id": PLACE_SF,
                        "per_page": 0, "verifiable": "true"},
                timeout=15,
                headers={"User-Agent": "nature-in-sf/1.0 (mertbozfakioglu@gmail.com)"},
            )
            r.raise_for_status()
            return name, r.json().get("total_results", 0)
        except Exception:
            return name, -1  # -1 = error, keep as unknown

if remaining:
    done = 0
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(fetch_count, n): n for n in remaining}
        for fut in as_completed(futs):
            name, count = fut.result()
            cache[name] = count
            done += 1
            if done % 50 == 0 or done == len(remaining):
                CACHE_FILE.write_text(json.dumps(cache, indent=2, sort_keys=True))
                pct = done / len(remaining) * 100
                sys.stdout.write(f"\r  {done}/{len(remaining)} ({pct:.0f}%)  ")
                sys.stdout.flush()
    print()
    CACHE_FILE.write_text(json.dumps(cache, indent=2, sort_keys=True))

sf_seen  = sum(1 for v in cache.values() if v > 0)
not_seen = sum(1 for v in cache.values() if v == 0)
errors   = sum(1 for v in cache.values() if v < 0)
print(f"\nSF observations summary:")
print(f"  observed in SF: {sf_seen}")
print(f"  not observed:   {not_seen}")
print(f"  query errors:   {errors}")

# top species
top = sorted(((n, v) for n, v in cache.items() if v > 0), key=lambda x: -x[1])
print("\nTop 20 butterfly species by SF observation count:")
for name, cnt in top[:20]:
    print(f"  {cnt:6d}  {name}")
