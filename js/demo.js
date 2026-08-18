// ── Demo account ─────────────────────────────────────────────
// A shipped sample so the boards can be understood before anyone is asked for
// an API token. Asking for a credential to find out whether a tool is worth
// using is the wrong order.
//
// The sample never touches IndexedDB. Its completions live in memory, so
// exploring the demo cannot leave invented rows in a real visitor's archive.

const DEMO_URL = 'data/demo-account.json';

export async function loadDemo(state) {
  const response = await fetch(DEMO_URL);
  if (!response.ok) throw new Error(`could not load the sample account (${response.status})`);
  const demo = await response.json();
  if (demo.format !== 'overworld-demo') throw new Error('sample account file is malformed');

  Object.assign(state, {
    demo: true,
    client: null,
    identity: { name: demo.user.profile.name, level: demo.user.stats.lvl,
                className: demo.user.stats.class },
    user: demo.user,
    tasks: demo.tasks || [],
    completedTodos: demo.completedTodos || [],
    tags: demo.tags || [],
    demoArchive: demo.archivedCompletions || [],
    lastPulledAt: demo.generated,
    error: null,
  });
  return state;
}

export function exitDemo(state) {
  Object.assign(state, {
    demo: false, demoArchive: [], user: null,
    tasks: [], completedTodos: [], tags: [], identity: null,
  });
}
