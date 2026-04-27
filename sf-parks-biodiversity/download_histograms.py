#!/usr/bin/env python3
"""
Download monthly observation histograms (by month-of-year) for every species
found across all SF parks, scoped to San Francisco County on iNaturalist.

Run once, or again whenever you want to pick up newly-discovered taxa.

Usage:
    python3 download_histograms.py            # skip already-cached taxa
    python3 download_histograms.py --refresh  # re-fetch everything
"""

import json
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

INAT_API    = 'https://api.inaturalist.org/v1'
SF_PLACE_ID = 854
DELAY       = 1.0   # seconds between requests per thread (iNat limit: 100/min)
WORKERS     = 1

_print_lock = threading.Lock()

def tprint(*args, **kwargs):
    with _print_lock:
        print(*args, **kwargs)

def fetch_json(url, retries=4):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={'User-Agent': 'SF-Parks-Biodiversity/1.0'})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except Exception as e:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            tprint(f'  retry in {wait}s ({e})', file=sys.stderr)
            time.sleep(wait)

def main():
    refresh     = '--refresh' in sys.argv
    base        = Path(__file__).parent / 'data'
    species_dir = base / 'species'
    out_path    = base / 'histograms.json'

    # Collect all unique taxon IDs from per-park species files
    taxon_ids = set()
    for f in species_dir.glob('*.json'):
        for s in json.loads(f.read_text()).get('species', []):
            tid = (s.get('taxon') or {}).get('id')
            if tid:
                taxon_ids.add(int(tid))
    taxon_ids = sorted(taxon_ids)
    print(f'Found {len(taxon_ids)} unique taxa across all parks')

    # Load existing cache
    existing = {}
    if out_path.exists() and not refresh:
        existing = json.loads(out_path.read_text())
        print(f'  {len(existing)} already cached — skipping those')

    to_fetch = [tid for tid in taxon_ids if str(tid) not in existing]
    if not to_fetch:
        print('Nothing new to fetch.')
        return

    print(f'Fetching {len(to_fetch)} histograms with {WORKERS} workers…')

    results   = dict(existing)
    done      = [0]
    total     = len(to_fetch)
    lock      = threading.Lock()

    def fetch_one(taxon_id):
        params = dict(
            taxon_id=taxon_id,
            place_id=SF_PLACE_ID,
            quality_grade='research',
            date_field='observed',
            interval='month_of_year',
        )
        url = f"{INAT_API}/observations/histogram?" + urllib.parse.urlencode(params)
        time.sleep(DELAY)
        data       = fetch_json(url)
        month_data = data.get('results', {}).get('month_of_year', {})
        # Normalise keys (API may return int or str keys)
        counts = [int(month_data.get(m, month_data.get(str(m), 0))) for m in range(1, 13)]
        with lock:
            results[str(taxon_id)] = counts
            done[0] += 1
            if done[0] % 100 == 0 or done[0] == total:
                tprint(f'  {done[0]}/{total}')

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        ex.map(fetch_one, to_fetch)

    out_path.write_text(json.dumps(results, separators=(',', ':')))
    print(f'\nSaved histograms.json  ({len(results)} taxa, {out_path.stat().st_size // 1024} KB)')

if __name__ == '__main__':
    main()
