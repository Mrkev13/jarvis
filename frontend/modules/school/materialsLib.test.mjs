import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  ZIP_IMPORT_PATH, activeFilterCount, fileState, formatSize, importErrorMessage, importSummary, isZipFile, materialMeta,
  materialsPath, parseFilters, syncSummary, uploadMoodleZip,
} from './materialsLib.ts';
import { createModuleAccess, manifestFlags } from '../../lib/modules.ts';

const base = {
  id: 1, title: 'Lecture 1', file_name: 'lecture.pdf', material_type: 'pdf', size_bytes: 2_500_000, section_name: 'Week 1',
  source_modified_at: '2026-10-09T08:00:00', created_at: '2026-10-09T08:00:00', updated_at: '2026-10-09T08:00:00',
  source_missing_at: null, state: 'active', download_status: 'stored', has_file: true, extraction_status: 'ok',
  course: { id: 3, name: 'Biology I' }, subject: null,
};

test('filters from URL drop invalid values and build only allowlisted API params', () => {
  const params = new URLSearchParams('subject=4&type=exe&state=missing&course=-1');
  const filters = parseFilters(params);
  assert.deepEqual(filters, { subject: '4', course: '', type: '', state: 'missing' });
  assert.equal(materialsPath(filters), '/school/materials?subject_id=4&state=missing');
  assert.equal(materialsPath(parseFilters(new URLSearchParams(''))), '/school/materials');
  assert.equal(materialsPath(parseFilters(new URLSearchParams('type=pptx&course=7'))), '/school/materials?course_id=7&type=pptx');
  assert.equal(activeFilterCount(filters), 2);
});

test('missing and metadata-only states are visible, never presented as downloadable', () => {
  assert.deepEqual(fileState(base), { label: 'Uloženo', tone: 'info' });
  assert.equal(fileState({ ...base, state: 'source_missing', source_missing_at: '2026-10-10T08:00:00' }).label, 'Zmizelo z Moodlu');
  assert.equal(fileState({ ...base, has_file: false, download_status: 'too_large' }).label, 'Příliš velký');
  assert.equal(fileState({ ...base, has_file: false, download_status: 'failed' }).tone, 'warning');
});

test('meta shows subject before course, size and Prague date', () => {
  assert.match(materialMeta(base), /^Biology I · Week 1 · 2,4 MB · změněno 9\. 10\. 2026$/);
  assert.match(materialMeta({ ...base, subject: { id: 4, name: 'Biologie' } }), /^Biologie/);
  assert.equal(formatSize(null), null);
  assert.equal(formatSize(512), '512 B');
  assert.match(syncSummary({ created: 2, updated: 1, courses_failed: 1 }), /1 kurzů se nepodařilo načíst/);
});

test('materials live under the School module gate', () => {
  const on = createModuleAccess(manifestFlags());
  const off = createModuleAccess({ ...manifestFlags(), school: false });
  assert.equal(on.allowsPath('/school/materials'), true);
  assert.equal(off.allowsPath('/school/materials'), false);
  assert.equal(off.allowsEntity('study_material', 'search'), false);
  assert.equal(on.allowsEntity('study_material', 'search'), true);
});

// ---------- MRK-44: cílené čtení ----------
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';
import * as lib from './materialsLib.ts';

const content = (over = {}) => ({
  material: { id: 7, title: 'Algoritmy', state: 'active' }, text_status: 'available', text_message: 'Text je k dispozici.',
  extraction_truncated: false, query: null, query_terms: [], total_chunks: 5, matched_chunks: 0, returned_chars: 60,
  truncated: true, chunks: [{ index: 0, text: 'Algoritmy a datové struktury', location: { kind: 'slide', from: 1, to: 1 } }],
  outline: [{ kind: 'slide', number: 1, label: 'Algoritmy a datové struktury' }], ...over,
});

