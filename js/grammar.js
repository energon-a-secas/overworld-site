// ── Tag grammar ──────────────────────────────────────────────
// Mirror of tools/hbxlib/grammar.py. Habitica has no location field and no
// custom fields, so zone, area, horizon and kind all live in tag *names*.
// The sigil clusters each facet in Habitica's own flat, alphabetical tag list,
// which is what keeps the scheme readable inside the mobile widget.
//
// Keep this file and grammar.py in step. A divergence means the site and the
// CLI disagree about what a tag means, which is worse than either being wrong.

// `time` came from data, not design: a real account already grouped its dailies
// as "Routine: morning" / "Routine: night" / "Chores: morning". For an account
// that is mostly dailies, when in the day a thing belongs is the primary axis.
export const SIGILS = { '@': 'zone', '+': 'area', '!': 'horizon', '*': 'time', '?': 'kind' };
export const FACETS = ['zone', 'area', 'horizon', 'time', 'kind'];
export const FACET_SIGIL = { zone: '@', area: '+', horizon: '!', time: '*', kind: '?' };

export const FACET_LABEL = {
  zone: 'Zone', area: 'Area', horizon: 'Horizon', time: 'Time', kind: 'Kind',
};
export const FACET_HINT = {
  zone: 'where it can be done',
  area: 'which life it belongs to',
  horizon: 'how urgent it is',
  time: 'what part of the day it belongs to',
  kind: 'what shape of action',
};

export const DEFAULT_VOCAB = {
  zone: ['home', 'office', 'errand', 'mall', 'anywhere'],
  area: ['work', 'personal', 'health', 'money'],
  horizon: ['now', 'week', 'month', 'someday'],
  time: ['morning', 'midday', 'evening', 'night', 'anytime'],
  kind: ['buy', 'call', 'read', 'fix', 'decide'],
};

// Anchored so ordinary punctuation never matches: "milk?" is not a kind tag.
const TOKEN_RE = /^([@+!*?])([a-z0-9][a-z0-9-]*)$/i;

/**
 * Reduce any tag name to a legal facet value: ^[a-z0-9][a-z0-9-]*$.
 *
 * Anything outside that set becomes a hyphen, because a value that does not
 * match TOKEN_RE produces a tag the parser cannot read back. A real account
 * carried "Health + Wellness", and collapsing only whitespace left the embedded
 * "+" in the slug. Accents are folded rather than dropped, so "Organizacion"
 * and "Organizacion" with an accent reach the same value.
 */
export function normalise(value) {
  return String(value || '').trim().toLowerCase()
    .normalize('NFKD').replace(/[\u0300-\u036f]/g, '')
    // One pass is enough: the + already collapses a run of illegal characters
    // into a single hyphen, so there is never a doubled hyphen to squeeze.
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

/** '@errand' -> { facet: 'zone', value: 'errand' }; null for anything else. */
export function facetOf(tagName) {
  const match = TOKEN_RE.exec(String(tagName || '').trim());
  return match ? { facet: SIGILS[match[1]], value: match[2].toLowerCase() } : null;
}

/** ('zone', 'Corner Store') -> '@corner-store' */
export function tagFor(facet, value) {
  const sigil = FACET_SIGIL[facet];
  if (!sigil) throw new Error(`unknown facet ${facet}`);
  return sigil + normalise(value);
}

/**
 * Split capture text into prose and facets.
 * 'buy filters @errand ?buy !week' -> { text: 'buy filters', facets: {...} }
 */
export function parseText(input) {
  const words = [];
  const facets = {};
  for (const word of String(input || '').split(/\s+/)) {
    if (!word) continue;
    const match = TOKEN_RE.exec(word);
    if (match) facets[SIGILS[match[1]]] = match[2].toLowerCase();
    else words.push(word);
  }
  return { text: words.join(' ').trim(), facets };
}

/** Inverse of parseText, emitting facets in declared order. */
export function formatText(text, facets) {
  const parts = [String(text || '').trim()];
  for (const facet of FACETS) {
    if (facets && facets[facet]) parts.push(tagFor(facet, facets[facet]));
  }
  return parts.filter(Boolean).join(' ');
}

/** Facets carried by a task, given a Map of tagId -> tagName. */
export function facetsOfTask(task, tagNameById) {
  const facets = {};
  for (const tagId of task.tags || []) {
    const parsed = facetOf(tagNameById.get(tagId) || '');
    if (parsed && !facets[parsed.facet]) facets[parsed.facet] = parsed.value;
  }
  return facets;
}

/** Every zone value present across a task list, with how many tasks carry it. */
export function zoneCounts(tasks, tagNameById) {
  const counts = new Map();
  for (const task of tasks) {
    const zone = facetsOfTask(task, tagNameById).zone || null;
    counts.set(zone, (counts.get(zone) || 0) + 1);
  }
  return counts;
}
