// ── Data layer ───────────────────────────────────────────────
// Pull orchestration plus the pure selectors the views render from. Keeping the
// selectors free of DOM and of `state` makes them the part worth testing.

import { archivePull } from './archive.js';
import { facetsOfTask, FACETS } from './grammar.js';

const HORIZON_ORDER = { now: 0, week: 1, month: 2, someday: 3 };

/** Four requests: the whole account. Well inside the 30/minute budget. */
export async function pullAll(client) {
  const [user, tasks, completedTodos, tags] = [
    await client.getUser(),
    await client.getTasks({ withHistory: true }),
    await client.getCompletedTodos(),
    await client.getTags(),
  ];
  return { user, tasks, completedTodos, tags, pulledAt: new Date().toISOString() };
}

/**
 * Refresh state from Habitica and fold the result into the local archive.
 * The archive step is the safety net for stretches where `hbx snapshot` has not
 * run: Habitica deletes completed to-dos at 30 days, so a visit is a rescue.
 */
export async function refresh(state) {
  const pull = await pullAll(state.client);
  Object.assign(state, {
    user: pull.user,
    tasks: pull.tasks || [],
    completedTodos: pull.completedTodos || [],
    tags: pull.tags || [],
    lastPulledAt: pull.pulledAt,
  });
  const archived = await archivePull(pull);
  return archived;
}

/** Tasks you could actually act on now: open to-dos, due dailies, and habits. */
export function openMissions(tasks) {
  return (tasks || []).filter((task) => {
    if (task.type === 'todo') return !task.completed;
    if (task.type === 'daily') return task.isDue && !task.completed;
    if (task.type === 'habit') return true;
    return false;
  });
}

export function sortMissions(missions, tagNameById) {
  return [...missions].sort((a, b) => {
    const fa = facetsOfTask(a, tagNameById);
    const fb = facetsOfTask(b, tagNameById);
    const ha = HORIZON_ORDER[fa.horizon] ?? 9;
    const hb = HORIZON_ORDER[fb.horizon] ?? 9;
    if (ha !== hb) return ha - hb;

    const da = a.date ? Date.parse(a.date) : Infinity;
    const db = b.date ? Date.parse(b.date) : Infinity;
    if (da !== db) return da - db;

    return (b.priority || 1) - (a.priority || 1);
  });
}

/**
 * Group missions by zone. `null` is its own bucket rather than being dropped:
 * an untagged mission is invisible on a zone board, which is the failure this
 * whole grammar exists to prevent, so it is shown as "unzoned" instead.
 */
export function missionsByZone(missions, tagNameById) {
  const groups = new Map();
  for (const task of missions) {
    const zone = facetsOfTask(task, tagNameById).zone || null;
    if (!groups.has(zone)) groups.set(zone, []);
    groups.get(zone).push(task);
  }
  return groups;
}

export function filterByZone(missions, tagNameById, zone) {
  if (!zone) return missions;
  if (zone === '(unzoned)') {
    return missions.filter((t) => !facetsOfTask(t, tagNameById).zone);
  }
  return missions.filter((t) => {
    const taskZone = facetsOfTask(t, tagNameById).zone;
    return taskZone === zone || taskZone === 'anywhere';
  });
}

const STALE_DAYS = 90;

export function hygieneFindings(tasks, tags, completedTodos = []) {
  const usage = new Map();
  for (const task of [...tasks, ...completedTodos]) {
    for (const tagId of task.tags || []) usage.set(tagId, (usage.get(tagId) || 0) + 1);
  }
  const staleCutoff = Date.now() - STALE_DAYS * 86400000;
  const openTodos = tasks.filter((t) => t.type === 'todo' && !t.completed);

  return {
    // Rewards are excluded here for the same reason the suggester skips them:
    // they are prizes bought with gold, not actions with a place or a shape.
    // Listing them as untagged would report as a defect the thing we decided.
    untagged: tasks.filter((t) => t.type !== 'reward' && !(t.tags || []).length),
    noDueDate: openTodos.filter((t) => !t.date),
    stale: openTodos.filter((t) => t.createdAt && Date.parse(t.createdAt) < staleCutoff),
    deadDailies: tasks.filter((t) => t.type === 'daily' && t.isDue && !t.streak),
    orphanTags: tags.filter((t) => !usage.get(t.id || t._id)),
  };
}

/**
 * Facet coverage across the task list, the number the Upkeep view leads on.
 *
 * Derived from grammar.FACETS rather than a local list. A hardcoded copy of the
 * four original facets survived the addition of `time` and returned undefined
 * for it, which threw the moment a view iterated the real list.
 */
