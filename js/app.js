// ── Entry point ──────────────────────────────────────────────
// Wiring only. Everything else lives in its own module.

import { state, loadCredentials, loadPrefs, applyUrlState, hasCredentials } from './state.js';
import { render } from './render.js';
import { bindEvents, makeClient } from './events.js';

async function init() {
  loadCredentials(state);
  loadPrefs(state);
  applyUrlState(state);

  if (hasCredentials(state)) {
    state.client = makeClient(state.credentials);
  } else {
    state.view = 'connect';
  }

  bindEvents(state);
  await render(state);
}

init();
