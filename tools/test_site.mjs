// Site-module tests that need no browser.  Run:  node --test tools/test_site.mjs
//
// The share-link test is the reason this file exists. Several sites in this
// fleet carry whole documents in the URL hash, and this is the first one
// holding a credential, so "the token cannot reach a URL" has to be an
// assertion rather than an intention.

import { test } from 'node:test';
import assert from 'node:assert/strict';

// state.js reads localStorage at call time only, but the module is imported at
// load time, so the globals have to exist before the import.
const store = new Map();
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
};
globalThis.window = { location: { origin: 'https://overworld.neorgon.com', pathname: '/', hash: '' } };

const grammar = await import('../js/grammar.js');
const data = await import('../js/data.js');
const stateMod = await import('../js/state.js');

// The view modules build strings; escHtml is the only DOM-adjacent thing they
// touch and it is pure. Stubs exist so importing them does not throw.
globalThis.document = { getElementById: () => null };
const dashboard = await import('../js/views/dashboard.js');
const archiveView = await import('../js/views/archive.js');

const USER_ID = '11111111-2222-3333-4444-555555555555';
const API_TOKEN = '99999999-8888-7777-6666-555555555555';

const TAGS = new Map([
  ['t-home', '@home'], ['t-errand', '@errand'], ['t-any', '@anywhere'],
  ['t-work', '+work'], ['t-now', '!now'], ['t-buy', '?buy'], ['t-free', 'Random'],
]);

test('share URL cannot carry credentials', () => {
  const s = { ...stateMod.state, view: 'quests', zone: 'errand' };
  stateMod.saveCredentials(s, { userId: USER_ID, apiToken: API_TOKEN });

  const url = stateMod.buildShareUrl(s, 'https://overworld.neorgon.com/');
  assert.ok(!url.includes(USER_ID), 'user id leaked into the share URL');
  assert.ok(!url.includes(API_TOKEN), 'api token leaked into the share URL');
  assert.equal(url, 'https://overworld.neorgon.com/#view=quests&zone=errand');
});

test('shareParams is an allowlist, so a new state field is not shareable by default', () => {
  const s = { ...stateMod.state, view: 'today', zone: null, secretNote: 'do-not-publish' };
  const params = String(stateMod.shareParams(s));
  assert.ok(!params.includes('do-not-publish'));
  assert.ok(!params.includes('secretNote'));
  assert.equal(params, 'view=today');
});

test('forgetCredentials clears storage as well as memory', () => {
  const s = { ...stateMod.state };
  stateMod.saveCredentials(s, { userId: USER_ID, apiToken: API_TOKEN });
  assert.ok(stateMod.hasCredentials(s));

  stateMod.forgetCredentials(s);
  assert.equal(stateMod.hasCredentials(s), false);
  assert.equal(localStorage.getItem('overworld.credentials'), null);
});

test('applyUrlState only accepts known views', () => {
  const s = { ...stateMod.state, view: 'today' };
  stateMod.applyUrlState(s, '#view=not-a-view&zone=mall');
  assert.equal(s.view, 'today', 'an unknown view was accepted from the URL');
  assert.equal(s.zone, 'mall');
});

test('grammar matches the Python implementation on the shared cases', () => {
  assert.deepEqual(grammar.parseText('buy coffee filters @errand ?buy !week'), {
    text: 'buy coffee filters',
    facets: { zone: 'errand', kind: 'buy', horizon: 'week' },
  });
  // "off?" must stay prose, or every question mark becomes a tag.
  assert.deepEqual(grammar.parseText('is the milk off? call mum').facets, {});
  assert.equal(grammar.tagFor('zone', 'Corner Store'), '@corner-store');
  assert.equal(grammar.facetOf('Work'), null);
  assert.deepEqual(grammar.facetOf('@errand'), { facet: 'zone', value: 'errand' });
});

