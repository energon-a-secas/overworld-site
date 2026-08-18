// ── Events ───────────────────────────────────────────────────
// Delegated from two roots, so re-rendering never orphans a listener. No inline
// onclick anywhere (PROJECTS.md section 10).

import { state, savePrefs, saveCredentials, forgetCredentials, buildShareUrl, applyUrlState } from './state.js';
import { loadDemo, exitDemo } from './demo.js';
import { starterPlan } from './views/recipes.js';
import { render, setStatus } from './render.js';
import { HabiticaClient, RateLimiter, verifyCredentials, ApiError } from './habitica.js';
import { refresh } from './data.js';
import { parseText, tagFor, FACETS } from './grammar.js';
import { exportBundle, importBundle, clearAll } from './archive.js';
import { renderPreview } from './views/capture.js';
import { showToast } from './utils.js';

// One limiter for the whole session: Habitica's 30/minute is per account, not
// per component, and two limiters would each believe they had the full budget.
const limiter = new RateLimiter();

export function makeClient(credentials) {
  return new HabiticaClient({ ...credentials, limiter });
}

async function withBusy(fn, statusId) {
  try {
    return await fn();
  } catch (error) {
    if (statusId) setStatus(statusId, error.message, 'error');
    else {
      state.error = error;
      await render(state);
    }
    return null;
  }
}

export function bindEvents(s = state) {
  const nav = document.getElementById('viewNav');
  const main = document.getElementById('appMain');

  nav?.addEventListener('click', async (event) => {
    const tab = event.target.closest('[data-view]');
    if (!tab) return;
    s.view = tab.dataset.view;
    s.error = null;
    savePrefs(s);
    await render(s);
    // Switching board while scrolled halfway down the old one lands you in the
    // middle of the new one with no idea what is above.
    window.scrollTo({ top: 0 });
  });

  main?.addEventListener('click', (event) => handleMainClick(event, s));
  main?.addEventListener('input', (event) => handleMainInput(event));
  main?.addEventListener('change', (event) => handleMainChange(event, s));

  window.addEventListener('hashchange', async () => {
    applyUrlState(s);
    await render(s);
  });
}

async function handleMainClick(event, s) {
  const target = event.target;

  const zoneChip = target.closest('[data-zone]');
  if (zoneChip) {
    s.zone = zoneChip.dataset.zone || null;
    savePrefs(s);
    await render(s);
    return;
  }

  const copyId = target.closest('[data-copy]')?.dataset.copy;
  if (copyId) return onCopyRecipe(copyId);

  const action = target.closest('[data-action]')?.dataset.action;
  const taskId = target.closest('[data-task-id]')?.dataset.taskId;

  switch (target.id || action) {
    case 'demoStart':       return onDemo(s);
    case 'connectVerify':   return onVerify(s);
    case 'connectForget':   return onForget(s);
    case 'missionsRefresh': return onRefresh(s);
    case 'missionsShare':   return onShare(s);
    case 'captureSubmit':   return onCapture(s);
    case 'archiveExport':   return onExportBundle();
    case 'recipeDownloadPlan': return onDownloadStarterPlan();
    case 'archiveImport':   return document.getElementById('archiveFile')?.click();
    case 'archiveClear':    return onClearArchive(s);
    case 'complete':        return onScore(s, taskId, 'up');
    case 'toggle-daily':    return onToggleDaily(s, taskId, target);
    case 'score-up':        return onScore(s, taskId, 'up');
    case 'score-down':      return onScore(s, taskId, 'down');
    default:                return undefined;
  }
}

function handleMainInput(event) {
  if (event.target.id === 'captureInput') {
    const preview = document.getElementById('capturePreview');
    if (preview) preview.innerHTML = renderPreview(event.target.value);
  }
}

async function handleMainChange(event, s) {
  if (event.target.id !== 'archiveFile') return;
  const file = event.target.files?.[0];
  if (!file) return;
  await withBusy(async () => {
    const bundle = JSON.parse(await file.text());
    const result = await importBundle(bundle);
    setStatus('archiveStatus',
      `Imported ${result.added} new records, skipped ${result.skipped} already held.`, 'ok');
    await render(s);
  }, 'archiveStatus');
}

async function onDemo(s) {
  await withBusy(async () => {
    await loadDemo(s);
    s.view = 'today';
    savePrefs(s);
    await render(s);
    showToast('Exploring the sample account. Nothing here touches Habitica.');
  }, 'connectStatus');
}

/** Every write goes through here, so demo mode has exactly one place to stop. */
function blockedInDemo(s) {
  if (!s.demo) return false;
  showToast('This is the sample account. Connect your own to make changes.');
  return true;
}

