"""Archive exporters. The point of the archive is that other tools can read it."""

import csv
import io
import json
from collections import Counter

from . import grammar


def to_json(store):
    return json.dumps(store.bundle(), indent=2, sort_keys=True)


def to_csv(store):
    """Completed to-dos, one row each, facets split into their own columns."""
    buffer = io.StringIO()
    tag_names = {}
    for record in store.read('tags'):
        tag_names[record.get('id')] = record.get('name', '')

    writer = csv.writer(buffer)
    writer.writerow(['dateCompleted', 'text', 'zone', 'area', 'horizon', 'kind',
                     'tags', 'priority', 'createdAt', 'id'])
    for todo in sorted(store.read('todos-completed'),
                       key=lambda r: r.get('dateCompleted') or ''):
        names = [tag_names.get(tid, tid) for tid in todo.get('tags') or []]
        facets = {}
        for name in names:
            parsed = grammar.facet_of(name)
            if parsed:
                facets[parsed[0]] = parsed[1]
        writer.writerow([
            todo.get('dateCompleted') or '', todo.get('text', ''),
            facets.get('zone', ''), facets.get('area', ''),
            facets.get('horizon', ''), facets.get('kind', ''),
            ' '.join(names), todo.get('priority') or '',
            todo.get('createdAt') or '', todo.get('id', ''),
        ])
    return buffer.getvalue()


def to_markdown(store):
    counts = store.counts()
    todos = list(store.read('todos-completed'))
    tag_names = {r.get('id'): r.get('name', '') for r in store.read('tags')}

    by_month = Counter((t.get('dateCompleted') or '')[:7] for t in todos if t.get('dateCompleted'))
    by_zone = Counter()
    for todo in todos:
        zone = '(none)'
        for tid in todo.get('tags') or []:
            parsed = grammar.facet_of(tag_names.get(tid, ''))
            if parsed and parsed[0] == 'zone':
                zone = parsed[1]
                break
        by_zone[zone] += 1

    lines = ['# Overworld archive', '', '## Records', '']
    lines += ['- `{}`: {}'.format(name, count) for name, count in counts.items()]
    lines += ['', '## Completed to-dos by month', '']
    lines += ['- {}: {}'.format(month, count) for month, count in sorted(by_month.items()) if month]
    lines += ['', '## Completed to-dos by zone', '']
    lines += ['- {}: {}'.format(zone, count) for zone, count in by_zone.most_common()]
    return '\n'.join(lines) + '\n'


FORMATS = {'json': to_json, 'csv': to_csv, 'md': to_markdown}
