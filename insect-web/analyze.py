"""
Exploratory analysis of GloBI interactions for SF native plants.
Generates multiple PNG charts covering:
  - interaction type landscape
  - top plants by interaction richness
  - taxonomic breakdown of interactors
  - insect ↔ insect / insect ↔ animal interactions
  - insect order breakdown
"""

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
import seaborn as sns

DATA_DIR = Path(__file__).parent
RAW_FILE        = DATA_DIR / "raw_interactions.json"
ANIMAL_RAW_FILE = DATA_DIR / "raw_animal_interactions.json"
OUT_DIR = DATA_DIR / "charts"
OUT_DIR.mkdir(exist_ok=True)

# ── colour palette ─────────────────────────────────────────────────────────────
PALETTE = {
    "Insecta":    "#4e9a8c",
    "Arachnida":  "#c8a45c",
    "Aves":       "#5c7fc8",
    "Mammalia":   "#b05a7a",
    "Fungi":      "#a07050",
    "Nematoda":   "#8a8a50",
    "Plantae":    "#5db05d",
    "Bacteria":   "#c05050",
    "Other":      "#aaaaaa",
}

# ── taxonomy helpers ────────────────────────────────────────────────────────────
INSECT_ORDERS = [
    "Lepidoptera", "Diptera", "Hymenoptera", "Coleoptera",
    "Hemiptera", "Orthoptera", "Thysanoptera", "Neuroptera",
    "Trichoptera", "Odonata", "Blattodea", "Psocodea",
]

def taxon_kingdom(path: str) -> str:
    if not path:
        return "Other"
    for group, kw in [
        ("Insecta",   "Insecta"),
        ("Arachnida", "Arachnida"),
        ("Aves",      "Aves"),
        ("Mammalia",  "Mammalia"),
        ("Fungi",     "Fungi"),
        ("Nematoda",  "Nematoda"),
        ("Bacteria",  "Bacteria"),
        ("Plantae",   "Plantae"),
        ("Plantae",   "Angiosperms"),
        ("Plantae",   "Viridiplantae"),
    ]:
        if kw in path:
            return group
    return "Other"

def insect_order(path: str) -> str:
    for o in INSECT_ORDERS:
        if o in path:
            return o
    return "Other"

def is_insect(path: str) -> bool:
    return taxon_kingdom(path) == "Insecta"

def is_animal(path: str) -> bool:
    return taxon_kingdom(path) in ("Insecta", "Arachnida", "Aves", "Mammalia")

def is_plant(path: str) -> bool:
    return any(k in (path or "") for k in
               ("Plantae", "Angiosperms", "Viridiplantae", "Tracheophyta", "Gymnosperms", "Bryophyta"))

PARASITIC_TYPES = {"parasiteOf", "hasParasite", "hostOf", "hasHost"}

# Vague / co-occurrence types with no specific ecological meaning
NOISE_TYPES = {
    "interactsWith", "coOccursWith", "adjacentTo",
    "visits", "visitedBy",
    "livesOn", "livedOnBy",
    "ecologicallyRelatedTo",
}

# ── load data ──────────────────────────────────────────────────────────────────
records = json.loads(RAW_FILE.read_text())
animal_records = json.loads(ANIMAL_RAW_FILE.read_text()) if ANIMAL_RAW_FILE.exists() else []
print(f"Loaded {len(records)} plant-interaction records")
print(f"Loaded {len(animal_records)} animal↔animal records")

# ── flatten / clean ────────────────────────────────────────────────────────────
def get(rec, *keys):
    for k in keys:
        if k in rec and rec[k]:
            return str(rec[k])
    return ""

rows = []
for r in records:
    rows.append({
        "src_name":  get(r, "source_taxon_name"),
        "src_path":  get(r, "source_taxon_path"),
        "itype":     get(r, "interaction_type", "type"),
        "tgt_name":  get(r, "target_taxon_name"),
        "tgt_path":  get(r, "target_taxon_path"),
    })

# drop rows missing both names
rows = [r for r in rows if r["src_name"] or r["tgt_name"]]

