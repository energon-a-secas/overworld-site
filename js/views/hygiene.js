// ── Hygiene ──────────────────────────────────────────────────
// The tag doctor. Single-task fixes happen here; bulk retagging deliberately
// does not. A one-click button that rewrites 200 tasks is a button whose
// consequences you cannot read beforehand, so that path is `hbx plan` ->
// read the file -> `hbx apply --apply`.

import { escHtml } from '../utils.js';
import { FACETS, FACET_LABEL } from '../grammar.js';
import { hygieneFindings, facetCoverage } from '../data.js';

const SECTIONS = [
  ['untagged', 'Tasks with no tags', 'Invisible to every board here.'],
  ['noDueDate', 'Open to-dos with no due date', 'They never surface as urgent.'],
  ['stale', 'To-dos older than 90 days', 'Still open, probably not still wanted.'],
  ['deadDailies', 'Dailies due with a dead streak', 'Either do them or retire them.'],
  ['orphanTags', 'Tags no task carries', 'Cruft in the tag picker.'],
];

export function render(state, tagNameById) {
  const findings = hygieneFindings(state.tasks, state.tags, state.completedTodos);
  const coverage = facetCoverage(state.tasks, tagNameById);

  return `
  <section class="section" aria-labelledby="hygiene-title">
    <div class="section__titles">
      <h2 class="section__title" id="hygiene-title">Upkeep</h2>
      <p class="section__lead">
        What the account looks like against the grammar. Fix one task at a time here;
        for a sweep across many, use <code>hbx plan</code> and read the change set first.
      </p>
    </div>

    <div class="coverage-grid">
      ${FACETS.map((facet) => {
        const { tagged, of } = coverage[facet];
        const pct = of ? Math.round((100 * tagged) / of) : 0;
        return `
        <div class="coverage-card">
          <div class="coverage-card__label">${FACET_LABEL[facet]}</div>
          <div class="coverage-card__value">${pct}%</div>
          <div class="coverage-bar"><div class="coverage-bar__fill" style="width:${pct}%"></div></div>
          <div class="coverage-card__sub">${tagged} of ${of} tasks</div>
        </div>`;
      }).join('')}
    </div>

    ${SECTIONS.map(([key, title, why]) => renderFinding(key, title, why, findings[key])).join('')}
  </section>`;
}

function renderFinding(key, title, why, items) {
  if (!items || !items.length) {
    return `<div class="card finding finding--clear">
      <h3 class="card__title">${title}</h3>
      <p class="muted">Nothing here. ${why}</p>
    </div>`;
  }
  return `
  <div class="card finding">
    <h3 class="card__title">${title} <span class="badge">${items.length}</span></h3>
    <p class="muted">${why}</p>
    <ul class="finding__list">
      ${items.slice(0, 25).map((item) => `
        <li>
          <span class="finding__text">${escHtml(item.text || item.name || '(untitled)')}</span>
          ${item.type ? `<span class="finding__type">${escHtml(item.type)}</span>` : ''}
        </li>`).join('')}
    </ul>
    ${items.length > 25 ? `<p class="muted">and ${items.length - 25} more</p>` : ''}
  </div>`;
}
