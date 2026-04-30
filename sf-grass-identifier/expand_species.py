#!/usr/bin/env python3
"""
Expand grasses.json with iNaturalist any-quality species that:
  - have ≥ MIN_OBS SF observations
  - are not already in grasses.json
  - are species rank (not genus, hybrid, section)
  - are not in the ornamental/cultivated exclusion list

Fetches IPNI id and POWO morphology for each new species.
"""
import json, time, re, os, sys, urllib.request

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
GRASSES  = os.path.join(DATA_DIR, 'grasses.json')

MIN_OBS = 2

# Bamboos and obvious crop staples already in dataset or not field-ID-relevant
EXCLUDE_GENERA = {
    'Bambusa', 'Phyllostachys', 'Himalayacalamus', 'Chusquea',
    'Dendrocalamus', 'Fargesia', 'Pleioblastus', 'Pseudosasa',
}

# ── HTTP helpers ──────────────────────────────────────────────────────────────

def fetch(url, accept='text/html', delay=1.5, retries=3):
    for attempt in range(retries):
        try:
            time.sleep(delay * (attempt + 1))
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
                'Accept': accept,
            })
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read().decode('utf-8', errors='replace')
        except Exception as e:
            print(f"  [attempt {attempt+1}] {e}", file=sys.stderr)
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    return None

def fetch_json(url, delay=1.5):
    raw = fetch(url, accept='application/json', delay=delay)
    return json.loads(raw) if raw else None

# ── Step 1: fetch all quality_grade=any species for SF ───────────────────────

def get_all_sf_grasses():
    species, page = [], 1
    while True:
        url = (f'https://api.inaturalist.org/v1/observations/species_counts'
               f'?taxon_id=47434&place_id=854&quality_grade=any'
               f'&per_page=500&page={page}')
        data = fetch_json(url, delay=2)
        if not data:
            break
        results = data.get('results', [])
        if not results:
            break
        for item in results:
            t = item['taxon']
            species.append({
                'inat_id':     t['id'],
                'sci_name':    t['name'],
                'common_name': t.get('preferred_common_name', ''),
                'rank':        t.get('rank', 'species'),
                'inat_obs_sf': item['count'],
            })
        if len(species) >= data.get('total_results', 0):
            break
        page += 1
    return species

# ── Step 2: IPNI lookup ───────────────────────────────────────────────────────

def get_ipni_id(sci_name):
    genus, *rest = sci_name.split()
    epithet = rest[0] if rest else ''
    q = f'{genus}+{epithet}' if epithet else genus
    url = f'https://www.ipni.org/api/1/search?q={q}&f=f_infraspecific:false&perPage=10'
    data = fetch_json(url, delay=1.2)
    if not data:
        return None
    for r in data.get('results', []):
        if r.get('name', '').lower() == sci_name.lower() and r.get('inPowo'):
            return r['url'].replace('/n/', '')
    for r in data.get('results', []):
        if r.get('inPowo'):
            return r['url'].replace('/n/', '')
    return None

# ── Step 3: POWO morphology ───────────────────────────────────────────────────

