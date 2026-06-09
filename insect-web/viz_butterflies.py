"""
Butterfly × Plant network for SF-area native plants.
True butterflies only: Papilionidae, Pieridae, Lycaenidae,
Nymphalidae, Riodinidae, Hesperiidae.
"""
import json, math
from collections import defaultdict, Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import networkx as nx
import numpy as np

DATA_DIR = Path(__file__).parent
OUT_DIR  = DATA_DIR / "charts"
OUT_DIR.mkdir(exist_ok=True)

# ── load ───────────────────────────────────────────────────────────────────────
raw           = json.load(open(DATA_DIR / "raw_interactions.json"))
nat           = json.load(open(DATA_DIR / "nativity.json"))
sf_obs        = json.load(open(DATA_DIR / "sf_obs_cache.json"))
bfly_sf_obs   = json.load(open(DATA_DIR / "butterfly_sf_obs_cache.json"))
sf_nat   = {l.strip() for l in
    (DATA_DIR.parent / "sf-parks-biodiversity/data/sf_natives.csv")
    .read_text().splitlines() if l.strip()}

EXCLUDE = {k for k, v in nat.items() if v in ("non_native", "no_ca_obs")}

# butterflies with confirmed SF iNaturalist observations (count > 0)
SF_BUTTERFLIES = {name for name, cnt in bfly_sf_obs.items() if cnt > 0}
print(f"Butterflies with SF iNat observations: {len(SF_BUTTERFLIES)}")

# ── butterfly family detection ─────────────────────────────────────────────────
FAMILY_KW = {
    "Papilionidae": ["Papilionidae"],
    "Pieridae":     ["Pieridae"],
    "Lycaenidae":   ["Lycaenidae", "Polyommatini"],
    "Nymphalidae":  ["Nymphalidae"],
    "Hesperiidae":  ["Hesperiidae"],
    "Riodinidae":   ["Riodinidae"],
}
ALL_BUTTERFLY_KW = [kw for kws in FAMILY_KW.values() for kw in kws] + ["Papilionoidea"]

FAMILY_COLORS = {
    "Papilionidae": "#f5c842",   # golden — swallowtails
    "Pieridae":     "#f0f0a0",   # pale yellow — whites/yellows
    "Lycaenidae":   "#6ab5e8",   # sky blue — blues/coppers
    "Nymphalidae":  "#e8834a",   # orange — brush-foots
    "Hesperiidae":  "#c97de0",   # violet — skippers
    "Riodinidae":   "#e84a7a",   # pink — metalmarks
    "Unknown":      "#aaaaaa",
}

def butterfly_family(path: str) -> str:
    p = path or ""
    for fam, kws in FAMILY_KW.items():
        if any(k in p for k in kws):
            return fam
    if "Papilionoidea" in p:
        return "Unknown"
    return "Unknown"

def is_butterfly(path: str) -> bool:
    return any(k in (path or "") for k in ALL_BUTTERFLY_KW)

def is_plant(p: str) -> bool:
    return any(k in (p or "") for k in (
        "Plantae","Angiosperms","Viridiplantae","Tracheophyta","Spermatophytes",
        "Gymnosperms","Bryophyta","Fagales","Poales","Caryophyllales","Lamiales",
        "Asterales","Rosales","Fabales","Malpighiales","Ericales","Solanales",
        "Apiales","Ranunculales","Myrtales","Malvales","lamiids","Equisetopsida",
    ))

# ── build butterfly-plant edges ───────────────────────────────────────────────
path_of: dict[str, str] = {}
pairs: dict[tuple, str] = {}   # (butterfly, plant) → itype

for r in raw:
    sn = (r.get("source_taxon_name") or "").strip()
    tn = (r.get("target_taxon_name") or "").strip()
    sp = (r.get("source_taxon_path") or "")
    tp = (r.get("target_taxon_path") or "")
    itype = r.get("interaction_type", "")
    if sn: path_of[sn] = sp
    if tn: path_of[tn] = tp
    if sn in EXCLUDE or tn in EXCLUDE:
        continue
    if is_butterfly(sp) and is_plant(tp):
        if sn in SF_BUTTERFLIES:
            pairs[(sn, tn)] = itype
    elif is_plant(sp) and is_butterfly(tp):
        if tn in SF_BUTTERFLIES:
            pairs[(tn, sn)] = itype

# ── degree filter: min 3 connections on each side ─────────────────────────────
MIN_DEG = 2

def filter_degrees(pair_set, min_deg):
    b_deg = Counter(b for b, _ in pair_set)
    p_deg = Counter(p for _, p in pair_set)
    kept = {(b, p) for b, p in pair_set
            if b_deg[b] >= min_deg and p_deg[p] >= min_deg}
    return kept

edge_set = set(pairs.keys())
for _ in range(3):
    edge_set = filter_degrees(edge_set, MIN_DEG)

butterflies = {b for b, _ in edge_set}
plants      = {p for _, p in edge_set}
print(f"After degree≥{MIN_DEG} filter: {len(butterflies)} butterflies, "
      f"{len(plants)} plants, {len(edge_set)} edges")

# ── build graph ───────────────────────────────────────────────────────────────
G = nx.Graph()
for b, p in edge_set:
    G.add_node(b, kind="butterfly", family=butterfly_family(path_of.get(b, "")))
    G.add_node(p, kind="plant")
    G.add_edge(b, p)

