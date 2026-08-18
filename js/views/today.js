// ── Today ────────────────────────────────────────────────────
// The default board, and the answer to "it is hard to grasp the value".
//
// The first build led with a zone map. That was right for an account full of
// errands and wrong for this one, which is 14 habits and 11 dailies against 10
// to-dos. What such an account wants on opening is not "where am I" but "what
// does today look like, and am I keeping my streaks".
//
// Everything here is grouped by time of day, the axis the account was already
// using informally through its "Routine: morning" tags.

import { escHtml } from '../utils.js';
import { facetsOfTask, FACET_SIGIL } from '../grammar.js';
import {
  TIME_BLOCKS, TIME_LABEL, currentTimeBlock, dailiesByTime, habitsByDirection,
  valueTier, dailyProgress, topStreaks,
} from '../data.js';

export function render(state, tagNameById, now = new Date()) {
  const block = currentTimeBlock(now);
  const groups = dailiesByTime(state.tasks, tagNameById);
  const habits = habitsByDirection(state.tasks);
  const progress = dailyProgress(state.tasks);
  const streaks = topStreaks(state.tasks);

  return `
  <section class="section" aria-labelledby="today-title">
    ${renderHero(state, progress, streaks, block)}

    <h2 class="section__title visually-quiet" id="today-title">Routines</h2>
    <div class="blocks">
      ${TIME_BLOCKS.map((b) => renderBlock(b, groups.get(b) || [], b === block, tagNameById))
        .filter(Boolean).join('')}
    </div>

    ${renderHabits(habits, tagNameById)}
  </section>`;
}

function renderHero(state, progress, streaks, block) {
  const stats = state.user?.stats || {};
  const hpPct = Math.max(0, Math.min(100, (stats.hp / (stats.maxHealth || 50)) * 100));
  const xpPct = Math.max(0, Math.min(100, (stats.exp / (stats.toNextLevel || 1)) * 100));

  return `
  <div class="hero">
    <div class="hero__left">
      <div class="hero__greeting">${greeting(block)}</div>
      <div class="hero__progress">
        <strong>${progress.done} of ${progress.due}</strong> routines done today
      </div>
      <div class="meter meter--xp" role="img"
           aria-label="Experience ${Math.round(xpPct)} percent to level ${(stats.lvl || 0) + 1}">
        <span class="meter__fill" style="width:${xpPct}%"></span>
      </div>
      <div class="hero__meta">
        <span class="chip chip--level">Lv ${escHtml(stats.lvl ?? '?')} ${escHtml(stats.class || '')}</span>
        <span class="chip chip--hp">
          <span class="meter meter--hp meter--inline"><span class="meter__fill" style="width:${hpPct}%"></span></span>
          ${Math.round(stats.hp ?? 0)}/${Math.round(stats.maxHealth ?? 50)}
        </span>
        <span class="chip chip--gold">${Math.round(stats.gp ?? 0)} gold</span>
      </div>
    </div>
    ${streaks.length ? `
    <div class="hero__streaks">
      <div class="hero__streaks-label">Longest streaks</div>
      ${streaks.map((t) => `
        <div class="streak">
          <span class="streak__count">${t.streak}</span>
          <span class="streak__text">${escHtml(t.text)}</span>
        </div>`).join('')}
    </div>` : ''}
  </div>`;
}

function greeting(block) {
  return {
    morning: 'Good morning', midday: 'Good afternoon',
    evening: 'Good evening', night: 'Late one',
  }[block] || 'Welcome back';
}

function renderBlock(block, tasks, isCurrent, tagNameById) {
  // An empty block is hidden unless it is the one you are standing in, where
  // "nothing scheduled" is itself the answer.
  if (!tasks.length && !isCurrent) return '';
  const done = tasks.filter((t) => t.completed).length;

  return `
  <section class="block ${isCurrent ? 'is-current' : ''}" aria-labelledby="block-${block}">
    <header class="block__head">
      <h3 class="block__title" id="block-${block}">${TIME_LABEL[block]}</h3>
      ${isCurrent ? '<span class="block__now">now</span>' : ''}
      <span class="block__count">${done}/${tasks.length}</span>
    </header>
    ${tasks.length
      ? `<ul class="task-list">${tasks.map((t) => renderDaily(t, tagNameById)).join('')}</ul>`
      : '<p class="block__empty">Nothing scheduled. Take the win.</p>'}
  </section>`;
}

function renderDaily(task, tagNameById) {
  const facets = facetsOfTask(task, tagNameById);
  const id = task.id || task._id;
  return `
  <li class="task ${task.completed ? 'is-done' : ''}" data-task-id="${escHtml(id)}">
    <button type="button" class="task__check" data-action="toggle-daily"
            data-task-id="${escHtml(id)}" aria-pressed="${Boolean(task.completed)}"
            aria-label="${task.completed ? 'Undo' : 'Complete'} ${escHtml(task.text)}">
      <span aria-hidden="true">${task.completed ? '✓' : ''}</span>
    </button>
    <span class="task__body">
      <span class="task__text">${escHtml(task.text)}</span>
      ${renderFacets(facets, ['zone', 'area', 'kind'])}
    </span>
    ${task.streak ? `<span class="task__streak" title="${task.streak} day streak">${task.streak}</span>` : ''}
  </li>`;
}

function renderHabits({ build, avoid }, tagNameById) {
  if (!build.length && !avoid.length) return '';
  return `
  <div class="habit-columns">
    ${renderHabitColumn('Build', build, tagNameById, 'up',
      'Score these when you do them.')}
    ${renderHabitColumn('Resist', avoid, tagNameById, 'down',
      'Habitica records these as down-only. Scoring one means it happened.')}
  </div>`;
}

function renderHabitColumn(title, tasks, tagNameById, direction, hint) {
  if (!tasks.length) return '';
  return `
  <section class="habit-col habit-col--${direction}" aria-labelledby="habits-${direction}">
    <header class="block__head">
      <h3 class="block__title" id="habits-${direction}">${title}</h3>
      <span class="block__count">${tasks.length}</span>
    </header>
    <p class="block__hint">${hint}</p>
    <ul class="task-list">
      ${tasks.map((task) => {
        const id = task.id || task._id;
        return `
        <li class="task task--habit" data-task-id="${escHtml(id)}">
          <button type="button" class="task__score task__score--${direction}"
                  data-action="score-${direction}" data-task-id="${escHtml(id)}"
                  aria-label="Score ${escHtml(task.text)}">
            <span aria-hidden="true">${direction === 'up' ? '+' : '−'}</span>
          </button>
          <span class="task__body">
            <span class="task__text">${escHtml(task.text)}</span>
            ${renderFacets(facetsOfTask(task, tagNameById), ['zone', 'area'])}
          </span>
          <span class="tier tier--${valueTier(task.value)}" title="Habitica strength"></span>
        </li>`;
      }).join('')}
    </ul>
  </section>`;
}

function renderFacets(facets, show) {
  const chips = show.filter((f) => facets[f])
    .map((f) => `<span class="facet-chip facet-chip--${f}">${FACET_SIGIL[f]}${escHtml(facets[f])}</span>`)
    .join('');
  return chips ? `<span class="facet-row">${chips}</span>` : '';
}
