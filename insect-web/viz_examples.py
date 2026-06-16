"""
Generate 4 visualization style previews using the real filtered dataset.
"""
import json, math
from collections import defaultdict, Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.patheffects as pe
import numpy as np
import networkx as nx

DATA_DIR  = Path(__file__).parent
OUT_DIR   = DATA_DIR / "charts"

# ── load + filter (same pipeline as analyze.py) ───────────────────────────────
raw  = json.load(open(DATA_DIR / "raw_interactions.json"))
araw = json.load(open(DATA_DIR / "raw_animal_interactions.json"))
nat  = json.load(open(DATA_DIR / "nativity.json"))
sf_obs_raw = json.load(open(DATA_DIR / "sf_obs_cache.json"))
sf_natives = {l.strip() for l in
    (DATA_DIR.parent / "sf-parks-biodiversity/data/sf_natives.csv")
    .read_text().splitlines() if l.strip()}

NOISE    = {'interactsWith','coOccursWith','adjacentTo','visits','visitedBy',
            'livesOn','livedOnBy','ecologicallyRelatedTo'}
PARASITIC = {'parasiteOf','hasParasite','hostOf','hasHost'}
EXCLUDE  = {k for k,v in nat.items() if v in ('non_native','no_ca_obs')}
KEEP_K   = {'Insecta','Plantae','Aves','Mammalia','Arachnida','Fungi'}
MIRROR   = {'hasHost':'hostOf','eatenBy':'eats','pollinatedBy':'pollinates',
            'preyedUponBy':'preysOn','hasParasite':'parasiteOf',
            'hasParasitoid':'parasitoidOf','pathogenOf':'hasPathogen',
            'flowersVisitedBy':'visitsFlowersOf'}
MIN_SF_OBS = 10
MIN_DEGREE = 5

def is_plant(p): return any(k in (p or '') for k in (
    'Plantae','Angiosperms','Viridiplantae','Tracheophyta','Spermatophytes',
    'Gymnosperms','Bryophyta','Equisetopsida','Pteridophytes','Pteridobiotina',
    'Fagales','Poales','Caryophyllales','Lamiales','Asterales','Rosales',
    'Fabales','Malpighiales','Ericales','Solanales','Apiales',
    'Ranunculales','Myrtales','Malvales','lamiids',
))

def kingdom(p):
    p = p or ''
    for k,kw in [
        ('Insecta','Insecta'),
        ('Insecta','Hemiptera'),('Insecta','Hymenoptera'),
        ('Insecta','Lepidoptera'),('Insecta','Coleoptera'),('Insecta','Diptera'),
        ('Insecta','Orthoptera'),('Insecta','Thysanoptera'),('Insecta','Neuroptera'),
        ('Insecta','Trichoptera'),('Insecta','Odonata'),('Insecta','Blattodea'),
        ('Insecta','Noctuoidea'),('Insecta','Geometroidea'),('Insecta','Bombycoidea'),
        ('Insecta','Papilionoidea'),
        ('Insecta','Aschiza'),('Insecta','Schizophora'),
        ('Insecta','Cicadellidae'),('Insecta','Tropiduchidae'),('Insecta','Miridae'),
        ('Insecta','Aphididae'),('Insecta','Membracidae'),('Insecta','Cercopidae'),
        ('Insecta','Psyllidae'),('Insecta','Tingidae'),('Insecta','Lygaeidae'),
        ('Insecta','Pentatomidae'),
        ('Insecta','Megachilidae'),('Insecta','Apidae'),('Insecta','Vespidae'),
        ('Insecta','Eumeninae'),('Insecta','Ichneumonidae'),('Insecta','Braconidae'),
        ('Insecta','Formicidae'),
        ('Insecta','Tortricidae'),('Insecta','Noctuidae'),('Insecta','Geometridae'),
        ('Insecta','Hesperiidae'),('Insecta','Pterophoridae'),('Insecta','Nymphalidae'),
        ('Insecta','Lycaenidae'),('Insecta','Pieridae'),('Insecta','Papilionidae'),
        ('Insecta','Saturniidae'),('Insecta','Sphingidae'),
        ('Insecta','Syrphidae'),('Insecta','Tachinidae'),
        ('Insecta','Cerambycidae'),('Insecta','Curculionidae'),('Insecta','Chrysomelidae'),
        ('Insecta','Coccinellidae'),('Insecta','Buprestidae'),
        ('Insecta','Polyommatini'),
        ('Arachnida','Arachnida'),
        ('Aves','Aves'),('Aves','Australavis'),
        ('Mammalia','Mammalia'),('Mammalia','Theria'),
        ('Fungi','Fungi'),('Fungi','Ascomycota'),('Fungi','Basidiomycota'),
        ('Fungi','Puccinia'),('Fungi','Coleosporium'),('Fungi','Exobasidium'),
        ('Fungi','Podosphaera'),('Fungi','Erysiphe'),('Fungi','Ramularia'),
        ('Fungi','Harknessia'),('Fungi','Stamnaria'),('Fungi','Otidea'),
        ('Fungi','Ovularia'),('Fungi','Graphyllium'),
        ('Plantae','Plantae'),('Plantae','Angiosperms'),('Plantae','Viridiplantae'),
        ('Plantae','Tracheophyta'),('Plantae','Spermatophytes'),('Plantae','Gymnosperms'),
        ('Plantae','Bryophyta'),('Plantae','Equisetopsida'),
        ('Plantae','Pteridophytes'),('Plantae','Pteridobiotina'),
        ('Plantae','Fagales'),('Plantae','Poales'),('Plantae','Caryophyllales'),
        ('Plantae','Lamiales'),('Plantae','Asterales'),('Plantae','Rosales'),
        ('Plantae','Fabales'),('Plantae','Malpighiales'),('Plantae','Ericales'),
        ('Plantae','Solanales'),('Plantae','Apiales'),('Plantae','Ranunculales'),
        ('Plantae','Myrtales'),('Plantae','Malvales'),('Plantae','lamiids'),
        ('Nematoda','Nematoda'),('Bacteria','Bacteria'),
    ]:
        if kw in p: return k
    return 'Other'

