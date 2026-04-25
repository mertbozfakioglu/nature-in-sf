#!/usr/bin/env python3
"""
Download iNaturalist species data for all SF Rec & Park properties.
Saves static JSON files consumed by the web app.

Usage:
    python3 download_data.py

Skips parks already cached in data/species/. Safe to re-run.
Rate-limits to ~1 request per 0.6 s to stay within iNaturalist limits.
"""

import urllib.request
import urllib.parse
import json
import time
import sys
import os
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

INAT_API      = 'https://api.inaturalist.org/v1'
SF_PLACE_ID   = 854   # San Francisco County, CA  (from iNaturalist)
DELAY         = 0.3   # seconds between API calls per thread
WORKERS       = 5     # concurrent park downloads
_print_lock   = threading.Lock()

SF_PARKS_URL  = (
    "https://data.sfgov.org/resource/gtr9-ntp6.geojson"
    "?$limit=500&$where=city%3D%27San%20Francisco%27"
)

CATEGORIES = [
    'Plantae', 'Aves', 'Insecta', 'Mammalia', 'Fungi',
    'Reptilia', 'Amphibia', 'Arachnida', 'Mollusca',
]

# ── helpers ───────────────────────────────────────────────────────────────────

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

def park_id(feature):
    p = feature.get('properties') or {}
    return str(
        p.get('property_id') or p.get('name') or
        feature.get('id') or
        abs(hash(json.dumps(feature['geometry']['coordinates'][0][0])))
    )

def park_name(feature):
    p = feature.get('properties') or {}
    return (p.get('property_name') or p.get('name') or 'Unknown')

def park_bounds(feature):
    geom = feature['geometry']
    coords = []
    if geom['type'] == 'Polygon':
        coords = geom['coordinates'][0]
    elif geom['type'] == 'MultiPolygon':
        for poly in geom['coordinates']:
            coords.extend(poly[0])
    lats = [c[1] for c in coords]
    lngs = [c[0] for c in coords]
    return dict(swlat=min(lats), swlng=min(lngs),
                nelat=max(lats), nelng=max(lngs))

def establishment_means(taxon):
    em = (taxon.get('establishment_means') or {}).get('establishment_means')
    if not em:
        em = (taxon.get('listed_taxon') or {}).get('establishment_means')
    return em

# ── iNaturalist ───────────────────────────────────────────────────────────────

def fetch_species(bounds):
    params = dict(
        swlat=bounds['swlat'], swlng=bounds['swlng'],
        nelat=bounds['nelat'], nelng=bounds['nelng'],
        quality_grade='research',
        place_id=SF_PLACE_ID,
        per_page=200,
        order_by='count',
        order='desc',
    )
    url = f"{INAT_API}/observations/species_counts?" + urllib.parse.urlencode(params)
    data = fetch_json(url)
    all_sp = data.get('results', [])
    total  = data.get('total_results', 0)

    pages = min((total + 199) // 200, 5)   # cap at 1 000 species per park
    for page in range(2, pages + 1):
        params['page'] = page
        time.sleep(DELAY)
        more = fetch_json(f"{INAT_API}/observations/species_counts?" + urllib.parse.urlencode(params))
        all_sp.extend(more.get('results', []))

    return all_sp

def compress_species(species_list):
    out = []
    for s in species_list:
        t     = s.get('taxon') or {}
        photo = t.get('default_photo') or {}
        em    = establishment_means(t)
        out.append({
            'count': s['count'],
            'taxon': {
                'id':                   t.get('id'),
                'name':                 t.get('name'),
                'preferred_common_name':t.get('preferred_common_name'),
                'iconic_taxon_name':    t.get('iconic_taxon_name'),
                'default_photo':        {'square_url': photo['square_url']} if photo.get('square_url') else None,
                'establishment_means':  {'establishment_means': em} if em else None,
            },
        })
    return out

def build_summary(species_list):
    cats = {c: 0 for c in CATEGORIES}
    native = introduced = 0
    for s in species_list:
        t  = s.get('taxon') or {}
        k  = t.get('iconic_taxon_name')
        if k in cats:
            cats[k] += 1
        em = establishment_means(t)
        if em in ('native', 'endemic'):
            native += 1
        elif em in ('introduced', 'naturalizing'):
            introduced += 1
    return dict(total=len(species_list), cats=cats,
                nativeCount=native, introducedCount=introduced)

# ── main ─────────────────────────────────────────────────────────────────────

def main():
    base        = Path(__file__).parent / 'data'
    species_dir = base / 'species'
    base.mkdir(exist_ok=True)
    species_dir.mkdir(exist_ok=True)

    # ── Parks GeoJSON ──────────────────────────────────────────────────────
    parks_path = base / 'parks.geojson'
    if parks_path.exists():
        print('Loading cached parks.geojson...')
        with open(parks_path) as f:
            geojson = json.load(f)
        features = geojson['features']
    else:
        print('Fetching SF parks from SF Open Data...')
        raw = fetch_json(SF_PARKS_URL)
        features = [
            feat for feat in raw.get('features', [])
            if feat.get('geometry') and
               feat['geometry']['type'] in ('Polygon', 'MultiPolygon')
        ]
        with open(parks_path, 'w') as f:
            json.dump({'type': 'FeatureCollection', 'features': features}, f,
                      separators=(',', ':'))
        print(f'Saved parks.geojson ({len(features)} parks)')

    # ── Per-park species ────────────────────────────────────────────────────
    summary = {}
    total_parks = len(features)
    done_count  = [0]

    def process_park(args):
        i, feature = args
        pid  = park_id(feature)
        name = park_name(feature)
        out  = species_dir / f'{pid}.json'

        if out.exists():
            with open(out) as f:
                cached = json.load(f)
            done_count[0] += 1
            tprint(f'[{done_count[0]:>3}/{total_parks}] {name[:45]:<45}  (cached  {cached["summary"]["total"]:>4} spp)')
            return pid, {**cached['summary'], 'name': name}

        try:
            bounds  = park_bounds(feature)
            time.sleep(DELAY)
            species = fetch_species(bounds)
            summ    = build_summary(species)
            comp    = compress_species(species)

            with open(out, 'w') as f:
                json.dump({'summary': summ, 'species': comp}, f, separators=(',', ':'))

            done_count[0] += 1
            tprint(f'[{done_count[0]:>3}/{total_parks}] {name[:45]:<45}  {summ["total"]:>4} spp')
            return pid, {**summ, 'name': name}
        except Exception as e:
            done_count[0] += 1
            tprint(f'[{done_count[0]:>3}/{total_parks}] {name[:45]:<45}  ERROR: {e}', file=sys.stderr)
            return pid, dict(total=0, cats={}, nativeCount=0, introducedCount=0, name=name)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = ex.map(process_park, enumerate(features))
        for pid_val, summ_val in futures:
            summary[pid_val] = summ_val

    # ── Summary JSON ────────────────────────────────────────────────────────
    with open(base / 'summary.json', 'w') as f:
        json.dump(summary, f, separators=(',', ':'))

    total_spp = sum(v['total'] for v in summary.values())
    print(f'\nDone – {len(summary)} parks, {total_spp:,} total species records.')
    print('Files written to data/')

if __name__ == '__main__':
    main()