# drop non-parasitic plant↔plant interactions
before = len(rows)
rows = [
    r for r in rows
    if not (is_plant(r["src_path"]) and is_plant(r["tgt_path"])
            and r["itype"] not in PARASITIC_TYPES)
]
pp_removed = before - len(rows)

# drop all globally vague / co-occurrence interaction types
before = len(rows)
rows = [r for r in rows if r["itype"] not in NOISE_TYPES]
noise_removed = before - len(rows)

print(f"Clean rows: {len(rows)} "
      f"(removed {pp_removed} non-parasitic plant↔plant, "
      f"{noise_removed} co-occurrence/generic)")

# classify each endpoint
for r in rows:
    r["src_kingdom"] = taxon_kingdom(r["src_path"])
    r["tgt_kingdom"] = taxon_kingdom(r["tgt_path"])

# ══════════════════════════════════════════════════════════════════════════════
# FIGURE 1 – Interaction type landscape
# ══════════════════════════════════════════════════════════════════════════════
itype_counts = Counter(r["itype"] for r in rows)
top_itypes = itype_counts.most_common(20)

fig, ax = plt.subplots(figsize=(10, 7))
labels, vals = zip(*top_itypes)
colors = plt.cm.viridis([v / max(vals) for v in vals])
bars = ax.barh(labels[::-1], vals[::-1], color=colors[::-1], edgecolor="white", linewidth=0.5)
ax.set_xlabel("Number of interactions", fontsize=11)
ax.set_title("Top 20 Interaction Types\n(SF native plants — GloBI data)", fontsize=13, fontweight="bold")
for bar, val in zip(bars, vals[::-1]):
    ax.text(bar.get_width() + 30, bar.get_y() + bar.get_height() / 2,
            f"{val:,}", va="center", fontsize=8)
plt.tight_layout()
fig.savefig(OUT_DIR / "01_interaction_types.png", dpi=150)
plt.close()
print("Saved 01_interaction_types.png")

# ══════════════════════════════════════════════════════════════════════════════
# FIGURE 2 – Taxonomic breakdown of who interacts with SF plants
# ══════════════════════════════════════════════════════════════════════════════
# Keep interactions where target is a plant (SF native) — look at sources
plant_targeted = [r for r in rows if is_plant(r["tgt_path"]) or (not r["tgt_path"] and not is_plant(r["src_path"]))]
src_kingdoms = Counter(r["src_kingdom"] for r in rows)

fig, axes = plt.subplots(1, 2, figsize=(13, 6))

# Pie: who interacts with plants
pie_labels = list(src_kingdoms.keys())
pie_vals   = list(src_kingdoms.values())
pie_colors = [PALETTE.get(l, "#aaaaaa") for l in pie_labels]
wedges, texts, autotexts = axes[0].pie(
    pie_vals, labels=pie_labels, colors=pie_colors,
    autopct=lambda p: f"{p:.1f}%" if p > 2 else "",
    startangle=140, pctdistance=0.75,
)
for t in autotexts:
    t.set_fontsize(8)
axes[0].set_title("Source organisms in all interactions\n(who interacts with SF native plants?)",
                   fontsize=11, fontweight="bold")

# Bar: target kingdoms
tgt_kingdoms = Counter(r["tgt_kingdom"] for r in rows)
tk_labels, tk_vals = zip(*tgt_kingdoms.most_common())
bar_colors = [PALETTE.get(l, "#aaaaaa") for l in tk_labels]
axes[1].bar(tk_labels, tk_vals, color=bar_colors, edgecolor="white", linewidth=0.5)
axes[1].set_ylabel("Interaction count")
axes[1].set_title("Target organisms in all interactions\n(what do they interact with?)",
                   fontsize=11, fontweight="bold")
axes[1].tick_params(axis="x", rotation=30)
for i, (lbl, val) in enumerate(zip(tk_labels, tk_vals)):
    axes[1].text(i, val + 50, f"{val:,}", ha="center", fontsize=8)