path_of = {}
base = []
seen = set()
sf_pass = {p for p in sf_natives if sf_obs_raw.get(p, -1) >= MIN_SF_OBS}

for r in raw + araw:
    itype = r.get('interaction_type','')
    sp = (r.get('source_taxon_path') or '')
    tp = (r.get('target_taxon_path') or '')
    sn = (r.get('source_taxon_name') or '').strip()
    tn = (r.get('target_taxon_name') or '').strip()
    if sn: path_of[sn] = sp
    if tn: path_of[tn] = tp
    if itype in NOISE and is_plant(sp) and is_plant(tp): continue
    if is_plant(sp) and is_plant(tp) and itype not in PARASITIC: continue
    if sn in EXCLUDE or tn in EXCLUDE: continue
    if sn in sf_natives and sn not in sf_pass: continue
    if tn in sf_natives and tn not in sf_pass: continue
    sk, tk = kingdom(sp), kingdom(tp)
    if sk not in KEEP_K or tk not in KEEP_K: continue
    canonical = MIRROR.get(itype, itype)
    if itype in MIRROR: sn, tn, sk, tk = tn, sn, tk, sk
    key = (sn, canonical, tn)
    if key in seen: continue
    seen.add(key)
    base.append({'sn':sn,'tn':tn,'sk':sk,'tk':tk,'itype':canonical})

for _ in range(2):
    deg = defaultdict(int)
    for r in base: deg[r['sn']] += 1; deg[r['tn']] += 1
    base = [r for r in base if deg[r['sn']] >= MIN_DEGREE and deg[r['tn']] >= MIN_DEGREE]

print(f"Filtered: {len({r['sn'] for r in base}|{r['tn'] for r in base})} nodes, {len(base)} edges")

node_kingdom = {}
for r in base:
    node_kingdom[r['sn']] = r['sk']
    node_kingdom[r['tn']] = r['tk']

COLORS = {
    'Plantae':  '#4a9e6b',
    'Insecta':  '#e08c2e',
    'Fungi':    '#9b6b3a',
    'Aves':     '#4a7bbf',
    'Mammalia': '#c45c7a',
    'Arachnida':'#8e6bbf',
    'Other':    '#aaaaaa',
}
EDGE_COLORS = {
    'hostOf':         '#9b6b3a',
    'eats':           '#c0392b',
    'visitsFlowersOf':'#f39c12',
    'pollinates':     '#f1c40f',
    'parasiteOf':     '#8e44ad',
    'hasPathogen':    '#e74c3c',
    'preysOn':        '#c0392b',
    'mutualistOf':    '#27ae60',
    'symbiontOf':     '#16a085',
    'parasitoidOf':   '#6c3483',
}

