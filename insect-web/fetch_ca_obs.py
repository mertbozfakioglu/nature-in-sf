"""
For every species with unknown nativity, check whether it has ANY
iNaturalist observations in California (place_id=14).
Zero observations → mark as 'no_ca_obs' → will be removed.
Results merged back into nativity.json.
"""

import json
import time
import sys
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Semaphore
from pathlib import Path

DATA_DIR   = Path(__file__).parent
NAT_FILE   = DATA_DIR / "nativity.json"
OBS_CACHE  = DATA_DIR / "ca_obs_cache.json"
INAT_OBS   = "https://api.inaturalist.org/v1/observations"
PLACE_CA   = 14

nativity  = json.loads(NAT_FILE.read_text())
obs_cache: dict[str, int] = {}
if OBS_CACHE.exists():
    obs_cache = json.loads(OBS_CACHE.read_text())

unknowns = [name for name, status in nativity.items() if status == "unknown"]
remaining = [n for n in unknowns if n not in obs_cache]
print(f"Unknown-nativity species: {len(unknowns)}")
print(f"Already cached:           {len(unknowns) - len(remaining)}")
print(f"To query:                 {len(remaining)}")

SEM   = Semaphore(8)
DELAY = 0.15

def fetch_count(name: str) -> tuple[str, int]:
    with SEM:
        time.sleep(DELAY)
        try:
            r = requests.get(
                INAT_OBS,
                params={"taxon_name": name, "place_id": PLACE_CA, "per_page": 0},
                timeout=15,
                headers={"User-Agent": "nature-in-sf/1.0 (mertbozfakioglu@gmail.com)"},
            )
            r.raise_for_status()
            return name, r.json().get("total_results", 0)
        except Exception:
            return name, -1   # -1 = error, treat as unknown (keep)

if remaining:
    done = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(fetch_count, n): n for n in remaining}
        for fut in as_completed(futs):
            name, count = fut.result()
            obs_cache[name] = count
            done += 1
            if done % 200 == 0 or done == len(remaining):
                OBS_CACHE.write_text(json.dumps(obs_cache, indent=2, sort_keys=True))
                pct = done / len(remaining) * 100
                sys.stdout.write(f"\r  {done}/{len(remaining)} ({pct:.0f}%)  ")
                sys.stdout.flush()
    print()
    OBS_CACHE.write_text(json.dumps(obs_cache, indent=2, sort_keys=True))

# ── update nativity.json ───────────────────────────────────────────────────────
no_obs = 0
for name in unknowns:
    count = obs_cache.get(name, -1)
    if count == 0:
        nativity[name] = "no_ca_obs"
        no_obs += 1
    # count > 0 or -1 (error): leave as "unknown" (keep)

NAT_FILE.write_text(json.dumps(nativity, indent=2, sort_keys=True))

still_unknown = sum(1 for v in nativity.values() if v == "unknown")
non_native    = sum(1 for v in nativity.values() if v == "non_native")
native        = sum(1 for v in nativity.values() if v == "native")
print(f"\nUpdated nativity.json:")
print(f"  native:      {native}")
print(f"  non_native:  {non_native}")
print(f"  no_ca_obs:   {no_obs}  ← new, will be removed")
print(f"  unknown:     {still_unknown}  ← has CA obs but nativity unclear, kept")
