#!/usr/bin/env python3
"""
Re-fetch POWO GrassBase pages and re-extract all morphological fields,
including variable detection (e.g. 'awned or awnless' → 'variable').

Audit fixes applied:
  - Spikelet length: require semicolons; prefer "Fertile spikelets" to avoid
    picking up involucral bristle lengths or sterile companion spikelet lengths
  - Awn length: prefer "Principal lemma awn" over lateral/sterile awns
  - Awn type: restricted to principal awn context (avoids "geniculately ascending" culm)
  - Inflorescence: spiciform → panicle_contracted; "open, or contracted" → variable
  - Rhizomatous: "Rhizomes absent, or short" → False (not over-called as True)
"""
import json, time, re, os, sys, urllib.request

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
GRASSES  = os.path.join(DATA_DIR, 'grasses.json')
DELAY    = 1.8

FIELDS = [
    'has_awns', 'awn_length_mm_min', 'awn_length_mm_max', 'awn_length_class', 'awn_type',
    'ligule', 'ligule_length_mm_min', 'ligule_length_mm_max',
    'leaf_sheath', 'leaf_blade_shape', 'auricles', 'culm_habit',
    'inflorescence', 'rhizomatous',
    'anther_count', 'lemma_surface', 'lemma_length_mm_min', 'lemma_length_mm_max',
    'lemma_veins', 'spikelet_compression',
    'spikelet_length_mm_min', 'spikelet_length_mm_max',
    'spikelet_width_mm_min', 'spikelet_width_mm_max',
    'glume_relative',
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
    return text[idx:idx+8000]

def parse_fields(gb):
    feats = {}

    # ── Has awns ──────────────────────────────────────────────────────────────
    has_awn   = bool(re.search(r'\bAwn\b|\bawned\b', gb, re.I))
    has_noawn = bool(re.search(r'\bawnless\b|\bmuticous\b|\bexapiculate\b', gb, re.I))
    if has_awn and has_noawn:
        feats['has_awns'] = 'variable'
    elif has_awn:
        feats['has_awns'] = True
    else:
        feats['has_awns'] = False

    # ── Awn length (prefer "Principal lemma awn") ─────────────────────────────
    if feats.get('has_awns') in (True, 'variable'):
        ml = re.search(r'Principal\s+lemma\s+awn[^;]*?(\d+(?:\.\d+)?)[–\-](\d+(?:\.\d+)?)\s*mm', gb, re.I)
        if not ml:
            ml = re.search(r'[Ll]emma\s+awn[^;]*?(\d+(?:\.\d+)?)[–\-](\d+(?:\.\d+)?)\s*mm', gb, re.I)
        if ml:
            lo, hi = float(ml.group(1)), float(ml.group(2))
            feats['awn_length_mm_min'] = lo
            feats['awn_length_mm_max'] = hi
            feats['awn_length_class'] = 'short' if (lo+hi)/2 <= 5 else 'medium' if (lo+hi)/2 <= 20 else 'long'

    # ── Awn type (restrict to principal awn context) ──────────────────────────
    if feats.get('has_awns') in (True, 'variable'):
        awn_ctx = ''
        m = re.search(r'Principal\s+lemma\s+awn([^;]+(?:;[^;]+){0,3})', gb, re.I)
        if m:
            awn_ctx = m.group(1)
        if re.search(r'geniculate', awn_ctx, re.I):
            feats['awn_type'] = 'geniculate'
        elif re.search(r'\bstraight\b|\bstiff\b', awn_ctx, re.I):
            feats['awn_type'] = 'straight'

    # ── Ligule type + length ──────────────────────────────────────────────────
    m = re.search(r'([Ll]igule\b[^;]{0,250})', gb)
    if m:
        lig = m.group(1)
        is_mem  = bool(re.search(r'membran', lig, re.I))
        is_cil  = bool(re.search(r'fringe of hairs|ciliate', lig, re.I))
        is_ecil = bool(re.search(r'eciliate', lig, re.I))
        if is_cil and not is_ecil and is_mem:
            feats['ligule'] = 'variable'
        elif re.search(r'fringe of hairs', lig, re.I):
            feats['ligule'] = 'ciliate'
        elif is_ecil and is_mem:
            feats['ligule'] = 'membranous'
        elif is_mem:
            feats['ligule'] = 'membranous'
        elif is_cil and not is_ecil:
            feats['ligule'] = 'ciliate'
        ml = re.search(r'(\d+(?:\.\d+)?)[–\-](\d+(?:\.\d+)?)\s*mm\s*long', lig, re.I)
        if ml:
            feats['ligule_length_mm_min'] = float(ml.group(1))
            feats['ligule_length_mm_max'] = float(ml.group(2))
        else:
            ml = re.search(r'(\d+(?:\.\d+)?)\s*mm\s*long', lig, re.I)
            if ml:
                feats['ligule_length_mm_min'] = float(ml.group(1))
                feats['ligule_length_mm_max'] = float(ml.group(1))

    # ── Rhizomatous ("absent, or short" → False) ──────────────────────────────
    m = re.search(r'[Rr]hizomes?\b([^;]{0,80})', gb)
    if m:
        feats['rhizomatous'] = not bool(re.search(r'\babsent\b', m.group(1), re.I))
    else:
        feats['rhizomatous'] = False

    # ── Leaf sheath ───────────────────────────────────────────────────────────
    m = re.search(r'(Leaf.sheaths?[^;]{0,200})', gb, re.I)
    if m:
        sh = m.group(1)
        is_open   = bool(re.search(r'\bopen\b', sh, re.I))
        is_closed = bool(re.search(r'\bclosed\b', sh, re.I))
        if is_open and is_closed:
            feats['leaf_sheath'] = 'variable'
        elif is_open:
            feats['leaf_sheath'] = 'open'
        elif is_closed:
            feats['leaf_sheath'] = 'closed'

    # ── Leaf blade shape ──────────────────────────────────────────────────────
    m = re.search(r'(Leaf.blades?[^;]{0,200})', gb, re.I)
    if m:
        lb = m.group(1)
        is_flat = bool(re.search(r'\bflat\b', lb, re.I))
        is_inv  = bool(re.search(r'\binvolute\b', lb, re.I))
        if is_flat and is_inv:
            feats['leaf_blade_shape'] = 'flat_or_involute'
        elif is_flat:
            feats['leaf_blade_shape'] = 'flat'
        elif is_inv:
            feats['leaf_blade_shape'] = 'involute'
        elif re.search(r'\bfolded\b', lb, re.I):
            feats['leaf_blade_shape'] = 'folded'
        elif re.search(r'\bconvolute\b', lb, re.I):
            feats['leaf_blade_shape'] = 'convolute'

    # ── Auricles ──────────────────────────────────────────────────────────────
    if re.search(r'\bauricles?\b', gb, re.I):
        has_present = bool(re.search(r'auricle[^;]{0,40}(falcate|lanceolate|present|\d+\s*mm)', gb, re.I))
        has_absent  = bool(re.search(r'auricles?\s+absent|lacking\s+auricles?', gb, re.I))
        if has_present and has_absent:
            feats['auricles'] = 'variable'
        elif has_absent:
            feats['auricles'] = False
        else:
            feats['auricles'] = True

    # ── Culm habit ────────────────────────────────────────────────────────────
    m = re.search(r'Culms?\s+([^;]{0,80})', gb, re.I)
    if m:
        culm = m.group(1).lower()
        habits = [h for h in ('erect', 'decumbent', 'geniculate', 'ascending', 'prostrate') if h in culm]
        if len(habits) > 1:
            feats['culm_habit'] = 'variable'
        elif habits:
            feats['culm_habit'] = habits[0]

    # ── Inflorescence (spiciform → panicle_contracted; open+contracted → variable) ──
    if re.search(r'Inflorescence a spike\b', gb, re.I):
        feats['inflorescence'] = 'spike'
    elif re.search(r'Inflorescence [^;]*raceme', gb, re.I):
        feats['inflorescence'] = 'raceme'
    elif re.search(r'[Pp]anicle\b', gb):
        m = re.search(r'[Pp]anicle\b([^;]{0,120})', gb)
        pan = m.group(1) if m else ''
        is_open  = bool(re.search(r'\bopen\b', pan, re.I))
        is_contr = bool(re.search(r'\b(contracted|dense|narrow|spike.like|spiciform)\b', pan, re.I))
        if is_open and is_contr:
            feats['inflorescence'] = 'variable'
        elif is_contr:
            feats['inflorescence'] = 'panicle_contracted'
        elif is_open:
            feats['inflorescence'] = 'panicle_open'
        else:
            feats['inflorescence'] = 'panicle'
    if re.search(r'digitate', gb, re.I):
        feats['inflorescence'] = 'digitate'

    # ── Anther count ──────────────────────────────────────────────────────────
    m = re.search(r'Anthers?\s+(\d)\b', gb, re.I)
    if m:
        feats['anther_count'] = int(m.group(1))

    # ── Lemma surface, length, veins ──────────────────────────────────────────
    m = re.search(r'([Ff]ertile lemma[^;]{0,400}(?:;[^;]{0,200}){0,5})', gb)
    if m:
        lem = m.group(1)
        ms = re.search(r'Lemma surface\s+([^;]{0,100})', gb, re.I)
        if ms:
            surf = ms.group(1)
            types_found = []
            if re.search(r'\bglabrous\b|\bsmooth\b', surf, re.I): types_found.append('glabrous')
            if re.search(r'\bpubescent\b', surf, re.I):           types_found.append('pubescent')
            if re.search(r'\bscabrous\b',  surf, re.I):           types_found.append('scabrous')
            if re.search(r'\bhairy\b',     surf, re.I):           types_found.append('hairy')
            result = 'variable' if len(types_found) > 1 else types_found[0] if types_found else None
            if result:
                feats['lemma_surface'] = result
        ml = re.search(r'(\d+(?:\.\d+)?)[–\-](\d+(?:\.\d+)?)\s*mm\s*long', lem, re.I)
        if ml:
            feats['lemma_length_mm_min'] = float(ml.group(1))
            feats['lemma_length_mm_max'] = float(ml.group(2))
        else:
            ml = re.search(r'(\d+(?:\.\d+)?)\s*mm\s*long', lem, re.I)
            if ml:
                feats['lemma_length_mm_min'] = float(ml.group(1))
                feats['lemma_length_mm_max'] = float(ml.group(1))
        mv = re.search(r'(\d+)[–\-](\d+)\s*-veined', lem, re.I)
        if mv:
            feats['lemma_veins'] = round((int(mv.group(1)) + int(mv.group(2))) / 2)
        else:
            mv = re.search(r'(\d+)\s*-veined', lem, re.I)
            if mv:
                feats['lemma_veins'] = int(mv.group(1))

    # ── Spikelet compression ──────────────────────────────────────────────────
    has_lat  = bool(re.search(r'laterally\s+compressed', gb, re.I))
    has_dors = bool(re.search(r'dorsiventrally\s+compressed|dorsally\s+compressed', gb, re.I))
    if has_lat and has_dors:
        feats['spikelet_compression'] = 'variable'
    elif has_lat:
        feats['spikelet_compression'] = 'lateral'
    elif has_dors:
        feats['spikelet_compression'] = 'dorsiventral'

    # ── Spikelet length (semicolons required; prefer "Fertile spikelets") ─────
    ml = re.search(r'[Ff]ertile\s+spikelets?[^;]*;[^;]*?(\d+(?:\.\d+)?)[–\-](\d+(?:\.\d+)?)\s*mm\s*long', gb, re.I)
    if not ml:
        ml = re.search(r'Spikelets?[^;]*;[^;]*?(\d+(?:\.\d+)?)[–\-](\d+(?:\.\d+)?)\s*mm\s*long', gb, re.I)
    if ml:
        feats['spikelet_length_mm_min'] = float(ml.group(1))
        feats['spikelet_length_mm_max'] = float(ml.group(2))

    # ── Spikelet width ────────────────────────────────────────────────────────
    mw = re.search(r'[Ff]ertile\s+spikelets?[^;]*;[^;]*?(\d+(?:\.\d+)?)[–\-](\d+(?:\.\d+)?)\s*mm\s*wide', gb, re.I)
    if not mw:
        mw = re.search(r'Spikelets?[^;]*;[^;]*?(\d+(?:\.\d+)?)[–\-](\d+(?:\.\d+)?)\s*mm\s*wide', gb, re.I)
    if mw:
        feats['spikelet_width_mm_min'] = float(mw.group(1))
        feats['spikelet_width_mm_max'] = float(mw.group(2))

    # ── Glume size relative to florets ────────────────────────────────────────
    mg = re.search(r'[Uu]pper glume[^;]*?(\d+(?:\.\d+)?)\s*length of adjacent fertile lemma', gb, re.I)
    if mg:
        ratio = float(mg.group(1))
        feats['glume_relative'] = 'shorter' if ratio < 0.8 else 'subequal' if ratio <= 1.05 else 'exceeding'
    else:
        mg2 = re.search(r'[Gg]lumes?\s[^;]{0,80}(shorter than spikelet|as long as spikelet|exceeding spikelet)', gb, re.I)
        if mg2:
            t = mg2.group(1).lower()
            feats['glume_relative'] = 'shorter' if 'shorter' in t else 'subequal' if 'as long' in t else 'exceeding'

    return feats


def needs_refresh(sp):
    return any(sp.get(f) is None for f in FIELDS)


species = json.load(open(GRASSES))
total   = len(species)
updated = 0

for i, sp in enumerate(species):
    ipni_id = sp.get('ipni_id')
    if not ipni_id:
        print(f'[{i+1}/{total}] {sp["sci_name"]}: no IPNI id, skip')
        continue

    if not needs_refresh(sp):
        print(f'[{i+1}/{total}] {sp["sci_name"]}: already complete')
        continue

    print(f'[{i+1}/{total}] {sp["sci_name"]}', end='', flush=True)
    try:
        url  = f'https://powo.science.kew.org/taxon/urn:lsid:ipni.org:names:{ipni_id}/general-information'
        html = fetch_html(url)
        gb   = extract_grassbase_text(html) if html else None
        if gb:
            new = parse_fields(gb)
            sp.update(new)
            found = [k for k in FIELDS if sp.get(k) is not None]
            print(f'  +{found}')
            updated += 1
        else:
            print('  no GrassBase section')
    except Exception as e:
        print(f'  ERROR: {e}')

    if (i + 1) % 10 == 0:
        json.dump(species, open(GRASSES, 'w'), indent=2)
        print(f'  [checkpoint {i+1}]')

json.dump(species, open(GRASSES, 'w'), indent=2)
print(f'\nDone. {updated}/{total} species processed.')
