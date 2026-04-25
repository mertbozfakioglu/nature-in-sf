'use strict';

// ─────────────────────────────────────────────────────────────────────────────
// Config
// ─────────────────────────────────────────────────────────────────────────────

const DATA_ROOT = 'data';   // relative to index.html

const CATEGORIES = [
  { key: 'Plantae',   label: 'Plants',      icon: '🌿' },
  { key: 'Aves',      label: 'Birds',       icon: '🐦' },
  { key: 'Insecta',   label: 'Insects',     icon: '🦋' },
  { key: 'Mammalia',  label: 'Mammals',     icon: '🦊' },
  { key: 'Fungi',     label: 'Fungi',       icon: '🍄' },
  { key: 'Reptilia',  label: 'Reptiles',    icon: '🦎' },
  { key: 'Amphibia',  label: 'Amphibians',  icon: '🐸' },
  { key: 'Arachnida', label: 'Arachnids',   icon: '🕷️' },
  { key: 'Mollusca',  label: 'Mollusks',    icon: '🐌' },
];

// ─────────────────────────────────────────────────────────────────────────────
// State
// ─────────────────────────────────────────────────────────────────────────────

const state = {
  parks:       [],      // GeoJSON features
  summary:     {},      // { [parkId]: { name, total, cats, nativeCount, ... } }
  detailCache: {},      // { [parkId]: { species[], cats, nativeCount, introducedCount } }
  selectedId:  null,
  sortCol:     'total',
  nativesOnly: false,
};

// ─────────────────────────────────────────────────────────────────────────────
// Map
// ─────────────────────────────────────────────────────────────────────────────

let map;
let parksLayer;

function initMap() {
  map = L.map('map', { center: [37.7599, -122.44], zoom: 12 });
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
    subdomains: 'abcd', maxZoom: 20,
  }).addTo(map);
}

const STYLE = {
  normal:   { fillColor: '#2a4a2a', fillOpacity: 0.30, color: '#4a7a4a', weight: 1 },
  hover:    { fillColor: '#3a6a3a', fillOpacity: 0.50, color: '#7ab07a', weight: 2 },
  selected: { fillColor: '#5a9b5a', fillOpacity: 0.55, color: '#a0cf9f', weight: 2 },
};

function pid(feature) {
  const p = feature.properties || {};
  return String(
    p.property_id || p.name || feature.id ||
    JSON.stringify(feature.geometry?.coordinates?.[0]?.[0])
  );
}

function pname(feature) {
  const p = feature.properties || {};
  return p.property_name || p.name || 'Unknown';
}

function resetStyles() {
  parksLayer?.eachLayer(l => {
    l.setStyle(pid(l.feature) === state.selectedId ? STYLE.selected : STYLE.normal);
  });
}

function addParksToMap(features) {
  if (parksLayer) parksLayer.remove();
  parksLayer = L.geoJSON({ type: 'FeatureCollection', features }, {
    style: () => ({ ...STYLE.normal }),
    onEachFeature(feature, layer) {
      const id   = pid(feature);
      const name = pname(feature);
      layer.on('mouseover', () => {
        if (id !== state.selectedId) layer.setStyle(STYLE.hover);
        layer.bindTooltip(esc(name), {
          permanent: false, className: 'park-tooltip', direction: 'top', offset: [0,-4],
        }).openTooltip();
      });
      layer.on('mouseout', () => {
        if (id !== state.selectedId) layer.setStyle(STYLE.normal);
      });
      layer.on('click', e => {
        L.DomEvent.stopPropagation(e);
        selectPark(feature, layer);
      });
    },
  }).addTo(map);
  map.on('click', closeSidebar);
}

function findLayer(feature) {
  let found = null;
  parksLayer?.eachLayer(l => { if (pid(l.feature) === pid(feature)) found = l; });
  return found;
}

function selectPark(feature, layer) {
  state.selectedId = pid(feature);
  resetStyles();
  layer.setStyle(STYLE.selected);
  openSidebar(feature);
  document.querySelectorAll('#rankings-body tr[data-pid]').forEach(r => {
    r.classList.toggle('row-selected', r.dataset.pid === state.selectedId);
  });
}

