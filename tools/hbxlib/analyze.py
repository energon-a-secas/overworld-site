"""Read the account and report what is actually there, then propose a taxonomy.

The proposal never guesses. A tag whose name maps to exactly one facet becomes a
rename; a tag that maps to two ('home' is both a place and a life area) goes to a
`review` list for the user to resolve by hand. Silently picking one would rewrite
real tasks on a coin flip, and the wrong choice is invisible afterwards.
"""

from collections import Counter, OrderedDict
from datetime import datetime, timedelta, timezone

from . import grammar
from . import suggest as suggest_mod

STALE_TODO_DAYS = 90


def _parse_iso(value):
    if not value:
        return None
    text = str(value).replace('Z', '+00:00')
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def analyze(snapshot, now=None):
    now = now or datetime.now(timezone.utc)
    tasks = snapshot.get('tasks') or []
    completed = snapshot.get('completedTodos') or []
    tags = snapshot.get('tags') or []

    tag_by_id = {(t.get('id') or t.get('_id')): t.get('name', '') for t in tags}
    usage = Counter()
    for task in tasks + completed:
        for tag_id in task.get('tags') or []:
            usage[tag_id] += 1

    counts = Counter(t.get('type', 'unknown') for t in tasks)
    counts['completedTodos'] = len(completed)

    in_grammar, free_form = [], []
    for tag_id, name in tag_by_id.items():
        (in_grammar if grammar.facet_of(name) else free_form).append((tag_id, name))

    facet_coverage = OrderedDict()
    for facet in grammar.FACETS:
        tagged = 0
        for task in tasks:
            names = [tag_by_id.get(tid, '') for tid in task.get('tags') or []]
            if any((grammar.facet_of(n) or (None,))[0] == facet for n in names):
                tagged += 1
        facet_coverage[facet] = {'tagged': tagged, 'of': len(tasks)}

    open_todos = [t for t in tasks if t.get('type') == 'todo']
    stale_cutoff = now - timedelta(days=STALE_TODO_DAYS)

    hygiene = {
        'untagged_tasks': [_brief(t) for t in tasks if not t.get('tags')],
        'todos_without_due': [_brief(t) for t in open_todos if not t.get('date')],
        'stale_todos': [_brief(t) for t in open_todos
                        if (_parse_iso(t.get('createdAt')) or now) < stale_cutoff],
        'dead_dailies': [_brief(t) for t in tasks
                         if t.get('type') == 'daily' and t.get('isDue')
                         and not t.get('streak')],
        # A free-form tag nobody uses is cruft. An unused *grammar* tag is an
        # empty slot in the vocabulary (no errands pending right now), so the two
        # are reported apart and only the first is ever proposed for deletion.
        'orphan_tags': [{'id': tid, 'name': name}
                        for tid, name in tag_by_id.items()
                        if usage[tid] == 0 and not grammar.facet_of(name)],
        'unused_vocabulary': [{'id': tid, 'name': name}
                              for tid, name in tag_by_id.items()
                              if usage[tid] == 0 and grammar.facet_of(name)],
    }

    return {
        'generated': now.isoformat(),
        'counts': dict(counts),
        'tags': {
            'total': len(tag_by_id),
            'in_grammar': len(in_grammar),
            'free_form': len(free_form),
            'usage': {tag_by_id[tid]: usage[tid] for tid in tag_by_id},
        },
        'facet_coverage': facet_coverage,
        'hygiene': hygiene,
        '_tag_by_id': tag_by_id,
        '_usage': dict(usage),
    }


def _brief(task):
    return {
        'id': task.get('id') or task.get('_id'),
        'type': task.get('type'),
        'text': (task.get('text') or '')[:80],
    }


