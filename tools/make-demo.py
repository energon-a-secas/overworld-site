#!/usr/bin/env python3
"""Generate data/demo-account.json.

A script rather than a hand-written blob so the dates stay relative to the day
it is regenerated: a demo whose "last 30 days" chart is empty because the fixture
was written in August is worse than no demo.

The account is invented. It is not a copy of anyone's real data, which matters
because this file ships on a public site.
"""

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

random.seed(7)                      # reproducible, so the demo never shifts under review
NOW = datetime.now(timezone.utc)

TAGS = [
    '@home', '@office', '@errand', '@anywhere',
    '+work', '+personal', '+health', '+money', '+hobby',
    '!now', '!week', '!someday',
    '*morning', '*midday', '*evening', '*night', '*anytime',
    '?buy', '?call', '?read', '?fix', '?practice', '?avoid', '?review',
]
TAG_ID = {name: 'demo-tag-{}'.format(i) for i, name in enumerate(TAGS)}


def tags(*names):
    return [TAG_ID[n] for n in names]


DAILIES = [
    ('Stretch and drink water', ['*morning', '+health', '@home'], 41, True, True),
    ('Make the bed', ['*morning', '@home', '?fix'], 41, True, True),
    ('Review the day ahead', ['*morning', '+work', '?review'], 12, True, False),
    ('Inbox to zero', ['*midday', '+work', '@office', '?review'], 6, True, False),
    ('Walk after lunch', ['*midday', '+health', '@anywhere'], 3, True, True),
    ('Practice guitar', ['*evening', '+hobby', '@home', '?practice'], 18, True, False),
    ('Tidy one surface', ['*evening', '@home', '?fix'], 9, True, True),
    ('Read before sleep', ['*night', '+hobby', '?read'], 27, True, False),
    ('Lay out tomorrow', ['*night', '@home'], 27, True, True),
    ('Log the day', ['*anytime', '+personal'], 5, True, False),
    ('Weekly budget check', ['*anytime', '+money', '?review'], 2, False, False),
]

HABITS = [
    ('Take the stairs', ['+health', '@anywhere'], True, False, 8.2),
    ('Read ten pages', ['+hobby', '?read', '@anywhere'], True, False, 12.5),
    ('Ten minutes of sun', ['+health', '@home'], True, False, 4.1),
    ('Say no to one thing', ['+personal'], True, False, 1.4),
    ('Ship something small', ['+work', '@office'], True, False, 6.7),
    ('Screen time under three hours', ['+health', '@anywhere'], True, True, 2.2),
    ('Doomscroll', ['+health', '?avoid', '@anywhere'], False, True, -12.0),
    ('Buy something I will not use', ['+money', '?avoid', '@errand'], False, True, -4.5),
    ('Skip breakfast', ['+health', '?avoid', '@home'], False, True, -21.0),
]

TODOS = [
    ('Replace the kitchen bulb', ['@home', '?fix', '!week'], 3),
    ('Buy coffee filters', ['@errand', '?buy', '!week'], 2),
    ('Call the dentist', ['@anywhere', '?call', '+health', '!now'], 1),
    ('Renew the domain', ['@office', '+money', '?review', '!now'], 4),
    ('Pick up the parcel', ['@errand', '!week'], 5),
    ('Draft the retro notes', ['@office', '+work', '!week'], 6),
    ('Compare bike locks', ['@anywhere', '?review', '+hobby', '!someday'], None),
    ('Sort the photo backlog', ['@home', '+hobby', '!someday'], None),
]

DONE_POOL = [
    ('Pay the electricity bill', ['@anywhere', '+money', '?review']),
    ('Restock cat food', ['@errand', '?buy']),
    ('Book the eye test', ['@anywhere', '?call', '+health']),
    ('Fix the wobbly shelf', ['@home', '?fix']),
    ('Send the invoice', ['@office', '+work']),
    ('Return the library book', ['@errand', '!week']),
    ('Back up the laptop', ['@home', '?fix']),
    ('Water the plants', ['@home', '+personal']),
]


