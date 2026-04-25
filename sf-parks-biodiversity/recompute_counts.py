#!/usr/bin/env python3
"""
Recompute all species counts for summary.json and per-park species files.

- Filters out genus-level observations (taxon name < 2 words)
- Computes native_cats / nativeCount using not-introduced logic
- Computes sf_native_cats / sfNativeCount using SF native plant list
  (sf_natives.csv) for plants; CA-native (not introduced) for all other taxa

Run from the sf-parks-biodiversity directory:
    python3 recompute_counts.py
"""

import json
from pathlib import Path

CATEGORIES = [
    'Plantae', 'Aves', 'Insecta', 'Mammalia', 'Fungi',
    'Reptilia', 'Amphibia', 'Arachnida', 'Mollusca',
]


def load_sf_natives(path):
    names = set()
    with open(path) as f:
        for line in f:
            name = line.strip()
            if name:
                names.add(name)
    return names


def species_key(name):
    """First two words of a taxon name (genus + epithet)."""
    parts = name.split()
    return ' '.join(parts[:2]) if len(parts) >= 2 else name


def is_species_level(taxon):
    return len((taxon.get('name') or '').split()) >= 2


def is_introduced(taxon):
    em = (taxon.get('establishment_means') or {}).get('establishment_means')
    return em in ('introduced', 'naturalizing')


def compute_counts(species_list, sf_natives):
    cats           = {c: 0 for c in CATEGORIES}
    native_cats    = {c: 0 for c in CATEGORIES}
    sf_native_cats = {c: 0 for c in CATEGORIES}
    total = native = introduced = sf_native = 0

    for s in species_list:
        t = s.get('taxon') or {}
        if not is_species_level(t):
            continue
        k = t.get('iconic_taxon_name')
        total += 1
        if k in cats:
            cats[k] += 1

        if is_introduced(t):
            introduced += 1
        else:
            native += 1
            if k in native_cats:
                native_cats[k] += 1
            # SF native: plants must be in sf_natives; others just not-introduced
            if k == 'Plantae':
                in_sf = species_key(t.get('name', '')) in sf_natives
            else:
                in_sf = True
            if in_sf:
                sf_native += 1
                if k in sf_native_cats:
                    sf_native_cats[k] += 1

    return dict(
        total=total, cats=cats,
        nativeCount=native, introducedCount=introduced, native_cats=native_cats,
        sfNativeCount=sf_native, sf_native_cats=sf_native_cats,
    )


def main():
    base       = Path(__file__).parent / 'data'
    sf_natives = load_sf_natives(base / 'sf_natives.csv')
    print(f'Loaded {len(sf_natives)} SF native plant names')

    summary_path = base / 'summary.json'
    summary      = json.loads(summary_path.read_text())

    updated = 0
    for f in sorted((base / 'species').glob('*.json')):
        pid = f.stem
        obj = json.loads(f.read_text())
        counts = compute_counts(obj.get('species', []), sf_natives)
        obj['summary'].update(counts)
        f.write_text(json.dumps(obj, separators=(',', ':')))
        if pid in summary:
            summary[pid].update(counts)
        updated += 1

    summary_path.write_text(json.dumps(summary, separators=(',', ':')))
    print(f'Updated {updated} species files and summary.json')


if __name__ == '__main__':
    main()