function closeSidebar() {
  document.getElementById('sidebar').classList.add('sidebar-closed');
  state.selectedId = null;
  resetStyles();
  document.querySelectorAll('#rankings-body tr').forEach(r => r.classList.remove('row-selected'));
}

// ─────────────────────────────────────────────────────────────────────────────
// Data loading (static files)
// ─────────────────────────────────────────────────────────────────────────────

async function loadJSON(path) {
  const resp = await fetch(path);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${path}`);
  return resp.json();
}

async function loadParks() {
  showOverlay('Loading parks…');
  const geojson = await loadJSON(`${DATA_ROOT}/parks.geojson`);
  const features = (geojson.features || []).filter(
    f => f.geometry && (f.geometry.type === 'Polygon' || f.geometry.type === 'MultiPolygon')
  );
  state.parks = features;
  addParksToMap(features);
  document.getElementById('stat-parks').textContent = features.length;
  hideOverlay();
}

async function loadSummary() {
  const summary = await loadJSON(`${DATA_ROOT}/summary.json`);
  state.summary = summary;
  // Populate rankings immediately from summary
  for (const [id, data] of Object.entries(summary)) {
    state.detailCache[id] = {
      species: null,  // not yet loaded
      cats:    data.cats || {},
      nativeCount:    data.nativeCount || 0,
      introducedCount:data.introducedCount || 0,
      total:   data.total || 0,
    };
  }
  renderRankings();
  document.getElementById('stat-ranked').textContent = Object.keys(summary).length;
}

async function loadParkDetail(feature) {
  const id = pid(feature);
  // Return summary stub if full species aren't loaded yet
  if (state.detailCache[id]?.species) return state.detailCache[id];

  const data = await loadJSON(`${DATA_ROOT}/species/${id}.json`);
  state.detailCache[id] = {
    species:        data.species || [],
    cats:           data.summary?.cats || {},
    nativeCount:    data.summary?.nativeCount || 0,
    introducedCount:data.summary?.introducedCount || 0,
    total:          data.summary?.total || 0,
  };
  return state.detailCache[id];
}

// ─────────────────────────────────────────────────────────────────────────────
// Sidebar
// ─────────────────────────────────────────────────────────────────────────────

let currentEM = 'all';

function openSidebar(feature) {
  currentEM = 'all';
  const sidebar = document.getElementById('sidebar');
  sidebar.classList.remove('sidebar-closed');

  const name = pname(feature);
  document.getElementById('sidebar-content').innerHTML = `
    <div class="park-header">
      <div class="park-title">${esc(name)}</div>
      <div class="park-meta">Loading species…</div>
    </div>
    <div class="loading-block"><div class="spinner"></div><span>Reading species data…</span></div>`;

  loadParkDetail(feature)
    .then(detail => renderSidebar(feature, detail))
    .catch(err => {
      document.getElementById('sidebar-content').innerHTML = `
        <div class="park-header"><div class="park-title">${esc(name)}</div></div>
        <div class="error-block">${esc(err.message)}</div>`;
    });
}

function renderSidebar(feature, detail) {
  const name  = pname(feature);
  const total = detail.species?.length ?? detail.total ?? 0;
  const initEM = state.nativesOnly ? 'native' : 'all';

  const catGrid = CATEGORIES.map(c => `
    <div class="cat-pill" data-cat="${c.key}">
      <span class="p-icon">${c.icon}</span>
      <span class="p-count">${detail.cats?.[c.key] ?? 0}</span>
      <span class="p-label">${c.label}</span>
    </div>`).join('');

  document.getElementById('sidebar-content').innerHTML = `
    <div class="park-header">
      <div class="park-title">${esc(name)}</div>
      <div class="park-meta">${total.toLocaleString()} species · ${detail.nativeCount} native · research grade</div>
    </div>
    <div class="cat-grid">${catGrid}</div>
    <div id="em-filter">
      <button class="em-btn${initEM === 'all' ? ' active' : ''}" data-em="all">All (${total})</button>
      <button class="em-btn${initEM === 'native' ? ' active' : ''}" data-em="native">Native (${detail.nativeCount})</button>
      <button class="em-btn" data-em="introduced">Introduced (${detail.introducedCount})</button>
    </div>
    <div id="sp-list-wrap">${buildSpeciesHTML(detail.species, initEM, null)}</div>`;

  let activeCat = null;

  document.querySelectorAll('.cat-pill').forEach(pill => {
    pill.addEventListener('click', () => {
      const cat = pill.dataset.cat;
      activeCat = (activeCat === cat) ? null : cat;
      document.querySelectorAll('.cat-pill').forEach(p =>
        p.classList.toggle('active', p.dataset.cat === activeCat));
      document.getElementById('sp-list-wrap').innerHTML =
        buildSpeciesHTML(detail.species, currentEM, activeCat);
    });
  });

  document.querySelectorAll('.em-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.em-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentEM = btn.dataset.em;
      activeCat = null;
      document.querySelectorAll('.cat-pill').forEach(p => p.classList.remove('active'));
      document.getElementById('sp-list-wrap').innerHTML =
        buildSpeciesHTML(detail.species, currentEM, null);
    });
  });
}

function buildSpeciesHTML(species, em = 'all', cat = null) {
  if (!species) return '<div style="color:#2a5a2a;font-size:.74rem;padding:10px 4px;font-style:italic">Full species list loading…</div>';

  let list = species;
  if (cat)          list = list.filter(s => s.taxon?.iconic_taxon_name === cat);
  if (em === 'native')
    list = list.filter(s => { const e = em_from(s); return e === 'native' || e === 'endemic'; });
  else if (em === 'introduced')
    list = list.filter(s => { const e = em_from(s); return e === 'introduced' || e === 'naturalizing'; });

  if (!list.length)
    return '<div style="color:#2a5a2a;font-size:.74rem;padding:10px 4px;font-style:italic">No species match this filter.</div>';

  const SHOW = 300;
  const items   = list.slice(0, SHOW).map(speciesItemHTML).join('');
  const overflow = list.length > SHOW
    ? `<div class="list-overflow">Showing ${SHOW} of ${list.length.toLocaleString()}</div>` : '';
  return `<div class="species-list">${items}</div>${overflow}`;
}

function em_from(s) {
  return s.taxon?.establishment_means?.establishment_means || null;
}

function speciesItemHTML(s) {
  const t      = s.taxon || {};
  const common = t.preferred_common_name || t.name || 'Unknown';
  const sci    = t.name || '';
  const cat    = CATEGORIES.find(c => c.key === t.iconic_taxon_name);
  const em     = em_from(s);

  const photoEl = t.default_photo?.square_url
    ? `<img class="sp-photo" src="${esc(t.default_photo.square_url)}" alt="${esc(common)}" loading="lazy">`
    : `<div class="sp-no-photo">${cat?.icon ?? '🔬'}</div>`;

  const emBadge =
    em === 'native'       ? '<span class="badge badge-native">native</span>' :
    em === 'endemic'      ? '<span class="badge badge-endemic">endemic</span>' :
    em === 'introduced'   ? '<span class="badge badge-introduced">introduced</span>' :
    em === 'naturalizing' ? '<span class="badge badge-naturalizing">naturalizing</span>' : '';

  const catBadge = cat ? `<span class="badge badge-cat">${cat.icon} ${cat.label}</span>` : '';

  return `
    <div class="sp-item">
      ${photoEl}
      <div class="sp-info">
        <div class="sp-common">${esc(common)}</div>
        <div class="sp-sci">${esc(sci)}</div>
        <div class="sp-badges">${catBadge}${emBadge}</div>
        <div class="sp-obs">${s.count.toLocaleString()} obs</div>
      </div>
    </div>`;
}

// ─────────────────────────────────────────────────────────────────────────────
// Rankings
// ─────────────────────────────────────────────────────────────────────────────

function renderRankings() {
  const body    = document.getElementById('rankings-body');
  const entries = Object.entries(state.detailCache);
  if (!entries.length) return;

  const col    = state.sortCol;
  const natv   = state.nativesOnly;
  entries.sort(([, a], [, b]) => {
    const av = natv ? (a.nativeCount ?? 0) : (col === 'total' ? (a.total ?? 0) : (a.cats?.[col] ?? 0));
    const bv = natv ? (b.nativeCount ?? 0) : (col === 'total' ? (b.total ?? 0) : (b.cats?.[col] ?? 0));
    return bv - av;
  });

  // Keep the "Species" header in sync with the current mode
  const thSp = document.getElementById('th-species');
  if (thSp) thSp.textContent = natv ? 'Native spp' : 'Species';

  body.innerHTML = entries.map(([id, d], i) => {
    const name = state.summary[id]?.name ?? id;
    const sel  = state.selectedId === id ? 'row-selected' : '';
    const n    = v => v != null ? v.toLocaleString() : '–';
    const displayTotal = natv ? n(d.nativeCount) : n(d.total);
    return `<tr class="${sel}" data-pid="${esc(id)}">
      <td class="td-rank">${i + 1}</td>
      <td class="td-name" title="${esc(name)}">${esc(name)}</td>
      <td class="td-num">${displayTotal}</td>
      <td class="td-num">${n(d.cats?.Plantae)}</td>
      <td class="td-num">${n(d.cats?.Aves)}</td>
      <td class="td-num">${n(d.cats?.Insecta)}</td>
      <td class="td-num">${n(d.cats?.Mammalia)}</td>
      <td class="td-num">${n(d.cats?.Fungi)}</td>
    </tr>`;
  }).join('');

  body.querySelectorAll('tr[data-pid]').forEach(row => {
    row.addEventListener('click', () => {
      const id      = row.dataset.pid;
      const feature = state.parks.find(f => pid(f) === id);
      if (!feature) return;
      const layer = findLayer(feature);
      if (layer) {
        map.fitBounds(layer.getBounds(), { padding: [50, 50], maxZoom: 16 });
        selectPark(feature, layer);
      }
    });
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Natives-only toggle
// ─────────────────────────────────────────────────────────────────────────────

function toggleNativesOnly() {
  state.nativesOnly = !state.nativesOnly;
  document.getElementById('natives-btn').classList.toggle('active', state.nativesOnly);
  renderRankings();

  // Update open sidebar species list and EM filter buttons to match
  const wrap = document.getElementById('sp-list-wrap');
  if (!wrap) return;
  currentEM = state.nativesOnly ? 'native' : 'all';
  wrap.innerHTML = buildSpeciesHTML(
    state.detailCache[state.selectedId]?.species ?? null,
    currentEM, null
  );
  document.querySelectorAll('.em-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.em === currentEM));
}

// ─────────────────────────────────────────────────────────────────────────────
// Map overlay
// ─────────────────────────────────────────────────────────────────────────────

function showOverlay(text) {
  const el = document.getElementById('map-overlay-msg');
  el.classList.remove('hidden');
  el.innerHTML = `<div class="spinner"></div><span>${esc(text)}</span>`;
}
function hideOverlay() { document.getElementById('map-overlay-msg').classList.add('hidden'); }

// ─────────────────────────────────────────────────────────────────────────────
// Utility
// ─────────────────────────────────────────────────────────────────────────────

function esc(s) {
  return String(s ?? '')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ─────────────────────────────────────────────────────────────────────────────
// Init
// ─────────────────────────────────────────────────────────────────────────────

async function init() {
  initMap();

  // Load parks GeoJSON and summary in parallel
  try {
    await loadParks();
  } catch (e) {
    showOverlay(`Failed to load parks: ${e.message}`, true);
    return;
  }

  loadSummary().catch(e => console.warn('Summary not yet available:', e.message));

  // Sidebar close
  document.getElementById('sidebar-close').addEventListener('click', closeSidebar);

  // Natives-only toggle
  document.getElementById('natives-btn').addEventListener('click', toggleNativesOnly);

  // Sort buttons
  document.querySelectorAll('.sort-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.sort-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.sortCol = btn.dataset.col;
      renderRankings();
    });
  });

  document.querySelectorAll('#rankings-table thead th.sortable').forEach(th => {
    th.addEventListener('click', () => {
      state.sortCol = th.dataset.col;
      document.querySelectorAll('.sort-btn').forEach(b =>
        b.classList.toggle('active', b.dataset.col === state.sortCol));
      renderRankings();
    });
  });
}

document.addEventListener('DOMContentLoaded', init);