def build():
    tasks = []
    for i, (text, names, streak, is_due, completed) in enumerate(DAILIES):
        tasks.append({
            'id': 'demo-daily-{}'.format(i), 'type': 'daily', 'text': text,
            'notes': '', 'tags': tags(*names), 'streak': streak,
            'isDue': is_due, 'completed': completed, 'priority': 1,
            'history': [], 'frequency': 'daily', 'everyX': 1,
        })
    for i, (text, names, up, down, value) in enumerate(HABITS):
        tasks.append({
            'id': 'demo-habit-{}'.format(i), 'type': 'habit', 'text': text,
            'notes': '', 'tags': tags(*names), 'up': up, 'down': down,
            'value': value, 'priority': 1, 'history': [],
        })
    for i, (text, names, due_in) in enumerate(TODOS):
        task = {
            'id': 'demo-todo-{}'.format(i), 'type': 'todo', 'text': text,
            'notes': '', 'tags': tags(*names), 'completed': False, 'priority': 1,
            'createdAt': (NOW - timedelta(days=20 + i)).isoformat(),
        }
        if due_in is not None:
            task['date'] = (NOW + timedelta(days=due_in)).isoformat()
        tasks.append(task)
    for i, name in enumerate(['Fancy coffee', 'An evening off', 'New headphones']):
        tasks.append({'id': 'demo-reward-{}'.format(i), 'type': 'reward',
                      'text': name, 'tags': [], 'value': 20 + i * 15})

    # Completions across the last 45 days, denser on weekdays, so the chart has
    # a shape rather than a flat line.
    completed = []
    for day in range(45):
        when = NOW - timedelta(days=day)
        count = random.choice([0, 1, 1, 2, 2, 3] if when.weekday() < 5 else [0, 0, 1, 2])
        # The last few days are never empty. A demo whose "day streak" tile reads
        # zero fails to demonstrate the tile, and the streak is the thing the
        # board is trying to make you care about.
        if day < 4:
            count = max(count, 1)
        for n in range(count):
            text, names = random.choice(DONE_POOL)
            completed.append({
                'id': 'demo-done-{}-{}'.format(day, n), 'type': 'todo',
                'text': text, 'notes': '', 'tags': tags(*names), 'completed': True,
                'dateCompleted': (when - timedelta(hours=n * 3 + 2)).isoformat(),
                'createdAt': (when - timedelta(days=random.randint(1, 14))).isoformat(),
                'priority': 1,
            })

    return {
        'format': 'overworld-demo',
        'version': 1,
        'generated': NOW.isoformat(),
        'note': 'Invented sample data. Not anyone real account.',
        'user': {
            '_id': 'demo-user',
            'profile': {'name': 'Wanderer'},
            'stats': {'lvl': 14, 'class': 'rogue', 'hp': 41, 'maxHealth': 50,
                      'mp': 32, 'exp': 118, 'toNextLevel': 260, 'gp': 174},
            'preferences': {'dayStart': 6},
            'history': {
                'exp': [{'date': (NOW - timedelta(days=d)).isoformat(),
                         'value': 40 + d * 3 + random.randint(-8, 8)} for d in range(45, 0, -1)],
                'todos': [{'date': (NOW - timedelta(days=d)).isoformat(),
                           'value': -random.randint(0, 6)} for d in range(45, 0, -1)],
            },
        },
        'tasks': tasks,
        'tags': [{'id': TAG_ID[n], 'name': n} for n in TAGS],
        'completedTodos': [c for c in completed
                           if datetime.fromisoformat(c['dateCompleted']) > NOW - timedelta(days=30)],
        'archivedCompletions': completed,
    }


if __name__ == '__main__':
    out = Path(__file__).resolve().parent.parent / 'data' / 'demo-account.json'
    out.parent.mkdir(exist_ok=True)
    payload = build()
    out.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding='utf-8')
    print('wrote {} ({:.0f} KB)'.format(out, out.stat().st_size / 1024))
    print('  tasks {}, tags {}, completed in window {}, archived {}'.format(
        len(payload['tasks']), len(payload['tags']),
        len(payload['completedTodos']), len(payload['archivedCompletions'])))
