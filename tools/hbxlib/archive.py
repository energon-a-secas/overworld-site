"""Append-only JSONL archive with dedupe on merge.

Habitica deletes completed to-dos at 30 days and averages daily history away at
60, so the archive is the only place long-range answers can come from. Its one
hard promise is idempotency: running `hbx snapshot` twice, or hourly, must never
duplicate a record. Every stream therefore declares a key, and merge drops any
record whose key is already on disk.

Append-only rather than rewrite-in-place because a truncating writer that dies
mid-write loses history that cannot be re-fetched.
"""

import json
import os
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

# stream name -> function producing the dedupe key for one record
STREAMS = OrderedDict((
    ('todos-completed', lambda r: (r.get('id'), r.get('dateCompleted'))),
    ('task-history', lambda r: (r.get('taskId'), r.get('date'))),
    ('user-history', lambda r: (r.get('kind'), r.get('date'))),
    ('tags', lambda r: (r.get('id'), r.get('name'))),
))


def utc_stamp():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H-%M-%SZ')


def _iso(value):
    """Normalise Habitica's mixed date encodings (ISO string or epoch ms) to ISO."""
    if value in (None, ''):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000.0, timezone.utc).isoformat()
    return str(value)


class MergeResult:
    def __init__(self):
        self.added = OrderedDict((name, 0) for name in STREAMS)
        self.skipped = OrderedDict((name, 0) for name in STREAMS)

    @property
    def total_added(self):
        return sum(self.added.values())

    @property
    def total_skipped(self):
        return sum(self.skipped.values())

    def __str__(self):
        rows = ['  {:<16} +{:<6} (dup {})'.format(name, self.added[name], self.skipped[name])
                for name in STREAMS if self.added[name] or self.skipped[name]]
        return '\n'.join(rows) or '  (nothing)'


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.archive_dir = self.root / 'archive'
        self.snapshot_dir = self.root / 'snapshots'

    def ensure(self):
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

    def path(self, stream):
        return self.archive_dir / '{}.jsonl'.format(stream)

    def read(self, stream):
        path = self.path(stream)
        if not path.is_file():
            return
        with path.open(encoding='utf-8') as handle:
            for line in handle:
                line = line.strip()
                if line:
                    yield json.loads(line)

    def existing_keys(self, stream):
        key_fn = STREAMS[stream]
        return {key_fn(record) for record in self.read(stream)}

    def merge_stream(self, stream, records, result=None):
        """Append records whose key is not already on disk. Returns (added, skipped)."""
        self.ensure()
        key_fn = STREAMS[stream]
        seen = self.existing_keys(stream)
        fresh = []
        skipped = 0
        for record in records:
            key = key_fn(record)
            if key in seen:
                skipped += 1
                continue
            seen.add(key)
            fresh.append(record)

        if fresh:
            blob = ''.join(json.dumps(r, sort_keys=True) + '\n' for r in fresh)
            with self.path(stream).open('a', encoding='utf-8') as handle:
                handle.write(blob)
                handle.flush()
                os.fsync(handle.fileno())

        if result is not None:
            result.added[stream] += len(fresh)
            result.skipped[stream] += skipped
        return len(fresh), skipped

    def merge_all(self, streams):
        result = MergeResult()
        for stream, records in streams.items():
            self.merge_stream(stream, records, result)
        return result

    def write_snapshot(self, payload):
        self.ensure()
        path = self.snapshot_dir / '{}.json'.format(utc_stamp())
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')
        return path

    def counts(self):
        return OrderedDict((name, sum(1 for _ in self.read(name))) for name in STREAMS)

    def bundle(self):
        """One object the site imports. Same records, no reshaping."""
        return {
            'format': 'overworld-bundle',
            'version': 1,
            'generated': datetime.now(timezone.utc).isoformat(),
            'streams': {name: list(self.read(name)) for name in STREAMS},
        }

    def merge_bundle(self, bundle):
        if bundle.get('format') != 'overworld-bundle':
            raise ValueError('not an overworld bundle: format={!r}'.format(bundle.get('format')))
        streams = {name: bundle.get('streams', {}).get(name, []) for name in STREAMS}
        return self.merge_all(streams)


def records_from_snapshot(snapshot):
    """Flatten a raw pull into the four archive streams."""
    user = snapshot.get('user') or {}
    tasks = snapshot.get('tasks') or []
    completed = snapshot.get('completedTodos') or []
    tags = snapshot.get('tags') or []

    todos_completed = [{
        'id': t.get('id') or t.get('_id'),
        'text': t.get('text', ''),
        'notes': t.get('notes', ''),
        'tags': t.get('tags', []),
        'priority': t.get('priority'),
        'dateCompleted': _iso(t.get('dateCompleted')),
        'createdAt': _iso(t.get('createdAt')),
        'date': _iso(t.get('date')),
        'challengeId': (t.get('challenge') or {}).get('id'),
    } for t in completed if (t.get('id') or t.get('_id'))]

    task_history = []
    for task in tasks:
        task_id = task.get('id') or task.get('_id')
        for entry in task.get('history') or []:
            iso = _iso(entry.get('date'))
            if not (task_id and iso):
                continue
            task_history.append({
                'taskId': task_id,
                'type': task.get('type'),
                'text': task.get('text', ''),
                'date': iso,
                'value': entry.get('value'),
                'completed': entry.get('completed'),
                'isDue': entry.get('isDue'),
                'scoredUp': entry.get('scoredUp'),
                'scoredDown': entry.get('scoredDown'),
            })

    user_history = []
    for kind in ('exp', 'todos'):
        for entry in (user.get('history') or {}).get(kind) or []:
            iso = _iso(entry.get('date'))
            if iso:
                user_history.append({'kind': kind, 'date': iso, 'value': entry.get('value')})

    tag_records = [{
        'id': tag.get('id') or tag.get('_id'),
        'name': tag.get('name', ''),
        'seen': snapshot.get('pulledAt'),
    } for tag in tags if (tag.get('id') or tag.get('_id'))]

    return {
        'todos-completed': todos_completed,
        'task-history': task_history,
        'user-history': user_history,
        'tags': tag_records,
    }
