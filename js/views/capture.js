// ── Capture ──────────────────────────────────────────────────
// One field. The sigils are parsed live so you can see the facets land before
// committing, which is the whole reason the grammar uses a prefix a person can
// type rather than a picker they have to hunt through.

import { escHtml } from '../utils.js';
import { FACETS, FACET_LABEL, FACET_HINT, FACET_SIGIL, DEFAULT_VOCAB, parseText } from '../grammar.js';

export function render(state) {
  return `
  <section class="section" aria-labelledby="capture-title">
    <div class="section__titles">
      <h2 class="section__title" id="capture-title">Capture</h2>
      <p class="section__lead">
        Type the thing and its facets in one line. Sigils become tags on the to-do,
        so it stays organised in the Habitica app and the widget too.
      </p>
    </div>

    <div class="card stack stack--tight">
      <label class="field">
        <span class="field__label">New to-do</span>
        <input type="text" id="captureInput" class="input input--lg" autocomplete="off"
               placeholder="buy coffee filters @errand ?buy !week">
      </label>
      <div id="capturePreview" class="capture-preview" aria-live="polite"></div>
      <div class="toolbar">
        <button type="button" class="btn btn--primary" id="captureSubmit">Create to-do</button>
        <span class="muted" id="captureStatus" role="status" aria-live="polite"></span>
      </div>
    </div>

    <div class="card">
      <h3 class="card__title">The grammar</h3>
      <table class="grammar-table">
        <thead><tr><th>Facet</th><th>Sigil</th><th>Answers</th><th>Starting vocabulary</th></tr></thead>
        <tbody>
          ${FACETS.map((facet) => `
            <tr>
              <td>${FACET_LABEL[facet]}</td>
              <td><code>${FACET_SIGIL[facet]}</code></td>
              <td class="muted">${FACET_HINT[facet]}</td>
              <td>${DEFAULT_VOCAB[facet].map((v) =>
                `<code>${FACET_SIGIL[facet]}${escHtml(v)}</code>`).join(' ')}</td>
            </tr>`).join('')}
        </tbody>
      </table>
      <p class="field__hint">
        A word only counts as a facet when the sigil starts it, so "is the milk off?"
        stays prose.
      </p>
    </div>
  </section>`;
}

/** Live preview, called on every keystroke. */
export function renderPreview(value) {
  const { text, facets } = parseText(value);
  if (!text && !Object.keys(facets).length) return '';
  const chips = FACETS.filter((f) => facets[f])
    .map((f) => `<span class="facet-chip facet-chip--${f}">${FACET_SIGIL[f]}${
      escHtml(facets[f])}</span>`).join('');
  return `
    <div class="capture-preview__row">
      <span class="capture-preview__label">creates</span>
      <strong>${escHtml(text) || '<em class="muted">(no text yet)</em>'}</strong>
      ${chips || '<span class="muted">no facets</span>'}
    </div>`;
}