test('anywhere-tagged missions appear in every zone', () => {
  const tasks = [
    { id: 'a', type: 'todo', tags: ['t-errand'], text: 'buy filters' },
    { id: 'b', type: 'todo', tags: ['t-any'], text: 'call the bank' },
    { id: 'c', type: 'todo', tags: ['t-home'], text: 'water plants' },
  ];
  const inErrand = data.filterByZone(tasks, TAGS, 'errand').map((t) => t.id);
  assert.deepEqual(inErrand.sort(), ['a', 'b']);

  const inHome = data.filterByZone(tasks, TAGS, 'home').map((t) => t.id);
  assert.deepEqual(inHome.sort(), ['b', 'c']);
});

test('unzoned missions are shown, not dropped', () => {
  const tasks = [
    { id: 'a', type: 'todo', tags: ['t-errand'] },
    { id: 'b', type: 'todo', tags: [] },
    { id: 'c', type: 'todo', tags: ['t-free'] },   // a tag outside the grammar
  ];
  const groups = data.missionsByZone(tasks, TAGS);
  assert.equal(groups.get(null).length, 2, 'untagged missions vanished from the board');
  assert.deepEqual(data.filterByZone(tasks, TAGS, '(unzoned)').map((t) => t.id), ['b', 'c']);
});

test('openMissions excludes rewards and completed work', () => {
  const tasks = [
    { id: 'todo-open', type: 'todo', completed: false },
    { id: 'todo-done', type: 'todo', completed: true },
    { id: 'daily-due', type: 'daily', isDue: true, completed: false },
    { id: 'daily-not-due', type: 'daily', isDue: false, completed: false },
    { id: 'daily-done', type: 'daily', isDue: true, completed: true },
    { id: 'habit', type: 'habit' },
    { id: 'reward', type: 'reward' },
  ];
  assert.deepEqual(data.openMissions(tasks).map((t) => t.id),
    ['todo-open', 'daily-due', 'habit']);
});

test('missions sort by horizon, then due date', () => {
  const tasks = [
    { id: 'someday', type: 'todo', tags: ['t-buy'] },
    { id: 'now', type: 'todo', tags: ['t-now'] },
    { id: 'due-soon', type: 'todo', tags: [], date: '2026-08-15T00:00:00Z' },
    { id: 'due-later', type: 'todo', tags: [], date: '2026-12-01T00:00:00Z' },
  ];
  assert.deepEqual(data.sortMissions(tasks, TAGS).map((t) => t.id),
    ['now', 'due-soon', 'due-later', 'someday']);
});

test('completion streak counts back from today and stops at the first gap', () => {
  const day = (offset) => {
    const d = new Date('2026-08-14T12:00:00Z');
    d.setDate(d.getDate() - offset);
    return d.toISOString().slice(0, 10);
  };
  const byDay = new Map([[day(0), 2], [day(1), 1], [day(3), 5]]);
  assert.equal(data.completionStreak(byDay, new Date('2026-08-14T12:00:00Z')), 2);
});

test('hygiene finds the seeded problems and nothing else', () => {
  const now = Date.now();
  const tasks = [
    { id: 'untagged', type: 'todo', tags: [], createdAt: new Date(now).toISOString() },
    { id: 'tagged-due', type: 'todo', tags: ['t-home'], date: '2026-09-01',
      createdAt: new Date(now).toISOString() },
    { id: 'old', type: 'todo', tags: ['t-home'], date: '2026-09-01',
      createdAt: new Date(now - 200 * 86400000).toISOString() },
    { id: 'dead-daily', type: 'daily', tags: ['t-home'], isDue: true, streak: 0 },
    { id: 'live-daily', type: 'daily', tags: ['t-home'], isDue: true, streak: 7 },
  ];
  const tags = [{ id: 't-home', name: '@home' }, { id: 't-free', name: 'Random' }];
  const findings = data.hygieneFindings(tasks, tags, []);

  assert.deepEqual(findings.untagged.map((t) => t.id), ['untagged']);
  // A reward with no tags is correct, not a finding: rewards are excluded from
  // tagging on purpose, so Upkeep must not report them as a problem.
  const withReward = data.hygieneFindings(
    [...tasks, { id: 'prize', type: 'reward', tags: [] }], tags, []);
  assert.deepEqual(withReward.untagged.map((t) => t.id), ['untagged']);
  assert.deepEqual(findings.noDueDate.map((t) => t.id), ['untagged']);
  assert.deepEqual(findings.stale.map((t) => t.id), ['old']);
  assert.deepEqual(findings.deadDailies.map((t) => t.id), ['dead-daily']);
  assert.deepEqual(findings.orphanTags.map((t) => t.name), ['Random']);
});

