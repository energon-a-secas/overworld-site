// ── State ────────────────────────────────────────────────────
// Credentials live under their OWN localStorage key, deliberately outside the
// serialisable app state. Several sites in this fleet carry whole documents in
// the URL hash; if the token ever sat in `state`, one careless share-link
// builder would publish it. shareParams() is an allowlist for that reason, and
// there is a test asserting neither UUID can reach a share URL.

const CRED_KEY = 'overworld.credentials';
const PREFS_KEY = 'overworld.prefs';

export const VIEWS = ['today', 'quests', 'capture', 'stats', 'upkeep', 'recipes', 'archive', 'connect'];

export const state = {
  view: 'today',
  zone: null,              // null = every zone
  credentials: null,       // { userId, apiToken } — never serialised into a URL
  identity: null,          // { name, level, className } from the verify call
  client: null,
  loading: false,
  error: null,
  lastPulledAt: null,
  archiveCounts: null,
  demo: false,             // exploring the shipped sample account
  demoArchive: [],         // its completions, kept in memory so the demo never
                           // writes sample rows into a real visitor's archive
  user: null,
  tasks: [],
  completedTodos: [],
  tags: [],
};

/** tagId -> tagName, rebuilt whenever tags change. */
export function tagNameById(s = state) {
  return new Map((s.tags || []).map((t) => [t.id || t._id, t.name || '']));
}

export function tagIdByName(s = state) {
  return new Map((s.tags || []).map((t) => [t.name || '', t.id || t._id]));
}

export function hasCredentials(s = state) {
  return Boolean(s.credentials?.userId && s.credentials?.apiToken);
}

/** Demo counts as "usable" for routing, but never for writing. */
export function canBrowse(s = state) {
  return hasCredentials(s) || s.demo;
}

export function loadCredentials(s = state) {
  try {
    const raw = localStorage.getItem(CRED_KEY);
    if (raw) s.credentials = JSON.parse(raw);
  } catch { s.credentials = null; }
  return s.credentials;
}

export function saveCredentials(s, credentials) {
  s.credentials = credentials;
  try { localStorage.setItem(CRED_KEY, JSON.stringify(credentials)); } catch { /* private mode */ }
}

/** Wipes the credentials and the derived identity. Does not touch the archive. */
export function forgetCredentials(s = state) {
  s.credentials = null;
  s.identity = null;
  s.client = null;
  s.user = null;
  s.tasks = [];
  s.completedTodos = [];
  s.tags = [];
  try { localStorage.removeItem(CRED_KEY); } catch { /* ignore */ }
}

export function loadPrefs(s = state) {
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    if (raw) {
      const prefs = JSON.parse(raw);
      if (VIEWS.includes(prefs.view)) s.view = prefs.view;
      if (typeof prefs.zone === 'string' || prefs.zone === null) s.zone = prefs.zone;
    }
  } catch { /* ignore corrupted prefs */ }
}

export function savePrefs(s = state) {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify({ view: s.view, zone: s.zone }));
  } catch { /* quota or private mode */ }
}

/**
 * The ONLY things allowed into a shareable URL. An allowlist, not a blocklist:
 * adding a field to `state` must never silently make it shareable.
 */
export function shareParams(s = state) {
  const params = new URLSearchParams();
  if (VIEWS.includes(s.view)) params.set('view', s.view);
  if (s.zone) params.set('zone', String(s.zone));
  return params;
}

export function buildShareUrl(s = state, origin = window.location.origin + window.location.pathname) {
  const params = shareParams(s);
  return String(params) ? `${origin}#${params}` : origin;
}

export function applyUrlState(s = state, hash = window.location.hash) {
  const params = new URLSearchParams(hash.replace(/^#/, ''));
  const view = params.get('view');
  if (VIEWS.includes(view)) s.view = view;
  if (params.has('zone')) s.zone = params.get('zone') || null;
}
