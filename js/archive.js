// ── Local archive (IndexedDB) ────────────────────────────────
// Habitica hard-deletes completed to-dos at 30 days and averages daily history
// away at 60, so anything not captured before then is gone. tools/hbx.py is the
// primary archivist; this is the safety net for stretches where it has not run,
// and the reader for bundles it produces.
//
// Same stream names and same dedupe keys as hbxlib/archive.py, so a bundle
// round-trips in either direction without duplicating a single record.

const DB_NAME = 'overworld';
const DB_VERSION = 1;
const STORE = 'records';

export const STREAMS = ['todos-completed', 'task-history', 'user-history', 'tags'];

const KEY_OF = {
  'todos-completed': (r) => `${r.id}|${r.dateCompleted}`,
  'task-history': (r) => `${r.taskId}|${r.date}`,
  'user-history': (r) => `${r.kind}|${r.date}`,
  tags: (r) => `${r.id}|${r.name}`,
};

let dbPromise = null;

function openDb() {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE)) {
        const store = db.createObjectStore(STORE, { keyPath: '_k' });
        store.createIndex('stream', 'stream', { unique: false });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  return dbPromise;
}

/**
 * Append records that are not already stored.
 * Returns { added, skipped }. `add` throws ConstraintError on a duplicate key,
 * which is exactly the dedupe signal, so it is counted rather than treated as
 * an error.
 */
export async function mergeRecords(stream, records) {
  if (!records || !records.length) return { added: 0, skipped: 0 };
  const db = await openDb();
  const keyOf = KEY_OF[stream];
  if (!keyOf) throw new Error(`unknown stream ${stream}`);

  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite');
    const store = tx.objectStore(STORE);
    let added = 0;
    let skipped = 0;

    for (const record of records) {
      const request = store.add({ ...record, _k: `${stream}:${keyOf(record)}`, stream });
      request.onsuccess = () => { added += 1; };
      request.onerror = (event) => {
        skipped += 1;
        event.preventDefault();     // a duplicate must not abort the transaction
        event.stopPropagation();
      };
    }

    tx.oncomplete = () => resolve({ added, skipped });
    tx.onerror = () => reject(tx.error);
  });
}

export async function readStream(stream) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const request = db.transaction(STORE, 'readonly')
      .objectStore(STORE).index('stream').getAll(IDBKeyRange.only(stream));
    request.onsuccess = () => resolve(request.result.map(({ _k, stream: _s, ...rest }) => rest));
    request.onerror = () => reject(request.error);
  });
}

export async function counts() {
  const out = {};
  for (const stream of STREAMS) out[stream] = (await readStream(stream)).length;
  return out;
}

export async function clearAll() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite');
    tx.objectStore(STORE).clear();
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

/** Same shape hbx bundle writes, so `hbx merge` accepts this file unchanged. */
export async function exportBundle() {
  const streams = {};
  for (const stream of STREAMS) streams[stream] = await readStream(stream);
  return {
    format: 'overworld-bundle',
    version: 1,
    generated: new Date().toISOString(),
    streams,
  };
}

export async function importBundle(bundle) {
  if (!bundle || bundle.format !== 'overworld-bundle') {
    throw new Error('not an Overworld bundle');
  }
  const total = { added: 0, skipped: 0 };
  for (const stream of STREAMS) {
    const result = await mergeRecords(stream, bundle.streams?.[stream] || []);
    total.added += result.added;
    total.skipped += result.skipped;
  }
  return total;
}

const iso = (value) => {
  if (value === null || value === undefined || value === '') return null;
  if (typeof value === 'number') return new Date(value).toISOString();
  return String(value);
};

/** Flatten a live pull into the four streams. Mirrors records_from_snapshot(). */
export function recordsFromPull({ user, tasks = [], completedTodos = [], tags = [] }) {
  const todosCompleted = completedTodos
    .filter((t) => t.id || t._id)
    .map((t) => ({
      id: t.id || t._id,
      text: t.text || '',
      notes: t.notes || '',
      tags: t.tags || [],
      priority: t.priority ?? null,
      dateCompleted: iso(t.dateCompleted),
      createdAt: iso(t.createdAt),
      date: iso(t.date),
      challengeId: t.challenge?.id ?? null,
    }));

  const taskHistory = [];
  for (const task of tasks) {
    const taskId = task.id || task._id;
    for (const entry of task.history || []) {
      const date = iso(entry.date);
      if (!taskId || !date) continue;
      taskHistory.push({
        taskId,
        type: task.type,
        text: task.text || '',
        date,
        value: entry.value,
        completed: entry.completed,
        isDue: entry.isDue,
        scoredUp: entry.scoredUp,
        scoredDown: entry.scoredDown,
      });
    }
  }

  const userHistory = [];
  for (const kind of ['exp', 'todos']) {
    for (const entry of user?.history?.[kind] || []) {
      const date = iso(entry.date);
      if (date) userHistory.push({ kind, date, value: entry.value });
    }
  }

  const tagRecords = tags
    .filter((t) => t.id || t._id)
    .map((t) => ({ id: t.id || t._id, name: t.name || '', seen: new Date().toISOString() }));

  return {
    'todos-completed': todosCompleted,
    'task-history': taskHistory,
    'user-history': userHistory,
    tags: tagRecords,
  };
}

/** Merge a whole pull. Called on every visit, which is the safety net. */
export async function archivePull(pull) {
  const records = recordsFromPull(pull);
  const total = { added: 0, skipped: 0 };
  for (const stream of STREAMS) {
    const result = await mergeRecords(stream, records[stream]);
    total.added += result.added;
    total.skipped += result.skipped;
  }
  return total;
}
