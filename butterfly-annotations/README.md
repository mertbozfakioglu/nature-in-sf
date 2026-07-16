# Butterfly annotation counts (SF Bay Area)

Counts how many iNaturalist butterfly (Papilionoidea, taxon 47224) observations
in the San Francisco Bay Area (place 54321) carry each annotation value.

Run `fetch-annotation-counts.py` to refresh `data/annotation-counts.json`. It
queries the iNaturalist API with `per_page=0`, which returns `total_results`
for a filter without downloading the matching observations, so counting
211k+ observations by annotation only takes a handful of API calls.

## Results (as of 2026-07-06)

Total observations: **211,684**

Note: annotations are optional and not mutually exclusive — an observation
can have zero, one, or several of these, so columns don't sum to the total.

### Life Stage
| Value | Count |
|---|---|
| Adult | 145,384 |
| Larva | 16,926 |
| Pupa | 2,209 |
| Egg | 1,156 |
| Teneral / Nymph / Juvenile / Subimago | 0 |

### Alive or Dead
| Value | Count |
|---|---|
| Alive | 24,977 |
| Dead | 757 |
| Cannot Be Determined | 44 |

### Sex
| Value | Count |
|---|---|
| Male | 3,409 |
| Female | 2,104 |
| Cannot Be Determined | 380 |

### Evidence of Presence
| Value | Count |
|---|---|
| Organism | 23,651 |
| Egg | 155 |
| Molt | 115 |
| Construction | 46 |
| Scat | 37 |
| Leafmine | 10 |
| Feather / Gall / Track / Bone / Hair | 0 |