plt.tight_layout()
fig.savefig(OUT_DIR / "02_taxonomic_breakdown.png", dpi=150)
plt.close()
print("Saved 02_taxonomic_breakdown.png")

# ══════════════════════════════════════════════════════════════════════════════
# FIGURE 3 – Top 25 plants by total interaction richness
# ══════════════════════════════════════════════════════════════════════════════
plant_counts: dict[str, Counter] = defaultdict(Counter)
for r in rows:
    src, tgt = r["src_name"], r["tgt_name"]
    # If source is a plant, count interactions pointing out
    if is_plant(r["src_path"]):
        plant_counts[src][r["tgt_kingdom"]] += 1
    # If target is a plant, count interactions pointing in
    if is_plant(r["tgt_path"]):
        plant_counts[tgt][r["src_kingdom"]] += 1

plant_totals = {p: sum(c.values()) for p, c in plant_counts.items() if p}
top_plants = sorted(plant_totals.items(), key=lambda x: x[1], reverse=True)[:25]

fig, ax = plt.subplots(figsize=(12, 9))
plant_names = [p for p, _ in top_plants]
kingdoms_present = sorted(PALETTE.keys())

bottom = [0] * len(plant_names)
bar_width = 0.7
for kingdom in kingdoms_present:
    vals = [plant_counts[p].get(kingdom, 0) for p in plant_names]
    if sum(vals) == 0:
        continue
    ax.barh(plant_names[::-1], [v for v in vals[::-1]],
            left=bottom[::-1], color=PALETTE[kingdom], label=kingdom,
            edgecolor="white", linewidth=0.3)
    bottom = [b + v for b, v in zip(bottom, vals)]

ax.set_xlabel("Number of unique interactions", fontsize=11)
ax.set_title("Top 25 SF Native Plants\nby Total Interaction Richness (GloBI)",
             fontsize=13, fontweight="bold")
ax.legend(loc="lower right", fontsize=9, title="Interactor type")
for i, (p, tot) in enumerate(reversed(top_plants)):
    ax.text(tot + 5, i, f"{tot}", va="center", fontsize=8)
plt.tight_layout()
fig.savefig(OUT_DIR / "03_top_plants_richness.png", dpi=150)
plt.close()
print("Saved 03_top_plants_richness.png")

# ══════════════════════════════════════════════════════════════════════════════
# FIGURE 4 – Insect orders interacting with SF plants
# ══════════════════════════════════════════════════════════════════════════════
insect_rows = [r for r in rows if is_insect(r["src_path"]) and is_plant(r["tgt_path"])]
insect_rows += [r for r in rows if is_plant(r["src_path"]) and is_insect(r["tgt_path"])]
print(f"Insect↔Plant interactions: {len(insect_rows)}")

order_plant: dict[str, Counter] = defaultdict(Counter)
for r in insect_rows:
    if is_insect(r["src_path"]):
        order = insect_order(r["src_path"])
        order_plant[order][r["tgt_name"]] += 1
    else:
        order = insect_order(r["tgt_path"])
        order_plant[order][r["src_name"]] += 1

order_totals = {o: len(plants) for o, plants in order_plant.items()}
top_orders = sorted(order_totals.items(), key=lambda x: x[1], reverse=True)

fig, axes = plt.subplots(1, 2, figsize=(14, 6))

# Left: insect order richness (plant species count)
order_labels, order_vals = zip(*top_orders) if top_orders else ([], [])
order_colors = sns.color_palette("Set2", len(order_labels))
axes[0].barh(order_labels[::-1], order_vals[::-1], color=order_colors[::-1],
             edgecolor="white", linewidth=0.5)
axes[0].set_xlabel("Number of plant species as hosts")
axes[0].set_title("Insect Order × Plant Richness\n(unique plant species used as hosts)",
                  fontsize=11, fontweight="bold")
for i, v in enumerate(order_vals[::-1]):
    axes[0].text(v + 0.3, i, str(v), va="center", fontsize=9)