degrees = dict(G.degree())

# ── layout: spring with plant/butterfly separation hint ───────────────────────
# Seed the layout so plants cluster on one side
pos_init = {}
plant_nodes = [n for n in G.nodes() if G.nodes[n]["kind"] == "plant"]
butt_nodes  = [n for n in G.nodes() if G.nodes[n]["kind"] == "butterfly"]
for n in plant_nodes:
    ang = np.random.default_rng(abs(hash(n)) % 2**32).uniform(math.pi * 0.6, math.pi * 1.4)
    pos_init[n] = (math.cos(ang) * 0.8, math.sin(ang) * 0.8)
for n in butt_nodes:
    ang = np.random.default_rng(abs(hash(n)) % 2**32).uniform(-math.pi * 0.4, math.pi * 0.4)
    pos_init[n] = (math.cos(ang) * 0.8, math.sin(ang) * 0.8)

pos = nx.spring_layout(G, k=2.2 / math.sqrt(len(G)), seed=42,
                       iterations=120, pos=pos_init, weight=None)

# ── figure ────────────────────────────────────────────────────────────────────
BG = "#0d1117"
fig, ax = plt.subplots(figsize=(18, 14), facecolor=BG)
ax.set_facecolor(BG)
ax.axis("off")

# edges — very faint
edge_xy = [(pos[b], pos[p]) for b, p in edge_set if b in pos and p in pos]
for (bpos, ppos) in edge_xy:
    ax.plot([bpos[0], ppos[0]], [bpos[1], ppos[1]],
            color="#ffffff", alpha=0.06, linewidth=0.4, zorder=1)

# plant nodes
px = [pos[n][0] for n in plant_nodes if n in pos]
py = [pos[n][1] for n in plant_nodes if n in pos]
ps = [30 + degrees[n] ** 1.5 * 6 for n in plant_nodes if n in pos]
ax.scatter(px, py, s=ps, c="#4ecb71", alpha=0.85, zorder=3,
           edgecolors="#ffffff", linewidths=0.4)

# butterfly nodes by family
for fam, col in FAMILY_COLORS.items():
    nodes = [n for n in butt_nodes if G.nodes[n].get("family") == fam and n in pos]
    if not nodes: continue
    bx = [pos[n][0] for n in nodes]
    by = [pos[n][1] for n in nodes]
    bs = [20 + degrees[n] ** 1.5 * 5 for n in nodes]
    ax.scatter(bx, by, s=bs, c=col, alpha=0.85, zorder=3,
               edgecolors="#ffffff", linewidths=0.4, marker="D")

# labels: top plants and butterflies by degree
TOP_N = 18
top_plants = sorted(plant_nodes, key=lambda n: -degrees[n])[:TOP_N]
top_butts  = sorted(butt_nodes,  key=lambda n: -degrees[n])[:TOP_N]

def short(name):
    parts = name.split()
    if len(parts) >= 2:
        return f"{parts[0][0]}. {' '.join(parts[1:])}"
    return name

for n in top_plants:
    if n not in pos: continue
    x, y = pos[n]
    ax.text(x, y + 0.022, short(n), ha="center", va="bottom",
            fontsize=6.5, color="#a0ffb0", fontweight="bold", zorder=5)

for n in top_butts:
    if n not in pos: continue
    x, y = pos[n]
    ax.text(x, y - 0.024, short(n), ha="center", va="top",
            fontsize=6.0, color="#ffd080", zorder=5)

# ── legend ────────────────────────────────────────────────────────────────────
legend_patches = [
    mpatches.Patch(color="#4ecb71", label="Native plant"),
] + [
    mpatches.Patch(color=FAMILY_COLORS[f], label=f)
    for f in ["Papilionidae","Nymphalidae","Lycaenidae","Pieridae","Hesperiidae","Riodinidae"]
]
ax.legend(handles=legend_patches, loc="lower left", framealpha=0.25,
          facecolor="#1a1f2e", edgecolor="#555555",
          labelcolor="white", fontsize=10, title="Taxon",
          title_fontsize=10)

n_bfly  = len(butterflies)
n_plant = len(plants)
n_edge  = len(edge_set)
ax.set_title(
    f"Butterfly × Native Plant Network  ·  {n_bfly} butterfly species  ·  "
    f"{n_plant} host plants  ·  {n_edge} interactions  ·  min {MIN_DEG} connections",
    color="white", fontsize=13, pad=14,
)

out = OUT_DIR / "butterflies_plants.png"
fig.savefig(out, dpi=160, bbox_inches="tight", facecolor=BG)
plt.close()
print(f"Saved → {out}")

# ── stats ─────────────────────────────────────────────────────────────────────
print("\nTop 10 plants by butterfly diversity:")
for n in sorted(plant_nodes, key=lambda n: -degrees[n])[:10]:
    print(f"  {degrees[n]:3d} butterflies  {n}")

print("\nTop 10 butterflies by host breadth:")
for n in sorted(butt_nodes, key=lambda n: -degrees[n])[:10]:
    fam = G.nodes[n].get("family","?")
    print(f"  {degrees[n]:3d} plants  {n}  [{fam}]")

fam_cnt = Counter(G.nodes[n].get("family","Unknown") for n in butt_nodes)
print("\nButterflies by family:")
for f, c in fam_cnt.most_common(): print(f"  {c:3d}  {f}")
