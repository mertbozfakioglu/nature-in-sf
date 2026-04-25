#!/usr/bin/env node
'use strict';
/**
 * Unit tests for sf-parks-biodiversity pure data logic.
 * Run with: node test.js
 */
const assert = require('assert');

// ─── replicate pure functions (mirrored from app.js) ─────────────────────────

const CATEGORIES = [
  { key: 'Plantae' }, { key: 'Aves' },     { key: 'Insecta' },
  { key: 'Mammalia'},{ key: 'Fungi' },     { key: 'Reptilia' },
  { key: 'Amphibia'},{ key: 'Arachnida' },{ key: 'Mollusca' },
];

// Small mock SF natives set for testing
const MOCK_SF_NATIVES = new Set(['Quercus agrifolia', 'Eschscholzia californica']);

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

function isNativeForMode(s, mode, sfNatives) {
  if (isIntroduced(s)) return false;
  if (mode === 'sf' && s.taxon?.iconic_taxon_name === 'Plantae') {
    const sp = (s.taxon.name || '').split(' ').slice(0, 2).join(' ');
    return sfNatives.has(sp);
  }
  return true;
}

function nativeCatsFromSpecies(species, mode = 'ca', sfNatives = new Set()) {
  const out = {};
  CATEGORIES.forEach(c => { out[c.key] = 0; });
  for (const s of (species || [])) {
    if (!isSpeciesLevel(s)) continue;
    const k = s.taxon?.iconic_taxon_name;
    if (k in out && isNativeForMode(s, mode, sfNatives)) out[k]++;
  }
  return out;
}

function buildSortVal(d, col, mode) {
  const cats  = mode === 'sf' ? d.sf_native_cats
              : mode === 'ca' ? d.native_cats
              : d.cats;
  const count = mode === 'sf' ? (d.sfNativeCount  ?? 0)
              : mode === 'ca' ? (d.nativeCount     ?? 0)
              : (d.total ?? 0);
  return col === 'total' ? count : (cats?.[col] ?? 0);
}

/** Simulate loadSummary populating detailCache from summary.json data */
function summaryToCache(summaryEntry) {
  return {
    species:        null,
    cats:           summaryEntry.cats            || {},
    native_cats:    summaryEntry.native_cats     || {},
    sf_native_cats: summaryEntry.sf_native_cats  || {},
    nativeCount:    summaryEntry.nativeCount     || 0,
    sfNativeCount:  summaryEntry.sfNativeCount   || 0,
    introducedCount:summaryEntry.introducedCount || 0,
    total:          summaryEntry.total           || 0,
  };
}

/** Simulate loadParkDetail populating detailCache from species/{id}.json */
function speciesFileToCache(fileData, sfNatives = new Set()) {
  const species = fileData.species || [];
  return {
    species,
    cats:           fileData.summary?.cats        || {},
    native_cats:    nativeCatsFromSpecies(species, 'ca', sfNatives),
    sf_native_cats: nativeCatsFromSpecies(species, 'sf', sfNatives),
    nativeCount:    species.filter(s => isSpeciesLevel(s) && isNativeForMode(s, 'ca', sfNatives)).length,
    sfNativeCount:  species.filter(s => isSpeciesLevel(s) && isNativeForMode(s, 'sf', sfNatives)).length,
    introducedCount:fileData.summary?.introducedCount|| 0,
    total:          species.filter(isSpeciesLevel).length,
  };
}

// ─── mock data ────────────────────────────────────────────────────────────────

const MOCK_SPECIES = [
  { count: 5, taxon: { iconic_taxon_name: 'Plantae',  name: 'Quercus agrifolia', establishment_means: { establishment_means: 'native' } } },
  { count: 3, taxon: { iconic_taxon_name: 'Plantae',  name: 'English Ivy',       establishment_means: { establishment_means: 'introduced' } } },
  { count: 2, taxon: { iconic_taxon_name: 'Aves',     name: 'Turdus migratorius',establishment_means: { establishment_means: 'native' } } },
  { count: 1, taxon: { iconic_taxon_name: 'Aves',     name: 'Columba livia',     establishment_means: { establishment_means: 'introduced' } } },
  { count: 4, taxon: { iconic_taxon_name: 'Insecta',  name: 'Vanessa cardui',    establishment_means: null } },
  { count: 1, taxon: { iconic_taxon_name: 'Mammalia', name: 'Urocyon cinereoargenteus', establishment_means: { establishment_means: 'endemic' } } },
  { count: 2, taxon: { iconic_taxon_name: 'Plantae',  name: 'Quercus',           establishment_means: null } }, // genus-level, should be excluded
];

// With CA mode (not introduced):
//   Plantae: Quercus agrifolia (native) = 1  [English Ivy excluded, Quercus genus excluded]
//   Aves:    Turdus migratorius (native) = 1  [Columba livia excluded]
//   Insecta: Vanessa cardui (null = not introduced) = 1
//   Mammalia: Urocyon cinereoargenteus (endemic) = 1
// With SF mode (plants must be in MOCK_SF_NATIVES):
//   Plantae: Quercus agrifolia (in set) = 1
//   Aves/Insecta/Mammalia: same as CA mode

