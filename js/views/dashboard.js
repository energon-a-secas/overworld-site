// ── Dashboard ────────────────────────────────────────────────
// Live state answers "today". Everything longer comes from the local archive,
// because Habitica has already deleted the to-dos and averaged the history.
// Charts are inline SVG: the CSP blocks external hosts, and a bar chart does
// not justify a dependency.

import { escHtml } from '../utils.js';
import { completionsByDay, completionsByZone, completionStreak } from '../data.js';

/**
 * `completed` is passed in rather than read here. A view that does its own I/O
 * cannot be rendered in a test without a database, and these two were the only
 * ones the fixture harness could not cover.
 */
export function render(state, tagNameById, completed = []) {
  const byDay = completionsByDay(completed);
  const byZone = completionsByZone(completed, tagNameById);
  const streak = completionStreak(byDay);
  const stats = state.user?.stats || {};

  const last30 = lastNDays(30).map((day) => ({ day, value: byDay.get(day) || 0 }));
  const total30 = last30.reduce((sum, d) => sum + d.value, 0);

  return `
  <section class="section" aria-labelledby="dashboard-title">
    <div class="section__titles">
      <h2 class="section__title" id="dashboard-title">Stats</h2>
      <p class="section__lead">
        Today comes from Habitica. History comes from your local archive, which is
        the only place it survives: Habitica deletes completed to-dos after 30 days.
      </p>
    </div>

    <div class="stat-row">
      ${statTile('Level', stats.lvl ?? '—', escHtml(stats.class || ''))}
      ${statTile('Health', Math.round(stats.hp ?? 0), `of ${Math.round(stats.maxHealth ?? 50)}`)}
      ${statTile('Gold', Math.round(stats.gp ?? 0), '')}
      ${statTile('Done, 30 days', total30, 'from the archive')}
      ${statTile('Day streak', streak, streak === 1 ? 'day' : 'days')}
    </div>

    <div class="card">
      <h3 class="card__title">Completions per day, last 30</h3>
      ${total30 ? barChart(last30) : emptyArchiveNote(completed.length)}
    </div>

    <div class="card">
      <h3 class="card__title">Completions by zone</h3>
      ${byZone.size ? zoneBars(byZone) : '<p class="muted">No zone-tagged completions archived yet.</p>'}
    </div>

    <div class="card">
      <h3 class="card__title">Archive depth</h3>
      <p class="muted">
        ${completed.length} completed to-do${completed.length === 1 ? '' : 's'} archived.
        ${completed.length ? `Oldest: ${escHtml(oldest(completed))}.` : ''}
        Run <code>hbx snapshot</code> on a schedule so this keeps growing while the
        browser is closed.
      </p>
    </div>
  </section>`;
}

function emptyArchiveNote(archivedCount) {
  return `<p class="muted">
    ${archivedCount ? 'No completions in the last 30 days.'
      : 'Nothing archived yet. Refresh on the Missions view, or import a bundle from <code>hbx bundle</code> on the Archive view.'}
  </p>`;
}

function statTile(label, value, sub) {
  return `
  <div class="stat-tile">
    <div class="stat-tile__label">${label}</div>
    <div class="stat-tile__value">${escHtml(value)}</div>
    <div class="stat-tile__sub">${sub}</div>
  </div>`;
}

function lastNDays(n) {
  const days = [];
  const cursor = new Date();
  for (let i = n - 1; i >= 0; i -= 1) {
    const day = new Date(cursor);
    day.setDate(cursor.getDate() - i);
    days.push(day.toISOString().slice(0, 10));
  }
  return days;
}

function barChart(points) {
  const max = Math.max(...points.map((p) => p.value), 1);
  const width = 640;
  const height = 140;
  const gap = 3;
  const barWidth = (width - gap * (points.length - 1)) / points.length;

  return `
  <div class="chart-scroll">
    <svg viewBox="0 0 ${width} ${height}" class="chart" role="img"
         aria-label="Completions per day over the last 30 days">
      ${points.map((point, i) => {
        const barHeight = Math.round((point.value / max) * (height - 24));
        const x = i * (barWidth + gap);
        return `<rect x="${x.toFixed(1)}" y="${height - barHeight - 18}"
                 width="${barWidth.toFixed(1)}" height="${barHeight}" rx="2"
                 class="chart__bar"><title>${point.day}: ${point.value}</title></rect>`;
      }).join('')}
      <line x1="0" y1="${height - 18}" x2="${width}" y2="${height - 18}" class="chart__axis"/>
    </svg>
  </div>
  <p class="muted">Peak ${max} in a day.</p>`;
}

function zoneBars(byZone) {
  const rows = [...byZone.entries()].sort((a, b) => b[1] - a[1]);
  const max = rows[0][1];
  return `<div class="zone-bars">
    ${rows.map(([zone, count]) => `
      <div class="zone-bar">
        <span class="zone-bar__label">${zone === '(unzoned)' ? 'unzoned' : `@${escHtml(zone)}`}</span>
        <span class="zone-bar__track">
          <span class="zone-bar__fill" style="width:${Math.round((100 * count) / max)}%"></span>
        </span>
        <span class="zone-bar__count">${count}</span>
      </div>`).join('')}
  </div>`;
}

function oldest(completed) {
  const dates = completed.map((t) => t.dateCompleted).filter(Boolean).sort();
  return dates.length ? dates[0].slice(0, 10) : '';
}
