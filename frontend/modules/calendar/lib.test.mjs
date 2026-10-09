import assert from 'node:assert/strict';
import { test } from 'node:test';
import { groupEvents, eventTime, eventState } from './lib.ts';
import { createModuleAccess, manifestFlags } from '../../lib/modules.ts';

const timed = { id: 1, source_id: 1, title: 'Synthetic lecture', starts_at: '2026-10-09T12:00:00+00:00', ends_at: '2026-10-09T13:30:00+00:00', all_day: false, starts_on: null, ends_on: null, status: 'active', location: 'Room A', rrule: null };
const allDay = { ...timed, id: 2, title: 'Two days', all_day: true, starts_on: '2026-10-09', ends_on: '2026-10-11' };

test('Calendar grouping retains distinct ids and honours exclusive all-day end', () => {
  const records = [{ ...timed, id: 3, starts_at: '2026-10-10T08:00:00Z' }, allDay, timed, { ...timed, id: 4, status: 'cancelled' }];
  const groups = groupEvents(records, '2026-10-09');
  assert.equal(groups.today.length, 2);
  assert.equal(groups.upcoming.length, 1);
  assert.equal(groups.cancelled.length, 1);
  assert.equal(groupEvents([allDay], '2026-10-10').today.length, 1);
  assert.equal(groupEvents([allDay], '2026-10-11').today.length, 0);
  assert.equal(records[0].id, 3, 'does not mutate source');
  assert.deepEqual(groupEvents([], '2026-10-09'), { today: [], upcoming: [], cancelled: [], past: [] });
});

test('Calendar all-day label is date based; timed events use Prague; cancellation visible', () => {
  assert.match(eventTime(allDay), /Celý den/);
  assert.match(eventTime(allDay), /10\. 10\./);
  assert.doesNotMatch(eventTime(allDay), /11\. 10\./);
  assert.match(eventTime(timed), /14:00/);
  assert.match(eventTime(timed), /15:30/);
  assert.equal(eventState({ ...timed, status: 'cancelled' }), 'Zrušeno');
});

test('Calendar runtime flag gates route and contributions', () => {
  const on = createModuleAccess(manifestFlags());
  const off = createModuleAccess({ ...manifestFlags(), calendar: false });
  assert.equal(on.allowsPath('/calendar'), true);
  assert.equal(off.allowsPath('/calendar'), false);
  assert.equal(off.allowsEntity('calendar_event', 'search'), false);
});

import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';
import * as calendar from './lib.ts';

function renderList(events) {
  const require = createRequire(import.meta.url);
  const ui = {
    EmptyState: ({ children }) => React.createElement('p', { 'data-empty': true }, children),
    EntityList: ({ children }) => React.createElement('ul', null, children),
    EntityRow: ({ title, badges, meta, searchTarget, muted }) => React.createElement('li', { 'data-event': searchTarget, 'data-cancelled': muted || undefined }, badges, title, meta),
    StatusBadge: ({ children }) => React.createElement('span', null, children),
  };
  const compiled = ts.transpileModule(readFileSync(new URL('./CalendarList.tsx', import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const compiledModule = { exports: {} };
  new Function('require', 'module', 'exports', compiled)(name => name === '@/components/ui' ? ui : name === './lib' ? calendar : require(name), compiledModule, compiledModule.exports);
  return renderToStaticMarkup(React.createElement(compiledModule.exports.CalendarList, { events, sources: { 1: 'Synthetic source' }, empty: 'Žádné události.' }));
}

test('Real CalendarList renders separate records, source, all-day and cancelled state', () => {
  const html = renderList([timed, allDay, { ...timed, id: 3, status: 'cancelled' }]);
  assert.equal((html.match(/data-event=/g) ?? []).length, 3);
  assert.match(html, /event-1/); assert.match(html, /event-2/); assert.match(html, /event-3/);
  assert.match(html, /Celý den/); assert.match(html, /Zrušeno/); assert.match(html, /Synthetic source/);
  assert.match(html, /data-cancelled="true"/);
  assert.doesNotMatch(html, /token|feed URL/);
});

test('Real CalendarList renders empty state', () => {
  assert.match(renderList([]), /Žádné události/);
  assert.doesNotMatch(renderList([]), /data-event=/);
});

test('MRK-40: recurring instances share an event id but render as separate rows by key', () => {
  const weekly = { ...timed, recurring: true, state: 'active' };
  const instances = [
    { ...weekly, key: '1@2026-10-13T08:00:00+00:00', starts_at: '2026-10-13T08:00:00+00:00', ends_at: '2026-10-13T09:30:00+00:00' },
    { ...weekly, key: '1@2026-10-20T08:00:00+00:00', starts_at: '2026-10-20T08:00:00+00:00', ends_at: '2026-10-20T09:30:00+00:00' },
  ];
  const groups = calendar.groupEvents(instances, '2026-10-13');
  assert.equal(groups.today.length, 1);
  assert.equal(groups.upcoming.length, 1);
  const html = renderList(instances);
  assert.equal((html.match(/data-event=/g) ?? []).length, 2);
  assert.match(html, /Opakuje se/);
  assert.doesNotMatch(html, /první výskyt/);
});

test('MRK-40: source-missing records are history, never active', () => {
  const missing = { ...timed, state: 'source_missing' };
  assert.equal(calendar.isActive(missing), false);
  assert.equal(calendar.eventState(missing), 'Zmizelo ze zdroje');
  assert.equal(calendar.groupEvents([missing], '2026-10-09').cancelled.length, 1);
  assert.match(renderList([missing]), /data-cancelled="true"/);
});
