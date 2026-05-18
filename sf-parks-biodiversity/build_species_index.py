#!/usr/bin/env python3
"""
Build data/species_index.json from per-park species files.
Inverts park→species into species→parks so the app can look up
which parks a given species has been observed in.

Usage:
    python3 build_species_index.py
"""

import json
from pathlib import Path


def main():
    base        = Path(__file__).parent / 'data'
    species_dir = base / 'species'
    out_path    = base / 'species_index.json'

    taxon_map = {}  # id → entry dict

    files = sorted(species_dir.glob('*.json'))
    print(f'Reading {len(files)} park species files…')

    for f in files:
        park_id = f.stem
        for s in json.loads(f.read_text()).get('species', []):
            t   = s.get('taxon') or {}
            tid = t.get('id')
            if not tid:
                continue
            if tid not in taxon_map:
                photo = (t.get('default_photo') or {}).get('square_url') or ''
                taxon_map[tid] = {
                    'id':     tid,
                    'name':   t.get('name')                   or '',
                    'common': t.get('preferred_common_name')   or '',
                    'iconic': t.get('iconic_taxon_name')       or '',
                    'photo':  photo,
                    'parks':  [],
                }
            taxon_map[tid]['parks'].append(park_id)

    species_list = sorted(taxon_map.values(), key=lambda s: s['name'].lower())

    out_path.write_text(json.dumps(species_list, separators=(',', ':')))
    size_kb = out_path.stat().st_size // 1024
    print(f'Saved species_index.json  ({len(species_list)} species, {size_kb} KB)')


if __name__ == '__main__':
    main()
