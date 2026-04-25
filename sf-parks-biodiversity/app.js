'use strict';

// ─────────────────────────────────────────────────────────────────────────────
// Config
// ─────────────────────────────────────────────────────────────────────────────

const INAT_API = 'https://api.inaturalist.org/v1';

// SF Open Data – Recreation & Park Department Properties (polygon geometries)
// Dataset: https://data.sfgov.org/Recreation-and-Parks/Recreation-and-Park-Department-Park-Info/gtr9-ntp6
// Filter to SF city limits only (excludes Camp Mather etc.) and limit to parks/open spaces
const SF_PARKS_URL =
  "https://data.sfgov.org/resource/gtr9-ntp6.geojson?$limit=500&$where=city='San Francisco'";

const CATEGORIES = [
  { key: 'Plantae',   label: 'Plants',      icon: '🌿', col: '#4a8c4a' },
  { key: 'Aves',      label: 'Birds',       icon: '🐦', col: '#4a7aad' },
  { key: 'Insecta',   label: 'Insects',     icon: '🦋', col: '#c9a227' },
  { key: 'Mammalia',  label: 'Mammals',     icon: '🦊', col: '#a07040' },
  { key: 'Fungi',     label: 'Fungi',       icon: '🍄', col: '#8b5e3c' },
  { key: 'Reptilia',  label: 'Reptiles',    icon: '🦎', col: '#5a7a3a' },
  { key: 'Amphibia',  label: 'Amphibians',  icon: '🐸', col: '#3a7a5a' },
  { key: 'Arachnida', label: 'Arachnids',   icon: '🕷️', col: '#6a3a6a' },
  { key: 'Mollusca',  label: 'Mollusks',    icon: '🐌', col: '#7a5a3a' },
];

// ─────────────────────────────────────────────────────────────────────────────
// State
// ─────────────────────────────────────────────────────────────────────────────

const state = {
  parks: [],                  // GeoJSON features
  sfPlaceId: null,            // iNaturalist place_id for SF County
  selectedId: null,           // currently-selected park ID
  countCache: {},             // id → total species count (from quick query)
  detailCache: {},            // id → { species[], cats{}, nativeCount, introducedCount }
  rankings: {},               // id → { name, total, cats{}, nativeCount, feature }
  sortCol: 'total',
  loadingAll: false,
};

// ─────────────────────────────────────────────────────────────────────────────
// Map
// ─────────────────────────────────────────────────────────────────────────────

let map;
let parksLayer;

function initMap() {
  map = L.map('map', { center: [37.7599, -122.44], zoom: 12, zoomControl: true });

  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 20,
  }).addTo(map);
}

const PARK_STYLE = {
  default:  { fillColor: '#2a4a2a', fillOpacity: 0.30, color: '#4a7a4a', weight: 1 },
  hover:    { fillColor: '#3a6a3a', fillOpacity: 0.50, color: '#7ab07a', weight: 2 },
  selected: { fillColor: '#5a9b5a', fillOpacity: 0.55, color: '#a0cf9f', weight: 2 },
};

function parkId(feature) {
  const p = feature.properties || {};
  return (
    p.property_id || p.rec_park_id || p.parkid || p.park_id ||
    p.object_id || p.objectid || p.map_label || p.common_nm ||
    p.name || p.park_name ||
    JSON.stringify(feature.geometry?.coordinates?.[0]?.[0])
  );
}

function parkName(feature) {
  const p = feature.properties || {};
  return (
    p.property_name || p.common_nm || p.name || p.park_name ||
    p.parkname || p.rec_park_nm || p.map_label || 'Unnamed Park'
  );
}

function parkBounds(feature) {
  const b = L.geoJSON(feature).getBounds();
  return { swlat: b.getSouth(), swlng: b.getWest(), nelat: b.getNorth(), nelng: b.getEast() };
}

function addParksToMap(features) {
  if (parksLayer) parksLayer.remove();

  parksLayer = L.geoJSON({ type: 'FeatureCollection', features }, {
    style: () => ({ ...PARK_STYLE.default }),
    onEachFeature(feature, layer) {
      const name = parkName(feature);
      const id   = parkId(feature);

      layer.on('mouseover', () => {
        if (state.selectedId !== id) layer.setStyle(PARK_STYLE.hover);
        layer.bindTooltip(esc(name), {
          permanent: false,
          className: 'park-tooltip',
          direction: 'top',
          offset: [0, -4],
        }).openTooltip();
      });

      layer.on('mouseout', () => {
        if (state.selectedId !== id) layer.setStyle(PARK_STYLE.default);
      });

      layer.on('click', (e) => {
        L.DomEvent.stopPropagation(e);
        selectPark(feature, layer);
      });
    },
  }).addTo(map);

  // Deselect on bare map click
  map.on('click', closeSidebar);
}