test('facet coverage counts tasks, not tags', () => {
  const tasks = [
    { id: 'a', tags: ['t-home', 't-work'] },
    { id: 'b', tags: ['t-errand'] },
    { id: 'c', tags: [] },
  ];
  const coverage = data.facetCoverage(tasks, TAGS);
  assert.deepEqual(coverage.zone, { tagged: 2, of: 3 });
  assert.deepEqual(coverage.area, { tagged: 1, of: 3 });
  assert.deepEqual(coverage.kind, { tagged: 0, of: 3 });
});


// ── Views that read the archive ──────────────────────────────
// These two used to fetch from IndexedDB themselves, which made them the only
// views no test could render. They now take their records as an argument.

const ARCHIVE_STATE = {
  user: { stats: { lvl: 27, hp: 44.5, maxHealth: 50, gp: 310.2, class: 'warrior' } },
};

function completedOn(offsetDays, tags = []) {
  const d = new Date();
  d.setDate(d.getDate() - offsetDays);
  return { id: `c${offsetDays}${tags.join('')}`, text: 'a task', tags,
           dateCompleted: d.toISOString() };
}

test('dashboard renders from supplied records, with no database', () => {
  const completed = [
    completedOn(0, ['t-errand']), completedOn(0, ['t-home']),
    completedOn(1, ['t-errand']), completedOn(5, []),
  ];
  const html = dashboard.render(ARCHIVE_STATE, TAGS, completed);

  assert.ok(!/undefined|NaN|\[object Object\]/.test(html), 'placeholder leaked into output');
  assert.match(html, /Completions per day/);
  assert.match(html, /27/, 'level missing');
  assert.match(html, /@errand/, 'zone breakdown missing');
  assert.match(html, /<svg/, 'chart missing');
});

test('dashboard degrades honestly with an empty archive', () => {
  const html = dashboard.render(ARCHIVE_STATE, TAGS, []);
  assert.ok(!/undefined|NaN/.test(html));
  assert.match(html, /Nothing archived yet/);
  assert.doesNotMatch(html, /<svg/, 'drew a chart with no data');
});

test('dashboard streak counts only consecutive days ending today', () => {
  // Yesterday and today, then a gap, then day 5. Streak is 2, not 3.
  const html = dashboard.render(ARCHIVE_STATE, TAGS,
    [completedOn(0), completedOn(1), completedOn(5)]);
  assert.match(html, /Day streak<\/div>\s*<div class="stat-tile__value">2</);
});

test('archive view renders supplied counts and totals them', () => {
  const html = archiveView.render({}, {
    'todos-completed': 0, 'task-history': 670, 'user-history': 104, tags: 18,
  });
  assert.ok(!/undefined|NaN/.test(html));
  assert.match(html, /792/, 'total not computed');
  assert.match(html, /task-history/);
});

test('archive view survives an empty archive', () => {
  const html = archiveView.render({}, {});
  assert.ok(!/undefined|NaN/.test(html));
  assert.match(html, /<td class="num">0<\/td>/);
});


// ── Facets and the demo account ──────────────────────────────

const grammarMod = await import('../js/grammar.js');
const todayView = await import('../js/views/today.js');
const hygieneView = await import('../js/views/hygiene.js');
const { readFileSync } = await import('node:fs');

