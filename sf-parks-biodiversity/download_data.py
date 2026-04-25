#!/usr/bin/env python3
"""
Download iNaturalist species data for SF parks and green spaces.
Park boundaries sourced from OpenStreetMap via Overpass API.
Saves static JSON files consumed by the web app.

Usage:
    python3 download_data.py            # skip already-cached parks
    python3 download_data.py --refresh  # re-fetch parks.geojson from OSM
                                        # (also clears species cache)

Rate-limits to ~1 request per 0.3 s per thread to stay within iNaturalist limits.
"""

import urllib.request
import urllib.parse
import urllib.error
import json
import math
import time
import sys
import threading
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

INAT_API    = 'https://api.inaturalist.org/v1'
SF_PLACE_ID = 854       # San Francisco County, CA
DELAY       = 0.3       # seconds between iNat API calls per thread
WORKERS     = 5         # concurrent park downloads

OVERPASS_URL = 'https://overpass-api.de/api/interpreter'
SF_BBOX      = (37.700, -122.530, 37.840, -122.345)  # south, west, north, east
MIN_AREA_M2  = 1_000    # ~0.1 ha — filters out tiny slivers and road medians

CATEGORIES = [
    'Plantae', 'Aves', 'Insecta', 'Mammalia', 'Fungi',
    'Reptilia', 'Amphibia', 'Arachnida', 'Mollusca',
]

_print_lock = threading.Lock()

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
    return p.get('property_name') or p.get('name') or 'Unknown'

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

# ── OpenStreetMap / Overpass ──────────────────────────────────────────────────

def polygon_area_m2(coords):
    """Shoelace formula → approximate m² for a lat/lng ring."""
    LAT_M = 111_000
    LON_M = 111_000 * math.cos(math.radians((SF_BBOX[0] + SF_BBOX[2]) / 2))
    n = len(coords)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        xi, yi = coords[i][0] * LON_M, coords[i][1] * LAT_M
        xj, yj = coords[j][0] * LON_M, coords[j][1] * LAT_M
        area += xi * yj - xj * yi
    return abs(area) / 2

def way_coords(geom_list):
    return [[p['lon'], p['lat']] for p in geom_list]

def osm_elements_to_features(elements):
    """Convert Overpass JSON elements to GeoJSON features."""
    features = []
    seen_names = {}   # name → (index, area) for deduplication

    for el in elements:
        tags   = el.get('tags', {})
        name   = tags.get('name', '').strip()
        if not name:
            continue

        el_type = el['type']
        el_id   = el['id']
        prop_id = f'w{el_id}' if el_type == 'way' else f'r{el_id}'

        if el_type == 'way':
            geom_list = el.get('geometry', [])
            if len(geom_list) < 4:
                continue
            coords = way_coords(geom_list)
            area   = polygon_area_m2(coords)
            if area < MIN_AREA_M2:
                continue
            geometry = {'type': 'Polygon', 'coordinates': [coords]}

        elif el_type == 'relation':
            members = el.get('members', [])
            outers  = [way_coords(m['geometry']) for m in members
                       if m.get('type') == 'way' and m.get('geometry')
                       and m.get('role') != 'inner']
            inners  = [way_coords(m['geometry']) for m in members
                       if m.get('type') == 'way' and m.get('geometry')
                       and m.get('role') == 'inner']
            if not outers:
                continue
            area = sum(polygon_area_m2(o) for o in outers)
            if area < MIN_AREA_M2:
                continue
            if len(outers) == 1:
                geometry = {'type': 'Polygon', 'coordinates': [outers[0]] + inners}
            else:
                geometry = {'type': 'MultiPolygon',
                            'coordinates': [[o] for o in outers]}
        else:
            continue

        feature = {
            'type': 'Feature',
            'properties': {
                'property_id':   prop_id,
                'property_name': name,
            },
            'geometry': geometry,
        }

        # Deduplicate: if same name seen before, keep the larger one
        if name in seen_names:
            prev_idx, prev_area = seen_names[name]
            if area > prev_area:
                features[prev_idx] = feature
                seen_names[name]   = (prev_idx, area)
        else:
            seen_names[name] = (len(features), area)
            features.append(feature)

    return features

