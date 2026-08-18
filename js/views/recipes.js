// ── Recipes ──────────────────────────────────────────────────
// The part that outlives this site.
//
// A dashboard is worth something; a dashboard you cannot get your data out of
// is worth less than the API it wraps. This view hands over three things a
// visitor can use elsewhere: the taxonomy as a file, prompts that make any LLM
// produce a change set `hbx apply` will accept, and code that reads the export.
//
// The prompts quote the real schema, so what comes back is runnable rather than
// plausible-looking.

import { escHtml } from '../utils.js';
import { FACETS, FACET_LABEL, FACET_HINT, FACET_SIGIL, DEFAULT_VOCAB } from '../grammar.js';

const PROMPTS = [
  {
    id: 'map-tags',
    title: 'Map my existing tags onto the grammar',
    when: 'You have a pile of free-form tags and want them sorted into facets.',
    body: () => `You are helping me reorganise a Habitica account onto a five-facet tag grammar.

THE GRAMMAR
Each facet is a tag whose name starts with a sigil. A task carries at most one
value per facet.
${FACETS.map((f) => `  ${FACET_SIGIL[f]}  ${FACET_LABEL[f].padEnd(8)} ${FACET_HINT[f]}
      vocabulary: ${DEFAULT_VOCAB[f].map((v) => FACET_SIGIL[f] + v).join(' ')}`).join('\n')}

A value must match ^[a-z0-9][a-z0-9-]*$. Lowercase, hyphens for spaces, no
accents, no punctuation. "Health + Wellness" becomes "health", not
"health-+-wellness".

MY TAGS
<paste your tag list here, one per line>

WHAT I WANT BACK
A single JSON object, no prose around it:

{
  "format": "overworld-plan",
  "version": 1,
  "create_tags": ["@home", "..."],
  "rename_tags": [
    {"tag_id": "", "from": "Work", "to": "+work", "facet": "area",
     "confidence": "single-match", "why": "one-line reason", "tasks_affected": 0}
  ],
  "delete_tags": [],
  "retag": [],
  "review": [
    {"tag_id": "", "name": "home", "tasks_affected": 0,
     "candidates": [{"facet": "zone", "to": "@home", "matched": "home"},
                    {"facet": "area", "to": "+home", "matched": "home"}],
     "why": "ambiguous, pick one"}
  ]
}

RULES
1. If a tag maps cleanly to exactly one facet, put it in rename_tags.
2. If it could belong to two facets, put it in review with BOTH candidates.
   Do not choose for me. A wrong guess rewrites real tasks invisibly.
3. Collapse to the canonical vocabulary word, not to a slug of the whole name.
4. If two tags map to the same target, say so in "why": that is a merge, not
   two renames, or I end up with two tags of the same name.
5. Leave tag_id empty. I will fill it from my account.`,
  },
  {
    id: 'suggest-facets',
    title: 'Suggest facets for my untagged tasks',
    when: 'Your tags are sorted but half your tasks carry none of them.',
    body: () => `Given the tag grammar below and a list of my Habitica tasks, propose which
facet tags each task should carry.

FACETS
${FACETS.map((f) => `  ${FACET_SIGIL[f]} ${FACET_LABEL[f]}: ${FACET_HINT[f]}`).join('\n')}

MY TASKS
<paste as: type | text | notes | current tags>

RETURN a JSON array, no prose:
[{"task_id": "", "text": "...", "type": "daily",
  "add": ["@home", "*morning"], "remove": [],
  "why": "title mentions 'bed', which is a home task done in the morning"}]

RULES
1. Judge from the TITLE first. Notes are context and are often misleading:
   a note reading "Order 66 for dust" is a joke, not a purchase.
2. At most one value per facet per task.
3. A habit that can only be scored down is a vice: give it ?avoid.
4. Rewards get nothing. They are prizes, not actions.
5. If you cannot tell, leave the facet out. An empty facet is honest; a wrong
   one is invisible.`,
  },
  {
    id: 'weekly-review',
    title: 'Run a weekly review from my archive',
    when: 'You have an exported bundle and want to know what it says.',
    body: () => `Here is an export from my Habitica archive. Each record in
streams["todos-completed"] is a task I finished, with the tags it carried and
the timestamp it was completed at. Tag names use sigils: @ zone, + area,
! horizon, * time of day, ? kind.

<paste overworld-bundle.json here, or just the todos-completed array>

Tell me, in this order and with the numbers you used:
1. How many things I finished per week, and whether the trend is up or down.
2. Which life area (+) took the most of my completions, and which took least.
3. Which zone (@) I actually get things done in, versus where I said they belong.
4. Any task that sat open a long time before I finished it.
5. One change to my week that the data supports. Only one, and say what number
   made you suggest it.

Do not congratulate me and do not invent a number I did not give you. If the
data is too thin to answer one of these, say so for that item.`,
  },
  {
    id: 'design-routine',
    title: 'Design my routine blocks',
    when: 'Your dailies exist but nothing says when in the day they belong.',
    body: () => `I want to assign each of my Habitica dailies to a part of the day, using
these tags: ${DEFAULT_VOCAB.time.map((v) => '*' + v).join(' ')}.

MY DAILIES
<paste as: text | current tags | streak | due today?>

Return a JSON array of {"text": "...", "add": ["*morning"], "why": "..."}.

RULES
1. Anchor to things that already have a fixed time: waking, meals, sleep.
2. Do not stack more than about four dailies into one block. If a block is
   overloaded, say which one you would move and why.
3. Use *anytime only when the task genuinely has no natural slot, not as a
   default for the ones you find hard to place.
4. Tell me if two dailies are really the same habit written twice.`,
  },
];