const MOCK_SUMMARY_ENTRY = {
  total: 6,  // 7 records minus 1 genus-level
  cats:           { Plantae:2, Aves:2, Insecta:1, Mammalia:1, Fungi:0, Reptilia:0, Amphibia:0, Arachnida:0, Mollusca:0 },
  native_cats:    { Plantae:1, Aves:1, Insecta:1, Mammalia:1, Fungi:0, Reptilia:0, Amphibia:0, Arachnida:0, Mollusca:0 },
  sf_native_cats: { Plantae:1, Aves:1, Insecta:1, Mammalia:1, Fungi:0, Reptilia:0, Amphibia:0, Arachnida:0, Mollusca:0 },
  nativeCount: 4,
  sfNativeCount: 4,
  introducedCount: 2,
  name: 'Test Park',
};

const MOCK_SPECIES_FILE = { summary: MOCK_SUMMARY_ENTRY, species: MOCK_SPECIES };

// ─── test runner ──────────────────────────────────────────────────────────────

let passed = 0, failed = 0;

function group(name) { console.log(`\n${name}`); }

function test(name, fn) {
  try {
    fn();
    console.log(`  ✓ ${name}`);
    passed++;
  } catch (e) {
    console.error(`  ✗ ${name}`);
    console.error(`    ${e.message}`);
    failed++;
  }
}

// ─── tests ────────────────────────────────────────────────────────────────────

group('isSpeciesLevel');

test('accepts genus + species', () => {
  assert.ok(isSpeciesLevel({ taxon: { name: 'Quercus agrifolia' } }));
});
test('accepts genus + species + subspecies', () => {
  assert.ok(isSpeciesLevel({ taxon: { name: 'Quercus agrifolia var. agrifolia' } }));
});
test('rejects genus-only', () => {
  assert.ok(!isSpeciesLevel({ taxon: { name: 'Quercus' } }));
});
test('rejects empty name', () => {
  assert.ok(!isSpeciesLevel({ taxon: { name: '' } }));
});

group('nativeCatsFromSpecies — CA mode');

test('counts non-introduced plants', () => {
  assert.equal(nativeCatsFromSpecies(MOCK_SPECIES, 'ca').Plantae, 1);
});
test('treats endemic as native', () => {
  assert.equal(nativeCatsFromSpecies(MOCK_SPECIES, 'ca').Mammalia, 1);
});
test('excludes introduced species', () => {
  assert.equal(nativeCatsFromSpecies(MOCK_SPECIES, 'ca').Aves, 1); // pigeon excluded
});
test('counts species with null establishment_means as not-introduced', () => {
  assert.equal(nativeCatsFromSpecies(MOCK_SPECIES, 'ca').Insecta, 1);
});
test('excludes genus-level observations', () => {
  // Quercus (genus only) must not count even though it is not introduced
  const r = nativeCatsFromSpecies(MOCK_SPECIES, 'ca');
  assert.equal(r.Plantae, 1); // only Quercus agrifolia, not bare Quercus
});
test('returns 0 for all categories on empty input', () => {
  const r = nativeCatsFromSpecies([], 'ca');
  CATEGORIES.forEach(c => assert.equal(r[c.key], 0, `expected 0 for ${c.key}`));
});
test('handles null input gracefully', () => {
  const r = nativeCatsFromSpecies(null, 'ca');
  CATEGORIES.forEach(c => assert.equal(r[c.key], 0, `expected 0 for ${c.key}`));
});
test('all category keys present', () => {
  const r = nativeCatsFromSpecies(MOCK_SPECIES, 'ca');
  CATEGORIES.forEach(c => assert.ok(c.key in r, `missing ${c.key}`));
});

group('nativeCatsFromSpecies — SF mode');

test('SF mode: counts plant only if in sfNatives set', () => {
  assert.equal(nativeCatsFromSpecies(MOCK_SPECIES, 'sf', MOCK_SF_NATIVES).Plantae, 1);
});
test('SF mode: plant not in sfNatives returns 0', () => {
  // Remove Quercus agrifolia from set
  const smallSet = new Set(['Eschscholzia californica']);
  assert.equal(nativeCatsFromSpecies(MOCK_SPECIES, 'sf', smallSet).Plantae, 0);
});
test('SF mode: non-plant taxa still use CA native logic', () => {
  assert.equal(nativeCatsFromSpecies(MOCK_SPECIES, 'sf', MOCK_SF_NATIVES).Aves, 1);
  assert.equal(nativeCatsFromSpecies(MOCK_SPECIES, 'sf', MOCK_SF_NATIVES).Insecta, 1);
});
test('SF mode: subspecies name matches species-level key', () => {
  const subspecies = [{ count: 1, taxon: {
    iconic_taxon_name: 'Plantae', name: 'Quercus agrifolia var. agrifolia',
    establishment_means: { establishment_means: 'native' },
  }}];
  assert.equal(nativeCatsFromSpecies(subspecies, 'sf', MOCK_SF_NATIVES).Plantae, 1);
});