function resetAllStyles() {
  if (!parksLayer) return;
  parksLayer.eachLayer((layer) => {
    const id = layer.feature ? parkId(layer.feature) : null;
    layer.setStyle(id && id === state.selectedId ? PARK_STYLE.selected : PARK_STYLE.default);
  });
}

function selectPark(feature, layer) {
  state.selectedId = parkId(feature);
  resetAllStyles();
  layer.setStyle(PARK_STYLE.selected);
  openSidebar(feature);

  // Highlight matching ranking row
  document.querySelectorAll('#rankings-body tr').forEach((r) => {
    r.classList.toggle('row-selected', r.dataset.pid === state.selectedId);
  });
}

function findLayerByFeature(feature) {
  let found = null;
  parksLayer?.eachLayer((l) => {
    if (parkId(l.feature) === parkId(feature)) found = l;
  });
  return found;
}

// ─────────────────────────────────────────────────────────────────────────────
// iNaturalist API
// ─────────────────────────────────────────────────────────────────────────────

async function apiFetch(url) {
  for (let attempt = 0; attempt < 4; attempt++) {
    const resp = await fetch(url);
    if (resp.status === 429) {
      await sleep(1200 * (attempt + 1));
      continue;
    }
    if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${url}`);
    return resp.json();
  }
  throw new Error('Rate-limited after retries');
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function findSFPlaceId() {
  try {
    const d = await apiFetch(`${INAT_API}/places/autocomplete?q=San+Francisco&per_page=10`);
    const place = (d.results || []).find(
      p => p.name === 'San Francisco County' ||
           (p.name === 'San Francisco' && p.place_type_name === 'County')
    ) || (d.results || []).find(p => p.name === 'San Francisco');
    return place?.id ?? null;
  } catch {
    return null;
  }
}

function buildParams(bounds, extra = {}) {
  const p = new URLSearchParams({
    swlat: bounds.swlat, swlng: bounds.swlng,
    nelat: bounds.nelat, nelng: bounds.nelng,
    quality_grade: 'research',
  });
  if (state.sfPlaceId) p.set('place_id', state.sfPlaceId);
  for (const [k, v] of Object.entries(extra)) p.set(k, v);
  return p;
}

/** Quick count only – used for bulk rankings loading */
async function fetchCount(feature) {
  const id = parkId(feature);
  if (state.countCache[id] !== undefined) return state.countCache[id];

  const params = buildParams(parkBounds(feature), { per_page: 1 });
  const d = await apiFetch(`${INAT_API}/observations/species_counts?${params}`);
  const count = d.total_results ?? 0;
  state.countCache[id] = count;
  return count;
}

/** Full species detail – used when a park is clicked */
async function fetchDetail(feature) {
  const id = parkId(feature);
  if (state.detailCache[id]) return state.detailCache[id];

  const bounds = parkBounds(feature);
  const base = buildParams(bounds, { per_page: 200, order_by: 'count', order: 'desc' });
  const first = await apiFetch(`${INAT_API}/observations/species_counts?${base}`);

  let all = first.results || [];
  const total = first.total_results || 0;
  const pages = Math.min(Math.ceil(total / 200), 5); // cap at 1 000 species

  if (pages > 1) {
    const more = await Promise.all(
      Array.from({ length: pages - 1 }, (_, i) => {
        const p = new URLSearchParams(base);
        p.set('page', i + 2);
        return apiFetch(`${INAT_API}/observations/species_counts?${p}`);
      })
    );
    for (const r of more) all = all.concat(r.results || []);
  }

  const cats = {};
  CATEGORIES.forEach(c => { cats[c.key] = 0; });
  let nativeCount = 0, introducedCount = 0;

  for (const s of all) {
    const k = s.taxon?.iconic_taxon_name;
    if (k && cats.hasOwnProperty(k)) cats[k]++;

    const em = establishmentMeans(s);
    if (em === 'native' || em === 'endemic') nativeCount++;
    else if (em === 'introduced' || em === 'naturalizing') introducedCount++;
  }

  const detail = { species: all, cats, nativeCount, introducedCount };
  state.detailCache[id] = detail;
  return detail;
}

function establishmentMeans(s) {
  return (
    s.taxon?.establishment_means?.establishment_means ||
    s.taxon?.listed_taxon?.establishment_means ||
    null
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Sidebar
// ─────────────────────────────────────────────────────────────────────────────

function openSidebar(feature) {
  const sidebar = document.getElementById('sidebar');
  sidebar.classList.remove('sidebar-closed');

  const name = parkName(feature);
  const content = document.getElementById('sidebar-content');
  content.innerHTML = `
    <div class="park-header">
      <div class="park-title">${esc(name)}</div>
      <div class="park-meta">Fetching iNaturalist data…</div>
    </div>
    <div class="loading-block">
      <div class="spinner"></div>
      <span>Loading species…</span>
    </div>`;

  currentEM = 'all'; // reset filter state for each new park open

  fetchDetail(feature)
    .then(detail => {
      renderSidebar(feature, detail);
      updateRankingFromDetail(feature, detail);
    })
    .catch(err => {
      content.innerHTML = `
        <div class="park-header"><div class="park-title">${esc(name)}</div></div>
        <div class="error-block">Failed to load: ${esc(err.message)}</div>`;
    });
}

function closeSidebar() {
  document.getElementById('sidebar').classList.add('sidebar-closed');
  state.selectedId = null;
  resetAllStyles();
  document.querySelectorAll('#rankings-body tr').forEach(r => r.classList.remove('row-selected'));
}

function renderSidebar(feature, detail) {
  const name = parkName(feature);
  const { species, cats, nativeCount, introducedCount } = detail;
  const total = species.length;
  const nativePct = total > 0 ? Math.round((nativeCount / total) * 100) : '–';

  // Category grid
  const catHTML = CATEGORIES.map(c => `
    <div class="cat-pill" data-cat="${c.key}">
      <span class="p-icon">${c.icon}</span>
      <span class="p-count">${cats[c.key] || 0}</span>
      <span class="p-label">${c.label}</span>
    </div>`).join('');

  document.getElementById('sidebar-content').innerHTML = `
    <div class="park-header">
      <div class="park-title">${esc(name)}</div>
      <div class="park-meta">${total.toLocaleString()} species · ${nativePct}% native/endemic · research grade</div>
    </div>
    <div class="cat-grid">${catHTML}</div>
    <div id="em-filter">
      <button class="em-btn active" data-em="all">All (${total})</button>
      <button class="em-btn" data-em="native">Native (${nativeCount})</button>
      <button class="em-btn" data-em="introduced">Introduced (${introducedCount})</button>
    </div>
    <div id="sp-list-wrap">${buildSpeciesHTML(species, 'all', null)}</div>`;

  // Category pill filtering
  let activeCat = null;
  document.querySelectorAll('.cat-pill').forEach(pill => {
    pill.addEventListener('click', () => {
      const cat = pill.dataset.cat;
      activeCat = (activeCat === cat) ? null : cat;
      document.querySelectorAll('.cat-pill').forEach(p => p.classList.toggle('active', p.dataset.cat === activeCat));
      refreshSpeciesList(species, activeCat);
    });
  });

  // EM filter buttons
  document.querySelectorAll('.em-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.em-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      // reset cat
      activeCat = null;
      document.querySelectorAll('.cat-pill').forEach(p => p.classList.remove('active'));
      refreshSpeciesList(species, null, btn.dataset.em);
    });
  });
}

let currentEM = 'all';
function refreshSpeciesList(species, cat, em) {
  if (em != null) currentEM = em;
  document.getElementById('sp-list-wrap').innerHTML = buildSpeciesHTML(species, currentEM, cat ?? null);
}

function buildSpeciesHTML(species, em = 'all', cat = null) {
  let list = species;

  if (cat) list = list.filter(s => s.taxon?.iconic_taxon_name === cat);

  if (em === 'native')
    list = list.filter(s => { const e = establishmentMeans(s); return e === 'native' || e === 'endemic'; });
  else if (em === 'introduced')
    list = list.filter(s => { const e = establishmentMeans(s); return e === 'introduced' || e === 'naturalizing'; });

  if (list.length === 0)
    return '<div style="color:#2a5a2a;font-size:0.74rem;padding:10px 4px;font-style:italic">No species match this filter.</div>';

  const SHOW = 300;
  const items = list.slice(0, SHOW).map(speciesItemHTML).join('');
  const overflow = list.length > SHOW
    ? `<div class="list-overflow">Showing ${SHOW} of ${list.length.toLocaleString()} species</div>`
    : '';
  return `<div class="species-list">${items}</div>${overflow}`;
}

function speciesItemHTML(s) {
  const t = s.taxon || {};
  const common = t.preferred_common_name || t.name || 'Unknown';
  const sci    = t.name || '';
  const cat    = CATEGORIES.find(c => c.key === t.iconic_taxon_name);
  const em     = establishmentMeans(s);

  const photoUrl = t.default_photo?.square_url;
  const photoEl = photoUrl
    ? `<img class="sp-photo" src="${esc(photoUrl)}" alt="${esc(common)}" loading="lazy">`
    : `<div class="sp-no-photo">${cat?.icon ?? '🔬'}</div>`;

  const emBadge =
    em === 'native'       ? '<span class="badge badge-native">native</span>' :
    em === 'endemic'      ? '<span class="badge badge-endemic">endemic</span>' :
    em === 'introduced'   ? '<span class="badge badge-introduced">introduced</span>' :
    em === 'naturalizing' ? '<span class="badge badge-naturalizing">naturalizing</span>' : '';

  const catBadge = cat ? `<span class="badge badge-cat">${cat.icon} ${cat.label}</span>` : '';
  const obsLabel = `${s.count.toLocaleString()} obs`;

  return `
    <div class="sp-item">
      ${photoEl}
      <div class="sp-info">
        <div class="sp-common">${esc(common)}</div>
        <div class="sp-sci">${esc(sci)}</div>
        <div class="sp-badges">${catBadge}${emBadge}</div>
        <div class="sp-obs">${obsLabel}</div>
      </div>
    </div>`;
}

// ─────────────────────────────────────────────────────────────────────────────
// Rankings
// ─────────────────────────────────────────────────────────────────────────────

function updateRankingFromDetail(feature, detail) {
  const id = parkId(feature);
  state.rankings[id] = {
    name:    parkName(feature),
    total:   detail.species.length,
    cats:    detail.cats,
    nativeCount: detail.nativeCount,
    feature,
  };
  renderRankings();
  document.getElementById('stat-ranked').textContent = Object.keys(state.rankings).length;
}

function updateRankingFromCount(feature, count) {
  const id = parkId(feature);
  if (state.rankings[id]) return; // already have detail
  state.rankings[id] = {
    name:    parkName(feature),
    total:   count,
    cats:    null, // will be filled when clicked
    nativeCount: null,
    feature,
  };
  renderRankings();
  document.getElementById('stat-ranked').textContent = Object.keys(state.rankings).length;
}

function sortedRankings() {
  const entries = Object.values(state.rankings);
  const col = state.sortCol;

  return entries.sort((a, b) => {
    if (col === 'native_pct') {
      const ap = a.nativeCount != null && a.total > 0 ? a.nativeCount / a.total : -1;
      const bp = b.nativeCount != null && b.total > 0 ? b.nativeCount / b.total : -1;
      return bp - ap;
    }
    if (col === 'total') return (b.total ?? 0) - (a.total ?? 0);
    return ((b.cats?.[col] ?? 0) - (a.cats?.[col] ?? 0));
  });
}

function renderRankings() {
  const body = document.getElementById('rankings-body');
  const sorted = sortedRankings();

  if (sorted.length === 0) {
    body.innerHTML = `<tr><td colspan="9" class="empty-msg">
      Click a park on the map, or press <strong>Load all parks</strong> to build the full ranking.
    </td></tr>`;
    return;
  }

  body.innerHTML = sorted.map((entry, i) => {
    const id  = parkId(entry.feature);
    const sel = state.selectedId === id ? 'row-selected' : '';
    const nativePct = entry.nativeCount != null && entry.total > 0
      ? Math.round((entry.nativeCount / entry.total) * 100) + '%'
      : entry.total != null ? '–' : '<span class="td-loading">…</span>';

    const numOrDash = (v) =>
      v != null ? v.toLocaleString() : '<span class="td-loading">…</span>';

    const other = entry.cats
      ? Math.max(0, entry.total -
          CATEGORIES.filter(c => ['Plantae','Aves','Insecta','Mammalia','Fungi'].includes(c.key))
            .reduce((s, c) => s + (entry.cats[c.key] || 0), 0))
      : null;

    return `<tr class="${sel}" data-pid="${esc(id)}">
      <td class="td-rank">${i + 1}</td>
      <td class="td-name" title="${esc(entry.name)}">${esc(entry.name)}</td>
      <td class="td-num">${numOrDash(entry.total)}</td>
      <td class="td-num">${numOrDash(entry.cats?.Plantae)}</td>
      <td class="td-num">${numOrDash(entry.cats?.Aves)}</td>
      <td class="td-num">${numOrDash(entry.cats?.Insecta)}</td>
      <td class="td-num">${numOrDash(entry.cats?.Mammalia)}</td>
      <td class="td-num">${numOrDash(entry.cats?.Fungi)}</td>
      <td class="td-num">${nativePct}</td>
    </tr>`;
  }).join('');

  // Row click → select park on map
  body.querySelectorAll('tr[data-pid]').forEach(row => {
    row.addEventListener('click', () => {
      const entry = state.rankings[row.dataset.pid];
      if (!entry?.feature) return;

      const layer = findLayerByFeature(entry.feature);
      if (layer) {
        map.fitBounds(layer.getBounds(), { padding: [50, 50], maxZoom: 16 });
        selectPark(entry.feature, layer);
      }
    });
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Load-all-parks workflow
// ─────────────────────────────────────────────────────────────────────────────

async function loadAllParks() {
  if (state.loadingAll) return;
  state.loadingAll = true;

  const btn  = document.getElementById('load-all-btn');
  const prog = document.getElementById('rank-progress');
  const fill = document.getElementById('rank-progress-fill');
  const lbl  = document.getElementById('rank-progress-label');

  btn.disabled = true;
  prog.classList.remove('hidden');

  const parks = state.parks.filter(f => f.geometry);
  const total = parks.length;
  let done = 0;

  // Process with limited concurrency so we respect iNaturalist rate limits
  const CONCURRENCY = 3;
  const queue = [...parks];

  async function worker() {
    while (queue.length > 0) {
      const feature = queue.shift();
      try {
        const count = await fetchCount(feature);
        updateRankingFromCount(feature, count);
      } catch {
        /* skip failed parks */
      }
      done++;
      const pct = Math.round((done / total) * 100);
      fill.style.width = pct + '%';
      lbl.textContent  = `${done} / ${total}`;
    }
  }

  await Promise.all(Array.from({ length: CONCURRENCY }, worker));

  state.loadingAll = false;
  btn.disabled     = false;
  btn.textContent  = 'Reload';
  prog.classList.add('hidden');
}

// ─────────────────────────────────────────────────────────────────────────────
// Parks data loading
// ─────────────────────────────────────────────────────────────────────────────

async function tryFetchParks(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const data = await resp.json();

  // Socrata GeoJSON returns a FeatureCollection directly
  const features = (data.features || []).filter(
    f => f.geometry &&
         (f.geometry.type === 'Polygon' || f.geometry.type === 'MultiPolygon')
  );

  if (features.length === 0) throw new Error('No polygon features found');
  return features;
}

async function loadParks() {
  showMapOverlay('Loading SF parks…');

  let features;
  try {
    features = await tryFetchParks(SF_PARKS_URL);
  } catch (e1) {
    showMapOverlay(`Failed to load parks data: ${e1.message}`, true);
    return;
  }

  state.parks = features;
  addParksToMap(features);
  hideMapOverlay();
  document.getElementById('stat-parks').textContent = features.length;
}

function showMapOverlay(text, isError = false) {
  const el = document.getElementById('map-overlay-msg');
  el.classList.remove('hidden');
  el.innerHTML = isError
    ? `<span style="color:#cf9f9f">${esc(text)}</span>`
    : `<div class="spinner"></div><span>${esc(text)}</span>`;
}

function hideMapOverlay() {
  document.getElementById('map-overlay-msg').classList.add('hidden');
}

// ─────────────────────────────────────────────────────────────────────────────
// Utilities
// ─────────────────────────────────────────────────────────────────────────────

function esc(str) {
  return String(str ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ─────────────────────────────────────────────────────────────────────────────
// Init
// ─────────────────────────────────────────────────────────────────────────────

async function init() {
  initMap();

  // Kick off SF place-ID lookup in parallel with parks load
  findSFPlaceId().then(id => { state.sfPlaceId = id; });

  await loadParks();

  // Sidebar close
  document.getElementById('sidebar-close').addEventListener('click', closeSidebar);

  // Load-all button
  document.getElementById('load-all-btn').addEventListener('click', loadAllParks);

  // Sort buttons (bar)
  document.querySelectorAll('.sort-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.sort-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.sortCol = btn.dataset.col;
      renderRankings();
    });
  });

  // Table header clicks also sort
  document.querySelectorAll('#rankings-table thead th.sortable').forEach(th => {
    th.addEventListener('click', () => {
      state.sortCol = th.dataset.col;
      document.querySelectorAll('.sort-btn').forEach(b => b.classList.toggle('active', b.dataset.col === state.sortCol));
      renderRankings();
    });
  });
}

document.addEventListener('DOMContentLoaded', init);
