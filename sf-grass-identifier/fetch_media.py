#!/usr/bin/env python3
"""
Fetch photos and California monthly histograms for all SF grass species.

Outputs:
  data/grasses.json        – updated in-place with photo_url added
  data/histograms_ca.json  – { "taxon_id": [jan, feb, …, dec], … }

iNaturalist California place_id = 14
"""
import json, time, urllib.request, urllib.parse, os, sys

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
GRASSES  = os.path.join(DATA_DIR, 'grasses.json')
HIST_OUT = os.path.join(DATA_DIR, 'histograms_ca.json')
CA_PLACE = 14
DELAY    = 1.3   # seconds between requests

def fetch_json(url, retries=4):
    for attempt in range(retries):
        try:
            time.sleep(DELAY)
            req = urllib.request.Request(url, headers={'User-Agent': 'SF-Grass-Identifier/1.0'})
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read())
        except Exception as e:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            print(f'  retry in {wait}s ({e})', file=sys.stderr)
            time.sleep(wait)

species = json.load(open(GRASSES))
hist_cache = {}
if os.path.exists(HIST_OUT):
    hist_cache = json.load(open(HIST_OUT))
    print(f'{len(hist_cache)} histograms already cached')

total = len(species)
for i, sp in enumerate(species):
    tid  = sp['inat_id']
    name = sp['sci_name']
    tid_str = str(tid)

    needs_photo = not sp.get('photo_url')
    needs_hist  = tid_str not in hist_cache

    if not needs_photo and not needs_hist:
        print(f'[{i+1}/{total}] {name}: cached')
        continue

    print(f'[{i+1}/{total}] {name}', end='')

    # ── Photo ──────────────────────────────────────────────────
    if needs_photo:
        try:
            d = fetch_json(f'https://api.inaturalist.org/v1/taxa/{tid}')
            taxon = (d.get('results') or [{}])[0]
            photo = taxon.get('default_photo') or {}
            url = photo.get('medium_url') or photo.get('square_url') or ''
            # prefer square (75px) for table thumbnails; fall back to medium
            sq = photo.get('square_url') or url
            sp['photo_url']   = sq
            sp['photo_medium'] = photo.get('medium_url') or sq
            print(f'  photo={"yes" if sq else "no"}', end='')
        except Exception as e:
            print(f'  photo_err={e}', end='')

    # ── CA histogram ───────────────────────────────────────────
    if needs_hist:
        try:
            params = urllib.parse.urlencode(dict(
                taxon_id=tid,
                place_id=CA_PLACE,
                quality_grade='research',
                date_field='observed',
                interval='month_of_year',
            ))
            d = fetch_json(f'https://api.inaturalist.org/v1/observations/histogram?{params}')
            moy = d.get('results', {}).get('month_of_year', {})
            counts = [int(moy.get(m, moy.get(str(m), 0))) for m in range(1, 13)]
            hist_cache[tid_str] = counts
            print(f'  hist={"yes" if any(counts) else "empty"}', end='')
        except Exception as e:
            print(f'  hist_err={e}', end='')

    print()

    # checkpoint every 10
    if (i + 1) % 10 == 0:
        json.dump(species, open(GRASSES, 'w'), indent=2)
        json.dump(hist_cache, open(HIST_OUT, 'w'), separators=(',', ':'))
        print(f'  [checkpoint {i+1}]')

# Final save
json.dump(species, open(GRASSES, 'w'), indent=2)
json.dump(hist_cache, open(HIST_OUT, 'w'), separators=(',', ':'))
print(f'\nDone. {sum(1 for s in species if s.get("photo_url"))} photos, {len(hist_cache)} histograms.')