def fetch_osm_parks():
    s, w, n, e = SF_BBOX
    bbox  = f'{s},{w},{n},{e}'
    query = f'''[out:json][timeout:90];
(
  way["leisure"~"^(park|nature_reserve|garden)$"]["name"]({bbox});
  way["boundary"~"^(national_park|protected_area)$"]["name"]({bbox});
  relation["leisure"~"^(park|nature_reserve|garden)$"]["name"]({bbox});
  relation["boundary"~"^(national_park|protected_area)$"]["name"]({bbox});
);
out geom;'''

    print('Querying OpenStreetMap (Overpass API)…')
    data   = query.encode()
    req    = urllib.request.Request(
        OVERPASS_URL, data=data,
        headers={'Content-Type': 'application/x-www-form-urlencoded',
                 'User-Agent': 'SF-Parks-Biodiversity/1.0'})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.load(resp)
            break
        except Exception as e:
            if attempt == 3:
                raise
            wait = 2 ** attempt
            print(f'  retry in {wait}s ({e})', file=sys.stderr)
            time.sleep(wait)

    elements = result.get('elements', [])
    print(f'OSM returned {len(elements)} elements')
    features = osm_elements_to_features(elements)
    print(f'Converted to {len(features)} park features (area ≥ {MIN_AREA_M2} m²)')
    return features

# ── iNaturalist ───────────────────────────────────────────────────────────────

def fetch_species(bounds):
    params = dict(
        swlat=bounds['swlat'], swlng=bounds['swlng'],
        nelat=bounds['nelat'], nelng=bounds['nelng'],
        quality_grade='research',
        place_id=SF_PLACE_ID,
        taxon_geoprivacy='open',
        per_page=200,
        order_by='count',
        order='desc',
    )
    url  = f"{INAT_API}/observations/species_counts?" + urllib.parse.urlencode(params)
    data = fetch_json(url)
    all_sp = data.get('results', [])
    total  = data.get('total_results', 0)

    pages = min((total + 199) // 200, 5)
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
    refresh     = '--refresh' in sys.argv
    base        = Path(__file__).parent / 'data'
    species_dir = base / 'species'
    base.mkdir(exist_ok=True)
    species_dir.mkdir(exist_ok=True)

    # ── Parks GeoJSON ──────────────────────────────────────────────────────
    parks_path = base / 'parks.geojson'
    if refresh and parks_path.exists():
        parks_path.unlink()
        print('Cleared cached parks.geojson (--refresh)')
        # Also clear species cache since park IDs will change
        if species_dir.exists():
            shutil.rmtree(species_dir)
            species_dir.mkdir()
            print('Cleared species cache')

    if parks_path.exists():
        print('Loading cached parks.geojson…')
        features = json.loads(parks_path.read_text())['features']
        print(f'  {len(features)} parks loaded from cache')
    else:
        features = fetch_osm_parks()
        parks_path.write_text(json.dumps(
            {'type': 'FeatureCollection', 'features': features},
            separators=(',', ':')))
        print(f'Saved parks.geojson ({len(features)} parks)')

    # ── Per-park species ────────────────────────────────────────────────────
    summary    = {}
    total_parks = len(features)
    done_count  = [0]

    def process_park(args):
        i, feature = args
        pid  = park_id(feature)
        name = park_name(feature)
        out  = species_dir / f'{pid}.json'

        if out.exists():
            cached = json.loads(out.read_text())
            done_count[0] += 1
            tprint(f'[{done_count[0]:>3}/{total_parks}] {name[:45]:<45}  (cached  {cached["summary"]["total"]:>4} spp)')
            return pid, {**cached['summary'], 'name': name}

        try:
            bounds  = park_bounds(feature)
            time.sleep(DELAY)
            species = fetch_species(bounds)
            summ    = build_summary(species)
            comp    = compress_species(species)

            out.write_text(json.dumps({'summary': summ, 'species': comp}, separators=(',', ':')))
            done_count[0] += 1
            tprint(f'[{done_count[0]:>3}/{total_parks}] {name[:45]:<45}  {summ["total"]:>4} spp')
            return pid, {**summ, 'name': name}
        except Exception as e:
            done_count[0] += 1
            tprint(f'[{done_count[0]:>3}/{total_parks}] {name[:45]:<45}  ERROR: {e}', file=sys.stderr)
            return pid, dict(total=0, cats={}, nativeCount=0, introducedCount=0, name=name)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for pid_val, summ_val in ex.map(process_park, enumerate(features)):
            summary[pid_val] = summ_val

    # ── Summary JSON ────────────────────────────────────────────────────────
    (base / 'summary.json').write_text(json.dumps(summary, separators=(',', ':')))

    total_spp = sum(v['total'] for v in summary.values())
    print(f'\nDone – {len(summary)} parks, {total_spp:,} total species records.')
    print('Files written to data/')
    print('\nNext: run python3 recompute_counts.py to add SF native counts.')

if __name__ == '__main__':
    main()