async function onVerify(s) {
  const userId = document.getElementById('connectUserId')?.value.trim();
  const apiToken = document.getElementById('connectToken')?.value.trim();
  if (!userId || !apiToken) {
    setStatus('connectStatus', 'Both the User ID and the API Token are required.', 'error');
    return;
  }
  setStatus('connectStatus', 'Checking with Habitica…');
  try {
    const identity = await verifyCredentials({ userId, apiToken });
    exitDemo(s);
    saveCredentials(s, { userId, apiToken });
    s.identity = identity;
    s.client = makeClient(s.credentials);
    s.error = null;
    setStatus('connectStatus', `Connected as ${identity.name}.`, 'ok');
    await onRefresh(s);
  } catch (error) {
    const message = error instanceof ApiError && error.status === 401
      ? 'Habitica rejected those credentials. The User ID and API Token are both UUIDs and are easy to swap, so check the order.'
      : error.message;
    setStatus('connectStatus', message, 'error');
  }
}

async function onForget(s) {
  forgetCredentials(s);
  s.view = 'connect';
  await render(s);
  showToast('Credentials removed from this browser. The archive is untouched.');
}

async function onRefresh(s) {
  if (s.demo) { await render(s); return; }
  if (!s.client) s.client = makeClient(s.credentials);
  s.loading = true;
  s.error = null;
  await render(s);
  const archived = await withBusy(() => refresh(s));
  s.loading = false;
  await render(s);
  if (archived) {
    showToast(archived.added
      ? `Refreshed. ${archived.added} new records archived.`
      : 'Refreshed. Archive already had everything.');
  }
}

async function onShare(s) {
  const url = buildShareUrl(s);
  try {
    await navigator.clipboard.writeText(url);
    showToast('Link copied. It carries the view and the zone, nothing else.');
  } catch {
    showToast(url);
  }
}

async function onCapture(s) {
  if (blockedInDemo(s)) return;
  const input = document.getElementById('captureInput');
  const raw = input?.value || '';
  const { text, facets } = parseText(raw);
  if (!text) {
    setStatus('captureStatus', 'Give it some words as well as facets.', 'error');
    return;
  }

  setStatus('captureStatus', 'Creating…');
  await withBusy(async () => {
    const wanted = FACETS.filter((f) => facets[f]).map((f) => tagFor(f, facets[f]));
    const tagIds = await ensureTags(s, wanted);
    await s.client.createTodo({ text, tags: tagIds });
    input.value = '';
    document.getElementById('capturePreview').innerHTML = '';
    setStatus('captureStatus', `Created "${text}".`, 'ok');
    await refresh(s);
  }, 'captureStatus');
}

/** Create any facet tag the account does not have yet, then return every id. */
async function ensureTags(s, names) {
  const byName = new Map((s.tags || []).map((t) => [t.name, t.id || t._id]));
  const ids = [];
  for (const name of names) {
    if (!byName.has(name)) {
      const created = await s.client.createTag(name);
      byName.set(name, created.id || created._id);
      s.tags.push(created);
    }
    ids.push(byName.get(name));
  }
  return ids;
}

/**
 * A daily toggles: scoring 'up' completes it, 'down' un-completes it. Sending
 * 'up' to an already-done daily would score it twice, which Habitica accepts
 * and which quietly inflates the streak.
 */
async function onToggleDaily(s, taskId, target) {
  if (!taskId) return;
  const done = target?.closest('[data-action]')?.getAttribute('aria-pressed') === 'true';
  await onScore(s, taskId, done ? 'down' : 'up');
}

async function onScore(s, taskId, direction) {
  if (!taskId || blockedInDemo(s)) return;
  await withBusy(async () => {
    await s.client.scoreTask(taskId, direction);
    await refresh(s);
    await render(s);
  });
}

async function onCopyRecipe(id) {
  const block = document.getElementById(`recipe-${id}`);
  if (!block) return;
  try {
    await navigator.clipboard.writeText(block.textContent);
    showToast('Copied.');
  } catch {
    showToast('Could not reach the clipboard. Select the text and copy it.');
  }
}

function download(filename, payload) {
  const blob = new Blob([payload], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function onDownloadStarterPlan() {
  download('overworld-starter-plan.json', JSON.stringify(starterPlan(), null, 2));
  setStatus('recipeStatus',
    'Downloaded. Preview it with: hbx apply --plan overworld-starter-plan.json', 'ok');
}

async function onExportBundle() {
  const bundle = await exportBundle();
  download('overworld-bundle.json', JSON.stringify(bundle, null, 2));
  setStatus('archiveStatus', 'Exported. Fold it into the archive on disk with `hbx merge`.', 'ok');
}

async function onClearArchive(s) {
  if (!window.confirm(
    'Clear the local archive?\n\nCompleted to-dos older than 30 days exist nowhere else '
    + 'unless you have exported a bundle or run `hbx snapshot`. This cannot be undone.')) return;
  await clearAll();
  await render(s);
  showToast('Local archive cleared.');
}