# Right: top 20 insect species (by # of plant hosts)
insect_host_counts: Counter = Counter()
for r in insect_rows:
    if is_insect(r["src_path"]):
        insect_host_counts[r["src_name"]] += 1
    else:
        insect_host_counts[r["tgt_name"]] += 1

top_insects = insect_host_counts.most_common(20)
if top_insects:
    ins_labels, ins_vals = zip(*top_insects)
    ins_colors = sns.color_palette("mako", len(ins_labels))
    axes[1].barh(ins_labels[::-1], ins_vals[::-1], color=ins_colors[::-1],
                 edgecolor="white", linewidth=0.5)
    axes[1].set_xlabel("Interaction count with SF native plants")
    axes[1].set_title("Top 20 Insect Species\ninteracting with SF native plants",
                      fontsize=11, fontweight="bold")
    for i, v in enumerate(ins_vals[::-1]):
        axes[1].text(v + 0.1, i, str(v), va="center", fontsize=8)

plt.tight_layout()
fig.savefig(OUT_DIR / "04_insect_breakdown.png", dpi=150)
plt.close()
print("Saved 04_insect_breakdown.png")

# ══════════════════════════════════════════════════════════════════════════════
# FIGURE 5 – Insect ↔ Insect / Insect ↔ Animal interactions
# ══════════════════════════════════════════════════════════════════════════════
# Use the dedicated animal-interactions dataset
aa_rows = []
for r in animal_records:
    aa_rows.append({
        "src_name":    get(r, "source_taxon_name"),
        "src_path":    get(r, "source_taxon_path"),
        "itype":       get(r, "interaction_type", "type"),
        "tgt_name":    get(r, "target_taxon_name"),
        "tgt_path":    get(r, "target_taxon_path"),
    })
for r in aa_rows:
    r["src_kingdom"] = taxon_kingdom(r["src_path"])
    r["tgt_kingdom"] = taxon_kingdom(r["tgt_path"])

animal_animal = [r for r in aa_rows if is_animal(r["src_path"]) and is_animal(r["tgt_path"])]
print(f"Animal↔Animal interactions: {len(animal_animal)}")

# breakdown by kingdom pair
pair_counts: Counter = Counter()
for r in animal_animal:
    pair = tuple(sorted([r["src_kingdom"], r["tgt_kingdom"]]))
    pair_counts[pair] += 1

# interaction type breakdown within animal↔animal
itype_aa: Counter = Counter(r["itype"] for r in animal_animal)
top_aa_types = itype_aa.most_common(15)

# Insect↔insect specifically
ins_ins = [r for r in animal_animal if is_insect(r["src_path"]) and is_insect(r["tgt_path"])]
ins_bird = [r for r in animal_animal
            if (is_insect(r["src_path"]) and taxon_kingdom(r["tgt_path"]) == "Aves")
            or (taxon_kingdom(r["src_path"]) == "Aves" and is_insect(r["tgt_path"]))]
ins_mam = [r for r in animal_animal
           if (is_insect(r["src_path"]) and taxon_kingdom(r["tgt_path"]) == "Mammalia")
           or (taxon_kingdom(r["src_path"]) == "Mammalia" and is_insect(r["tgt_path"]))]

fig, axes = plt.subplots(1, 2, figsize=(14, 6))

# Left: interaction types for animal↔animal
if top_aa_types:
    aa_labels, aa_vals = zip(*top_aa_types)
    aa_colors = sns.color_palette("rocket", len(aa_labels))
    axes[0].barh(aa_labels[::-1], aa_vals[::-1], color=aa_colors[::-1],
                 edgecolor="white", linewidth=0.5)
    axes[0].set_xlabel("Count")
    axes[0].set_title(f"Interaction Types — Animal↔Animal\n({len(animal_animal):,} total interactions)",
                      fontsize=11, fontweight="bold")
    for i, v in enumerate(aa_vals[::-1]):
        axes[0].text(v + 0.3, i, str(v), va="center", fontsize=9)

