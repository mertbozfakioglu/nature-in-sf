#!/usr/bin/env python3
"""
Enrich grasses.json with additional GrassBase morphological fields
not extracted in the original fetch_data.py run.

New fields added per species (where available):
  leaf_blade_shape    – flat | involute | folded | convolute
  auricles            – True / False
  anther_count        – 1 | 2 | 3
  lemma_surface       – glabrous | pubescent | scabrous | hairy
  spikelet_compression – lateral | dorsiventral
  spikelet_length_mm_min / spikelet_length_mm_max
  glumes              – description string (short / as long as / exceeding florets)
  lemma_shape         – lanceolate | ovate | oblong | elliptic etc.
"""
import json, time, re, os, sys, urllib.request

DATA_DIR  = os.path.join(os.path.dirname(__file__), 'data')
GRASSES   = os.path.join(DATA_DIR, 'grasses.json')
DELAY     = 1.8

NEW_FIELDS = [
    'leaf_blade_shape', 'auricles', 'anther_count',
    'lemma_surface', 'spikelet_compression',
    'spikelet_length_mm_min', 'spikelet_length_mm_max',
]

def fetch_html(url, retries=4):
    for attempt in range(retries):
        try:
            time.sleep(DELAY * (1 + attempt * 0.5))
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
                'Accept': 'text/html',
            })
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode('utf-8', errors='replace')
        except Exception as e:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            print(f'  retry in {wait}s ({e})', file=sys.stderr)
            time.sleep(wait)

def extract_grassbase_text(html):
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    html = re.sub(r'<style[^>]*>.*?</style>',  '', html, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text).strip()
    idx = text.find('GrassBase')
    if idx < 0:
        return None
    return text[idx:idx+6000]   # wider window than before

def parse_new_fields(gb):
    feats = {}

    # ── Leaf blade shape ──────────────────────────────────────────────────────
    # GrassBase: "Leaf-blades flat, or involute; ..."
    lb_section = ''
    m = re.search(r'(Leaf.blades?[^;.]{0,200})', gb, re.I)
    if m:
        lb_section = m.group(1)
    if re.search(r'\bflat\b', lb_section, re.I) and not re.search(r'\binvolute\b', lb_section, re.I):
        feats['leaf_blade_shape'] = 'flat'
    elif re.search(r'\binvolute\b', lb_section, re.I) and not re.search(r'\bflat\b', lb_section, re.I):
        feats['leaf_blade_shape'] = 'involute'
    elif re.search(r'\bflat\b', lb_section, re.I) and re.search(r'\binvolute\b', lb_section, re.I):
        feats['leaf_blade_shape'] = 'flat_or_involute'
    elif re.search(r'\bfolded\b', lb_section, re.I):
        feats['leaf_blade_shape'] = 'folded'
    elif re.search(r'\bconvolute\b', lb_section, re.I):
        feats['leaf_blade_shape'] = 'convolute'

    # ── Auricles ──────────────────────────────────────────────────────────────
    if re.search(r'\bauricles?\b', gb, re.I):
        # "auricles absent" vs any positive mention
        if re.search(r'auricles?\s+absent', gb, re.I):
            feats['auricles'] = False
        else:
            feats['auricles'] = True

    # ── Anther count ──────────────────────────────────────────────────────────
    # GrassBase format: "Anthers 3" or "Anthers 3; 0.7–1.2 mm long"
    m = re.search(r'Anthers?\s+(\d)\b', gb, re.I)
    if m:
        feats['anther_count'] = int(m.group(1))

    # ── Lemma surface ─────────────────────────────────────────────────────────
    # GrassBase: "Lemma surface glabrous, or pubescent; ..."
    m = re.search(r'Lemma surface\s+([^;.]{0,80})', gb, re.I)
    if m:
        surf = m.group(1)
        if re.search(r'\bglabrous\b', surf, re.I):
            feats['lemma_surface'] = 'glabrous'
        elif re.search(r'\bpubescent\b', surf, re.I):
            feats['lemma_surface'] = 'pubescent'
        elif re.search(r'\bscabrous\b', surf, re.I):
            feats['lemma_surface'] = 'scabrous'
        elif re.search(r'\bhairy\b', surf, re.I):
            feats['lemma_surface'] = 'hairy'
        elif re.search(r'\bsmooth\b', surf, re.I):
            feats['lemma_surface'] = 'glabrous'

    # ── Spikelet compression ──────────────────────────────────────────────────
    if re.search(r'laterally\s+compressed', gb, re.I):
        feats['spikelet_compression'] = 'lateral'
    elif re.search(r'dorsiventrally\s+compressed|dorsally\s+compressed', gb, re.I):
        feats['spikelet_compression'] = 'dorsiventral'

    # ── Spikelet length ───────────────────────────────────────────────────────
    m = re.search(r'Spikelets?[^.]*?(\d+(?:\.\d+)?)[–\-](\d+(?:\.\d+)?)\s*mm\s*(long|in\s+length)', gb, re.I)
    if m:
        feats['spikelet_length_mm_min'] = float(m.group(1))
        feats['spikelet_length_mm_max'] = float(m.group(2))

    return feats


def needs_enrichment(sp):
    return any(sp.get(f) is None for f in NEW_FIELDS)


species = json.load(open(GRASSES))
total = len(species)
updated = 0

for i, sp in enumerate(species):
    ipni_id = sp.get('ipni_id')
    if not ipni_id:
        print(f'[{i+1}/{total}] {sp["sci_name"]}: no IPNI id, skip')
        continue

    if not needs_enrichment(sp):
        print(f'[{i+1}/{total}] {sp["sci_name"]}: already enriched')
        continue

    print(f'[{i+1}/{total}] {sp["sci_name"]}', end='', flush=True)
    try:
        url = f'https://powo.science.kew.org/taxon/urn:lsid:ipni.org:names:{ipni_id}/general-information'
        html = fetch_html(url)
        gb = extract_grassbase_text(html) if html else None
        if gb:
            new = parse_new_fields(gb)
            sp.update(new)
            found = [k for k in NEW_FIELDS if sp.get(k) is not None]
            print(f'  +{found}')
            updated += 1
        else:
            print('  no GrassBase section')
    except Exception as e:
        print(f'  ERROR: {e}')

    # checkpoint every 10
    if (i + 1) % 10 == 0:
        json.dump(species, open(GRASSES, 'w'), indent=2)
        print(f'  [checkpoint {i+1}]')

json.dump(species, open(GRASSES, 'w'), indent=2)
print(f'\nDone. {updated}/{total} species enriched.')