# build networkx graph
G = nx.Graph()
for r in base:
    G.add_node(r['sn'], kingdom=r['sk'])
    G.add_node(r['tn'], kingdom=r['tk'])
    G.add_edge(r['sn'], r['tn'], itype=r['itype'])

degrees = dict(G.degree())
all_nodes = list(G.nodes())
node_colors = [COLORS.get(node_kingdom.get(n,'Other'),'#aaaaaa') for n in all_nodes]
node_sizes  = [20 + degrees[n]**1.4 * 4 for n in all_nodes]

# ══════════════════════════════════════════════════════════════════════════════
# VIZ 1 — Force-directed graph (spring layout)
# ══════════════════════════════════════════════════════════════════════════════
print("Rendering viz 1: force-directed …")
fig, ax = plt.subplots(figsize=(16, 14), facecolor='#0d1117')
ax.set_facecolor('#0d1117')

pos = nx.spring_layout(G, k=1.8/math.sqrt(len(G)), seed=42, iterations=80)

# edges by type, faint
for r in base:
    u, v = r['sn'], r['tn']
    if u not in pos or v not in pos: continue
    ec = EDGE_COLORS.get(r['itype'], '#444444')
    x = [pos[u][0], pos[v][0]]
    y = [pos[u][1], pos[v][1]]
    ax.plot(x, y, color=ec, alpha=0.15, linewidth=0.5, zorder=1)

nx.draw_networkx_nodes(G, pos, nodelist=all_nodes,
    node_color=node_colors, node_size=node_sizes,
    alpha=0.92, ax=ax, linewidths=0.3,
    edgecolors=[c + '88' for c in node_colors])

# label only high-degree nodes
top_nodes = sorted(degrees.items(), key=lambda x: x[1], reverse=True)[:30]
for name, deg in top_nodes:
    if name not in pos: continue
    short = name.split()[-1] if kingdom(path_of.get(name,'')) == 'Insecta' else name.split()[0]
    ax.text(pos[name][0], pos[name][1]+0.022, short,
        fontsize=5.5, color='white', ha='center', va='bottom', zorder=5,
        path_effects=[pe.withStroke(linewidth=1.5, foreground='#0d1117')])

legend_patches = [mpatches.Patch(color=v, label=k) for k,v in COLORS.items() if k != 'Other']
ax.legend(handles=legend_patches, loc='lower left', fontsize=9,
    framealpha=0.4, facecolor='#1a1a2e', edgecolor='#444', labelcolor='white')
ax.set_title('SF Native Plant Ecological Web  —  Force-Directed Layout',
    color='white', fontsize=14, pad=12, fontweight='bold')
ax.axis('off')
plt.tight_layout()
fig.savefig(OUT_DIR / "viz1_force_directed.png", dpi=150, bbox_inches='tight',
    facecolor='#0d1117')
plt.close()
print("  saved viz1_force_directed.png")

# ══════════════════════════════════════════════════════════════════════════════
# VIZ 2 — Radial hub layout: plants at center ring, interactors outside
# ══════════════════════════════════════════════════════════════════════════════
print("Rendering viz 2: radial hub …")
fig, ax = plt.subplots(figsize=(16, 16), facecolor='#0d1117')
ax.set_facecolor('#0d1117')

plant_nodes = sorted([n for n in G.nodes() if node_kingdom.get(n) == 'Plantae'],
                     key=lambda n: degrees[n], reverse=True)
outer_nodes = [n for n in G.nodes() if node_kingdom.get(n) != 'Plantae']

pos2 = {}
# inner ring: plants
for i, n in enumerate(plant_nodes):
    angle = 2 * math.pi * i / len(plant_nodes)
    r = 0.45 + 0.08 * (degrees[n] / max(degrees[p] for p in plant_nodes))
    pos2[n] = (r * math.cos(angle), r * math.sin(angle))

# outer nodes: group by kingdom, place in bands
k_outer = defaultdict(list)
for n in outer_nodes:
    k_outer[node_kingdom.get(n,'Other')].append(n)

k_order = ['Insecta','Fungi','Aves','Mammalia','Arachnida']
k_angles = {}
start = 0
for k in k_order:
    nodes_k = sorted(k_outer[k], key=lambda n: degrees[n], reverse=True)
    span = 2 * math.pi * len(nodes_k) / len(outer_nodes)
    for j, n in enumerate(nodes_k):
        angle = start + span * j / max(len(nodes_k), 1)
        r = 0.78 + 0.12 * (degrees[n] / max(degrees.get(x,1) for x in nodes_k))
        pos2[n] = (r * math.cos(angle), r * math.sin(angle))
    start += span