def propose_plan(snapshot, report=None, now=None, with_suggestions=False):
    """Turn the report into a reviewable change set. Writes nothing."""
    now = now or datetime.now(timezone.utc)
    report = report or analyze(snapshot, now)
    tag_by_id = report['_tag_by_id']
    usage = report['_usage']
    tasks = snapshot.get('tasks') or []
    completed = snapshot.get('completedTodos') or []

    # Map each free-form tag onto the CANONICAL vocabulary value, not onto a slug
    # of its own name. "Health + Wellness" becomes "+health", not
    # "+health-wellness": a taxonomy whose every term is bespoke is not a
    # taxonomy, and the first version left the account holding both.
    #
    # Collapsing to canon means two tags can land on the same target. That is a
    # merge, not a rename, and Habitica would happily hold two tags with the
    # same name if we renamed both. Merges are expressed with the machinery that
    # already exists: add the target to every affected task, then delete the
    # source (deleting a tag strips it from every task, so no removal step).
    review, delete = [], []
    targets = OrderedDict()      # target name -> [(tag_id, original name, seed)]

    for tag_id, name in sorted(tag_by_id.items(), key=lambda kv: kv[1].lower()):
        if grammar.facet_of(name):
            continue
        if usage.get(tag_id, 0) == 0:
            delete.append({'tag_id': tag_id, 'name': name, 'why': 'no task carries it'})
            continue
        candidates = grammar.suggest_facets(name)
        if len(candidates) == 1:
            facet, seed = candidates[0]
            targets.setdefault(grammar.tag_for(facet, seed), []).append((tag_id, name, seed))
        else:
            review.append({
                'tag_id': tag_id, 'name': name,
                'candidates': [{'facet': f, 'to': grammar.tag_for(f, s), 'matched': s}
                               for f, s in candidates],
                'tasks_affected': usage.get(tag_id, 0),
                'why': 'ambiguous, pick one and move it into rename_tags'
                       if candidates else 'outside the grammar; leave it alone unless '
                                          'it really is one of the four facets',
            })

    tasks_by_tag = {}
    for task in tasks + completed:
        for tag_id in task.get('tags') or []:
            tasks_by_tag.setdefault(tag_id, []).append(task)

    existing = set(tag_by_id.values())
    rename, merge_retags, merge_creates = [], [], []

    for target, sources in targets.items():
        # One source and the name is free: a rename re-labels every task in a
        # single request, which beats N retags by a factor of N.
        if len(sources) == 1 and target not in existing:
            tag_id, name, seed = sources[0]
            rename.append({
                'tag_id': tag_id, 'from': name, 'to': target,
                'facet': grammar.facet_of(target)[0], 'confidence': 'single-match',
                'why': "'{}' matches the {} vocabulary".format(
                    seed, grammar.facet_of(target)[0]),
                'tasks_affected': usage.get(tag_id, 0),
            })
            continue

        if target not in existing:
            merge_creates.append(target)
        for tag_id, name, seed in sources:
            for task in tasks_by_tag.get(tag_id, []):
                merge_retags.append({
                    'task_id': task.get('id') or task.get('_id'),
                    'text': (task.get('text') or '')[:70],
                    'type': task.get('type'),
                    'add': [target], 'remove': [],
                    'why': 'merging {!r} into {}'.format(name, target),
                })
            delete.append({'tag_id': tag_id, 'name': name,
                           'why': 'merged into {}'.format(target)})

    taken = set(tag_by_id.values()) | {r['to'] for r in rename}
    create = [name for name in merge_creates if name not in taken]
    taken.update(create)
    create += [grammar.tag_for(facet, value)
               for facet, values in grammar.DEFAULT_VOCAB.items()
               for value in values
               if grammar.tag_for(facet, value) not in taken]

    retags = list(merge_retags)
    if with_suggestions:
        draft = {'rename_tags': rename}
        suggested, extra_creates = suggest_mod.build_retags(
            snapshot, draft, pending_retags=merge_retags)
        retags += suggested
        for name in extra_creates:
            if name not in create and name not in taken:
                create.append(name)

    return {
        'format': 'overworld-plan',
        'version': 1,
        'generated': now.isoformat(),
        'summary': {
            'create_tags': len(create),
            'rename_tags': len(rename),
            'delete_tags': len(delete),
            'needs_review': len(review),
            'retag': len(retags),
        },
        'create_tags': create,
        'rename_tags': rename,
        'delete_tags': delete,
        'retag': retags,
        'review': review,
    }


def render_report(report):
    lines = ['Account', '-------']
    for key in ('habit', 'daily', 'todo', 'reward', 'completedTodos'):
        if key in report['counts']:
            lines.append('  {:<16} {}'.format(key, report['counts'][key]))

    tags = report['tags']
    lines += ['', 'Tags', '----',
              '  {:<16} {}'.format('total', tags['total']),
              '  {:<16} {}'.format('in grammar', tags['in_grammar']),
              '  {:<16} {}'.format('free form', tags['free_form']),
              '', 'Facet coverage', '--------------']
    for facet, cov in report['facet_coverage'].items():
        pct = (100.0 * cov['tagged'] / cov['of']) if cov['of'] else 0.0
        lines.append('  {:<16} {}/{} ({:.0f}%)'.format(facet, cov['tagged'], cov['of'], pct))

    lines += ['', 'Hygiene', '-------']
    for key, items in sorted(report['hygiene'].items()):
        lines.append('  {:<20} {}'.format(key.replace('_', ' '), len(items)))
    return '\n'.join(lines)
