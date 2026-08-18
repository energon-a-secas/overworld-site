#!/usr/bin/env python3
"""hbx test suite.  Run:  python3 tools/test_hbx.py

Every guard here is tested twice: once that it fires, and once that it stays
quiet when it should. A guard that always says "fine" is worse than no guard
because it gets quoted; a guard that always fires gets disabled. Both halves
are the test.
"""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hbx                                                        # noqa: E402
from hbxlib import analyze as analyze_mod                         # noqa: E402
from hbxlib import grammar, plans
from hbxlib import suggest as suggest_mod                                 # noqa: E402
from hbxlib.api import DryRunViolation, HabiticaClient, RateLimiter  # noqa: E402
from hbxlib.archive import Store, records_from_snapshot           # noqa: E402
from hbxlib.config import ConfigError, assert_not_cloud_synced, resolve_credentials  # noqa: E402


def sample_snapshot():
    return {
        'pulledAt': '2026-08-14T12:00:00+00:00',
        'user': {'history': {
            'exp': [{'date': 1755000000000, 'value': 120}, {'date': 1755086400000, 'value': 130}],
            'todos': [{'date': 1755000000000, 'value': -3}]}},
        'tasks': [
            {'id': 'd1', 'type': 'daily', 'text': 'stretch', 'isDue': True, 'streak': 0,
             'tags': ['tag-home'],
             'history': [{'date': 1755000000000, 'value': 1, 'completed': True},
                         {'date': 1755086400000, 'value': 2, 'completed': True}]},
            {'id': 't1', 'type': 'todo', 'text': 'buy filters', 'tags': [],
             'createdAt': '2026-08-10T00:00:00.000Z', 'date': None},
            {'id': 't2', 'type': 'todo', 'text': 'file expenses', 'tags': ['tag-work'],
             'createdAt': '2025-01-01T00:00:00.000Z', 'date': '2026-09-01T00:00:00.000Z'},
        ],
        'completedTodos': [
            {'id': 'c1', 'text': 'pay rent', 'tags': ['tag-work'],
             'dateCompleted': '2026-08-01T09:00:00.000Z', 'challenge': {}},
            {'id': 'c2', 'text': 'oat milk', 'tags': [],
             'dateCompleted': '2026-08-02T09:00:00.000Z', 'challenge': {}},
        ],
        'tags': [
            {'id': 'tag-home', 'name': 'home'},        # ambiguous: zone and area
            {'id': 'tag-work', 'name': 'Work'},        # single match: area
            {'id': 'tag-dead', 'name': 'obsolete'},    # unused
            {'id': 'tag-ok', 'name': '@errand'},       # already in grammar
        ],
    }


