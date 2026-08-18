"""Execute a reviewed change set against Habitica.

Order matters and is not negotiable:

  1. rename tags   - one request re-labels every task carrying the tag, which is
                     why renaming beats create + retag + delete by a factor of N
  2. create tags   - after renames, so that resolving a review item into a rename
                     ('home' -> '@home') does not race the vocabulary step into
                     creating a second, empty tag with the same name
  3. retag tasks   - per-task adds and removes, needing ids from both steps above
  4. delete tags   - last, because deleting strips the tag from every task

Anything in the plan's `review` list is skipped and reported. Those are the tags
the proposer found genuinely ambiguous, and guessing on the user's behalf is the
one thing this file must never do.
"""

from .api import DryRunViolation


class PlanError(ValueError):
    pass


def validate_plan(plan):
    if not isinstance(plan, dict):
        raise PlanError('plan is not an object')
    if plan.get('format') != 'overworld-plan':
        raise PlanError('not an overworld plan: format={!r}'.format(plan.get('format')))
    if plan.get('version') != 1:
        raise PlanError('unsupported plan version {!r}'.format(plan.get('version')))
    for key in ('create_tags', 'rename_tags', 'delete_tags', 'retag'):
        if not isinstance(plan.get(key, []), list):
            raise PlanError('{} must be a list'.format(key))
    return plan


def count_writes(plan):
    """How many mutating requests this plan will make. Shown before --apply."""
    retag = sum(len(r.get('add') or []) + len(r.get('remove') or [])
                for r in plan.get('retag') or [])
    return (len(plan.get('create_tags') or [])
            + len(plan.get('rename_tags') or [])
            + len(plan.get('delete_tags') or [])
            + retag)


def apply_plan(client, plan, log=print, tag_ids=None):
    """Run the plan. Returns a result dict. Raises DryRunViolation if client is dry-run.

    `tag_ids` maps an existing tag name to its id. Pass one to keep the call
    entirely offline: previewing a change set must not require credentials or a
    network round trip, or a dry run stops being something you can do on a plane.
    """
    validate_plan(plan)
    result = {'created': [], 'renamed': [], 'retagged': 0, 'deleted': [],
              'skipped_review': len(plan.get('review') or []), 'errors': []}

    if tag_ids is None:
        tag_ids = {}
        for tag in client.get_tags() or []:
            tag_ids[tag.get('name', '')] = tag.get('id') or tag.get('_id')
    else:
        tag_ids = dict(tag_ids)

    for entry in plan.get('rename_tags') or []:
        try:
            client.rename_tag(entry['tag_id'], entry['to'])
            tag_ids[entry['to']] = entry['tag_id']
            tag_ids.pop(entry.get('from'), None)
            result['renamed'].append((entry.get('from'), entry['to']))
            log('  ~ renamed {} -> {} ({} tasks)'.format(
                entry.get('from'), entry['to'], entry.get('tasks_affected', '?')))
        except DryRunViolation:
            raise
        except Exception as exc:                       # noqa: BLE001
            result['errors'].append('rename {}: {}'.format(entry.get('from'), exc))

    for name in plan.get('create_tags') or []:
        if name in tag_ids:
            log('  = tag exists, skipping: {}'.format(name))
            continue
        try:
            created = client.create_tag(name)
            tag_ids[name] = created.get('id') or created.get('_id')
            result['created'].append(name)
            log('  + created tag {}'.format(name))
        except DryRunViolation:
            raise
        except Exception as exc:                       # noqa: BLE001 - reported, not swallowed
            result['errors'].append('create {}: {}'.format(name, exc))

    for entry in plan.get('retag') or []:
        task_id = entry.get('task_id')
        for name in entry.get('add') or []:
            tag_id = tag_ids.get(name)
            if not tag_id:
                result['errors'].append('retag {}: no tag named {}'.format(task_id, name))
                continue
            try:
                client.add_tag_to_task(task_id, tag_id)
                result['retagged'] += 1
            except DryRunViolation:
                raise
            except Exception as exc:                   # noqa: BLE001
                result['errors'].append('add {} to {}: {}'.format(name, task_id, exc))
        for name in entry.get('remove') or []:
            tag_id = tag_ids.get(name)
            if not tag_id:
                continue
            try:
                client.remove_tag_from_task(task_id, tag_id)
                result['retagged'] += 1
            except DryRunViolation:
                raise
            except Exception as exc:                   # noqa: BLE001
                result['errors'].append('remove {} from {}: {}'.format(name, task_id, exc))

    for entry in plan.get('delete_tags') or []:
        try:
            client.delete_tag(entry['tag_id'])
            result['deleted'].append(entry.get('name'))
            log('  - deleted tag {} ({})'.format(entry.get('name'), entry.get('why', '')))
        except DryRunViolation:
            raise
        except Exception as exc:                       # noqa: BLE001
            result['errors'].append('delete {}: {}'.format(entry.get('name'), exc))

    return result


def render_plan(plan):
    """Human-readable preview, printed by every dry run."""
    lines = ['Change set ({} writes)'.format(count_writes(plan)), '=' * 40]

    creates = plan.get('create_tags') or []
    if creates:
        lines += ['', 'Create {} tags:'.format(len(creates))]
        lines += ['  + {}'.format(name) for name in creates]

    renames = plan.get('rename_tags') or []
    if renames:
        lines += ['', 'Rename {} tags:'.format(len(renames))]
        lines += ['  ~ {:<24} -> {:<20} ({} tasks) {}'.format(
            e.get('from'), e.get('to'), e.get('tasks_affected', '?'), e.get('why', ''))
            for e in renames]

    retags = plan.get('retag') or []
    if retags:
        lines += ['', 'Retag {} tasks:'.format(len(retags))]
        # "add:" / "drop:" rather than +/-, because the area facet's own sigil
        # is "+" and the two were indistinguishable in the preview.
        for e in retags:
            parts = []
            if e.get('add'):
                parts.append('add ' + ' '.join(e['add']))
            if e.get('remove'):
                parts.append('drop ' + ' '.join(e['remove']))
            lines.append('  * {:<42} {}'.format(
                (e.get('text') or e.get('task_id') or '')[:42], '  '.join(parts)))

    deletes = plan.get('delete_tags') or []
    if deletes:
        lines += ['', 'Delete {} tags:'.format(len(deletes))]
        lines += ['  - {:<24} {}'.format(e.get('name'), e.get('why', '')) for e in deletes]

    review = plan.get('review') or []
    if review:
        lines += ['', 'Needs your decision ({}), skipped by apply:'.format(len(review))]
        for entry in review:
            options = ' | '.join(c['to'] for c in entry.get('candidates') or []) or '(no match)'
            lines.append('  ? {:<24} {:<40} {}'.format(
                entry.get('name'), options, entry.get('why', '')))
    return '\n'.join(lines)
