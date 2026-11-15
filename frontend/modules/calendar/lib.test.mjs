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

function renderFreeBlocks(props) {
  const require = createRequire(import.meta.url);
  const ui = {
    EmptyState: ({ children }) => React.createElement('p', { 'data-empty': true }, children),
    ErrorState: ({ message }) => React.createElement('p', { 'data-error': true }, message),
    LoadingState: () => React.createElement('p', { 'data-loading': true }),
  };
  const compiled = ts.transpileModule(readFileSync(new URL('./FreeBlocksList.tsx', import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const compiledModule = { exports: {} };
  new Function('require', 'module', 'exports', compiled)(name => name === '@/components/ui' ? ui : name === './lib' ? calendar : require(name), compiledModule, compiledModule.exports);
  return renderToStaticMarkup(React.createElement(compiledModule.exports.FreeBlocksList, props));
}

const block = (start, end, minutes) => ({ starts_at: `2026-10-12T${start}:00+02:00`, ends_at: `2026-10-12T${end}:00+02:00`, local_date: '2026-10-12', local_start: start, local_end: end, duration_minutes: minutes });

test('MRK-32: free-block durations and labels', () => {
  assert.equal(calendar.formatDuration(90), '1 h 30 min');
  assert.equal(calendar.formatDuration(120), '2 h');
  assert.equal(calendar.formatDuration(45), '45 min');
  assert.equal(calendar.formatDuration(0), '0 min');
  assert.equal(calendar.freeBlockLabel(block('10:30', '12:00', 90)), '10:30–12:00 · 1 h 30 min');
  assert.equal(calendar.freeBlockLabel(block('21:00', '24:00', 180)), '21:00–24:00 · 3 h');
});

test('MRK-32: free-block query is one bounded local day with the chosen minimum', () => {
  assert.equal(calendar.freeBlocksPath('2026-10-12', 60), '/calendar/free-blocks?start=2026-10-12&end=2026-10-13&min_minutes=60');
  assert.equal(calendar.freeBlocksPath('2026-12-31', 30), '/calendar/free-blocks?start=2026-12-31&end=2027-01-01&min_minutes=30');
  assert.equal(calendar.freeBlocksPath('', 30), null, 'no request without a valid day');
  assert.deepEqual([...calendar.FREE_BLOCK_MINUTES], [15, 30, 60, 90, 120]);
});

test('MRK-32: FreeBlocksList renders blocks, empty (e.g. busy all day), loading, error and truncation', () => {
  const html = renderFreeBlocks({ blocks: [block('07:00', '09:00', 120), block('10:00', '22:00', 720)], loading: false, error: null });
  assert.equal((html.match(/data-free-block/g) ?? []).length, 2);
  assert.match(html, /07:00–09:00 · 2 h/);
  assert.match(html, /10:00–22:00 · 12 h/);
  assert.match(renderFreeBlocks({ blocks: [], loading: false, error: null }), /data-empty/);
  assert.match(renderFreeBlocks({ blocks: null, loading: true, error: null }), /data-loading/);
  assert.match(renderFreeBlocks({ blocks: null, loading: false, error: 'x' }), /data-error/);
  assert.match(renderFreeBlocks({ blocks: [block('07:00', '22:00', 900)], loading: false, error: null, truncated: true }), /nemusí být úplný/);
  assert.doesNotMatch(html, /RRULE|recurrence/);
});

function renderTimeline(props) {
  const require = createRequire(import.meta.url);
  const ui = {
    EmptyState: ({ children }) => React.createElement('p', { 'data-empty': true }, children),
    ErrorState: ({ message }) => React.createElement('p', { 'data-error': true }, message),
    LoadingState: () => React.createElement('p', { 'data-loading': true }),
    StatusBadge: ({ children }) => React.createElement('span', { 'data-badge': true }, children),
  };
  const compiled = ts.transpileModule(readFileSync(new URL('./DayTimelineList.tsx', import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const compiledModule = { exports: {} };
  new Function('require', 'module', 'exports', compiled)(name => name === '@/components/ui' ? ui : name === './lib' ? calendar : require(name), compiledModule, compiledModule.exports);
  return renderToStaticMarkup(React.createElement(compiledModule.exports.DayTimelineList, { moduleLabels: { calendar: 'Kalendář', school: 'Škola' }, ...props }));
}

const at = (hhmm) => `2026-10-12T${String(Number(hhmm.slice(0, 2)) - 2).padStart(2, '0')}:${hhmm.slice(3)}:00+00:00`;
const tItem = (id, kind, module_id, title, start, end, extra = {}) => ({ id, kind, module_id, title, subtitle: '', starts_at: start ? at(start) : null,
  ends_at: end ? at(end) : null, all_day: !start, date: '2026-10-12', status: 'upcoming', href: `/x/${id}`, busy: Boolean(end),
  ...(start ? { local_start: start, local_end: end } : {}), ...extra });
const gap = (start, end, minutes) => ({ starts_at: at(start), ends_at: at(end), local_date: '2026-10-12', local_start: start, local_end: end, duration_minutes: minutes });
const mixed = {
  date: '2026-10-12', truncated: false, free_blocks_from: ['calendar'],
  all_day_items: [tItem('exam:1', 'exam', 'school', 'Algebra exam'), tItem('calendar_event:2', 'calendar_event', 'calendar', 'Holiday')],
  timed_items: [tItem('reminder:1', 'reminder', null, 'Take pills', '10:00', null), tItem('calendar_event:3', 'calendar_event', 'calendar', 'Lecture', '10:00', '11:30'),
    tItem('calendar_event:4', 'calendar_event', 'calendar', 'Meeting', '11:00', '12:00')],
  free_blocks: [gap('07:00', '10:00', 180), gap('12:00', '22:00', 600)],
};

test('MRK-13: timeline path is one valid day', () => {
  assert.equal(calendar.timelinePath('2026-10-12'), '/timeline/day?date=2026-10-12&min_minutes=30');
  assert.equal(calendar.timelinePath('x'), null);
});

test('MRK-13: dayRows interleaves free gaps chronologically and keeps overlapping items separate', () => {
  const rows = calendar.dayRows(mixed);
  assert.deepEqual(rows.map(r => r.type === 'item' ? r.item.title : `free ${r.block.local_start}`),
    ['free 07:00', 'Take pills', 'Lecture', 'Meeting', 'free 12:00']);
  assert.equal(new Set(rows.map(r => r.key)).size, rows.length);
  assert.equal(calendar.timelineTime(mixed.timed_items[0]), '10:00', 'a point has no range');
  assert.equal(calendar.timelineTime(mixed.timed_items[1]), '10:00–11:30');
});

test('MRK-13: DayTimelineList renders mixed modules, all-day section, timed rows, gaps, links and states', () => {
  const html = renderTimeline({ data: mixed, loading: false, error: null });
  assert.match(html, /Celý den a termíny/);
  assert.match(html, /Během dne/);
  assert.equal((html.match(/data-timeline-item=/g) ?? []).length, 5);
  assert.equal((html.match(/data-free-gap/g) ?? []).length, 2);
  assert.match(html, /Volno · 3 h/);
  assert.match(html, /Škola/); assert.match(html, /Kalendář/); assert.match(html, /Obecné/);
  assert.match(html, /href="\/x\/calendar_event:3"/);
  assert.ok(html.indexOf('Lecture') < html.indexOf('Meeting'), 'overlaps listed, in order');
  const empty = { ...mixed, all_day_items: [], timed_items: [], free_blocks: [] };
  assert.match(renderTimeline({ data: empty, loading: false, error: null }), /Na tento den nic nemáš/);
  assert.match(renderTimeline({ data: null, loading: true, error: null }), /data-loading/);
  assert.match(renderTimeline({ data: null, loading: false, error: 'x' }), /data-error/);
  assert.match(renderTimeline({ data: { ...mixed, truncated: true }, loading: false, error: null }), /nemusí být úplný/);
  const busy = { ...mixed, all_day_items: [tItem('calendar_event:9', 'calendar_event', 'calendar', 'Trip')], timed_items: [], free_blocks: [] };
  const busyHtml = renderTimeline({ data: busy, loading: false, error: null });
  assert.match(busyHtml, /Trip/); assert.doesNotMatch(busyHtml, /Během dne/);
});

// MRK-77: více zdrojů – stav připojení a hláška po synchronizaci (jen názvy zdrojů, nikdy URL ani text chyby)
test('anySourceConfigured, connectedSources a syncNotice', () => {
  assert.equal(calendar.anySourceConfigured({ moodle_configured: false, configured: true }), true);
  assert.equal(calendar.anySourceConfigured({ moodle_configured: true }), true, 'starší backend');
  const available = [{ key: 'moodle', name: 'Moodle', configured: true }, { key: 'google', name: 'Google Kalendář', configured: true }];
  assert.equal(calendar.connectedSources({ available_sources: available }), 'Moodle a Google Kalendář');
  assert.equal(calendar.connectedSources({ available_sources: [available[0], { ...available[1], configured: false }] }), 'Moodle');
  assert.equal(calendar.connectedSources({}), '');
  const ok = { created: 3, updated: 1, cancelled: 0, errors: 0 };
  assert.equal(calendar.syncNotice(ok), 'Přidáno 3, změněno 1, zrušeno 0.');
  const partial = { ...ok, sources: { moodle: { created: 3 }, google: { error: 'feed_unavailable' } } };
  assert.equal(calendar.syncNotice(partial, available),
    'Přidáno 3, změněno 1, zrušeno 0. Nepodařilo se načíst: Google Kalendář (uložené události zůstaly).');
  assert.ok(!calendar.syncNotice(partial, available).includes('feed_unavailable'));
});
