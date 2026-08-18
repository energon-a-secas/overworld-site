// ── Rendering ────────────────────────────────────────────────
// Shell chrome plus dispatch. Two views read IndexedDB, so render is async and
// every caller must await it, otherwise a refresh paints stale content over
// fresh state.

import { state, tagNameById, canBrowse } from './state.js';
import { readStream, counts } from './archive.js';
import { escHtml } from './utils.js';
import * as connect from './views/connect.js';
import * as today from './views/today.js';
import * as missions from './views/missions.js';
import * as capture from './views/capture.js';
import * as dashboard from './views/dashboard.js';
import * as hygiene from './views/hygiene.js';
import * as archiveView from './views/archive.js';
import * as recipes from './views/recipes.js';

// Names stay plain on purpose. The board is themed; the labels are not, because
// a visitor should never have to decode "Cellar" to find their archive.
const NAV = [
  ['today', 'Today'],
  ['quests', 'Quests'],
  ['capture', 'Capture'],
  ['stats', 'Stats'],
  ['upkeep', 'Upkeep'],
  ['recipes', 'Recipes'],
  ['archive', 'Archive'],
  ['connect', 'Connect'],
];

export function renderNav(s = state) {
  const nav = document.getElementById('viewNav');
  if (!nav) return;
  nav.innerHTML = NAV.map(([id, label]) => `
    <button type="button" class="nav-tab ${s.view === id ? 'is-active' : ''}"
            data-view="${id}" aria-current="${s.view === id ? 'page' : 'false'}">
      ${label}
    </button>`).join('');
}

export async function render(s = state) {
  const main = document.getElementById('appMain');
  if (!main) return;

  renderNav(s);

  // Nothing but Connect makes sense without an account, and pretending
  // otherwise produces empty boards and no explanation.
  if (!canBrowse(s) && s.view !== 'connect' && s.view !== 'recipes') {
    main.innerHTML = connect.render(s);
    return;
  }

  if (s.error) {
    main.innerHTML = renderError(s.error) + (s.view === 'connect' ? connect.render(s) : '');
    return;
  }

  if (s.loading) {
    main.innerHTML = '<p class="loading" role="status">Reading your account…</p>';
    return;
  }

  const names = tagNameById(s);
  const banner = s.demo ? renderDemoBanner() : '';
  switch (s.view) {
    case 'connect':   main.innerHTML = connect.render(s); break;
    case 'capture':   main.innerHTML = capture.render(s); break;
    case 'quests':    main.innerHTML = missions.render(s, names); break;
    case 'upkeep':    main.innerHTML = hygiene.render(s, names); break;
    case 'recipes':   main.innerHTML = recipes.render(s); break;
    // The two archive-backed views take their records as arguments, so the
    // reads happen here and the views stay renderable without a database.
    case 'stats':
      main.innerHTML = dashboard.render(
        s, names, s.demo ? s.demoArchive : await readStream('todos-completed'));
      break;
    case 'archive':
      main.innerHTML = archiveView.render(
        s, s.demo ? { 'todos-completed': s.demoArchive.length } : await counts());
      break;
    default:          main.innerHTML = today.render(s, names); break;
  }
  if (banner) main.insertAdjacentHTML('afterbegin', banner);
}

/** Never let sample data be mistaken for the visitor's own. */
function renderDemoBanner() {
  return `
  <div class="demo-banner" role="status">
    <strong>Sample account.</strong>
    Invented data, so you can see the boards with something on them. Nothing here
    touches Habitica.
    <button type="button" class="btn btn--secondary btn--sm" data-view="connect">
      Connect your own
    </button>
  </div>`;
}

function renderError(error) {
  const hint = error.status === 401
    ? 'Habitica rejected those credentials. Check both values on the Connect view: the User ID and the API Token are different UUIDs and are easy to swap.'
    : 'If this keeps happening, check habitica.com is up.';
  return `
  <div class="card card--error" role="alert">
    <h3 class="card__title">Could not reach your account</h3>
    <p>${escHtml(error.message || String(error))}</p>
    <p class="muted">${hint}</p>
  </div>`;
}

export function setStatus(id, message, tone = '') {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = message;
  el.className = `${el.className.replace(/\bis-\w+/g, '').trim()} ${tone ? `is-${tone}` : ''}`.trim();
}
