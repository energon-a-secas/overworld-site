// ── Archive ──────────────────────────────────────────────────
// Import what hbx captured while the browser was closed, and export what the
// browser captured while hbx was not running. Same format both directions, so
// `hbx merge` accepts this file and dedupes on the way in.

import { escHtml } from '../utils.js';

/** `stored` is passed in for the same reason as in dashboard.js. */
export function render(state, stored = {}) {
  const total = Object.values(stored).reduce((sum, n) => sum + n, 0);

  return `
  <section class="section" aria-labelledby="archive-title">
    <div class="section__titles">
      <h2 class="section__title" id="archive-title">Archive</h2>
      <p class="section__lead">
        Habitica deletes completed to-dos after 30 days and averages daily history
        away after 60. Whatever is here survived because something captured it first.
      </p>
    </div>

    <div class="card">
      <h3 class="card__title">Stored locally</h3>
      <table class="count-table">
        <tbody>
          ${Object.entries(stored).map(([stream, n]) => `
            <tr><td><code>${escHtml(stream)}</code></td><td class="num">${n}</td></tr>`).join('')}
          <tr class="count-table__total"><td>total</td><td class="num">${total}</td></tr>
        </tbody>
      </table>
    </div>

    <div class="card stack stack--tight">
      <h3 class="card__title">Move data in and out</h3>
      <div class="toolbar">
        <button type="button" class="btn btn--secondary" id="archiveImport">Import a bundle</button>
        <button type="button" class="btn btn--secondary" id="archiveExport">Export a bundle</button>
        <button type="button" class="btn btn--danger" id="archiveClear">Clear local archive</button>
      </div>
      <input type="file" id="archiveFile" accept="application/json,.json" hidden>
      <p class="field__hint" id="archiveStatus" role="status" aria-live="polite">
        Import accepts the file <code>hbx bundle</code> writes. Export writes the same
        shape, so <code>hbx merge overworld-bundle.json</code> folds it back into the
        archive on disk without duplicating anything.
      </p>
    </div>

    <div class="card">
      <h3 class="card__title">Keeping it complete</h3>
      <p class="muted">
        This browser only archives while the page is open. For unattended capture, run
        <code>hbx snapshot</code> from the launchd job in <code>tools/</code>. That is
        what makes the 30-day window survivable.
      </p>
    </div>
  </section>`;
}
