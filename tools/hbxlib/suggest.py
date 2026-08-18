"""Derive facets for tasks that have none, so the boards are not empty on day one.

Two sources, in order of trust:

1. **The tags already on the task.** The user classified it once already;
   "Routine: morning" is a stronger signal about time of day than any keyword.
2. **The task text.** Weaker, and only used for facets the tags did not supply.

Everything produced here is a *suggestion* written to a plan file. Nothing is
applied without `--apply`, and the plan records why each one was proposed so a
wrong guess is visible rather than mysterious.
"""

import re
from collections import OrderedDict

from . import grammar

# (facet, value, keywords). First match per facet wins, so order matters:
# put the specific before the general.
TEXT_RULES = [
    # -- time of day --------------------------------------------------
    ('time', 'morning', ['morning', 'wake', 'breakfast', 'brush', 'dress', 'sunlight']),
    ('time', 'night', ['night', 'bedtime', 'sleep', 'evening', 'relaxation', 'meditation']),

    # -- zone ---------------------------------------------------------
    ('zone', 'errand', ['buy', 'shampoo', 'groceries', 'grocery', 'pharmacy', 'shop',
                        'store', 'market', 'pick up', 'pickup']),
    ('zone', 'home', ['room', 'cleaning', 'clean', 'tidy', 'laundry', 'dishes', 'piano',
                      'meditation', 'relaxation', 'workout', 'teeth', 'dress', 'junk food',
                      'soda', 'sunlight', 'organization']),
    ('zone', 'office', ['meeting', 'report', 'invoice', 'payment', 'payments',
                        'ensurance', 'insurance', 'bupa', 'client']),
    ('zone', 'anywhere', ['phone', 'device', 'screen time', 'email', 'emails', 'account',
                          'accounts', 'read', 'study', 'walk']),

    # -- kind ---------------------------------------------------------
    ('kind', 'buy', ['buy', 'purchase', 'order', 'shampoo']),
    ('kind', 'read', ['read', 'pages', 'book']),
    ('kind', 'write', ['write', 'draft', 'blog', 'post']),
    ('kind', 'review', ['review', 'follow up', 'check', 'compare', 'comparison']),
    ('kind', 'practice', ['practice', 'training', 'train', 'workout', 'exercise',
                          'piano', 'study', 'learn', 'skill']),
    ('kind', 'fix', ['fix', 'harden', 'repair', 'upgrade', 'organize', 'organization']),
    ('kind', 'clean', ['clean', 'cleaning', 'tidy']),

    # -- area ---------------------------------------------------------
    ('area', 'health', ['health', 'workout', 'exercise', 'walk', 'meditation', 'sunlight',
                        'teeth', 'junk food', 'soda', 'mood', 'wellness', 'screen time']),
    ('area', 'hobby', ['piano', 'photography', 'videography', 'picture', 'image', 'anime',
                       'game', 'gaming', 'hobbies', 'music']),
    ('area', 'work', ['work', 'payment', 'payments', 'invoice', 'bupa', 'ensurance',
                      'insurance', 'meeting']),
    ('area', 'learning', ['study', 'learn', 'learning', 'workflow', 'workflows', 'skill',
                          'tech', 'development', 'cheat engine', 'practice']),
    ('area', 'money', ['payment', 'payments', 'bill', 'bills', 'budget', 'invoice']),
]


def _title_of(task):
    return (task.get('text') or '').lower()


def _notes_of(task):
    return (task.get('notes') or '').lower()


def _facets_from_tags(task, tag_name_by_id):
    """Facets the task already carries, plus facets implied by its free-form tags.

    When two tags imply the same facet with *different* values the facet is
    dropped rather than resolved by iteration order. A task carrying both
    "Skill Development" and "Health + Wellness" has no single area, and picking
    whichever came first in the list is a coin flip wearing a suit.
    """
    carried, implied = OrderedDict(), OrderedDict()
    candidates = OrderedDict()

    for tag_id in task.get('tags') or []:
        name = tag_name_by_id.get(tag_id, '')
        parsed = grammar.facet_of(name)
        if parsed:
            carried.setdefault(parsed[0], parsed[1])
            continue
        matches = grammar.suggest_facets(name)
        if len(matches) != 1:
            continue          # an ambiguous free-form tag stays ambiguous
        facet, seed = matches[0]
        candidates.setdefault(facet, []).append((seed, name))

    for facet, options in candidates.items():
        values = {seed for seed, _ in options}
        if len(values) == 1:
            implied[facet] = options[0]
    return carried, implied


