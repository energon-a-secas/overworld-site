// ── Missions ─────────────────────────────────────────────────
// The zone board. Two questions it exists to answer: "what can I do here", and
// "what opens up if I go there". The second is why zones are shown even when
// they are not the current filter.

import { escHtml } from '../utils.js';
import { facetsOfTask, FACET_SIGIL } from '../grammar.js';
import { openMissions, sortMissions, missionsByZone, filterByZone } from '../data.js';

export function render(state, tagNameById) {
  const missions = openMissions(state.tasks);
  const byZone = missionsByZone(missions, tagNameById);
  const shown = sortMissions(filterByZone(missions, tagNameById, state.zone), tagNameById);

  return `
  <section class="section" aria-labelledby="missions-title">
    <div class="section__header">
      <div class="section__titles">
        <h2 class="section__title" id="missions-title">Missions</h2>
        <p class="section__lead">
          ${shown.length} open ${shown.length === 1 ? 'mission' : 'missions'}${
            state.zone ? ` in <strong>${escHtml(state.zone)}</strong>` : ' across every zone'}.
          Anywhere-tagged missions show up in every zone.
        </p>
      </div>
      <div class="toolbar">
        <button type="button" class="btn btn--ghost btn--sm" id="missionsRefresh">Refresh</button>
        <button type="button" class="btn btn--ghost btn--sm" id="missionsShare">Copy link</button>
      </div>
    </div>

    ${renderZoneRail(byZone, state.zone)}

    <div class="mission-grid">
      ${shown.length ? shown.map((t) => renderMission(t, tagNameById)).join('')
        : `<p class="empty">Nothing open here. Try another zone, or capture something new.</p>`}
    </div>
  </section>`;
}

function renderZoneRail(byZone, active) {
  const zones = [...byZone.entries()]
    .map(([zone, tasks]) => ({ zone: zone || '(unzoned)', count: tasks.length }))
    .sort((a, b) => b.count - a.count);
  const total = zones.reduce((sum, z) => sum + z.count, 0);

  return `
  <div class="zone-rail" role="tablist" aria-label="Zones">
    <button type="button" class="zone-chip ${!active ? 'is-active' : ''}"
            role="tab" aria-selected="${!active}" data-zone="">
      All <span class="zone-chip__count">${total}</span>
    </button>
    ${zones.map((z) => `
      <button type="button" class="zone-chip ${active === z.zone ? 'is-active' : ''}"
              role="tab" aria-selected="${active === z.zone}" data-zone="${escHtml(z.zone)}">
        ${z.zone === '(unzoned)' ? 'Unzoned' : `@${escHtml(z.zone)}`}
        <span class="zone-chip__count">${z.count}</span>
      </button>`).join('')}
  </div>`;
}

const TYPE_LABEL = { todo: 'To-do', daily: 'Daily', habit: 'Habit' };

function renderMission(task, tagNameById) {
  const facets = facetsOfTask(task, tagNameById);
  const chips = Object.entries(facets)
    .map(([facet, value]) => `<span class="facet-chip facet-chip--${facet}">${
      FACET_SIGIL[facet]}${escHtml(value)}</span>`).join('');
  const due = task.date
    ? `<span class="mission__due ${Date.parse(task.date) < Date.now() ? 'is-overdue' : ''}">${
        new Date(task.date).toLocaleDateString()}</span>`
    : '';

  return `
  <article class="card card--interactive mission" data-task-id="${escHtml(task.id || task._id)}">
    <header class="mission__head">
      <span class="mission__type">${TYPE_LABEL[task.type] || task.type}</span>
      ${due}
    </header>
    <h3 class="mission__title">${escHtml(task.text)}</h3>
    ${task.notes ? `<p class="mission__notes">${escHtml(task.notes)}</p>` : ''}
    ${chips ? `<div class="facet-row">${chips}</div>` : '<div class="facet-row facet-row--empty">no facets</div>'}
    <div class="card--actions">
      <button type="button" class="btn btn--primary btn--sm" data-action="complete"
              data-task-id="${escHtml(task.id || task._id)}">
        ${task.type === 'habit' ? 'Score up' : 'Complete'}
      </button>
    </div>
  </article>`;
}