export function facetCoverage(tasks, tagNameById) {
  const coverage = {};
  for (const facet of FACETS) {
    const tagged = tasks.filter((t) => facetsOfTask(t, tagNameById)[facet]).length;
    coverage[facet] = { tagged, of: tasks.length };
  }
  return coverage;
}

/** Completion counts per ISO day, from archived completed to-dos. */
export function completionsByDay(todosCompleted) {
  const byDay = new Map();
  for (const todo of todosCompleted) {
    if (!todo.dateCompleted) continue;
    const day = todo.dateCompleted.slice(0, 10);
    byDay.set(day, (byDay.get(day) || 0) + 1);
  }
  return byDay;
}

export function completionsByZone(todosCompleted, tagNameById) {
  const byZone = new Map();
  for (const todo of todosCompleted) {
    const zone = facetsOfTask(todo, tagNameById).zone || '(unzoned)';
    byZone.set(zone, (byZone.get(zone) || 0) + 1);
  }
  return byZone;
}

/** Longest run of consecutive days with at least one completion. */
export function completionStreak(byDay, today = new Date()) {
  let streak = 0;
  const cursor = new Date(today);
  for (;;) {
    const key = cursor.toISOString().slice(0, 10);
    if (!byDay.get(key)) break;
    streak += 1;
    cursor.setDate(cursor.getDate() - 1);
  }
  return streak;
}

// ── Routines ─────────────────────────────────────────────────
// The account this was built for is 14 habits and 11 dailies against 10 to-dos.
// Leading with a zone board asked "where are you" of an account whose real
// question is "what does today look like". These selectors serve that view.

export const TIME_BLOCKS = ['morning', 'midday', 'evening', 'night', 'anytime'];

export const TIME_LABEL = {
  morning: 'Morning', midday: 'Midday', evening: 'Evening',
  night: 'Night', anytime: 'Any time',
};

/** Which block the clock is in. `anytime` is never "current"; it is a catch-all. */
export function currentTimeBlock(now = new Date()) {
  const hour = now.getHours();
  if (hour >= 5 && hour < 12) return 'morning';
  if (hour >= 12 && hour < 17) return 'midday';
  if (hour >= 17 && hour < 21) return 'evening';
  return 'night';
}

/**
 * Habitica's day rolls over at `user.preferences.dayStart`, not midnight. Before
 * that hour you are still inside yesterday's Habitica day, and a routines board
 * that says "today" while Habitica disagrees is worse than one that says nothing.
 */
export function habiticaToday(dayStart = 0, now = new Date()) {
  const day = new Date(now);
  if (now.getHours() < dayStart) day.setDate(day.getDate() - 1);
  return day;
}

export function dailiesByTime(tasks, tagNameById) {
  const groups = new Map(TIME_BLOCKS.map((block) => [block, []]));
  for (const task of tasks) {
    if (task.type !== 'daily' || !task.isDue) continue;
    const time = facetsOfTask(task, tagNameById).time;
    groups.get(TIME_BLOCKS.includes(time) ? time : 'anytime').push(task);
  }
  for (const list of groups.values()) {
    list.sort((a, b) => Number(a.completed) - Number(b.completed)
      || (b.streak || 0) - (a.streak || 0));
  }
  return groups;
}

/**
 * Split habits by the direction Habitica actually records.
 * A down-only habit is a vice: showing it beside "read 20 pages" as another
 * thing to tick invites you to score the wrong direction.
 */
export function habitsByDirection(tasks) {
  const build = [];
  const avoid = [];
  for (const task of tasks) {
    if (task.type !== 'habit') continue;
    (task.down && !task.up ? avoid : build).push(task);
  }
  return { build, avoid };
}

/** Habitica's own colour scale for a task's accumulated value. */
export function valueTier(value = 0) {
  if (value < -20) return 'worst';
  if (value < -10) return 'worse';
  if (value < -1) return 'bad';
  if (value < 1) return 'neutral';
  if (value < 5) return 'good';
  if (value < 10) return 'better';
  return 'best';
}

export function dailyProgress(tasks) {
  const due = tasks.filter((t) => t.type === 'daily' && t.isDue);
  const done = due.filter((t) => t.completed);
  return { done: done.length, due: due.length,
           pct: due.length ? Math.round((100 * done.length) / due.length) : 0 };
}

/** The streaks worth showing off, longest first. */
export function topStreaks(tasks, limit = 3) {
  return tasks
    .filter((t) => t.type === 'daily' && (t.streak || 0) > 0)
    .sort((a, b) => (b.streak || 0) - (a.streak || 0))
    .slice(0, limit);
}