# Right: stacked summary across insect↔X pairs
pair_labels = [
    "Insect↔Insect",
    "Insect↔Bird",
    "Insect↔Mammal",
    "Insect↔Arachnid",
    "Other animal pairs",
]
ins_ara = [r for r in animal_animal
           if (is_insect(r["src_path"]) and taxon_kingdom(r["tgt_path"]) == "Arachnida")
           or (taxon_kingdom(r["src_path"]) == "Arachnida" and is_insect(r["tgt_path"]))]
other_aa = len(animal_animal) - len(ins_ins) - len(ins_bird) - len(ins_mam) - len(ins_ara)
pair_vals = [len(ins_ins), len(ins_bird), len(ins_mam), len(ins_ara), max(0, other_aa)]
pair_colors = ["#4e9a8c", "#5c7fc8", "#b05a7a", "#c8a45c", "#aaaaaa"]
axes[1].bar(pair_labels, pair_vals, color=pair_colors, edgecolor="white", linewidth=0.5)
axes[1].set_ylabel("Interaction count")
axes[1].set_title("Animal Interaction Pairs\ninvolving SF-plant-associated fauna",
                  fontsize=11, fontweight="bold")
axes[1].tick_params(axis="x", rotation=20)
for i, v in enumerate(pair_vals):
    axes[1].text(i, v + 1, str(v), ha="center", fontsize=10, fontweight="bold")

plt.tight_layout()
fig.savefig(OUT_DIR / "05_animal_animal_interactions.png", dpi=150)
plt.close()
print("Saved 05_animal_animal_interactions.png")

# ══════════════════════════════════════════════════════════════════════════════
# FIGURE 6 – Top bird and mammal species predating insects from this plant web
# ══════════════════════════════════════════════════════════════════════════════
predator_rows = [r for r in animal_animal
                 if r["itype"] in ("eats", "preysOn", "preyedUponBy")]

bird_predators: Counter = Counter()
mammal_predators: Counter = Counter()
for r in predator_rows:
    if taxon_kingdom(r["src_path"]) == "Aves" and is_insect(r["tgt_path"]):
        bird_predators[r["src_name"]] += 1
    elif taxon_kingdom(r["src_path"]) == "Mammalia" and is_insect(r["tgt_path"]):
        mammal_predators[r["src_name"]] += 1
    elif taxon_kingdom(r["tgt_path"]) == "Aves" and is_insect(r["src_path"]):
        bird_predators[r["tgt_name"]] += 1
    elif taxon_kingdom(r["tgt_path"]) == "Mammalia" and is_insect(r["src_path"]):
        mammal_predators[r["tgt_name"]] += 1

top_birds   = bird_predators.most_common(15)
top_mammals = mammal_predators.most_common(15)

fig, axes = plt.subplots(1, 2, figsize=(14, 6))

if top_birds:
    b_labels, b_vals = zip(*top_birds)
    axes[0].barh(b_labels[::-1], b_vals[::-1],
                 color=PALETTE["Aves"], edgecolor="white", linewidth=0.5)
    axes[0].set_xlabel("Predation interactions")
    axes[0].set_title("Top Bird Predators of Insects\nassociated with SF native plants",
                      fontsize=11, fontweight="bold")
    for i, v in enumerate(b_vals[::-1]):
        axes[0].text(v + 0.1, i, str(v), va="center", fontsize=9)
else:
    axes[0].text(0.5, 0.5, "No bird predation data", ha="center", va="center",
                 transform=axes[0].transAxes, fontsize=12)
    axes[0].set_title("Top Bird Predators of Insects")

if top_mammals:
    m_labels, m_vals = zip(*top_mammals)
    axes[1].barh(m_labels[::-1], m_vals[::-1],
                 color=PALETTE["Mammalia"], edgecolor="white", linewidth=0.5)
    axes[1].set_xlabel("Predation interactions")
    axes[1].set_title("Top Mammal Predators of Insects\nassociated with SF native plants",
                      fontsize=11, fontweight="bold")
    for i, v in enumerate(m_vals[::-1]):
        axes[1].text(v + 0.1, i, str(v), va="center", fontsize=9)
