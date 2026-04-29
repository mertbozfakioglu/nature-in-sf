#!/usr/bin/env python3
"""
Fetches SF grass species from iNaturalist and morphological data from Kew POWO/GrassBase.
Outputs data/grasses.json
"""
import urllib.request, json, time, re, os

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(DATA_DIR, exist_ok=True)

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
            print(f"  [attempt {attempt+1}] {e}")
    return None

def fetch_json(url, delay=1.5):
    raw = fetch(url, accept='application/json', delay=delay)
    return json.loads(raw) if raw else None

# ── Step 1: fetch SF grass species from iNaturalist ──────────────────────────

def get_sf_grasses():
    print("Fetching SF grass species from iNaturalist...")
    species = []
    page = 1
    while True:
        url = (f'https://api.inaturalist.org/v1/observations/species_counts'
               f'?taxon_id=47434&place_id=854&quality_grade=research'
               f'&per_page=100&page={page}')
        data = fetch_json(url, delay=2)
        if not data:
            break
        results = data.get('results', [])
        if not results:
            break
        for item in results:
            t = item['taxon']
            species.append({
                'inat_id':      t['id'],
                'sci_name':     t['name'],
                'common_name':  t.get('preferred_common_name', ''),
                'rank':         t.get('rank', 'species'),
                'inat_obs_sf':  item['count'],
            })
        print(f"  page {page}: {len(results)} species (total {len(species)})")
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
        # prefer exact name match that is in POWO
        if r.get('name', '').lower() == sci_name.lower() and r.get('inPowo'):
            return r['url'].replace('/n/', '')
    # fallback: first inPowo result
    for r in data.get('results', []):
        if r.get('inPowo'):
            return r['url'].replace('/n/', '')
    return None

# ── Step 3: fetch + parse GrassBase morphology from POWO ─────────────────────

def parse_grassbase(html):
    """Extract key morphological features from GrassBase section of POWO page."""
    # strip scripts/styles
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    html = re.sub(r'<style[^>]*>.*?</style>',  '', html, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text).strip()

    idx = text.find('GrassBase')
    if idx < 0:
        return {}
    gb = text[idx:idx+4000]

    feats = {}

    # Duration
    if re.search(r'\bAnnual\b', gb):
        feats['duration'] = 'annual'
    if re.search(r'\bPerennial\b', gb):
        feats['duration'] = 'perennial' if 'duration' not in feats else 'annual_or_perennial'

    # Habit
    feats['caespitose']    = bool(re.search(r'caespitose', gb, re.I))
    feats['rhizomatous']   = bool(re.search(r'rhizom', gb, re.I))
    feats['stoloniferous'] = bool(re.search(r'stolon', gb, re.I))

    # Culm height
    m = re.search(r'Culms[^.]*?(\d+)[–\-](\d+)\s*cm', gb)
    if m:
        feats['height_min_cm'] = int(m.group(1))
        feats['height_max_cm'] = int(m.group(2))

    # Ligule
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

    # Leaf blade width
    m = re.search(r'Leaf.blades[^.]*?(\d+(?:\.\d+)?)[–\-](\d+(?:\.\d+)?)\s*mm\s*wide', gb)
    if m:
        feats['leaf_width_min_mm'] = float(m.group(1))
        feats['leaf_width_max_mm'] = float(m.group(2))
        w = (float(m.group(1)) + float(m.group(2))) / 2
        if w < 1:
            feats['leaf_width_class'] = 'filiform'
        elif w < 3:
            feats['leaf_width_class'] = 'narrow'
        elif w <= 8:
            feats['leaf_width_class'] = 'medium'
        else:
            feats['leaf_width_class'] = 'wide'

    # Inflorescence
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

    # Florets per spikelet
    m = re.search(r'comprising\s+(\d+)[–\-](\d+)\s+fertile florets', gb)
    if m:
        feats['florets_min'] = int(m.group(1))
        feats['florets_max'] = int(m.group(2))
    else:
        m = re.search(r'comprising\s+(\d+)\s+fertile florets', gb)
        if m:
            feats['florets_min'] = int(m.group(1))
            feats['florets_max'] = int(m.group(1))

    # Awns
    awn_section = ''
    m = re.search(r'(Awn[^.]{0,400})', gb)
    if m:
        awn_section = m.group(1)

    has_awn   = bool(re.search(r'\bAwn\b|\bawned\b', gb, re.I))
    has_noawn = bool(re.search(r'\bawnless\b|\bmuticous\b|\bexapiculate\b', gb, re.I))
    if has_awn and has_noawn:
        feats['has_awns'] = 'variable'
    elif has_awn:
        feats['has_awns'] = True

    if feats.get('has_awns') in (True, 'variable'):
        # awn length
        m = re.search(r'[Aa]wn[^.]*?(\d+(?:\.\d+)?)[–\-](\d+(?:\.\d+)?)\s*mm\s*long', gb)
        if m:
            alen = (float(m.group(1)) + float(m.group(2))) / 2
            feats['awn_length_mm_min'] = float(m.group(1))
            feats['awn_length_mm_max'] = float(m.group(2))
            if alen <= 5:
                feats['awn_length_class'] = 'short'
            elif alen <= 20:
                feats['awn_length_class'] = 'medium'
            else:
                feats['awn_length_class'] = 'long'
        # awn type
        if re.search(r'geniculate', gb, re.I):
            feats['awn_type'] = 'geniculate'
        elif re.search(r'straight', awn_section, re.I):
            feats['awn_type'] = 'straight'
    elif 'has_awns' not in feats:
        feats['has_awns'] = False

    # ── Leaf blade shape ──────────────────────────────────────────────────────
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
        feats['auricles'] = not bool(re.search(r'auricles?\s+absent', gb, re.I))

    # ── Anther count ──────────────────────────────────────────────────────────
    m = re.search(r'Anthers?\s+(\d)\b', gb, re.I)
    if m:
        feats['anther_count'] = int(m.group(1))

    # ── Lemma surface ─────────────────────────────────────────────────────────
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

    # Native range (not in GrassBase but appears earlier on page)
    m = re.search(r'native range[^.]*?is\s+([^.]+)', text, re.I)
    if m:
        feats['native_range'] = m.group(1).strip()

    return feats

def get_powo_morphology(ipni_id):
    url = f'https://powo.science.kew.org/taxon/urn:lsid:ipni.org:names:{ipni_id}/general-information'
    html = fetch(url, delay=2)
    if not html:
        return {}
    return parse_grassbase(html)

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # Step 1
    species = get_sf_grasses()
    print(f"\nTotal SF grass species: {len(species)}\n")

    results = []
    for i, sp in enumerate(species):
        name = sp['sci_name']
        print(f"[{i+1}/{len(species)}] {name} ({sp['inat_obs_sf']} obs)")

        # Step 2: IPNI ID
        ipni_id = get_ipni_id(name)
        if ipni_id:
            print(f"  IPNI: {ipni_id}")
            # Step 3: morphology
            morph = get_powo_morphology(ipni_id)
            print(f"  features: {list(morph.keys())}")
        else:
            print(f"  IPNI: not found")
            morph = {}

        results.append({**sp, 'ipni_id': ipni_id, **morph})

        # Save checkpoint every 10 species
        if (i + 1) % 10 == 0:
            out = os.path.join(DATA_DIR, 'grasses.json')
            with open(out, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"  [checkpoint saved: {i+1} species]")

    # Final save
    out = os.path.join(DATA_DIR, 'grasses.json')
    with open(out, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nDone! Saved {len(results)} species to {out}")

if __name__ == '__main__':
    main()