def suggest_for_task(task, tag_name_by_id):
    """Return {facet: (value, why, confidence)} for facets the task lacks."""
    carried, implied = _facets_from_tags(task, tag_name_by_id)
    out = OrderedDict()

    for facet, (seed, source) in implied.items():
        if facet not in carried:
            out[facet] = (seed, 'existing tag {!r}'.format(source), 'from-tag')

    # Title first, notes only as a fallback. Weighting them equally produced
    # real misreads: a note saying "Order 66 for dust" made a room-tidying daily
    # look like a purchase, and "Review posible vulnerabilities" turned a
    # harden-the-phone task into a review.
    for source, confidence in ((_title_of(task), 'from-title'),
                               (_notes_of(task), 'from-notes')):
        if not source:
            continue
        for facet, value, keywords in TEXT_RULES:
            if facet in carried or facet in out:
                continue
            for keyword in keywords:
                if re.search(r'\b' + re.escape(keyword), source):
                    out[facet] = (value, '{} matches {!r}'.format(
                        'title' if confidence == 'from-title' else 'notes', keyword),
                        confidence)
                    break

    # A habit Habitica records as down-only is something to avoid, not to do.
    # That is structural, not a guess, so it overrides any kind derived from text.
    if task.get('type') == 'habit' and task.get('down') and not task.get('up'):
        out['kind'] = ('avoid', 'habit is down-only, so it is a vice', 'structural')

    # Dailies with no time signal are the ones you can do whenever, and leaving
    # them unfaceted is what makes a routines board look empty.
    if task.get('type') == 'daily' and 'time' not in carried and 'time' not in out:
        out['time'] = ('anytime', 'daily with no time signal', 'default')

    return out


def build_retags(snapshot, existing_plan=None, pending_retags=()):
    """Produce retag entries plus any tags they require. Adds nothing that exists.

    Two kinds of "already handled" have to be respected or the suggester
    double-tags a facet:

    * **renames** change what a tag the task already carries will be called;
    * **merges** are queued as retag entries that add a tag to the task, and
      those tags do not exist on it yet.

    Missing the second put both `*anytime` and `*morning` on one daily, because
    the merge of "Chores: morning" into `*morning` was invisible here and the
    default-time rule fired anyway.
    """
    tag_name_by_id = {(t.get('id') or t.get('_id')): t.get('name', '')
                      for t in snapshot.get('tags') or []}
    for entry in (existing_plan or {}).get('rename_tags', []):
        tag_name_by_id[entry['tag_id']] = entry['to']

    incoming = {}
    for entry in pending_retags:
        for name in entry.get('add') or []:
            parsed = grammar.facet_of(name)
            if parsed:
                incoming.setdefault(entry['task_id'], {})[parsed[0]] = parsed[1]

    retags, needed = [], OrderedDict()
    for task in snapshot.get('tasks') or []:
        # Rewards are things you buy with gold, not things you do. They have no
        # zone, no time of day and no shape of action, and facets on them would
        # only pollute every board's counts.
        if task.get('type') == 'reward':
            continue
        task_id = task.get('id') or task.get('_id')
        suggestions = suggest_for_task(task, tag_name_by_id)
        for facet in incoming.get(task_id, {}):
            suggestions.pop(facet, None)     # a queued merge already supplies it
        if not suggestions:
            continue
        add, why = [], []
        for facet, (value, reason, confidence) in suggestions.items():
            name = grammar.tag_for(facet, value)
            add.append(name)
            needed[name] = True
            why.append('{}={} ({}, {})'.format(facet, value, confidence, reason))
        retags.append({
            'task_id': task_id,
            'text': (task.get('text') or '')[:70],
            'type': task.get('type'),
            'add': add,
            'remove': [],
            'why': '; '.join(why),
        })

    have = set(tag_name_by_id.values())
    creates = [name for name in needed if name not in have]
    return retags, creates
