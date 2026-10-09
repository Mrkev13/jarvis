import assert from 'node:assert/strict';
import { test } from 'node:test';
import { activeFilterCount, fileState, formatSize, materialMeta, materialsPath, parseFilters, syncSummary } from './materialsLib.ts';
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
