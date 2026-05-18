#!/usr/bin/env python3
"""
Fetches monthly observation histograms from iNaturalist for each grass species
in grasses.json (SF, place_id=854, research-grade) and adds peak_month (1-12)
to each record. Skips species that already have peak_month set.
"""
import json, time, urllib.request, os

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
GRASSES  = os.path.join(DATA_DIR, 'grasses.json')
DELAY    = 1.2

def fetch_json(url):
    for attempt in range(3):
        try:
            time.sleep(DELAY * (attempt + 1))
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0',
                'Accept': 'application/json',
            })
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            print(f'  [attempt {attempt+1}] {e}')
    return None

def peak_month(inat_id):
    url = (f'https://api.inaturalist.org/v1/observations/histogram'
           f'?taxon_id={inat_id}&place_id=854&interval=month_of_year'
           f'&quality_grade=research')
    data = fetch_json(url)
    if not data:
        return None
    counts = data.get('results', {}).get('month_of_year', {})
    if not counts:
        return None
    # counts keys are strings "1".."12"
    best = max(counts, key=lambda m: counts[m])
    return int(best)

def main():
    species = json.load(open(GRASSES))
    total = len(species)
    updated = 0
    for i, sp in enumerate(species):
        if sp.get('peak_month') is not None:
            print(f'[{i+1}/{total}] {sp["sci_name"]} — already set ({sp["peak_month"]})')
            continue
        print(f'[{i+1}/{total}] {sp["sci_name"]} …', end=' ', flush=True)
        pm = peak_month(sp['inat_id'])
        sp['peak_month'] = pm
        updated += 1
        print(pm if pm else 'no data')

    with open(GRASSES, 'w') as f:
        json.dump(species, f, indent=2)
    print(f'\nDone — updated {updated} species.')

if __name__ == '__main__':
    main()