const SNIPPETS = [
  {
    id: 'py-weekly',
    title: 'Completions per week, from a bundle',
    lang: 'python',
    code: `import json, collections
from datetime import datetime

bundle = json.load(open('overworld-bundle.json'))
weeks = collections.Counter()
for todo in bundle['streams']['todos-completed']:
    done = todo.get('dateCompleted')
    if not done:
        continue
    when = datetime.fromisoformat(done.replace('Z', '+00:00'))
    weeks[when.strftime('%G-W%V')] += 1

for week, count in sorted(weeks.items()):
    print(f'{week}  {"#" * count} {count}')`,
  },
  {
    id: 'py-facet',
    title: 'Split completions by facet',
    lang: 'python',
    code: `import json, collections, re

SIGILS = {'@': 'zone', '+': 'area', '!': 'horizon', '*': 'time', '?': 'kind'}
TOKEN = re.compile(r'^([@+!*?])([a-z0-9][a-z0-9-]*)$')

bundle = json.load(open('overworld-bundle.json'))
names = {t['id']: t['name'] for t in bundle['streams']['tags']}
by_facet = collections.defaultdict(collections.Counter)

for todo in bundle['streams']['todos-completed']:
    for tag_id in todo.get('tags', []):
        m = TOKEN.match(names.get(tag_id, ''))
        if m:
            by_facet[SIGILS[m.group(1)]][m.group(2)] += 1

for facet, counts in by_facet.items():
    print(facet, dict(counts.most_common()))`,
  },
  {
    id: 'jq-recent',
    title: 'What did I finish this week (jq)',
    lang: 'bash',
    code: `jq -r --arg since "$(date -v-7d +%Y-%m-%d)" '
  .streams["todos-completed"][]
  | select(.dateCompleted >= $since)
  | [.dateCompleted[0:10], .text] | @tsv
' overworld-bundle.json | sort`,
  },
  {
    id: 'sh-pipeline',
    title: 'The whole pipeline',
    lang: 'bash',
    code: `export HABITICA_USER_ID=... HABITICA_API_TOKEN=...

python3 tools/hbx.py snapshot                       # archive before the 30-day purge
python3 tools/hbx.py analyze                        # what the account looks like
python3 tools/hbx.py plan --suggest -o plan.json    # propose, write nothing
$EDITOR plan.json                                   # resolve the review list
python3 tools/hbx.py apply --plan plan.json         # preview, offline
python3 tools/hbx.py apply --plan plan.json --apply # write
python3 tools/hbx.py export --format csv -o done.csv`,
  },
];