group('buildSortVal');

test('mode=all, total column → returns total', () => {
  assert.equal(buildSortVal(MOCK_SUMMARY_ENTRY, 'total', 'all'), 6);
});
test('mode=ca, total column → returns nativeCount', () => {
  assert.equal(buildSortVal(MOCK_SUMMARY_ENTRY, 'total', 'ca'), 4);
});
test('mode=sf, total column → returns sfNativeCount', () => {
  assert.equal(buildSortVal(MOCK_SUMMARY_ENTRY, 'total', 'sf'), 4);
});
test('mode=all, category column → returns cats[col]', () => {
  assert.equal(buildSortVal(MOCK_SUMMARY_ENTRY, 'Plantae', 'all'), 2);
});
test('mode=ca, category column → returns native_cats[col]', () => {
  assert.equal(buildSortVal(MOCK_SUMMARY_ENTRY, 'Plantae', 'ca'), 1);
});
test('mode=sf, category column → returns sf_native_cats[col]', () => {
  assert.equal(buildSortVal(MOCK_SUMMARY_ENTRY, 'Plantae', 'sf'), 1);
});
test('returns 0 when native_cats missing', () => {
  const d = { ...MOCK_SUMMARY_ENTRY, native_cats: undefined };
  assert.equal(buildSortVal(d, 'Plantae', 'ca'), 0);
});
test('returns 0 when sf_native_cats missing', () => {
  const d = { ...MOCK_SUMMARY_ENTRY, sf_native_cats: undefined };
  assert.equal(buildSortVal(d, 'Plantae', 'sf'), 0);
});

group('summaryToCache');

test('copies cats from summary', () => {
  const c = summaryToCache(MOCK_SUMMARY_ENTRY);
  assert.deepStrictEqual(c.cats, MOCK_SUMMARY_ENTRY.cats);
});
test('copies native_cats from summary', () => {
  const c = summaryToCache(MOCK_SUMMARY_ENTRY);
  assert.deepStrictEqual(c.native_cats, MOCK_SUMMARY_ENTRY.native_cats);
});
test('copies sf_native_cats from summary', () => {
  const c = summaryToCache(MOCK_SUMMARY_ENTRY);
  assert.deepStrictEqual(c.sf_native_cats, MOCK_SUMMARY_ENTRY.sf_native_cats);
});
test('copies sfNativeCount from summary', () => {
  const c = summaryToCache(MOCK_SUMMARY_ENTRY);
  assert.equal(c.sfNativeCount, 4);
});
test('sf_native_cats defaults to {} when absent', () => {
  const c = summaryToCache({ total: 5, cats: {}, nativeCount: 2 });
  assert.deepStrictEqual(c.sf_native_cats, {});
});
test('species is null (not yet loaded)', () => {
  assert.equal(summaryToCache(MOCK_SUMMARY_ENTRY).species, null);
});

group('speciesFileToCache');

test('species array populated', () => {
  const c = speciesFileToCache(MOCK_SPECIES_FILE, MOCK_SF_NATIVES);
  assert.equal(c.species.length, MOCK_SPECIES.length);
});
test('total excludes genus-level observations', () => {
  const c = speciesFileToCache(MOCK_SPECIES_FILE, MOCK_SF_NATIVES);
  assert.equal(c.total, 6); // 7 records - 1 genus-level
});
test('native_cats.Plantae correct in CA mode', () => {
  const c = speciesFileToCache(MOCK_SPECIES_FILE, MOCK_SF_NATIVES);
  assert.equal(c.native_cats.Plantae, 1);
});
test('sf_native_cats.Plantae correct with sfNatives', () => {
  const c = speciesFileToCache(MOCK_SPECIES_FILE, MOCK_SF_NATIVES);
  assert.equal(c.sf_native_cats.Plantae, 1);
});
test('sf_native_cats.Plantae = 0 when plant not in sfNatives', () => {
  const c = speciesFileToCache(MOCK_SPECIES_FILE, new Set());
  assert.equal(c.sf_native_cats.Plantae, 0);
});
test('sf_native_cats has all expected keys', () => {
  const c = speciesFileToCache(MOCK_SPECIES_FILE, MOCK_SF_NATIVES);
  CATEGORIES.forEach(cat => assert.ok(cat.key in c.sf_native_cats, `missing ${cat.key}`));
});

group('regression: genus-level observations excluded everywhere');

test('genus-only plant does not appear in total', () => {
  const c = speciesFileToCache(MOCK_SPECIES_FILE, MOCK_SF_NATIVES);
  assert.equal(c.total, 6);
});
test('genus-only plant does not appear in native_cats', () => {
  const genusOnly = [{ count: 1, taxon: { iconic_taxon_name: 'Plantae', name: 'Quercus', establishment_means: null } }];
  const r = nativeCatsFromSpecies(genusOnly, 'ca');
  assert.equal(r.Plantae, 0);
});

// ─── summary ──────────────────────────────────────────────────────────────────

console.log(`\n${'─'.repeat(50)}`);
console.log(`${passed + failed} tests: ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