def parse_grassbase(html):
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    html = re.sub(r'<style[^>]*>.*?</style>',  '', html, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text).strip()
    idx = text.find('GrassBase')
    if idx < 0:
        return {}
    gb = text[idx:idx+4000]
    feats = {}

    if re.search(r'\bAnnual\b', gb):
        feats['duration'] = 'annual'
    if re.search(r'\bPerennial\b', gb):
        feats['duration'] = 'perennial' if 'duration' not in feats else 'annual_or_perennial'

    feats['caespitose']    = bool(re.search(r'caespitose', gb, re.I))
    feats['rhizomatous']   = bool(re.search(r'rhizom', gb, re.I))
    feats['stoloniferous'] = bool(re.search(r'stolon', gb, re.I))

    m = re.search(r'Culms[^.]*?(\d+)[–\-](\d+)\s*cm', gb)
    if m:
        feats['height_min_cm'] = int(m.group(1))
        feats['height_max_cm'] = int(m.group(2))

    m = re.search(r'([Ll]igule\b[^.]{0,250})', gb)
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

    m = re.search(r'Leaf.blades[^.]*?(\d+(?:\.\d+)?)[–\-](\d+(?:\.\d+)?)\s*mm\s*wide', gb)
    if m:
        feats['leaf_width_min_mm'] = float(m.group(1))
        feats['leaf_width_max_mm'] = float(m.group(2))
        w = (float(m.group(1)) + float(m.group(2))) / 2
        feats['leaf_width_class'] = 'filiform' if w < 1 else 'narrow' if w < 3 else 'medium' if w <= 8 else 'wide'

    if re.search(r'Inflorescence a spike\b', gb, re.I):
        feats['inflorescence'] = 'spike'
    elif re.search(r'Inflorescence [^.]*raceme', gb, re.I):
        feats['inflorescence'] = 'raceme'
    elif re.search(r'[Pp]anicle\b', gb):
        if re.search(r'[Pp]anicle\b[^.]{0,60}(contracted|dense|narrow|spike.like)', gb, re.I):
            feats['inflorescence'] = 'panicle_contracted'
        elif re.search(r'[Pp]anicle\b[^.]{0,60}open', gb, re.I):
            feats['inflorescence'] = 'panicle_open'
        else:
            feats['inflorescence'] = 'panicle'
    if re.search(r'digitate', gb, re.I):
        feats['inflorescence'] = 'digitate'

    m = re.search(r'comprising\s+(\d+)[–\-](\d+)\s+fertile florets', gb)
    if m:
        feats['florets_min'] = int(m.group(1))
        feats['florets_max'] = int(m.group(2))
    else:
        m = re.search(r'comprising\s+(\d+)\s+fertile florets', gb)
        if m:
            feats['florets_min'] = feats['florets_max'] = int(m.group(1))

    has_awn   = bool(re.search(r'\bAwn\b|\bawned\b', gb, re.I))
    has_noawn = bool(re.search(r'\bawnless\b|\bmuticous\b|\bexapiculate\b', gb, re.I))
    if has_awn and has_noawn:
        feats['has_awns'] = 'variable'
    elif has_awn:
        feats['has_awns'] = True
        m = re.search(r'[Aa]wn[^.]*?(\d+(?:\.\d+)?)[–\-](\d+(?:\.\d+)?)\s*mm\s*long', gb)
        if m:
            lo, hi = float(m.group(1)), float(m.group(2))
            feats['awn_length_mm_min'] = lo
            feats['awn_length_mm_max'] = hi
            avg = (lo + hi) / 2
            feats['awn_length_class'] = 'short' if avg <= 5 else 'medium' if avg <= 20 else 'long'
        if re.search(r'geniculate', gb, re.I):
            feats['awn_type'] = 'geniculate'
        elif re.search(r'\bstraight\b', gb, re.I):
            feats['awn_type'] = 'straight'
    elif 'has_awns' not in feats:
        feats['has_awns'] = False

    lb = ''
    m = re.search(r'(Leaf.blades?[^;.]{0,200})', gb, re.I)
    if m: lb = m.group(1)
    if re.search(r'\bflat\b', lb, re.I) and re.search(r'\binvolute\b', lb, re.I):
        feats['leaf_blade_shape'] = 'flat_or_involute'
    elif re.search(r'\bflat\b', lb, re.I):
        feats['leaf_blade_shape'] = 'flat'
    elif re.search(r'\binvolute\b', lb, re.I):
        feats['leaf_blade_shape'] = 'involute'
    elif re.search(r'\bfolded\b', lb, re.I):
        feats['leaf_blade_shape'] = 'folded'
    elif re.search(r'\bconvolute\b', lb, re.I):
        feats['leaf_blade_shape'] = 'convolute'

    if re.search(r'\bauricles?\b', gb, re.I):
        feats['auricles'] = not bool(re.search(r'auricles?\s+absent', gb, re.I))

    m = re.search(r'Anthers?\s+(\d)\b', gb, re.I)
    if m: feats['anther_count'] = int(m.group(1))

    m = re.search(r'Lemma surface\s+([^;.]{0,100})', gb, re.I)
    if m:
        surf = m.group(1)
        types = [t for t in ('glabrous','pubescent','scabrous','hairy') if re.search(rf'\b{t}\b', surf, re.I)]
        if len(types) > 1:
            feats['lemma_surface'] = 'variable'
        elif types:
            feats['lemma_surface'] = types[0]
        elif re.search(r'\bsmooth\b', surf, re.I):
            feats['lemma_surface'] = 'glabrous'

    if re.search(r'laterally\s+compressed', gb, re.I):
        feats['spikelet_compression'] = 'lateral'
    elif re.search(r'dorsiventrally\s+compressed|dorsally\s+compressed', gb, re.I):
        feats['spikelet_compression'] = 'dorsiventral'

    m = re.search(r'Spikelets?[^.]*?(\d+(?:\.\d+)?)[–\-](\d+(?:\.\d+)?)\s*mm\s*(long|in\s+length)', gb, re.I)
    if m:
        feats['spikelet_length_mm_min'] = float(m.group(1))
        feats['spikelet_length_mm_max'] = float(m.group(2))

    m = re.search(r'native range[^.]*?is\s+([^.]+)', text, re.I)
    if m:
        feats['native_range'] = m.group(1).strip()

    return feats