else:
    axes[1].text(0.5, 0.5, "No mammal predation data", ha="center", va="center",
                 transform=axes[1].transAxes, fontsize=12)
    axes[1].set_title("Top Mammal Predators of Insects")

plt.tight_layout()
fig.savefig(OUT_DIR / "06_predator_species.png", dpi=150)
plt.close()
print("Saved 06_predator_species.png")

# ══════════════════════════════════════════════════════════════════════════════
# FIGURE 7 – Plant family heatmap: which families attract which insect orders
# ══════════════════════════════════════════════════════════════════════════════
def plant_family(path: str) -> str:
    # taxon path looks like "Angiosperms | Fagales | Fagaceae | Quercus | ..."
    parts = [p.strip() for p in path.split("|")]
    # Family names end in 'aceae' or 'idae'
    for p in parts:
        if p.endswith("aceae") or p.endswith("idae"):
            return p
    return "Unknown"

family_order_matrix: dict[str, Counter] = defaultdict(Counter)
for r in insect_rows:
    if is_insect(r["src_path"]) and is_plant(r["tgt_path"]):
        fam = plant_family(r["tgt_path"])
        ord_ = insect_order(r["src_path"])
        family_order_matrix[fam][ord_] += 1
    elif is_plant(r["src_path"]) and is_insect(r["tgt_path"]):
        fam = plant_family(r["src_path"])
        ord_ = insect_order(r["tgt_path"])
        family_order_matrix[fam][ord_] += 1

# keep top 20 families by total interactions
fam_totals = {f: sum(c.values()) for f, c in family_order_matrix.items() if f != "Unknown"}
top_fams = [f for f, _ in sorted(fam_totals.items(), key=lambda x: x[1], reverse=True)[:20]]
top_ords = [o for o, _ in Counter(
    ord_ for c in family_order_matrix.values() for ord_, cnt in c.items() for _ in range(cnt)
).most_common(10)]

import numpy as np
matrix = np.zeros((len(top_fams), len(top_ords)), dtype=int)
for i, fam in enumerate(top_fams):
    for j, ord_ in enumerate(top_ords):
        matrix[i, j] = family_order_matrix[fam].get(ord_, 0)

fig, ax = plt.subplots(figsize=(13, 8))
sns.heatmap(
    matrix, annot=True, fmt="d", cmap="YlOrRd",
    xticklabels=top_ords, yticklabels=top_fams,
    linewidths=0.5, linecolor="white", ax=ax,
    cbar_kws={"label": "Interaction count"},
)
ax.set_title("Plant Family × Insect Order Interaction Heatmap\n(SF native plants — GloBI data)",
             fontsize=13, fontweight="bold")
ax.set_xlabel("Insect Order", fontsize=11)
ax.set_ylabel("Plant Family", fontsize=11)
plt.tight_layout()
fig.savefig(OUT_DIR / "07_family_order_heatmap.png", dpi=150)
plt.close()
print("Saved 07_family_order_heatmap.png")

# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY STATS (printed)
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "═"*60)
print("SUMMARY STATISTICS")
print("═"*60)
print(f"Total unique interactions:        {len(rows):>8,}")
print(f"Insect↔Plant interactions:        {len(insect_rows):>8,}")
print(f"Animal↔Animal interactions:       {len(animal_animal):>8,}")
print(f"  Insect↔Insect:                  {len(ins_ins):>8,}")
print(f"  Insect↔Bird:                    {len(ins_bird):>8,}")
print(f"  Insect↔Mammal:                  {len(ins_mam):>8,}")
print(f"  Insect↔Arachnid:                {len(ins_ara):>8,}")
print(f"Unique insect species found:      {len(insect_host_counts):>8,}")
print(f"Unique plant families covered:    {len(fam_totals):>8,}")
print(f"\nTop 5 plants by interaction richness:")
for p, n in top_plants[:5]:
    print(f"  {p:<40} {n:>5}")
print(f"\nTop insect order (plant hosts):  {top_orders[0][0] if top_orders else 'N/A'}")
print("═"*60)
print(f"\nAll charts saved to: {OUT_DIR}")