for r in base:
    u, v = r['sn'], r['tn']
    if u not in pos2 or v not in pos2: continue
    ec = EDGE_COLORS.get(r['itype'], '#444444')
    ax.plot([pos2[u][0], pos2[v][0]], [pos2[u][1], pos2[v][1]],
        color=ec, alpha=0.12, linewidth=0.5, zorder=1)

for n in G.nodes():
    if n not in pos2: continue
    c = COLORS.get(node_kingdom.get(n,'Other'), '#aaaaaa')
    s = 15 + degrees[n]**1.5 * 3
    ax.scatter(*pos2[n], s=s, color=c, alpha=0.9, zorder=3, linewidths=0.2,
               edgecolors=c+'88')

top30 = {n for n,_ in sorted(degrees.items(), key=lambda x:x[1], reverse=True)[:35]}
for n in top30:
    if n not in pos2: continue
    short = ' '.join(n.split()[:2]) if node_kingdom.get(n) == 'Plantae' else n.split()[-1]
    ax.text(pos2[n][0], pos2[n][1], short, fontsize=5,
        color='white', ha='center', va='center', zorder=5,
        path_effects=[pe.withStroke(linewidth=1.2, foreground='#0d1117')])

# kingdom arc labels
ax.text(0, 0, 'Plants', color=COLORS['Plantae'], ha='center', va='center',
    fontsize=10, fontweight='bold', alpha=0.6)
legend_patches = [mpatches.Patch(color=v, label=k) for k,v in COLORS.items() if k != 'Other']
ax.legend(handles=legend_patches, loc='lower left', fontsize=9,
    framealpha=0.4, facecolor='#1a1a2e', edgecolor='#444', labelcolor='white')
ax.set_xlim(-1.1,1.1); ax.set_ylim(-1.1,1.1)
ax.set_title('SF Native Plant Ecological Web  —  Radial Layout\n(plants inner ring, interactors outer)',
    color='white', fontsize=13, pad=12, fontweight='bold')
ax.axis('off')
plt.tight_layout()
fig.savefig(OUT_DIR / "viz2_radial.png", dpi=150, bbox_inches='tight',
    facecolor='#0d1117')
plt.close()
print("  saved viz2_radial.png")

# ══════════════════════════════════════════════════════════════════════════════
# VIZ 3 — Chord diagram (kingdom × kingdom interaction volumes)
# ══════════════════════════════════════════════════════════════════════════════
print("Rendering viz 3: chord diagram …")
kingdoms_order = ['Plantae','Insecta','Fungi','Aves','Mammalia','Arachnida']
k_idx = {k:i for i,k in enumerate(kingdoms_order)}
n = len(kingdoms_order)
matrix = np.zeros((n, n))
for r in base:
    i = k_idx.get(r['sk'], -1)
    j = k_idx.get(r['tk'], -1)
    if i >= 0 and j >= 0:
        matrix[i][j] += 1
        matrix[j][i] += 1

fig, ax = plt.subplots(figsize=(11, 11), facecolor='#0d1117')
ax.set_facecolor('#0d1117')
ax.set_aspect('equal')

totals = matrix.sum(axis=1)
gap = 0.03
starts = {}
cur = 0
arcs = {}
for i, k in enumerate(kingdoms_order):
    span = (totals[i] / totals.sum()) * (2*math.pi - n*gap)
    starts[k] = cur
    arcs[k] = span
    cur += span + gap

def arc_path(ax, start, end, r_inner, r_outer, color, alpha=0.85):
    theta = np.linspace(start, end, 60)
    xs = np.concatenate([r_outer*np.cos(theta), r_inner*np.cos(theta[::-1])])
    ys = np.concatenate([r_outer*np.sin(theta), r_inner*np.sin(theta[::-1])])
    ax.fill(xs, ys, color=color, alpha=alpha, zorder=3)

# draw kingdom arcs
for k in kingdoms_order:
    s, sp = starts[k], arcs[k]
    arc_path(ax, s, s+sp, 0.82, 0.92, COLORS[k])
    mid = s + sp/2
    ax.text(0.97*math.cos(mid), 0.97*math.sin(mid), k,
        ha='center', va='center', fontsize=9, color='white', fontweight='bold',
        rotation=math.degrees(mid) if mid < math.pi else math.degrees(mid)-180)

