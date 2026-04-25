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

function em_from(s) {
  return s.taxon?.establishment_means?.establishment_means || null;
}

function nativeCatsFromSpecies(species) {
  const out = {};
  CATEGORIES.forEach(c => { out[c.key] = 0; });
  for (const s of (species || [])) {
    const k  = s.taxon?.iconic_taxon_name;
    const em = em_from(s);
    if (k in out && (em === 'native' || em === 'endemic')) out[k]++;
  }
  return out;
}

function buildSortVal(d, col, natv) {
  return col === 'total'
    ? (natv ? (d.nativeCount        ?? 0) : (d.total       ?? 0))
    : (natv ? (d.native_cats?.[col] ?? 0) : (d.cats?.[col] ?? 0));
}

/** Simulate loadSummary populating detailCache from summary.json data */
function summaryToCache(summaryEntry) {
  return {
    species:        null,
    cats:           summaryEntry.cats        || {},
    native_cats:    summaryEntry.native_cats || {},
    nativeCount:    summaryEntry.nativeCount    || 0,
    introducedCount:summaryEntry.introducedCount|| 0,
    total:          summaryEntry.total          || 0,
  };
}

/** Simulate loadParkDetail populating detailCache from species/{id}.json */
function speciesFileToCache(fileData) {
  const species = fileData.species || [];
  return {
    species,
    cats:           fileData.summary?.cats        || {},
    native_cats:    nativeCatsFromSpecies(species),
    nativeCount:    fileData.summary?.nativeCount    || 0,
    introducedCount:fileData.summary?.introducedCount|| 0,
    total:          fileData.summary?.total          || 0,
  };
}

// ─── mock data ────────────────────────────────────────────────────────────────

const MOCK_SPECIES = [
  { count: 5, taxon: { iconic_taxon_name: 'Plantae',  name: 'Coast Live Oak', establishment_means: { establishment_means: 'native' } } },
  { count: 3, taxon: { iconic_taxon_name: 'Plantae',  name: 'English Ivy',    establishment_means: { establishment_means: 'introduced' } } },
  { count: 2, taxon: { iconic_taxon_name: 'Aves',     name: 'American Robin', establishment_means: { establishment_means: 'native' } } },
  { count: 1, taxon: { iconic_taxon_name: 'Aves',     name: 'Rock Pigeon',    establishment_means: { establishment_means: 'introduced' } } },
  { count: 4, taxon: { iconic_taxon_name: 'Insecta',  name: 'Painted Lady',   establishment_means: null } },
  { count: 1, taxon: { iconic_taxon_name: 'Mammalia', name: 'Gray Fox',       establishment_means: { establishment_means: 'endemic' } } },
];

// Expected native counts from MOCK_SPECIES:
// Plantae:1 (oak native), Aves:1 (robin native), Insecta:0 (no em), Mammalia:1 (fox endemic)

const MOCK_SUMMARY_ENTRY = {
  total: 6,
  cats:        { Plantae:2, Aves:2, Insecta:1, Mammalia:1, Fungi:0, Reptilia:0, Amphibia:0, Arachnida:0, Mollusca:0 },
  native_cats: { Plantae:1, Aves:1, Insecta:0, Mammalia:1, Fungi:0, Reptilia:0, Amphibia:0, Arachnida:0, Mollusca:0 },
  nativeCount: 3,
  introducedCount: 2,
  name: 'Test Park',
};

const MOCK_SPECIES_FILE = { summary: MOCK_SUMMARY_ENTRY, species: MOCK_SPECIES };

// ─── test runner ──────────────────────────────────────────────────────────────

let passed = 0, failed = 0;
let currentGroup = '';

function group(name) {
  currentGroup = name;
  console.log(`\n${name}`);
}

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

group('nativeCatsFromSpecies');

test('counts native plants correctly', () => {
  assert.equal(nativeCatsFromSpecies(MOCK_SPECIES).Plantae, 1);
});
test('treats endemic as native (mammals)', () => {
  assert.equal(nativeCatsFromSpecies(MOCK_SPECIES).Mammalia, 1);
});
test('does not count introduced species', () => {
  // 2 plants total but only 1 native
  assert.equal(nativeCatsFromSpecies(MOCK_SPECIES).Plantae, 1);
});
test('returns 0 for species with no establishment_means', () => {
  assert.equal(nativeCatsFromSpecies(MOCK_SPECIES).Insecta, 0);
});
test('returns 0 for all categories on empty input', () => {
  const r = nativeCatsFromSpecies([]);
  CATEGORIES.forEach(c => assert.equal(r[c.key], 0, `expected 0 for ${c.key}`));
});
test('handles null input gracefully', () => {
  const r = nativeCatsFromSpecies(null);
  CATEGORIES.forEach(c => assert.equal(r[c.key], 0, `expected 0 for ${c.key}`));
});
test('all category keys are present in output', () => {
  const r = nativeCatsFromSpecies(MOCK_SPECIES);
  CATEGORIES.forEach(c => assert.ok(c.key in r, `missing key ${c.key}`));
});