test('facetCoverage covers every facet the grammar declares', () => {
  // Regression: the list was hardcoded to the original four, so adding `time`
  // returned undefined for it and the Upkeep view threw on first render.
  const coverage = data.facetCoverage([{ id: 'a', tags: ['t-home'] }], TAGS);
  for (const facet of grammarMod.FACETS) {
    assert.ok(coverage[facet], `facetCoverage is missing ${facet}`);
  }
  assert.equal(Object.keys(coverage).length, grammarMod.FACETS.length);
});

test('every declared facet has a label and a hint', () => {
  for (const facet of grammarMod.FACETS) {
    assert.ok(grammarMod.FACET_LABEL[facet], `no label for ${facet}`);
    assert.ok(grammarMod.FACET_HINT[facet], `no hint for ${facet}`);
    assert.ok(grammarMod.FACET_SIGIL[facet], `no sigil for ${facet}`);
    assert.ok(grammarMod.DEFAULT_VOCAB[facet]?.length, `no vocabulary for ${facet}`);
  }
});

test('habits split by the direction Habitica records', () => {
  const { build, avoid } = data.habitsByDirection([
    { id: 'up', type: 'habit', up: true, down: false },
    { id: 'both', type: 'habit', up: true, down: true },
    { id: 'vice', type: 'habit', up: false, down: true },
    { id: 'daily', type: 'daily', isDue: true },
  ]);
  assert.deepEqual(build.map((t) => t.id), ['up', 'both']);
  assert.deepEqual(avoid.map((t) => t.id), ['vice'],
    'a down-only habit must not appear as something to do');
});

test('the Habitica day rolls at dayStart, not midnight', () => {
  const early = new Date('2026-08-14T05:00:00');
  const late = new Date('2026-08-14T09:00:00');
  assert.equal(data.habiticaToday(8, early).getDate(), 13);
  assert.equal(data.habiticaToday(8, late).getDate(), 14);
});

test('dailies group into time blocks, unfaceted ones falling to anytime', () => {
  const groups = data.dailiesByTime([
    { id: 'm', type: 'daily', isDue: true, tags: ['t-morning'] },
    { id: 'none', type: 'daily', isDue: true, tags: [] },
    { id: 'notdue', type: 'daily', isDue: false, tags: ['t-morning'] },
  ], new Map([['t-morning', '*morning']]));
  assert.deepEqual(groups.get('morning').map((t) => t.id), ['m']);
  assert.deepEqual(groups.get('anytime').map((t) => t.id), ['none']);
  assert.equal(groups.get('evening').length, 0);
});

test('the demo account renders every board with data in it', () => {
  const demo = JSON.parse(readFileSync(new URL('../data/demo-account.json', import.meta.url)));
  assert.equal(demo.format, 'overworld-demo');
  const names = new Map(demo.tags.map((t) => [t.id, t.name]));
  const state = { user: demo.user, tasks: demo.tasks, tags: demo.tags,
                  completedTodos: demo.completedTodos, zone: null };

  for (const [label, html] of [
    ['today', todayView.render(state, names)],
    ['upkeep', hygieneView.render(state, names)],
    ['stats', dashboard.render(state, names, demo.archivedCompletions)],
  ]) {
    assert.ok(!/undefined|NaN|\[object Object\]/.test(html), `${label} rendered a placeholder`);
    assert.ok(html.length > 1000, `${label} rendered almost nothing`);
  }

  // A demo whose charts are empty teaches nothing, so assert it has substance.
  assert.ok(demo.archivedCompletions.length > 30, 'demo archive is too thin to chart');
  assert.ok(demo.tasks.filter((t) => t.type === 'daily').length >= 8);
  assert.ok(demo.tasks.some((t) => t.up === false && t.down === true),
    'demo has no vice habit, so the Resist column would never be shown');
});

test('the demo ships no real credentials or personal ids', () => {
  const raw = readFileSync(new URL('../data/demo-account.json', import.meta.url), 'utf8');
  const uuids = raw.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi) || [];
  assert.deepEqual(uuids, [], `demo file contains UUIDs: ${uuids.slice(0, 3)}`);
  assert.ok(!/apiToken|x-api-key/i.test(raw));
});