# draw chord ribbons
flow_starts = {k: starts[k] for k in kingdoms_order}
for i, ki in enumerate(kingdoms_order):
    for j, kj in enumerate(kingdoms_order):
        if j <= i: continue
        vol = matrix[i][j]
        if vol < 5: continue
        si_span = (vol / totals[i]) * arcs[ki]
        sj_span = (vol / totals[j]) * arcs[kj]
        si = flow_starts[ki]; flow_starts[ki] += si_span
        sj = flow_starts[kj]; flow_starts[kj] += sj_span
        t1 = np.linspace(si, si+si_span, 30)
        t2 = np.linspace(sj, sj+sj_span, 30)
        p1s = np.array([0.81*math.cos(si), 0.81*math.sin(si)])
        p1e = np.array([0.81*math.cos(si+si_span), 0.81*math.sin(si+si_span)])
        p2s = np.array([0.81*math.cos(sj), 0.81*math.sin(sj)])
        p2e = np.array([0.81*math.cos(sj+sj_span), 0.81*math.sin(sj+sj_span)])
        c1m = np.array([0.81*math.cos((si+si+si_span)/2), 0.81*math.sin((si+si+si_span)/2)])
        c2m = np.array([0.81*math.cos((sj+sj+sj_span)/2), 0.81*math.sin((sj+sj+sj_span)/2)])
        orig = np.array([0., 0.])
        ts = np.linspace(0,1,80)
        def bezier(P0,P1,P2,P3,t):
            return ((1-t)**3*P0[:,None] + 3*(1-t)**2*t*P1[:,None]
                    + 3*(1-t)*t**2*P2[:,None] + t**3*P3[:,None])
        top = bezier(p1s, orig*0.3, orig*0.3, p2s, ts)
        bot = bezier(p1e, orig*0.3, orig*0.3, p2e, ts)
        col = COLORS.get(ki if totals[i]>=totals[j] else kj, '#666')
        ax.fill(top[0].tolist()+bot[0,::-1].tolist(),
                top[1].tolist()+bot[1,::-1].tolist(),
                color=col, alpha=0.28, zorder=2)

ax.set_xlim(-1.2,1.2); ax.set_ylim(-1.2,1.2)
ax.set_title('Kingdom × Kingdom Interaction Volumes  —  Chord Diagram',
    color='white', fontsize=13, pad=12, fontweight='bold')
ax.axis('off')
plt.tight_layout()
fig.savefig(OUT_DIR / "viz3_chord.png", dpi=150, bbox_inches='tight', facecolor='#0d1117')
plt.close()
print("  saved viz3_chord.png")

# ══════════════════════════════════════════════════════════════════════════════
# VIZ 4 — Sankey: plant family → interaction type → consumer kingdom
# ══════════════════════════════════════════════════════════════════════════════
print("Rendering viz 4: Sankey flow …")

def plant_family(path):
    for p in (path or '').split('|'):
        p = p.strip()
        if p.endswith('aceae'): return p
    return 'Other'

fam_itype = defaultdict(Counter)
itype_kingdom = defaultdict(Counter)
for r in base:
    if r['sk'] == 'Plantae' and r['tk'] != 'Plantae':
        fam = plant_family(path_of.get(r['sn'],''))
        fam_itype[fam][r['itype']] += 1
        itype_kingdom[r['itype']][r['tk']] += 1
    elif r['tk'] == 'Plantae' and r['sk'] != 'Plantae':
        fam = plant_family(path_of.get(r['tn'],''))
        fam_itype[fam][r['itype']] += 1
        itype_kingdom[r['itype']][r['sk']] += 1

top_fams = [f for f,_ in sorted(
    ((f, sum(c.values())) for f,c in fam_itype.items() if f != 'Other'),
    key=lambda x:x[1], reverse=True)[:12]]
top_itypes = [t for t,_ in Counter(
    {t: sum(c.values()) for t,c in itype_kingdom.items()}).most_common(6)]
top_kingdoms = ['Insecta','Fungi','Aves','Mammalia','Arachnida']

fig, ax = plt.subplots(figsize=(15, 9), facecolor='#0d1117')
ax.set_facecolor('#0d1117')

col_x = [0.05, 0.38, 0.72]
col_labels = ['Plant Family', 'Interaction Type', 'Consumer Kingdom']