export function render(state) {
  return `
  <section class="section" aria-labelledby="recipes-title">
    <div class="section__titles">
      <h2 class="section__title" id="recipes-title">Recipes</h2>
      <p class="section__lead">
        The taxonomy, the prompts and the code, so you can take this somewhere else.
        A dashboard you cannot get your data out of is worth less than the API it wraps.
      </p>
    </div>

    <div class="card stack stack--tight">
      <h3 class="card__title">The starter taxonomy</h3>
      <p class="muted">
        ${FACETS.length} facets, ${FACETS.reduce((n, f) => n + DEFAULT_VOCAB[f].length, 0)}
        starting tags. Download it as a change set, point it at your own account,
        read the diff, then apply.
      </p>
      <table class="grammar-table">
        <thead><tr><th>Facet</th><th>Sigil</th><th>Answers</th><th>Vocabulary</th></tr></thead>
        <tbody>
          ${FACETS.map((f) => `
            <tr>
              <td>${FACET_LABEL[f]}</td>
              <td><code>${FACET_SIGIL[f]}</code></td>
              <td class="muted">${FACET_HINT[f]}</td>
              <td>${DEFAULT_VOCAB[f].map((v) => `<code>${FACET_SIGIL[f]}${escHtml(v)}</code>`).join(' ')}</td>
            </tr>`).join('')}
        </tbody>
      </table>
      <div class="toolbar">
        <button type="button" class="btn btn--primary btn--sm" id="recipeDownloadPlan">
          Download starter plan
        </button>
        <span class="muted" id="recipeStatus" role="status" aria-live="polite"></span>
      </div>
    </div>

    <h3 class="visually-quiet">Prompts</h3>
    <p class="muted recipes-intro">
      Each one quotes the real plan schema, so what comes back is something
      <code>hbx apply</code> accepts rather than something that merely looks right.
    </p>
    ${PROMPTS.map(renderCopyCard).join('')}

    <h3 class="visually-quiet">Code</h3>
    ${SNIPPETS.map(renderSnippet).join('')}
  </section>`;
}

function renderCopyCard(prompt) {
  return `
  <div class="card recipe">
    <div class="recipe__head">
      <h4 class="card__title">${escHtml(prompt.title)}</h4>
      <button type="button" class="btn btn--ghost btn--sm" data-copy="${prompt.id}">Copy</button>
    </div>
    <p class="muted">${escHtml(prompt.when)}</p>
    <pre class="recipe__body" id="recipe-${prompt.id}"><code>${escHtml(prompt.body())}</code></pre>
  </div>`;
}

function renderSnippet(snippet) {
  return `
  <div class="card recipe">
    <div class="recipe__head">
      <h4 class="card__title">${escHtml(snippet.title)}
        <span class="badge">${escHtml(snippet.lang)}</span></h4>
      <button type="button" class="btn btn--ghost btn--sm" data-copy="${snippet.id}">Copy</button>
    </div>
    <pre class="recipe__body" id="recipe-${snippet.id}"><code>${escHtml(snippet.code)}</code></pre>
  </div>`;
}

/** The starter taxonomy as a change set `hbx apply` will accept. */
export function starterPlan() {
  return {
    format: 'overworld-plan',
    version: 1,
    generated: new Date().toISOString(),
    note: 'Starter vocabulary only. It creates tags and touches nothing you already have.',
    summary: { create_tags: FACETS.reduce((n, f) => n + DEFAULT_VOCAB[f].length, 0),
               rename_tags: 0, delete_tags: 0, retag: 0, needs_review: 0 },
    create_tags: FACETS.flatMap((f) => DEFAULT_VOCAB[f].map((v) => FACET_SIGIL[f] + v)),
    rename_tags: [], delete_tags: [], retag: [], review: [],
  };
}
