#!/usr/bin/env python3
"""
Exploratory script: find SF native plants with the highest ultramafic affinity
(um_affinity) according to CalFlora.

um_affinity scale (1–6):
  ≥ 5.5  strict serpentine endemic
  4.5–5.5  broad serpentine endemic
  3.5–4.5  transition / strong indicator
  2.5–3.5  moderate indicator

Requirements:
  Set the env var CALFLORA_API_KEY or pass --api-key <key>.
  Sign up / request a key at https://www.calflora.org/entry/apidocs.html

Usage:
    export CALFLORA_API_KEY=your_key_here
    python3 calflora_ultramafic.py

    # or inline:
    python3 calflora_ultramafic.py --api-key your_key_here

    # show more than top 10:
    python3 calflora_ultramafic.py --top 25

    # skip cross-referencing with local sf_natives.csv (show all CalFlora SF natives):
    python3 calflora_ultramafic.py --no-filter
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path


CALFLORA_API = 'https://api.calflora.org'
# CalFlora county codes for San Francisco — try in order until one works
SF_COUNTY_CANDIDATES = ['San Francisco', 'SF', 'san francisco']
PAGE_SIZE = 1000
DELAY = 0.5   # seconds between pages


def fetch_json(url, headers, retries=4):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except Exception as e:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            print(f'  retry in {wait}s ({e})', file=sys.stderr)
            time.sleep(wait)


def fetch_all_plants(api_key, county):
    """Page through GET /plants for the given county, returning all plant dicts."""
    headers = {
        'X-API-Key': api_key,
        'Accept': 'application/json',
        'User-Agent': 'SF-Parks-Biodiversity-Explore/1.0',
    }

    plants = []
    page = 1
    while True:
        params = urllib.parse.urlencode({
            'county':   county,
            'pageSize': PAGE_SIZE,
            'page':     page,
        })
        url = f'{CALFLORA_API}/plants?{params}'
        print(f'  fetching page {page} …', end=' ', flush=True)
        data = fetch_json(url, headers)

        # API may return a list directly or wrap in a results/data key
        if isinstance(data, list):
            batch = data
        elif isinstance(data, dict):
            batch = (data.get('results') or data.get('data') or data.get('plants') or [])
        else:
            batch = []

        print(f'{len(batch)} records')
        if not batch:
            break

        plants.extend(batch)
        if len(batch) < PAGE_SIZE:
            break   # last page
        page += 1
        time.sleep(DELAY)

    return plants


def load_sf_native_names():
    """Load scientific names from the local sf_natives.csv (one name per line)."""
    csv_path = Path(__file__).parent / 'sf-parks-biodiversity' / 'data' / 'sf_natives.csv'
    if not csv_path.exists():
        print(f'Warning: {csv_path} not found — skipping local cross-reference', file=sys.stderr)
        return None
    names = set()
    with open(csv_path) as f:
        for row in f:
            name = row.strip()
            if name:
                names.add(name.lower())
    return names


def extract_um_affinity(plant):
    """Pull um_affinity from a plant dict regardless of key casing."""
    for key in ('um_affinity', 'umAffinity', 'UmAffinity', 'ultramafic_affinity'):
        v = plant.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return 0.0


def extract_native(plant):
    """Return True if CalFlora marks this plant as native."""
    for key in ('isNative', 'is_native', 'native'):
        v = plant.get(key)
        if v is not None:
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.lower() in ('true', '1', 'yes', 'y')
            if isinstance(v, int):
                return bool(v)
    return False


def extract_name(plant):
    for key in ('taxon', 'scientificName', 'scientific_name', 'name', 'species'):
        v = plant.get(key)
        if v:
            return str(v).strip()
    return '(unknown)'


def extract_common(plant):
    for key in ('commonName', 'common_name', 'common', 'vernacularName'):
        v = plant.get(key)
        if v:
            return str(v).strip()
    return ''


def try_county(api_key, candidate):
    """Try fetching with the given county string. Return plants list or None on auth/not-found errors."""
    headers = {
        'X-API-Key': api_key,
        'Accept': 'application/json',
        'User-Agent': 'SF-Parks-Biodiversity-Explore/1.0',
    }
    params = urllib.parse.urlencode({'county': candidate, 'pageSize': 1, 'page': 1})
    url = f'{CALFLORA_API}/plants?{params}'
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
        # If we got any response without 401/404, this county string works
        return True, data
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            print(f'Auth failed (HTTP {e.code}). Check your API key.', file=sys.stderr)
            sys.exit(1)
        return False, None
    except Exception as e:
        return False, None


def main():
    parser = argparse.ArgumentParser(description='Find SF native plants with high ultramafic affinity via CalFlora.')
    parser.add_argument('--api-key', default=os.environ.get('CALFLORA_API_KEY', ''),
                        help='CalFlora API key (or set CALFLORA_API_KEY env var)')
    parser.add_argument('--top', type=int, default=10, help='Number of top plants to show (default: 10)')
    parser.add_argument('--no-filter', action='store_true',
                        help='Skip cross-referencing with sf_natives.csv')
    parser.add_argument('--min-affinity', type=float, default=0.0,
                        help='Minimum um_affinity to include (default: 0, i.e., all with any affinity)')
    args = parser.parse_args()

    if not args.api_key:
        print('Error: CalFlora API key required.', file=sys.stderr)
        print('  Set CALFLORA_API_KEY env var or pass --api-key <key>', file=sys.stderr)
        print('  Obtain a key at: https://www.calflora.org/entry/apidocs.html', file=sys.stderr)
        sys.exit(1)

    # Detect working county string
    print('Probing CalFlora API for San Francisco county…')
    county = None
    for candidate in SF_COUNTY_CANDIDATES:
        ok, _ = try_county(args.api_key, candidate)
        if ok:
            county = candidate
            print(f'  Using county string: "{county}"')
            break
    if not county:
        print('Could not find a working county string. Try --county flag or check CalFlora docs.', file=sys.stderr)
        sys.exit(1)

    # Fetch all plants for the county
    print(f'\nFetching all plants for county="{county}" from CalFlora…')
    all_plants = fetch_all_plants(args.api_key, county)
    print(f'Total records returned: {len(all_plants)}')

    if not all_plants:
        print('\nNo plants returned. Possible issues:')
        print('  • County string not recognised by CalFlora (try a different format)')
        print('  • API key lacks access to plant data')
        print('  • First result page was empty')
        # Dump the raw response for debugging
        headers = {'X-API-Key': args.api_key, 'Accept': 'application/json',
                   'User-Agent': 'SF-Parks-Biodiversity-Explore/1.0'}
        params = urllib.parse.urlencode({'county': county, 'pageSize': 5, 'page': 1})
        raw = fetch_json(f'{CALFLORA_API}/plants?{params}', headers)
        print('\nRaw API response (first page, pageSize=5):')
        print(json.dumps(raw, indent=2)[:2000])
        sys.exit(1)

    # Print a sample record so we can see the field names
    print('\nSample plant record keys:', list(all_plants[0].keys()))

    # Filter: native + has ultramafic affinity
    native_um = [
        p for p in all_plants
        if extract_native(p) and extract_um_affinity(p) > args.min_affinity
    ]
    print(f'After filtering for native + um_affinity > {args.min_affinity}: {len(native_um)} plants')

    # Optionally cross-reference with local sf_natives.csv
    if not args.no_filter:
        sf_names = load_sf_native_names()
        if sf_names:
            before = len(native_um)
            native_um = [
                p for p in native_um
                if extract_name(p).lower() in sf_names
            ]
            print(f'After cross-referencing with sf_natives.csv: {len(native_um)} plants (was {before})')

    if not native_um:
        print('\nNo plants matched all filters. Consider --no-filter or --min-affinity 0')
        sys.exit(0)

    # Sort by um_affinity descending
    native_um.sort(key=lambda p: extract_um_affinity(p), reverse=True)

    # Print top N
    top_n = native_um[:args.top]
    print(f'\n{"─"*70}')
    print(f'  TOP {args.top} SF NATIVE PLANTS BY ULTRAMAFIC AFFINITY')
    print(f'  (source: CalFlora  |  county: {county})')
    print(f'{"─"*70}')
    print(f'  {"Rank":<5} {"um_aff":>6}  {"Scientific name":<35} {"Common name"}')
    print(f'{"─"*70}')
    for i, p in enumerate(top_n, 1):
        score  = extract_um_affinity(p)
        sci    = extract_name(p)
        common = extract_common(p)
        # Affinity label
        if score >= 5.5:
            label = 'strict endemic'
        elif score >= 4.5:
            label = 'broad endemic'
        elif score >= 3.5:
            label = 'transition'
        elif score >= 2.5:
            label = 'moderate indicator'
        else:
            label = ''
        tag = f'  [{label}]' if label else ''
        print(f'  {i:<5} {score:>6.2f}  {sci:<35} {common}{tag}')
    print(f'{"─"*70}')


if __name__ == '__main__':
    main()
