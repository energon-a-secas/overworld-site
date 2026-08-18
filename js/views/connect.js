// ── Connect ──────────────────────────────────────────────────
// This is the fleet's first page that asks a visitor for a third-party API
// credential, so it says exactly where the credential goes and gives an
// unambiguous way to remove it. The claims here are enforced by the CSP in
// index.html, not just asserted in prose.

import { escHtml } from '../utils.js';
import { hasCredentials } from '../state.js';

export function render(state) {
  const connected = hasCredentials(state) && state.identity;
  return `
  <section class="section" aria-labelledby="connect-title">
    <div class="section__titles">
      <h2 class="section__title" id="connect-title">Connect your Habitica account</h2>
      <p class="section__lead">
        Overworld reads your account straight from your browser. Your credentials are
        stored in this browser's localStorage and are sent to one place only:
        <code>habitica.com</code>. This page loads no third-party scripts, and its
        Content-Security-Policy blocks connections to any other host.
      </p>
    </div>

    ${connected ? renderConnected(state) : ''}

    <div class="card stack stack--tight">
      <label class="field">
        <span class="field__label">User ID</span>
        <input type="text" id="connectUserId" class="input" spellcheck="false"
               autocomplete="off" placeholder="00000000-0000-0000-0000-000000000000"
               value="${escHtml(state.credentials?.userId || '')}">
      </label>
      <label class="field">
        <span class="field__label">API Token</span>
        <input type="password" id="connectToken" class="input" spellcheck="false"
               autocomplete="off" placeholder="kept in this browser only"
               value="${escHtml(state.credentials?.apiToken || '')}">
      </label>
      <p class="field__hint">
        Both are at Habitica, under Settings, then Site Data, then API. They are
        different values, and both are required: Habitica authenticates on two headers.
        No account handy? The sample account shows every board with data in it.
      </p>
      <div class="toolbar">
        <button type="button" class="btn btn--primary" id="connectVerify">Verify and save</button>
        <button type="button" class="btn btn--secondary" id="demoStart">Explore a sample account</button>
        <button type="button" class="btn btn--danger" id="connectForget"
                ${hasCredentials(state) ? '' : 'disabled'}>Forget credentials</button>
      </div>
      <p class="connect-status" id="connectStatus" role="status" aria-live="polite"></p>
    </div>

    <div class="card">
      <h3 class="card__title">What Overworld does with your data</h3>
      <ul class="plain-list">
        <li><strong>Reads</strong> your tasks, tags and history to build the boards.</li>
        <li><strong>Writes</strong> only what you ask for: creating a to-do, ticking one
            off, adding or removing a tag on a single task.</li>
        <li><strong>Never</strong> bulk-rewrites your tags from this page. That runs
            through <code>hbx apply</code>, where you read the change set as a file first.</li>
        <li><strong>Archives</strong> completed to-dos into this browser's IndexedDB,
            because Habitica deletes them after 30 days.</li>
      </ul>
    </div>
  </section>`;
}

function renderConnected(state) {
  const { name, level, className } = state.identity;
  return `
    <div class="card card--connected">
      <span class="badge badge--ok">Connected</span>
      <strong>${escHtml(name)}</strong>
      <span class="muted">level ${escHtml(level)} ${escHtml(className)}</span>
    </div>`;
}
