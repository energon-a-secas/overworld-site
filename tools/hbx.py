#!/usr/bin/env python3
"""hbx — the Overworld archivist.

Habitica hard-deletes completed to-dos after 30 days and averages daily history
away after 60. This pulls the account before that happens and keeps the result in
an append-only, deduped archive that other tools can read.

    hbx snapshot                     pull and merge (safe to run hourly)
    hbx analyze                      what is in the account right now
    hbx plan -o plan.json            propose a taxonomy, write nothing
    hbx apply --plan plan.json       preview it;  add --apply to actually write
    hbx export --format csv          hand the archive to something else

Pure standard library, so it runs anywhere Python 3.8+ does with no install step.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hbxlib import analyze as analyze_mod          # noqa: E402
from hbxlib import archive as archive_mod          # noqa: E402
from hbxlib import exports, grammar, plans, reminders  # noqa: E402
from hbxlib.api import ApiError, DryRunViolation, HabiticaClient, RateLimiter  # noqa: E402
from hbxlib.config import ConfigError, archive_root, resolve_credentials  # noqa: E402

# What a snapshot keeps from GET /user. An allowlist, not a blocklist: the user
# object carries apiToken, auth.local.hashed_password, salt and webhooks, and a
# snapshot is written to disk and later handed to a browser. Guessing which
# fields the server happens to strip is not a safety model.
USER_ALLOWLIST = {
    '_id': True, 'id': True,
    'stats': True, 'history': True, 'tasksOrder': True, 'achievements': True,
    'profile': {'name': True},
    'party': {'_id': True},
    'auth': {'timestamps': True},
    'preferences': {'dayStart': True, 'timezoneOffset': True,
                    'timezoneOffsetAtLastCron': True, 'language': True},
}


def prune(value, spec):
    """Keep only what `spec` allows. spec True keeps the subtree wholesale."""
    if spec is True:
        return value
    if not isinstance(value, dict):
        return None
    kept = {}
    for key, sub in spec.items():
        if key in value:
            pruned = prune(value[key], sub)
            if pruned is not None:
                kept[key] = pruned
    return kept


def build_client(args, dry_run=True, need_credentials=True):
    """Build the API client.

    A dry run never sends a request, so it must not demand a credential either.
    Requiring one meant `hbx apply --plan starter.json` printed the whole preview
    and then exited 2, which is precisely the flow someone follows after
    downloading a starter plan and before they have an account set up.
    """
    if need_credentials:
        user_id, token = resolve_credentials()
    else:
        try:
            user_id, token = resolve_credentials()
        except ConfigError:
            user_id, token = 'dry-run', 'dry-run'
    return HabiticaClient(user_id, token, base_url=args.base_url,
                          limiter=RateLimiter(), dry_run=dry_run)


def pull(client):
    """Four requests: the whole account. Well inside the 30/minute budget."""
    return {
        'pulledAt': datetime.now(timezone.utc).isoformat(),
        'user': prune(client.get_user(), USER_ALLOWLIST),
        'tasks': client.get_tasks(with_history=True),
        'completedTodos': client.get_tasks(task_type='completedTodos'),
        'tags': client.get_tags(),
    }


def load_snapshot(store, path=None):
    if path:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    snapshots = sorted(store.snapshot_dir.glob('*.json'))
    if not snapshots:
        raise SystemExit('no snapshot on disk yet. Run `hbx snapshot` first, '
                         'or pass --snapshot <file>.')
    return json.loads(snapshots[-1].read_text(encoding='utf-8'))


# -- commands -------------------------------------------------------------

def cmd_snapshot(args, store):
    client = build_client(args, dry_run=True)
    snapshot = pull(client)
    path = store.write_snapshot(snapshot)
    result = store.merge_all(archive_mod.records_from_snapshot(snapshot))

    print('snapshot {}'.format(path))
    print('merged into {}'.format(store.archive_dir))
    print(result)
    print('  {:<16} +{} added, {} already archived'.format(
        'total', result.total_added, result.total_skipped))
    if client.rate_remaining is not None:
        print('  rate budget left this minute: {}'.format(client.rate_remaining))
    return 0


def cmd_status(args, store):
    print('archive {}'.format(store.root))
    for name, count in store.counts().items():
        print('  {:<16} {}'.format(name, count))
    snapshots = sorted(store.snapshot_dir.glob('*.json'))
    print('  {:<16} {}{}'.format('snapshots', len(snapshots),
                                 ' (latest {})'.format(snapshots[-1].name) if snapshots else ''))
    return 0


def cmd_analyze(args, store):
    snapshot = (pull(build_client(args)) if args.live
                else load_snapshot(store, args.snapshot))
    report = analyze_mod.analyze(snapshot)
    if args.json:
        report.pop('_tag_by_id', None)
        report.pop('_usage', None)
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(analyze_mod.render_report(report))
    return 0


def cmd_plan(args, store):
    snapshot = (pull(build_client(args)) if args.live
                else load_snapshot(store, args.snapshot))
    plan = analyze_mod.propose_plan(snapshot, with_suggestions=args.suggest)
    print(plans.render_plan(plan), file=sys.stderr)
    Path(args.out).write_text(json.dumps(plan, indent=2, sort_keys=True), encoding='utf-8')
    print('\nplan written to {}'.format(args.out), file=sys.stderr)
    print('Edit it, move anything from "review" into "rename_tags", then:', file=sys.stderr)
    print('  hbx apply --plan {}            # preview'.format(args.out), file=sys.stderr)
    print('  hbx apply --plan {} --apply    # write'.format(args.out), file=sys.stderr)
    return 0


def cmd_apply(args, store):
    plan = json.loads(Path(args.plan).read_text(encoding='utf-8'))
    plans.validate_plan(plan)
    writes = plans.count_writes(plan)

    print(plans.render_plan(plan))
    print()

    if not args.apply:
        # Offline on purpose: tag_ids is supplied so nothing here touches the
        # network, and the run still exercises the real gate rather than
        # asserting it in a comment.
        client = build_client(args, dry_run=True, need_credentials=False)
        try:
            plans.apply_plan(client, plan, log=lambda *_: None, tag_ids={})
        except DryRunViolation:
            pass
        sent = sum(1 for method, _ in client.request_log if method != 'GET')
        print('DRY RUN. {} writes withheld, {} sent.'.format(writes, sent))
        print('  first blocked: {} {}'.format(*client.suppressed_log[0])
              if client.suppressed_log else '  nothing to write')
        print('Re-run with --apply to send them.')
        return 0 if sent == 0 else 1

    print('Backing up before writing...')
    client = build_client(args, dry_run=False)
    snapshot = pull(client)
    backup = store.write_snapshot(snapshot)
    store.merge_all(archive_mod.records_from_snapshot(snapshot))
    print('  backup {}'.format(backup))

    print('Applying {} writes...'.format(writes))
    result = plans.apply_plan(client, plan)
    print('\ncreated {}, renamed {}, retagged {}, deleted {}, skipped for review {}'.format(
        len(result['created']), len(result['renamed']), result['retagged'],
        len(result['deleted']), result['skipped_review']))
    for error in result['errors']:
        print('  ERROR {}'.format(error), file=sys.stderr)
    return 1 if result['errors'] else 0


def cmd_bundle(args, store):
    Path(args.out).write_text(json.dumps(store.bundle(), indent=2, sort_keys=True),
                              encoding='utf-8')
    counts = store.counts()
    print('bundle written to {} ({} records)'.format(args.out, sum(counts.values())))
    return 0


def cmd_merge(args, store):
    bundle = json.loads(Path(args.bundle).read_text(encoding='utf-8'))
    result = store.merge_bundle(bundle)
    print('merged {}'.format(args.bundle))
    print(result)
    print('  {:<16} +{} added, {} already archived'.format(
        'total', result.total_added, result.total_skipped))
    return 0


def cmd_export(args, store):
    rendered = exports.FORMATS[args.format](store)
    if args.out:
        Path(args.out).write_text(rendered, encoding='utf-8')
        print('wrote {}'.format(args.out))
    else:
        sys.stdout.write(rendered)
    return 0


def cmd_import_reminders(args, store):
    list_facets = json.loads(Path(args.map).read_text(encoding='utf-8')) if args.map else {}
    items = reminders.read_reminders()
    todos = reminders.to_todos(items, list_facets)

    print('{} open reminders across {} lists'.format(
        len(items), len({i['list'] for i in items})))
    for todo in todos:
        print('  {:<50} {:<12} {}'.format(
            todo['text'][:50], todo['date'] or '(no due)', ' '.join(todo['tags_by_name'])))

    if not args.apply:
        print('\nDRY RUN. Nothing created. Re-run with --apply to create these to-dos.')
        return 0

    client = build_client(args, dry_run=False)
    tag_ids = {t.get('name', ''): (t.get('id') or t.get('_id')) for t in client.get_tags() or []}
    created, errors = 0, []
    for todo in todos:
        ids = [tag_ids[name] for name in todo['tags_by_name'] if name in tag_ids]
        try:
            client.create_todo(todo['text'], notes=todo['notes'],
                               tags=ids, date=todo['date'])
            created += 1
        except ApiError as exc:
            errors.append('{}: {}'.format(todo['text'][:40], exc))
    print('\ncreated {} to-dos'.format(created))
    for error in errors:
        print('  ERROR {}'.format(error), file=sys.stderr)
    return 1 if errors else 0


def cmd_grammar(args, store):
    print('Facets')
    for sigil, facet in grammar.SIGILS.items():
        values = grammar.DEFAULT_VOCAB[facet]
        print('  {} {:<9} {}'.format(sigil, facet, ' '.join(sigil + v for v in values)))
    if args.parse:
        prose, facets = grammar.parse_text(args.parse)
        print('\nparse {!r}'.format(args.parse))
        print('  prose  {!r}'.format(prose))
        for facet, value in facets.items():
            print('  {:<7} {}'.format(facet, value))
    return 0


# -- wiring ---------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog='hbx', description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--archive', help='archive root (default $OVERWORLD_ARCHIVE)')
    parser.add_argument('--base-url', default='https://habitica.com/api/v3',
                        help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest='command', required=True)

    sub.add_parser('snapshot', help='pull the account and merge into the archive'
                   ).set_defaults(func=cmd_snapshot)
    sub.add_parser('status', help='what the archive currently holds'
                   ).set_defaults(func=cmd_status)

    p = sub.add_parser('analyze', help='report the tag landscape and hygiene')
    p.add_argument('--live', action='store_true', help='pull fresh instead of reading a snapshot')
    p.add_argument('--snapshot', help='analyze this snapshot file')
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser('plan', help='propose a taxonomy change set (writes nothing to Habitica)')
    p.add_argument('-o', '--out', default='overworld-plan.json')
    p.add_argument('--live', action='store_true')
    p.add_argument('--snapshot')
    p.add_argument('--suggest', action='store_true',
                   help='also propose facets for tasks that have none, from their '
                        'existing tags and their text')
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser('apply', help='execute a change set (dry run unless --apply)')
    p.add_argument('--plan', required=True)
    p.add_argument('--apply', action='store_true', help='actually write to Habitica')
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser('bundle', help='collapse the archive into one file for the site')
    p.add_argument('-o', '--out', default='overworld-bundle.json')
    p.set_defaults(func=cmd_bundle)

    p = sub.add_parser('merge', help='fold a browser-exported bundle back into the archive')
    p.add_argument('bundle')
    p.set_defaults(func=cmd_merge)

    p = sub.add_parser('export', help='hand the archive to another tool')
    p.add_argument('--format', choices=sorted(exports.FORMATS), default='json')
    p.add_argument('-o', '--out')
    p.set_defaults(func=cmd_export)

    p = sub.add_parser('import-apple-reminders',
                       help='create Habitica to-dos from open macOS Reminders')
    p.add_argument('--map', help='JSON mapping a Reminders list name to facet tags')
    p.add_argument('--apply', action='store_true')
    p.set_defaults(func=cmd_import_reminders)

    p = sub.add_parser('grammar', help='show the tag grammar, optionally parsing a line')
    p.add_argument('--parse', help='capture text to parse, e.g. "buy filters @errand ?buy"')
    p.set_defaults(func=cmd_grammar)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        store = archive_mod.Store(archive_root(args.archive))
        return args.func(args, store)
    except (ConfigError, plans.PlanError, reminders.RemindersError) as exc:
        print('hbx: {}'.format(exc), file=sys.stderr)
        return 2
    except ApiError as exc:
        print('hbx: Habitica said {}'.format(exc), file=sys.stderr)
        return 3
    except DryRunViolation as exc:
        print('hbx: {}'.format(exc), file=sys.stderr)
        return 4


if __name__ == '__main__':
    sys.exit(main())