def get_powo_morphology(ipni_id):
    url = f'https://powo.science.kew.org/taxon/urn:lsid:ipni.org:names:{ipni_id}/general-information'
    html = fetch(url, delay=2)
    return parse_grassbase(html) if html else {}

def get_photo(inat_id):
    url = f'https://api.inaturalist.org/v1/taxa/{inat_id}'
    data = fetch_json(url, delay=1.5)
    if not data:
        return None, None
    taxon = data.get('results', [{}])[0]
    tp = taxon.get('taxon_photos', [])
    if tp:
        p = tp[0].get('photo', {})
        return (p.get('url', '').replace('square', 'small'),
                p.get('url', '').replace('square', 'medium'))
    return None, None

def get_native_to_ca(inat_id):
    url = f'https://api.inaturalist.org/v1/taxa/{inat_id}?place_id=14'
    data = fetch_json(url, delay=1.5)
    if not data:
        return None
    for r in data.get('results', []):
        em = r.get('establishment_means', {})
        if em:
            return em.get('establishment_means') in ('native', 'endemic')
    return None

# ── Main ──────────────────────────────────────────────────────────────────────

existing = json.load(open(GRASSES))
existing_names = {sp['sci_name'] for sp in existing}

print("Fetching all quality_grade=any species from iNaturalist SF...")
all_sf = get_all_sf_grasses()
print(f"  Total any-quality: {len(all_sf)}")

candidates = []
for sp in all_sf:
    if sp['sci_name'] in existing_names:
        continue
    if sp['inat_obs_sf'] < MIN_OBS:
        continue
    if sp['rank'] != 'species':
        continue
    if '×' in sp['sci_name']:
        continue
    genus = sp['sci_name'].split()[0]
    if genus in EXCLUDE_GENERA:
        continue
    candidates.append(sp)

print(f"\nNew species to add ({len(candidates)}):")
for sp in candidates:
    print(f"  {sp['sci_name']} ({sp['inat_obs_sf']} obs)")

if not candidates:
    print("Nothing to add.")
    sys.exit(0)

print(f"\nEnriching {len(candidates)} species...")
new_records = []
for i, sp in enumerate(candidates):
    name = sp['sci_name']
    print(f"[{i+1}/{len(candidates)}] {name}", end='', flush=True)

    ipni_id = get_ipni_id(name)
    morph   = get_powo_morphology(ipni_id) if ipni_id else {}
    photo_s, photo_m = get_photo(sp['inat_id'])
    native  = get_native_to_ca(sp['inat_id'])

    record = {
        **sp,
        'ipni_id':      ipni_id,
        'photo_url':    photo_s,
        'photo_medium': photo_m,
        'native_to_ca': native,
        **morph,
    }
    new_records.append(record)
    print(f"  ipni={ipni_id} morph={list(morph.keys())}")

existing.extend(new_records)
json.dump(existing, open(GRASSES, 'w'), indent=2)
print(f"\nDone. Added {len(new_records)} species. Total: {len(existing)}")