class ArchiveIdempotency(unittest.TestCase):
    """The archive's one hard promise: snapshotting twice must not duplicate."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='hbx-test-'))
        self.store = Store(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_second_merge_adds_nothing(self):
        records = records_from_snapshot(sample_snapshot())

        first = self.store.merge_all(records)
        self.assertGreater(first.total_added, 0, 'first merge archived nothing at all')
        self.assertEqual(first.total_skipped, 0)

        second = self.store.merge_all(records_from_snapshot(sample_snapshot()))
        self.assertEqual(second.total_added, 0,
                         'second merge added {} records; dedupe is broken'
                         .format(second.total_added))
        self.assertEqual(second.total_skipped, first.total_added)

        counts = self.store.counts()
        self.assertEqual(sum(counts.values()), first.total_added)

    def test_new_records_still_get_through(self):
        """The mirror image: dedupe must not swallow genuinely new records."""
        self.store.merge_all(records_from_snapshot(sample_snapshot()))
        moved_on = sample_snapshot()
        moved_on['completedTodos'].append(
            {'id': 'c3', 'text': 'new thing', 'tags': [],
             'dateCompleted': '2026-08-03T09:00:00.000Z', 'challenge': {}})

        result = self.store.merge_all(records_from_snapshot(moved_on))
        self.assertEqual(result.added['todos-completed'], 1)

    def test_bundle_round_trips_through_a_second_archive(self):
        self.store.merge_all(records_from_snapshot(sample_snapshot()))
        other_root = Path(tempfile.mkdtemp(prefix='hbx-test-b-'))
        try:
            other = Store(other_root)
            first = other.merge_bundle(self.store.bundle())
            self.assertEqual(first.total_added, sum(self.store.counts().values()))
            again = other.merge_bundle(self.store.bundle())
            self.assertEqual(again.total_added, 0, 'bundle re-import duplicated records')
        finally:
            shutil.rmtree(other_root, ignore_errors=True)


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


class RateLimiterGuard(unittest.TestCase):

    def test_never_exceeds_the_window(self):
        clock = FakeClock()
        limiter = RateLimiter(max_per_window=30, window=60.0,
                              clock=clock.now, sleeper=clock.sleep)
        stamps = []
        for _ in range(200):
            limiter.acquire()
            stamps.append(clock.now())

        for i, start in enumerate(stamps):
            in_window = sum(1 for t in stamps[i:] if t < start + 60.0)
            self.assertLessEqual(in_window, 30,
                                 'window starting at {}s held {} requests'.format(start, in_window))
        self.assertGreater(limiter.throttled, 0,
                           'limiter never throttled across 200 back-to-back calls, '
                           'so this test proves nothing')

    def test_it_really_sleeps(self):
        """Fake clocks prove the arithmetic. This proves the wall clock moves."""
        limiter = RateLimiter(max_per_window=5, window=2.0)
        started = time.monotonic()
        for _ in range(15):
            limiter.acquire()
        elapsed = time.monotonic() - started

        self.assertGreaterEqual(elapsed, 3.8,
                                '15 calls at 5-per-2s finished in {:.2f}s, so no real '
                                'throttling happened'.format(elapsed))
        self.assertEqual(limiter.throttled, 2)

    def test_it_stays_quiet_under_the_limit(self):
        """The discriminating half: a limiter that always throttles is also broken."""
        limiter = RateLimiter(max_per_window=30, window=60.0)
        for _ in range(5):
            limiter.acquire()
        self.assertEqual(limiter.throttled, 0)
        self.assertEqual(limiter.total_slept, 0.0)


class StubHandler(BaseHTTPRequestHandler):
    received = []

    def _reply(self, payload):
        body = json.dumps({'success': True, 'data': payload}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('X-RateLimit-Remaining', '29')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _record(self):
        type(self).received.append((self.command, self.path))

    def do_GET(self):
        self._record()
        if self.path.startswith('/tags'):
            self._reply([{'id': 'tag-work', 'name': 'Work'}])
        elif self.path.startswith('/user'):
            self._reply({'_id': 'u1', 'apiToken': 'LEAKED', 'history': {'exp': []}})
        else:
            self._reply([])

    def do_POST(self):
        self._record()
        self._reply({'id': 'new-tag', 'name': 'created'})

    def do_PUT(self):
        self._record()
        self._reply({'id': 'tag-work'})

    def do_DELETE(self):
        self._record()
        self._reply({})

    def log_message(self, *_args):
        pass


class DryRunMakesNoWrites(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), StubHandler)
        cls.base = 'http://127.0.0.1:{}'.format(cls.server.server_address[1])
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        StubHandler.received = []

    def _plan(self):
        return {
            'format': 'overworld-plan', 'version': 1,
            'create_tags': ['@errand'],
            'rename_tags': [{'tag_id': 'tag-work', 'from': 'Work', 'to': '+work'}],
            'delete_tags': [{'tag_id': 'tag-dead', 'name': 'obsolete'}],
            'retag': [{'task_id': 't1', 'add': ['@errand'], 'remove': []}],
            'review': [],
        }

    def test_dry_run_sends_no_mutating_request(self):
        client = HabiticaClient('u', 't', base_url=self.base, dry_run=True)
        with self.assertRaises(DryRunViolation):
            plans.apply_plan(client, self._plan(), log=lambda *_: None)

        verbs = {method for method, _ in StubHandler.received}
        self.assertNotIn('POST', verbs)
        self.assertNotIn('PUT', verbs)
        self.assertNotIn('DELETE', verbs)
        self.assertIn('GET', verbs, 'dry run should still be able to read')

    def test_apply_does_send_them(self):
        """Proves the assertion above can fail, rather than passing vacuously."""
        client = HabiticaClient('u', 't', base_url=self.base, dry_run=False)
        plans.apply_plan(client, self._plan(), log=lambda *_: None)

        verbs = [method for method, _ in StubHandler.received]
        self.assertIn('POST', verbs)
        self.assertIn('PUT', verbs)
        self.assertIn('DELETE', verbs)

    def test_dry_run_with_supplied_tag_ids_touches_the_network_not_at_all(self):
        """Previewing a plan must work with no credentials and no connection.

        The first version fetched tags to resolve ids, so `hbx apply --plan x`
        exited 3 with a 401 before printing anything useful.
        """
        client = HabiticaClient('u', 't', base_url=self.base, dry_run=True)
        with self.assertRaises(DryRunViolation):
            plans.apply_plan(client, self._plan(), log=lambda *_: None, tag_ids={})

        self.assertEqual(client.request_log, [],
                         'dry run sent {} request(s)'.format(len(client.request_log)))
        self.assertEqual(StubHandler.received, [])

    def test_snapshot_strips_the_api_token(self):
        client = HabiticaClient('u', 't', base_url=self.base, dry_run=True)
        snapshot = hbx.pull(client)
        blob = json.dumps(snapshot)
        self.assertNotIn('LEAKED', blob, 'apiToken survived into the snapshot')
        self.assertNotIn('apiToken', blob)
        self.assertIn('history', snapshot['user'], 'allowlist dropped a field we need')


class RenameCreateCollision(unittest.TestCase):
    """A resolved review item and the vocabulary step can target the same name.

    'home' is ambiguous, so the proposer parks it in review with @home as a
    candidate while the vocabulary step separately wants to create @home. If the
    user resolves the review by moving it into rename_tags, applying the plan
    must end with one @home, not two. Habitica allows duplicate tag names, so
    nothing downstream would have complained.
    """

    class FakeClient:
        dry_run = False

        def __init__(self):
            self.tags = [{'id': 'tag-home', 'name': 'home'}]
            self.created = []

        def get_tags(self):
            return list(self.tags)

        def create_tag(self, name):
            self.created.append(name)
            tag = {'id': 'new-' + name, 'name': name}
            self.tags.append(tag)
            return tag

        def rename_tag(self, tag_id, name):
            for tag in self.tags:
                if tag['id'] == tag_id:
                    tag['name'] = name
            return {'id': tag_id, 'name': name}

    def test_rename_target_is_not_created_twice(self):
        client = self.FakeClient()
        plan = {
            'format': 'overworld-plan', 'version': 1,
            'create_tags': ['@home', '@office'],
            'rename_tags': [{'tag_id': 'tag-home', 'from': 'home', 'to': '@home'}],
            'delete_tags': [], 'retag': [], 'review': [],
        }
        plans.apply_plan(client, plan, log=lambda *_: None)

        names = [t['name'] for t in client.tags]
        self.assertEqual(names.count('@home'), 1,
                         'ended with {} tags named @home'.format(names.count('@home')))
        self.assertEqual(client.created, ['@office'])


class CloudSyncGuard(unittest.TestCase):

    def test_refuses_cloud_synced_roots(self):
        for path in ('~/Library/Mobile Documents/com~apple~CloudDocs/overworld',
                     '~/Dropbox/overworld',
                     '~/Library/CloudStorage/OneDrive-Personal/overworld',
                     '~/Google Drive/overworld'):
            with self.subTest(path=path):
                with self.assertRaises(ConfigError):
                    assert_not_cloud_synced(path)

    def test_allows_an_ordinary_path(self):
        resolved = assert_not_cloud_synced(Path(tempfile.gettempdir()) / 'overworld')
        self.assertTrue(str(resolved))

    def test_substring_alone_is_not_a_match(self):
        """'Dropbox' must match a path component, not any substring of one."""
        resolved = assert_not_cloud_synced(Path(tempfile.gettempdir()) / 'NotDropboxAtAll')
        self.assertTrue(str(resolved))


class CredentialResolution(unittest.TestCase):

    def test_names_what_is_missing(self):
        with self.assertRaises(ConfigError) as caught:
            resolve_credentials({'HABITICA_API_TOKEN': 'x'})
        self.assertIn('HABITICA_USER_ID', str(caught.exception))

    def test_accepts_the_legacy_token_name(self):
        user_id, token = resolve_credentials(
            {'HABITICA_USER_ID': 'u', 'HABITICA_TOKEN': 't'})
        self.assertEqual((user_id, token), ('u', 't'))


class Grammar(unittest.TestCase):

    def test_round_trip(self):
        text = 'buy coffee filters @errand !week ?buy'
        prose, facets = grammar.parse_text(text)
        self.assertEqual(prose, 'buy coffee filters')
        self.assertEqual(grammar.format_text(prose, facets), text)

    def test_punctuation_is_not_a_facet(self):
        prose, facets = grammar.parse_text('is the milk off? call mum')
        self.assertEqual(facets, {})
        self.assertEqual(prose, 'is the milk off? call mum')

    def test_ambiguous_tag_reports_both_candidates(self):
        self.assertEqual(len(grammar.suggest_facets('home')), 2)
        self.assertEqual(len(grammar.suggest_facets('Work')), 1)
        self.assertEqual(grammar.suggest_facets('zzzz'), [])


class ProposerNeverGuesses(unittest.TestCase):

    def setUp(self):
        self.plan = analyze_mod.propose_plan(sample_snapshot())

    def test_ambiguous_tag_goes_to_review_not_rename(self):
        renamed = {e['from'] for e in self.plan['rename_tags']}
        reviewed = {e['name'] for e in self.plan['review']}
        self.assertIn('home', reviewed)
        self.assertNotIn('home', renamed)

    def test_unambiguous_tag_is_renamed(self):
        renames = {e['from']: e['to'] for e in self.plan['rename_tags']}
        self.assertEqual(renames.get('Work'), '+work')

    def test_unused_tag_is_proposed_for_deletion(self):
        self.assertEqual([e['name'] for e in self.plan['delete_tags']], ['obsolete'])

    def test_tag_already_in_grammar_is_left_alone(self):
        touched = ({e['from'] for e in self.plan['rename_tags']}
                   | {e['name'] for e in self.plan['review']}
                   | {e['name'] for e in self.plan['delete_tags']})
        self.assertNotIn('@errand', touched)

    def test_review_items_are_skipped_by_apply(self):
        self.assertEqual(plans.count_writes(self.plan),
                         len(self.plan['create_tags']) + len(self.plan['rename_tags'])
                         + len(self.plan['delete_tags']))


class CrossLanguageParity(unittest.TestCase):
    """js/grammar.js and hbxlib/grammar.py must agree, or the site and the CLI
    disagree about what a tag means. That is worse than either being wrong,
    because nothing reports it: the CLI writes a tag the site cannot read.

    Skipped rather than failed when node is unavailable, so the suite still runs
    on a machine with only Python.
    """

    CASES = [
        'Health + Wellness', 'Chores: morning', 'Routine: any time',
        'Development: Tech', 'a/b', 'MiXeD CaSe', 'trailing   spaces   ',
        'emoji \U0001F3AF tag', '100% done', 'Organizaci\u00f3n', 'Ni\u00f1o & Co.',
        '  ---  ', '', '@already', 'UPPER-CASE-DASHES',
    ]
    PARSE_CASES = [
        'buy coffee filters @errand ?buy !week',
        'stretch *morning +health',
        'brush teeth *morning *night keeps the last time',
        'is the milk off? call mum @home',
        'no facets at all',
        '@home @office duplicate zone keeps the last',
        'sigil alone @ ? ! + stays prose',
    ]

    def _node(self, script):
        try:
            proc = subprocess.run(['node', '--input-type=module', '-e', script],
                                  capture_output=True, text=True, timeout=30)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self.skipTest('node not available')
        if proc.returncode != 0:
            self.fail('node failed: {}'.format(proc.stderr[:400]))
        return json.loads(proc.stdout)

    def test_normalise_agrees(self):
        result = self._node(
            "import('./js/grammar.js').then(m=>console.log(JSON.stringify("
            "%s.map(c=>m.normalise(c)))))" % json.dumps(self.CASES))
        self.assertEqual([grammar.normalise(c) for c in self.CASES], result)

    def test_parse_text_agrees(self):
        result = self._node(
            "import('./js/grammar.js').then(m=>console.log(JSON.stringify("
            "%s.map(c=>{const r=m.parseText(c);return [r.text, r.facets];}))))"
            % json.dumps(self.PARSE_CASES))
        expected = [[t, dict(f)] for t, f in
                    (grammar.parse_text(c) for c in self.PARSE_CASES)]
        self.assertEqual(expected, result)

    def test_facet_of_agrees(self):
        names = ['@errand', '+work', '!now', '*morning', '?buy', 'Work', '@', '@-bad',
                 '@Corner-Store', 'x@errand', '@errand!', '*', '**night', '*any-time']
        result = self._node(
            "import('./js/grammar.js').then(m=>console.log(JSON.stringify("
            "%s.map(n=>{const r=m.facetOf(n);return r?[r.facet,r.value]:null;}))))"
            % json.dumps(names))
        expected = [list(grammar.facet_of(n)) if grammar.facet_of(n) else None
                    for n in names]
        self.assertEqual(expected, result)


class ProposalRoundTrips(unittest.TestCase):
    """Every tag the proposer emits must be readable by the parser that made it.

    Found against a real account: a tag literally named "Health + Wellness"
    became "+health-+-wellness", because normalise() only collapsed whitespace
    and slashes and left the embedded sigil in the value. facetOf() then refused
    to parse its own output, so applying the plan would have produced tags
    invisible to every board in the app.
    """

    REAL_WORLD_TAGS = [
        'Work', 'Exercise', 'Health + Wellness', 'Chores: morning', 'Hobby',
        'Learning', 'Routine: morning', 'Routine: night', 'Routine: any time',
        'Inventory', 'Development: Tech', 'Cleaning', 'Studying',
        'Life Organization', 'Storage Organization', 'Skill Development', 'Gaming',
        'a/b', 'MiXeD CaSe', 'trailing   spaces   ', 'emoji 🎯 tag', '100% done',
    ]

    def test_every_rename_target_parses_back(self):
        snapshot = {
            'tasks': [{'id': 't{}'.format(i), 'type': 'todo',
                       'tags': ['tag-{}'.format(i)], 'text': 'x'}
                      for i in range(len(self.REAL_WORLD_TAGS))],
            'completedTodos': [],
            'tags': [{'id': 'tag-{}'.format(i), 'name': name}
                     for i, name in enumerate(self.REAL_WORLD_TAGS)],
        }
        plan = analyze_mod.propose_plan(snapshot)

        for entry in plan['rename_tags']:
            with self.subTest(tag=entry['from']):
                parsed = grammar.facet_of(entry['to'])
                self.assertIsNotNone(
                    parsed,
                    'proposed {!r} -> {!r}, which facet_of() cannot parse'
                    .format(entry['from'], entry['to']))
                self.assertEqual(parsed[0], entry['facet'])

        for name in plan['create_tags']:
            with self.subTest(create=name):
                self.assertIsNotNone(grammar.facet_of(name))

    def test_tag_for_strips_sigils_from_the_value(self):
        self.assertEqual(grammar.tag_for('area', 'Health + Wellness'), '+health-wellness')
        self.assertEqual(grammar.tag_for('zone', 'Routine: morning'), '@routine-morning')
        self.assertEqual(grammar.tag_for('kind', 'a/b'), '?a-b')
        self.assertEqual(grammar.tag_for('area', '100% done'), '+100-done')

    def test_normalise_output_is_always_parseable(self):
        for name in self.REAL_WORLD_TAGS:
            slug = grammar.normalise(name)
            if not slug:
                continue
            with self.subTest(name=name):
                self.assertIsNotNone(
                    grammar.facet_of('@' + slug),
                    '{!r} normalised to {!r}, which is not a legal facet value'
                    .format(name, slug))


class MergeAndSuggestInteraction(unittest.TestCase):
    """A merge and the default-time rule must not both supply the time facet.

    Live regression: "Chores: morning" merged into *morning while the suggester,
    blind to queued merges, also added *anytime to the same daily. The task ended
    up with two values of one facet, which the boards then read arbitrarily.
    """

    def _snapshot(self):
        return {
            'tasks': [{'id': 'd1', 'type': 'daily', 'text': 'Organize accounts',
                       'tags': ['tag-chores'], 'notes': ''}],
            'completedTodos': [],
            'tags': [{'id': 'tag-chores', 'name': 'Chores: morning'}],
        }

    def test_one_value_per_facet_after_a_merge(self):
        snapshot = self._snapshot()
        # Mirror the operator decision: merge the tag rather than rename it.
        merge = [{'task_id': 'd1', 'text': 'Organize accounts', 'type': 'daily',
                  'add': ['*morning'], 'remove': [], 'why': 'merge'}]
        suggested, _ = suggest_mod.build_retags(snapshot, {'rename_tags': []},
                                                pending_retags=merge)

        added = [n for entry in merge + suggested for n in entry['add']]
        times = [n for n in added if n.startswith('*')]
        self.assertEqual(times, ['*morning'],
                         'task ended up with time facets {}'.format(times))

    def test_the_default_still_fires_when_nothing_supplies_time(self):
        """The discriminating half: suppressing the default unconditionally
        would leave every daily off the routines board."""
        suggested, _ = suggest_mod.build_retags(self._snapshot(), {'rename_tags': []},
                                                pending_retags=[])
        added = [n for entry in suggested for n in entry['add']]
        self.assertIn('*anytime', added)


class RecipesProduceRunnablePlans(unittest.TestCase):
    """The Recipes view's whole claim is that what it hands you actually runs.

    The starter plan is generated by browser JavaScript and consumed by this
    Python CLI. Nothing but a test crossing that boundary can keep the two
    honest, and the first version of the flow exited 2 because a dry run
    demanded credentials it never used.
    """

    def _starter_plan(self):
        script = (
            "globalThis.document={getElementById:()=>null};"
            "const r=await import(process.cwd()+'/js/views/recipes.js');"
            "console.log(JSON.stringify(r.starterPlan()));"
        )
        try:
            proc = subprocess.run(['node', '--input-type=module', '-e', script],
                                  capture_output=True, text=True, timeout=30,
                                  cwd=str(pathlib.Path(__file__).resolve().parent.parent))
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self.skipTest('node not available')
        if proc.returncode != 0:
            self.fail('node failed: {}'.format(proc.stderr[:400]))
        return json.loads(proc.stdout)

    def test_the_cli_validator_accepts_it(self):
        plan = self._starter_plan()
        plans.validate_plan(plan)
        self.assertEqual(plans.count_writes(plan), len(plan['create_tags']))
        self.assertGreater(len(plan['create_tags']), 20)

    def test_every_starter_tag_is_a_legal_facet(self):
        for name in self._starter_plan()['create_tags']:
            with self.subTest(tag=name):
                self.assertIsNotNone(grammar.facet_of(name))

    def test_it_covers_every_facet(self):
        facets = {grammar.facet_of(n)[0] for n in self._starter_plan()['create_tags']}
        self.assertEqual(facets, set(grammar.FACETS))

    def test_previewing_it_needs_no_credentials(self):
        """The flow after downloading a starter plan, before setting anything up."""
        plan_path = pathlib.Path(tempfile.mkdtemp()) / 'starter.json'
        plan_path.write_text(json.dumps(self._starter_plan()), encoding='utf-8')
        env = {k: v for k, v in os.environ.items() if not k.startswith('HABITICA_')}
        env['OVERWORLD_ARCHIVE'] = tempfile.mkdtemp()

        root = pathlib.Path(__file__).resolve().parent
        proc = subprocess.run(
            [sys.executable, str(root / 'hbx.py'), 'apply', '--plan', str(plan_path)],
            capture_output=True, text=True, env=env, timeout=60)

        self.assertEqual(proc.returncode, 0,
                         'preview exited {}: {}'.format(proc.returncode, proc.stderr[:300]))
        self.assertIn('0 sent', proc.stdout)
        self.assertNotIn('HABITICA_USER_ID', proc.stderr)


class Hygiene(unittest.TestCase):

    def test_report_finds_the_seeded_problems(self):
        report = analyze_mod.analyze(sample_snapshot())
        hygiene = report['hygiene']
        self.assertEqual([t['id'] for t in hygiene['untagged_tasks']], ['t1'])
        self.assertEqual([t['id'] for t in hygiene['todos_without_due']], ['t1'])
        self.assertEqual([t['id'] for t in hygiene['stale_todos']], ['t2'])
        self.assertEqual([t['id'] for t in hygiene['dead_dailies']], ['d1'])
        self.assertEqual([t['name'] for t in hygiene['orphan_tags']], ['obsolete'])
        # @errand is unused too, but it is vocabulary, not cruft. Deleting an
        # empty facet slot would be wrong, so it must land in the other bucket.
        self.assertEqual([t['name'] for t in hygiene['unused_vocabulary']], ['@errand'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