group('buildSortVal');

test('total column, natives off → returns total', () => {
  assert.equal(buildSortVal(MOCK_SUMMARY_ENTRY, 'total', false), 6);
});
test('total column, natives on → returns nativeCount', () => {
  assert.equal(buildSortVal(MOCK_SUMMARY_ENTRY, 'total', true), 3);
});
test('category column, natives off → returns cats[col]', () => {
  assert.equal(buildSortVal(MOCK_SUMMARY_ENTRY, 'Plantae', false), 2);
});
test('category column, natives on → returns native_cats[col]', () => {
  assert.equal(buildSortVal(MOCK_SUMMARY_ENTRY, 'Plantae', true), 1);
});
test('category column, natives on, Aves → returns native_cats.Aves', () => {
  assert.equal(buildSortVal(MOCK_SUMMARY_ENTRY, 'Aves', true), 1);
});
test('category column, natives on, Insecta (0 natives) → returns 0 not undefined', () => {
  assert.equal(buildSortVal(MOCK_SUMMARY_ENTRY, 'Insecta', true), 0);
});
test('returns 0 (not NaN/undefined) when native_cats is missing', () => {
  const d = { ...MOCK_SUMMARY_ENTRY, native_cats: undefined };
  assert.equal(buildSortVal(d, 'Plantae', true), 0);
});
test('returns 0 (not NaN/undefined) when cats is missing', () => {
  const d = { ...MOCK_SUMMARY_ENTRY, cats: undefined };
  assert.equal(buildSortVal(d, 'Plantae', false), 0);
});

group('summaryToCache (loadSummary mapping)');

test('copies cats from summary', () => {
  const c = summaryToCache(MOCK_SUMMARY_ENTRY);
  assert.deepStrictEqual(c.cats, MOCK_SUMMARY_ENTRY.cats);
});
test('copies native_cats from summary', () => {
  const c = summaryToCache(MOCK_SUMMARY_ENTRY);
  assert.deepStrictEqual(c.native_cats, MOCK_SUMMARY_ENTRY.native_cats);
});
test('native_cats.Plantae matches expected value', () => {
  const c = summaryToCache(MOCK_SUMMARY_ENTRY);
  assert.equal(c.native_cats.Plantae, 1);
});
test('native_cats defaults to {} when field is absent', () => {
  const c = summaryToCache({ total: 5, cats: {}, nativeCount: 2 });
  assert.deepStrictEqual(c.native_cats, {});
});
test('species is null (not yet loaded)', () => {
  const c = summaryToCache(MOCK_SUMMARY_ENTRY);
  assert.equal(c.species, null);
});

group('speciesFileToCache (loadParkDetail mapping)');

test('species array is populated', () => {
  const c = speciesFileToCache(MOCK_SPECIES_FILE);
  assert.equal(c.species.length, MOCK_SPECIES.length);
});
test('native_cats is computed — not missing', () => {
  const c = speciesFileToCache(MOCK_SPECIES_FILE);
  assert.ok(c.native_cats, 'native_cats should be defined');
});
test('native_cats has correct Plantae count', () => {
  const c = speciesFileToCache(MOCK_SPECIES_FILE);
  assert.equal(c.native_cats.Plantae, 1);
});
test('native_cats has correct Aves count', () => {
  const c = speciesFileToCache(MOCK_SPECIES_FILE);
  assert.equal(c.native_cats.Aves, 1);
});
test('native_cats has all expected keys', () => {
  const c = speciesFileToCache(MOCK_SPECIES_FILE);
  CATEGORIES.forEach(cat => assert.ok(cat.key in c.native_cats, `missing ${cat.key}`));
});

group('regression: clicking a park does not lose native_cats');

test('after loadParkDetail, native_cats is present', () => {
  const c = speciesFileToCache(MOCK_SPECIES_FILE);
  assert.ok(c.native_cats !== undefined, 'native_cats must not be undefined');
});
test('after loadParkDetail, native_cats is not empty object', () => {
  const c = speciesFileToCache(MOCK_SPECIES_FILE);
  const hasNonZero = Object.values(c.native_cats).some(v => v > 0);
  assert.ok(hasNonZero, 'expected at least one non-zero native category');
});
test('rankings row shows native count not dash after park click', () => {
  const c = speciesFileToCache(MOCK_SPECIES_FILE);
  const val = buildSortVal(c, 'Plantae', true);
  assert.ok(val !== undefined && val !== null, 'must not be undefined/null');
  assert.notEqual(val, '–', 'must not produce a dash');
});

// ─── summary ──────────────────────────────────────────────────────────────────

console.log(`\n${'─'.repeat(50)}`);
console.log(`${passed + failed} tests: ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