function renderReader(resource, props = { materialId: 7 }) {
  const require = createRequire(import.meta.url);
  const calls = [];
  const ui = {
    Button: ({ children, type }) => React.createElement('button', { type }, children),
    EmptyState: ({ children }) => React.createElement('p', { 'data-empty': true }, children),
    ErrorState: ({ message }) => React.createElement('p', { 'data-error': true }, message),
    LoadingState: () => React.createElement('p', { 'data-loading': true }),
    StatusBadge: ({ children }) => React.createElement('span', { 'data-badge': true }, children),
    fieldClass: 'field',
  };
  const hooks = { useApiResource: (path) => { calls.push(path); return { reload: async () => {}, ...resource }; } };
  const compiled = ts.transpileModule(readFileSync(new URL('./MaterialReader.tsx', import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', compiled)(name => name === '@/components/ui' ? ui
    : name === '@/hooks/useApiResource' ? hooks : name === './materialsLib' ? lib : require(name), mod, mod.exports);
  return { html: renderToStaticMarkup(React.createElement(mod.exports.MaterialReader, props)), calls };
}

test('content path accepts only positive ids and caps the query', () => {
  assert.equal(lib.contentPath(7), '/school/materials/7/content');
  assert.equal(lib.contentPath('7', ' rekurze '), '/school/materials/7/content?q=rekurze');
  assert.equal(lib.contentPath('../etc', 'x'), null);
  assert.equal(lib.contentPath(0), null);
  assert.equal(new URL(lib.contentPath(7, 'x'.repeat(500)), 'http://t').searchParams.get('q').length, 200);
});

test('location labels and summaries are explicit', () => {
  assert.equal(lib.locationLabel({ kind: 'slide', from: 3, to: 3 }), 'Snímek 3');
  assert.equal(lib.locationLabel({ kind: 'page', from: 2, to: 4 }), 'Strana 2–4');
  assert.equal(lib.locationLabel(null), null);
  assert.match(lib.contentSummary(content()), /Začátek materiálu \(1 z 5/);
  assert.match(lib.contentSummary(content({ query: 'grafy', matched_chunks: 0, chunks: [] })), /„grafy“ se v materiálu nenašlo/);
  assert.match(lib.contentSummary(content({ query: 'rekurze', matched_chunks: 2 })), /Nalezeno 2 místa/);
  assert.equal(lib.contentSummary(content({ text_status: 'empty', text_message: 'Bez textové vrstvy.' })), 'Bez textové vrstvy.');
  assert.equal(lib.textStatusLabel('empty', true), 'bez textové vrstvy (sken)');
  assert.equal(lib.textStatusLabel(null, false), 'není k dispozici (soubor neuložen)');
});

test('reader renders a bounded preview with slide location and outline', () => {
  const { html, calls } = renderReader({ data: content(), loading: false, error: null });
  assert.deepEqual(calls, ['/school/materials/7/content']);
  assert.match(html, /Snímek 1/); assert.match(html, /Algoritmy a datové struktury/); assert.match(html, /Obsah \(1\)/);
  assert.match(html, /Najít v materiálu/);
  assert.doesNotMatch(html, /pluginfile|token|study-materials/);
});

test('reader uses the deep-link query and shows matches or an explicit no-match state', () => {
  const hit = renderReader({ data: content({ query: 'rekurze', matched_chunks: 1, outline: undefined,
    chunks: [{ index: 2, text: 'Rekurze – funkce volá sama sebe', location: { kind: 'slide', from: 3, to: 3 }, score: 1, matched_terms: ['rekurze'] }] }),
    loading: false, error: null }, { materialId: 7, initialQuery: 'rekurze' });
  assert.deepEqual(hit.calls, ['/school/materials/7/content?q=rekurze']);
  assert.match(hit.html, /shoda: rekurze/); assert.match(hit.html, /Snímek 3/); assert.match(hit.html, /Začátek/);
  assert.doesNotMatch(hit.html, /Obsah \(/, 'outline only for the plain preview');
  const miss = renderReader({ data: content({ query: 'grafy', matched_chunks: 0, chunks: [], outline: undefined }), loading: false, error: null },
    { materialId: 7, initialQuery: 'grafy' });
  assert.match(miss.html, /nenašlo/); assert.match(miss.html, /data-empty/);
});

test('reader shows unavailable text, loading and error states', () => {
  const scan = renderReader({ data: content({ text_status: 'empty', text_message: 'Dokument nemá textovou vrstvu.', chunks: [], outline: [] }), loading: false, error: null });
  assert.match(scan.html, /nemá textovou vrstvu/); assert.doesNotMatch(scan.html, /data-empty/);
  assert.match(renderReader({ data: null, loading: true, error: null }).html, /data-loading/);
  assert.match(renderReader({ data: null, loading: false, error: 'x' }).html, /Text materiálu se nepodařilo načíst/);
});


// ---------- MRK-56: import ZIPu ----------

const zipFile = (name = 'course-export.zip', bytes = 'PK' + String.fromCharCode(3, 4) + 'synthetic') => new File([bytes], name, { type: '' });

function fakeFetch(response) {
  const calls = [];
  const fetcher = async (path, init) => {
    calls.push({ path, init });
    if (response instanceof Error) throw response;
    return response;
  };
  return { calls, fetcher };
}

test('only non-empty .zip files are accepted; anything else never reaches the server', async () => {
  assert.equal(isZipFile({ name: 'Kurz.ZIP', size: 10 }), true);
  assert.equal(isZipFile({ name: 'notes.pdf', size: 10 }), false);
  assert.equal(isZipFile({ name: 'empty.zip', size: 0 }), false);
  const { calls, fetcher } = fakeFetch(new Response('{}'));
  const outcome = await uploadMoodleZip(zipFile('lecture.pdf'), fetcher);
  assert.equal(outcome.ok, false);
  assert.match(outcome.message, /Vyber soubor \.zip/);
  assert.equal(calls.length, 0);
});

test('successful upload posts the raw ZIP to the import endpoint and summarises the result', async () => {
  const stats = { created: 5, updated: 1, unchanged: 2, file_unsupported: 1, files_listed_missing: 1, completeness: 'unproven' };
  const { calls, fetcher } = fakeFetch(new Response(JSON.stringify(stats), { status: 200 }));
  const file = zipFile();
  const outcome = await uploadMoodleZip(file, fetcher);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, ZIP_IMPORT_PATH);
  assert.equal(ZIP_IMPORT_PATH, '/school/materials/import-zip');
  assert.equal(calls[0].init.method, 'POST');
  assert.equal(calls[0].init.headers['Content-Type'], 'application/zip');
  assert.equal(calls[0].init.body, file);
  assert.deepEqual(outcome, { ok: true, summary: 'Import hotový: nové 5, změněné 1, beze změny 2 (nepodporované soubory 1, v ZIPu chybí 1).' });
  assert.equal(importSummary({ created: 0, updated: 0, unchanged: 3 }), 'Import hotový: nové 0, změněné 0, beze změny 3.');
});

test('backend validation errors show a safe Czech message, never the raw response body', async () => {
  const leaky = { detail: { category: 'unsafe_path', debug: 'C:/secret/path token=abc' } };
  const { fetcher } = fakeFetch(new Response(JSON.stringify(leaky), { status: 400 }));
  const outcome = await uploadMoodleZip(zipFile(), fetcher);
  assert.deepEqual(outcome, { ok: false, message: 'ZIP obsahuje nebezpečné cesty k souborům – import byl odmítnut.' });
  assert.doesNotMatch(outcome.message, /secret|token|C:/);
  for (const [category, pattern] of [['not_course_export', /Stáhnout obsah kurzu/], ['archive_too_large', /příliš velký/],
    ['compression_ratio', /kompresní poměr/], ['encrypted_entry', /šifrované/]]) {
    assert.match(importErrorMessage(category), pattern);
  }
  assert.equal(importErrorMessage('<script>alert(1)</script>'), importErrorMessage(undefined), 'unknown category → generic text');
  assert.equal(importErrorMessage('toString'), importErrorMessage(undefined), 'prototype keys are not categories');
});

test('non-JSON error bodies and network failures fall back to generic messages', async () => {
  const html = await uploadMoodleZip(zipFile(), fakeFetch(new Response('<html>Traceback: /srv/app.py</html>', { status: 502 })).fetcher);
  assert.equal(html.ok, false);
  assert.doesNotMatch(html.message, /Traceback|srv/);
  const offline = await uploadMoodleZip(zipFile(), fakeFetch(new TypeError('Failed to fetch')).fetcher);
  assert.deepEqual(offline, { ok: false, message: 'Import se nepovedl – server je nedostupný. Uložené materiály zůstaly beze změny.' });
});
