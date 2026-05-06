'use strict';

// ─────────────────────────────────────────────────────────────────────────────
// Config
// ─────────────────────────────────────────────────────────────────────────────

const DATA_ROOT = 'data';

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
  parks:        [],
  summary:      {},
  detailCache:  {},
  selectedId:   null,
  sortCol:      'total',
  nativeMode:   'all',   // 'all' | 'ca' | 'sf'
  sfNatives:    new Set(),
  nurseries:    {},
  nurseryIndex: new Map(),  // 'Genus species' → ['nursery_id', …]
  histograms:   {},         // taxon_id (string) → [jan…dec counts]
  spSort:       'obs',      // 'obs' | 'month'
  speciesIndex: [],         // [{id, name, common, iconic, photo, parks:[…]}]
  speciesFilter: null,      // Set<parkId> when a species is selected, else null
};

// ─────────────────────────────────────────────────────────────────────────────
// Map
// ─────────────────────────────────────────────────────────────────────────────

let map;
let parksLayer;

function initMap() {
  map = L.map('map', { center: [37.7599, -122.44], zoom: 12 });
  L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
    subdomains: 'abcd', maxZoom: 20,
  }).addTo(map);
}

const STYLE = {
  normal:    { fillColor: '#7ab88a', fillOpacity: 0.30, color: '#4a7a56', weight: 1.5 },
  hover:     { fillColor: '#5a9e6e', fillOpacity: 0.50, color: '#3a6a46', weight: 2 },
  selected:  { fillColor: '#3a8e56', fillOpacity: 0.60, color: '#2a6a3e', weight: 2.5 },
  highlight: { fillColor: '#e07b20', fillOpacity: 0.55, color: '#b85a0a', weight: 2.5 },
  dim:       { fillColor: '#999',    fillOpacity: 0.07, color: '#bbb',    weight: 1 },
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
    const id = pid(l.feature);
    if (id === state.selectedId)       l.setStyle(STYLE.selected);
    else if (state.speciesFilter)      l.setStyle(state.speciesFilter.has(id) ? STYLE.highlight : STYLE.dim);
    else                               l.setStyle(STYLE.normal);
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
        if (id !== state.selectedId) {
          const inFilter = !state.speciesFilter || state.speciesFilter.has(id);
          if (inFilter) layer.setStyle(STYLE.hover);
        }
        layer.bindTooltip(esc(name), {
          permanent: false, className: 'park-tooltip', direction: 'top', offset: [0,-4],
        }).openTooltip();
      });
      layer.on('mouseout', () => {
        if (id !== state.selectedId) {
          if (state.speciesFilter) layer.setStyle(state.speciesFilter.has(id) ? STYLE.highlight : STYLE.dim);
          else layer.setStyle(STYLE.normal);
        }
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
// Data loading
// ─────────────────────────────────────────────────────────────────────────────

async function loadJSON(path) {
  const resp = await fetch(path);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${path}`);
  return resp.json();
}

async function loadSFNatives() {
  const resp = await fetch(`${DATA_ROOT}/sf_natives.csv`);
  if (!resp.ok) return;
  const text = await resp.text();
  state.sfNatives = new Set(
    text.split('\n').map(l => l.trim()).filter(Boolean)
  );
}

async function loadHistograms() {
  try {
    state.histograms = await loadJSON(`${DATA_ROOT}/histograms.json`);
  } catch (e) {
    console.warn('Histograms not available:', e.message);
  }
}

async function loadNurseries() {
  try {
    const [nurseries, inventory] = await Promise.all([
      loadJSON(`${DATA_ROOT}/nurseries.json`),
      loadJSON(`${DATA_ROOT}/nursery_inventory.json`),
    ]);
    state.nurseries = nurseries;
    state.nurseryIndex = new Map(Object.entries(inventory.bySpecies ?? {}));
  } catch (e) {
    console.warn('Nursery data not available:', e.message);
  }
}

async function loadParks() {
  showOverlay('Loading parks…');
  const geojson = await loadJSON(`${DATA_ROOT}/parks.geojson`);
  state.parks = (geojson.features || []).filter(
    f => f.geometry && (f.geometry.type === 'Polygon' || f.geometry.type === 'MultiPolygon')
  );
}

async function loadSummary() {
  const summary = await loadJSON(`${DATA_ROOT}/summary.json`);
  state.summary = summary;
  for (const [id, data] of Object.entries(summary)) {
    state.detailCache[id] = {
      species:        null,
      cats:           data.cats            || {},
      native_cats:    data.native_cats     || {},
      sf_native_cats: data.sf_native_cats  || {},
      nativeCount:    data.nativeCount     || 0,
      sfNativeCount:  data.sfNativeCount   || 0,
      introducedCount:data.introducedCount || 0,
      total:          data.total           || 0,
    };
  }
  renderRankings();
}

async function loadParkDetail(feature) {
  const id = pid(feature);
  if (state.detailCache[id]?.species) return state.detailCache[id];

  const data    = await loadJSON(`${DATA_ROOT}/species/${id}.json`);
  const species = data.species || [];
  state.detailCache[id] = {
    species,
    cats:           data.summary?.cats            || {},
    native_cats:    nativeCatsFromSpecies(species, 'ca'),
    sf_native_cats: nativeCatsFromSpecies(species, 'sf'),
    nativeCount:    countNatives(species, 'ca'),
    sfNativeCount:  countNatives(species, 'sf'),
    introducedCount:data.summary?.introducedCount || 0,
    total:          species.filter(isSpeciesLevel).length,
  };
  return state.detailCache[id];
}

// ─────────────────────────────────────────────────────────────────────────────
// Species filtering helpers
// ─────────────────────────────────────────────────────────────────────────────

function em_from(s) {
  return s.taxon?.establishment_means?.establishment_means || null;
}

function isIntroduced(s) {
  const em = em_from(s);
  return em === 'introduced' || em === 'naturalizing';
}

function isSpeciesLevel(s) {
  return (s.taxon?.name || '').split(' ').length >= 2;
}

function isNativeForMode(s, mode) {
  if (isIntroduced(s)) return false;
  if (mode === 'sf' && s.taxon?.iconic_taxon_name === 'Plantae') {
    const sp = (s.taxon.name || '').split(' ').slice(0, 2).join(' ');
    return state.sfNatives.has(sp);
  }
  return true;
}

function nativeCatsFromSpecies(species, mode = 'ca') {
  const out = {};
  CATEGORIES.forEach(c => { out[c.key] = 0; });
  for (const s of (species || [])) {
    if (!isSpeciesLevel(s)) continue;
    const k = s.taxon?.iconic_taxon_name;
    if (k in out && isNativeForMode(s, mode)) out[k]++;
  }
  return out;
}

function countNatives(species, mode) {
  return (species || []).filter(s => isSpeciesLevel(s) && isNativeForMode(s, mode)).length;
}

// ─────────────────────────────────────────────────────────────────────────────
// Sidebar
// ─────────────────────────────────────────────────────────────────────────────

function openSidebar(feature) {
  document.getElementById('sidebar').classList.remove('sidebar-closed');
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
  const name = pname(feature);
  const mode = state.nativeMode;
  const total = detail.species?.filter(isSpeciesLevel).length ?? detail.total ?? 0;

  const dispTotal = mode === 'sf' ? detail.sfNativeCount : total;
  const dispCats  = mode === 'sf' ? detail.sf_native_cats : detail.cats;
  const modeLabel = mode === 'sf' ? 'SF native' : '';

  const catGrid = CATEGORIES.map(c => `
    <div class="cat-pill" data-cat="${c.key}">
      <span class="p-icon">${c.icon}</span>
      <span class="p-count">${dispCats?.[c.key] ?? 0}</span>
      <span class="p-label">${c.label}</span>
    </div>`).join('');

  const metaParts = [`${dispTotal.toLocaleString()}${modeLabel ? ' ' + modeLabel : ''} species`];
  if (mode !== 'all') metaParts.push(`${total.toLocaleString()} total`);
  metaParts.push('research grade');

  document.getElementById('sidebar-content').innerHTML = `
    <div class="park-header">
      <div class="park-title">${esc(name)}</div>
      <div class="park-meta">${metaParts.join(' · ')}</div>
    </div>
    <div class="cat-grid">${catGrid}</div>
    <div id="sp-sort-row">
      <span class="sp-sort-label">Sort by</span>
      <button class="sp-sort-btn${state.spSort === 'obs'   ? ' active' : ''}" data-sort="obs"># observations</button>
      <button class="sp-sort-btn${state.spSort === 'month' ? ' active' : ''}" data-sort="month">peak month</button>
    </div>
    <div id="sp-list-wrap">${buildSpeciesHTML(detail.species, null)}</div>`;

  const rerender = () => {
    document.getElementById('sp-list-wrap').innerHTML =
      buildSpeciesHTML(detail.species, activeCat);
  };

  let activeCat = null;
  document.querySelectorAll('.cat-pill').forEach(pill => {
    pill.addEventListener('click', () => {
      const cat = pill.dataset.cat;
      activeCat = (activeCat === cat) ? null : cat;
      document.querySelectorAll('.cat-pill').forEach(p =>
        p.classList.toggle('active', p.dataset.cat === activeCat));
      rerender();
    });
  });

  document.querySelectorAll('.sp-sort-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      state.spSort = btn.dataset.sort;
      document.querySelectorAll('.sp-sort-btn').forEach(b =>
        b.classList.toggle('active', b.dataset.sort === state.spSort));
      rerender();
    });
  });
}

function buildSpeciesHTML(species, cat = null) {
  if (!species) return '<div style="color:#2a5a2a;font-size:.74rem;padding:10px 4px;font-style:italic">Full species list loading…</div>';

  const mode = state.nativeMode;
  let list = species.filter(isSpeciesLevel);
  if (cat)           list = list.filter(s => s.taxon?.iconic_taxon_name === cat);
  if (mode !== 'all') list = list.filter(s => isNativeForMode(s, mode));

  if (!list.length)
    return '<div style="color:#2a5a2a;font-size:.74rem;padding:10px 4px;font-style:italic">No species match this filter.</div>';

  if (state.spSort === 'month')
    list.sort((a, b) => peakMonth(a.taxon?.id) - peakMonth(b.taxon?.id));

  const SHOW = 300;
  const items   = list.slice(0, SHOW).map(speciesItemHTML).join('');
  const overflow = list.length > SHOW
    ? `<div class="list-overflow">Showing ${SHOW} of ${list.length.toLocaleString()}</div>` : '';
  return `<div class="species-list">${items}</div>${overflow}`;
}

function peakMonth(taxonId) {
  const counts = state.histograms[String(taxonId)];
  if (!counts) return 99;
  let maxIdx = 0;
  counts.forEach((v, i) => { if (v > counts[maxIdx]) maxIdx = i; });
  return maxIdx; // 0–11
}

function histogramSVG(taxonId) {
  const counts = state.histograms[String(taxonId)];
  if (!counts) return '';
  const max = Math.max(...counts, 1);
  const MONTHS = ['J','F','M','A','M','J','J','A','S','O','N','D'];
  const H = 22, W = 8, GAP = 1, LABEL_H = 9;
  const totalW = 12 * (W + GAP) - GAP;
  const bars = counts.map((c, i) => {
    const h = Math.max(Math.round((c / max) * H), c > 0 ? 1 : 0);
    return `<rect x="${i * (W + GAP)}" y="${H - h}" width="${W}" height="${h}" rx="1"/>`;
  }).join('');
  const labels = MONTHS.map((m, i) =>
    `<text x="${i * (W + GAP) + W / 2}" y="${H + LABEL_H - 1}" text-anchor="middle" class="sp-hist-label">${m}</text>`
  ).join('');
  return `<svg class="sp-histogram" viewBox="0 0 ${totalW} ${H + LABEL_H}" width="${totalW}" height="${H + LABEL_H}" aria-hidden="true">${bars}${labels}</svg>`;
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

  const speciesKey = sci.split(' ').slice(0, 2).join(' ');
  const nurseryBadge = state.nurseryIndex.has(speciesKey)
    ? `<button class="badge badge-nursery" data-species="${esc(speciesKey)}">🪴 buy local</button>`
    : '';

  const histogram = histogramSVG(t.id);

  return `
    <div class="sp-item">
      ${photoEl}
      <div class="sp-info">
        <div class="sp-common">${esc(common)}</div>
        <div class="sp-sci">${esc(sci)}</div>
        <div class="sp-badges">${catBadge}${emBadge}${nurseryBadge}</div>
        <div class="sp-obs-row">
          <span class="sp-obs">${s.count.toLocaleString()} obs</span>
          ${histogram}
        </div>
      </div>
    </div>`;
}

// ─────────────────────────────────────────────────────────────────────────────
// Rankings
// ─────────────────────────────────────────────────────────────────────────────

function buildSortVal(d, col, mode) {
  const cats  = mode === 'sf' ? d.sf_native_cats : d.cats;
  const count = mode === 'sf' ? (d.sfNativeCount ?? 0) : (d.total ?? 0);
  return col === 'total' ? count : (cats?.[col] ?? 0);
}

function renderRankings() {
  const body    = document.getElementById('rankings-body');
  const entries = Object.entries(state.detailCache);
  if (!entries.length) return;

  const col  = state.sortCol;
  const mode = state.nativeMode;
  const visible = entries.filter(([, d]) => (d.sf_native_cats?.Plantae ?? 0) > 0);
  visible.sort(([, a], [, b]) => buildSortVal(b, col, mode) - buildSortVal(a, col, mode));

  body.innerHTML = visible.map(([id, d], i) => {
    const name  = state.summary[id]?.name ?? id;
    const sel   = state.selectedId === id ? 'row-selected' : '';
    const n     = v => v != null ? v.toLocaleString() : '–';
    const cats  = mode === 'sf' ? d.sf_native_cats : d.cats;
    const total = mode === 'sf' ? d.sfNativeCount : d.total;
    return `<tr class="${sel}" data-pid="${esc(id)}">
      <td class="td-rank">${i + 1}</td>
      <td class="td-name" title="${esc(name)}">${esc(name)}</td>
      <td class="td-num">${n(total)}</td>
      <td class="td-num">${n(cats?.Plantae)}</td>
      <td class="td-num">${n(cats?.Aves)}</td>
      <td class="td-num">${n(cats?.Insecta)}</td>
      <td class="td-num">${n(cats?.Mammalia)}</td>
      <td class="td-num">${n(cats?.Fungi)}</td>
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
// Native mode toggle
// ─────────────────────────────────────────────────────────────────────────────

function toggleNativeMode() {
  state.nativeMode = (state.nativeMode === 'sf') ? 'all' : 'sf';
  document.getElementById('natives-btn').classList.toggle('active', state.nativeMode === 'sf');
  renderRankings();
  if (state.selectedId) {
    const detail  = state.detailCache[state.selectedId];
    const feature = state.parks.find(f => pid(f) === state.selectedId);
    if (detail && feature) renderSidebar(feature, detail);
  }
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
// Nursery modal
// ─────────────────────────────────────────────────────────────────────────────

let _nurseryMap = null;

function openNurseryModal(speciesKey) {
  const nurseryIds = state.nurseryIndex.get(speciesKey) ?? [];
  document.getElementById('nursery-modal-title').textContent =
    `Buy ${speciesKey} at a local nursery`;

  const PRODUCT_LABEL = { plants: '🪴 Potted plants', seeds: '🌱 Seeds' };
  const FULFILLMENT_LABEL = { walkin: '🚶 Walk-in', pickup: '📦 Pickup', online: '🛒 Online order' };

  document.getElementById('nursery-modal-list').innerHTML = nurseryIds.map(id => {
    const n = state.nurseries[id];
    if (!n) return '';
    const tags = [
      PRODUCT_LABEL[n.productType],
      FULFILLMENT_LABEL[n.fulfillment],
    ].filter(Boolean).map(t => `<span class="nursery-tag">${t}</span>`).join('');
    return `<div class="nursery-card">
      <div class="nursery-card-name">${esc(n.name)}</div>
      ${tags ? `<div class="nursery-card-tags">${tags}</div>` : ''}
      <div class="nursery-card-address">${esc(n.address)}</div>
      ${n.phone ? `<div class="nursery-card-phone">${esc(n.phone)}</div>` : ''}
      <a href="${esc(n.website)}" target="_blank" rel="noopener" class="nursery-card-link">Visit website →</a>
      <a href="https://www.openstreetmap.org/directions?to=${n.lat},${n.lng}" target="_blank" rel="noopener" class="nursery-card-link">Get directions →</a>
    </div>`;
  }).join('');

  document.getElementById('nursery-modal').classList.remove('hidden');

  setTimeout(() => {
    if (!_nurseryMap) {
      _nurseryMap = L.map('nursery-modal-map').setView([37.85, -122.3], 11);
      L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
        subdomains: 'abcd', maxZoom: 20,
      }).addTo(_nurseryMap);
    }
    _nurseryMap.invalidateSize();

    _nurseryMap.eachLayer(l => { if (l instanceof L.Marker) _nurseryMap.removeLayer(l); });

    const markers = nurseryIds.map(id => state.nurseries[id]).filter(n => n?.lat && n?.lng).map(n => {
      const m = L.marker([n.lat, n.lng]).addTo(_nurseryMap);
      m.bindPopup(`<strong>${n.name}</strong><br>${n.address}`).openPopup();
      return m;
    });

    if (markers.length === 1) {
      const n = state.nurseries[nurseryIds[0]];
      _nurseryMap.setView([n.lat, n.lng], 14);
    } else if (markers.length > 1) {
      _nurseryMap.fitBounds(L.featureGroup(markers).getBounds().pad(0.3));
    }
  }, 50);
}

function closeNurseryModal() {
  document.getElementById('nursery-modal').classList.add('hidden');
}

// ─────────────────────────────────────────────────────────────────────────────
// Init
// ─────────────────────────────────────────────────────────────────────────────

async function init() {
  initMap();
  try {
    await Promise.all([loadParks(), loadSFNatives(), loadSummary()]);
  } catch (e) {
    showOverlay(`Failed to load parks: ${e.message}`);
    return;
  }

  const visibleParks = state.parks.filter(f => (state.detailCache[pid(f)]?.sf_native_cats?.Plantae ?? 0) > 0);
  addParksToMap(visibleParks);
  hideOverlay();
  const n = visibleParks.length;
  document.getElementById('stat-parks').textContent = n;
  document.getElementById('stat-ranked').textContent = n;

  loadNurseries();
  loadHistograms();
  loadSpeciesIndex().then(initSearch);

  document.getElementById('sidebar-close').addEventListener('click', closeSidebar);
  document.getElementById('natives-btn').addEventListener('click', toggleNativeMode);

  document.getElementById('nursery-modal-close').addEventListener('click', closeNurseryModal);
  document.getElementById('nursery-modal-backdrop').addEventListener('click', closeNurseryModal);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeNurseryModal(); });

  document.addEventListener('click', e => {
    const badge = e.target.closest('.badge-nursery');
    if (badge) { e.stopPropagation(); openNurseryModal(badge.dataset.species); }
  });

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

// ─────────────────────────────────────────────────────────────────────────────
// Species search
// ─────────────────────────────────────────────────────────────────────────────

async function loadSpeciesIndex() {
  try {
    state.speciesIndex = await loadJSON(`${DATA_ROOT}/species_index.json`);
  } catch (e) {
    console.warn('Species index not available:', e.message);
  }
}

function fuzzyScore(query, sp) {
  const q  = query.toLowerCase();
  const sc = (sp.name   || '').toLowerCase();
  const cm = (sp.common || '').toLowerCase();
  let score = 0;
  if (sc.startsWith(q))   score = Math.max(score, 100);
  else if (cm.startsWith(q))   score = Math.max(score, 95);
  else if (sc.includes(q))     score = Math.max(score, 70);
  else if (cm.includes(q))     score = Math.max(score, 65);
  else {
    // character-sequence fuzzy match
    const fuzzy = (str) => {
      let qi = 0;
      for (let i = 0; i < str.length && qi < q.length; i++)
        if (str[i] === q[qi]) qi++;
      return qi === q.length;
    };
    if (fuzzy(sc)) score = Math.max(score, 30);
    if (fuzzy(cm)) score = Math.max(score, 25);
  }
  return score;
}

function searchSpecies(query) {
  if (query.length < 2) return [];
  const results = [];
  for (const sp of state.speciesIndex) {
    const s = fuzzyScore(query, sp);
    if (s > 0) results.push({ sp, s });
  }
  results.sort((a, b) => b.s - a.s);
  return results.slice(0, 8).map(r => r.sp);
}

function applySpeciesFilter(sp) {
  state.speciesFilter = new Set(sp.parks);
  resetStyles();
  // fit map to highlighted parks
  const layers = [];
  parksLayer?.eachLayer(l => { if (state.speciesFilter.has(pid(l.feature))) layers.push(l); });
  if (layers.length) {
    const group = L.featureGroup(layers);
    map.fitBounds(group.getBounds(), { padding: [40, 40], maxZoom: 14 });
  }
}

function clearSpeciesFilter() {
  state.speciesFilter = null;
  resetStyles();
}

let _dropdownActive = -1;

function initSearch() {
  const input    = document.getElementById('species-search');
  const dropdown = document.getElementById('species-dropdown');
  const clearBtn = document.getElementById('species-search-clear');

  function showDropdown(results) {
    if (!results.length) { dropdown.classList.add('hidden'); return; }
    const CAT_ICON = { Plantae:'🌿', Aves:'🐦', Insecta:'🦋', Mammalia:'🦊',
                       Fungi:'🍄', Reptilia:'🦎', Amphibia:'🐸', Arachnida:'🕷️', Mollusca:'🐌' };
    dropdown.innerHTML = results.map((sp, i) => `
      <div class="sp-result" data-idx="${i}" tabindex="-1">
        ${sp.photo
          ? `<img class="sp-result-photo" src="${esc(sp.photo)}" alt="" loading="lazy">`
          : `<div class="sp-result-photo sp-result-no-photo">${CAT_ICON[sp.iconic] ?? '🔬'}</div>`}
        <div class="sp-result-names">
          <div class="sp-result-common">${esc(sp.common || sp.name)}</div>
          ${sp.common ? `<div class="sp-result-sci">${esc(sp.name)}</div>` : ''}
        </div>
        <div class="sp-result-count">${sp.parks.length} park${sp.parks.length !== 1 ? 's' : ''}</div>
      </div>`).join('');
    _dropdownActive = -1;
    dropdown.classList.remove('hidden');

    dropdown.querySelectorAll('.sp-result').forEach((el, i) => {
      el.addEventListener('mousedown', e => {
        e.preventDefault();
        selectResult(results[i]);
      });
    });
  }

  function selectResult(sp) {
    input.value = sp.common || sp.name;
    dropdown.classList.add('hidden');
    clearBtn.classList.remove('hidden');
    applySpeciesFilter(sp);
  }

  function hideDropdown() { dropdown.classList.add('hidden'); _dropdownActive = -1; }

  input.addEventListener('input', () => {
    const q = input.value.trim();
    if (!q) { clearSpeciesFilter(); clearBtn.classList.add('hidden'); hideDropdown(); return; }
    showDropdown(searchSpecies(q));
  });

  input.addEventListener('keydown', e => {
    const items = dropdown.querySelectorAll('.sp-result');
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      _dropdownActive = Math.min(_dropdownActive + 1, items.length - 1);
      items.forEach((el, i) => el.classList.toggle('active', i === _dropdownActive));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      _dropdownActive = Math.max(_dropdownActive - 1, -1);
      items.forEach((el, i) => el.classList.toggle('active', i === _dropdownActive));
    } else if (e.key === 'Enter' && _dropdownActive >= 0) {
      e.preventDefault();
      items[_dropdownActive].dispatchEvent(new MouseEvent('mousedown'));
    } else if (e.key === 'Escape') {
      hideDropdown();
    }
  });

  input.addEventListener('blur', () => setTimeout(hideDropdown, 150));

  clearBtn.addEventListener('click', () => {
    input.value = '';
    clearBtn.classList.add('hidden');
    clearSpeciesFilter();
    hideDropdown();
  });
}

document.addEventListener('DOMContentLoaded', init);