def draw_column(items, totals, x, col_colors, ax, col_width=0.12):
    total = sum(totals.values())
    y = 0.95
    positions = {}
    for item in items:
        h = (totals.get(item, 0) / total) * 0.88
        h = max(h, 0.01)
        color = col_colors.get(item, '#666')
        ax.barh(y - h/2, col_width, left=x, height=h, color=color, alpha=0.85,
                edgecolor='#0d1117', linewidth=0.5)
        ax.text(x + col_width/2, y - h/2, item.replace('aceae','').replace('visitsFlowersOf','pollin.'),
            ha='center', va='center', fontsize=7, color='white',
            path_effects=[pe.withStroke(linewidth=1, foreground='#0d1117')])
        positions[item] = (y - h/2, h)
        y -= h + 0.01
    return positions

fam_colors = {f: plt.cm.Set3(i/len(top_fams)) for i,f in enumerate(top_fams)}
itype_colors = {t: EDGE_COLORS.get(t,'#888') for t in top_itypes}
k_colors = COLORS

fam_totals   = {f: sum(fam_itype[f].values()) for f in top_fams}
itype_totals = {t: sum(itype_kingdom[t].values()) for t in top_itypes}
k_totals     = Counter()
for t in top_itypes:
    for k,v in itype_kingdom[t].items():
        if k in top_kingdoms: k_totals[k] += v
k_totals_d = dict(k_totals)

fam_pos   = draw_column(top_fams,   fam_totals,   col_x[0], fam_colors,   ax)
itype_pos = draw_column(top_itypes, itype_totals, col_x[1], itype_colors, ax)
k_pos     = draw_column(top_kingdoms, k_totals_d, col_x[2], k_colors,     ax)

def flow(ax, x1, x2, y1_mid, h1, y2_mid, h2, color, alpha=0.18):
    xs = np.linspace(x1, x2, 100)
    y_top_l = y1_mid + h1/2
    y_bot_l = y1_mid - h1/2
    y_top_r = y2_mid + h2/2
    y_bot_r = y2_mid - h2/2
    t = (xs - x1)/(x2 - x1)
    smooth = t*t*(3-2*t)
    y_top = y_top_l + (y_top_r - y_top_l)*smooth
    y_bot = y_bot_l + (y_bot_r - y_bot_l)*smooth
    ax.fill_between(xs, y_bot, y_top, color=color, alpha=alpha)

fam_itype_drawn = defaultdict(float)
itype_k_drawn   = defaultdict(float)
for f in top_fams:
    fym, fh = fam_pos[f]
    for it in top_itypes:
        vol = fam_itype[f].get(it,0)
        if vol == 0: continue
        iym, ih = itype_pos[it]
        scale_f = fh * vol / max(fam_totals[f],1)
        scale_i = ih * vol / max(itype_totals[it],1)
        y_f = fym - fh/2 + fam_itype_drawn[f] + scale_f/2
        y_i = iym - ih/2 + itype_k_drawn[it] + scale_i/2
        flow(ax, col_x[0]+0.12, col_x[1], y_f, scale_f, y_i, scale_i,
             fam_colors[f], alpha=0.22)
        fam_itype_drawn[f] += scale_f
        itype_k_drawn[it]  += scale_i

itype_k_out = defaultdict(float)
for it in top_itypes:
    iym, ih = itype_pos[it]
    for k in top_kingdoms:
        vol = itype_kingdom[it].get(k,0)
        if vol == 0: continue
        if k not in k_pos: continue
        kym, kh = k_pos[k]
        scale_i = ih * vol / max(itype_totals[it],1)
        scale_k = kh * vol / max(k_totals_d.get(k,1),1)
        y_i = iym - ih/2 + itype_k_out[it] + scale_i/2
        y_k = kym - kh/2 + scale_k/2
        flow(ax, col_x[1]+0.12, col_x[2], y_i, scale_i, y_k, scale_k,
             COLORS.get(k,'#888'), alpha=0.22)
        itype_k_out[it] += scale_i

for x, label in zip(col_x, col_labels):
    ax.text(x+0.06, 1.0, label, ha='center', va='bottom',
        color='#aaaaaa', fontsize=10, fontweight='bold')

ax.set_xlim(0, 0.86); ax.set_ylim(0, 1.02)
ax.set_title('Ecological Flow  —  Plant Family → Interaction Type → Consumer',
    color='white', fontsize=13, pad=12, fontweight='bold')
ax.axis('off')
plt.tight_layout()
fig.savefig(OUT_DIR / "viz4_sankey.png", dpi=150, bbox_inches='tight', facecolor='#0d1117')
plt.close()
print("  saved viz4_sankey.png")

print("\nDone — 4 viz examples in insect-web/charts/")
