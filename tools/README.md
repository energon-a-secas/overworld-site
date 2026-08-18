# hbx, the Overworld archivist

Habitica deletes your history. Specifically, from its own source:

- **Completed to-dos are hard-deleted after 30 days** (90 with a subscription).
  `website/server/libs/cron.js` runs `Tasks.Task.deleteMany({type:'todo',
  completed:true, dateCompleted:{$lt: now-30d}})` on every cron. Deleted, not archived.
- **Daily-resolution history survives 60 days** (365 subscribed), then
  `website/server/libs/preening.js` averages it into one point per month for ten
  months, then one per year. Averaging cannot be undone.

`hbx` pulls the account before that happens and keeps the result in an
append-only, deduped archive. Pure Python 3.8+ standard library, so there is
nothing to install on macOS, Linux or Windows.

## Setup

Habitica authenticates on two headers, `x-api-user` and `x-api-key`. Both values
are UUIDs and both are required. They are at **Habitica → Settings → Site Data → API**.

```bash
# environment, or a .env here, or ~/.config/hbx/env
export HABITICA_USER_ID=...
export HABITICA_API_TOKEN=...
```

Credentials are never accepted as a command-line flag: flags land in shell
history and in `ps` output.

## Commands

```bash
python3 tools/hbx.py snapshot          # pull and merge; safe to run hourly
python3 tools/hbx.py status            # what the archive holds
python3 tools/hbx.py analyze           # tag landscape and hygiene
python3 tools/hbx.py plan -o plan.json # propose a taxonomy, write nothing
python3 tools/hbx.py apply --plan plan.json          # preview, fully offline
python3 tools/hbx.py apply --plan plan.json --apply  # write
python3 tools/hbx.py bundle -o overworld-bundle.json # for the site to import
python3 tools/hbx.py merge overworld-bundle.json     # fold the site's export back
python3 tools/hbx.py export --format csv             # json | csv | md
python3 tools/hbx.py import-apple-reminders          # dry run; --apply to create
python3 tools/hbx.py grammar --parse "buy filters @errand ?buy"
```

## The archive

```
$OVERWORLD_ARCHIVE            default ~/.local/share/overworld
  snapshots/<utc>.json        raw pull, full fidelity
  archive/todos-completed.jsonl   dedupe key (id, dateCompleted)
  archive/task-history.jsonl      dedupe key (taskId, date)
  archive/user-history.jsonl      exp and todos daily points
  archive/tags.jsonl              tag id -> name over time, so renames stay traceable
```

Append-only JSONL, deduped on merge. Running `snapshot` twice adds nothing the
second time, which is what makes it safe on a schedule.

**`hbx` refuses an archive root inside iCloud, Dropbox, OneDrive or Google
Drive.** Sync daemons resolve a concurrent write by forking the file into a
silent `name 2.jsonl` copy, and a forked append-only archive loses records
without ever raising an error.

## What a snapshot does not contain

Snapshots keep an **allowlist** of the user object, not a blocklist of secrets.
Habitica's user schema carries `apiToken`, `auth.local.hashed_password`, `salt`,
`passwordResetCode` and `webhooks`; a snapshot is written to disk and later
handed to a browser, so guessing which fields the server happens to strip is not
a safety model. A test asserts a planted token never reaches a snapshot.

## Writing to Habitica

`apply` is a dry run unless you pass `--apply`, and the dry run is fully offline:
it needs no credentials and makes no request of any kind. When you do pass
`--apply`, it takes a fresh snapshot as a backup before the first write.

Rate limiting is Habitica's 30 requests per minute, honoured with a sliding
window that reads `X-RateLimit-Remaining` and backs off on a 429.

## Scheduling

`com.neorgon.overworld.snapshot.plist` runs `hbx snapshot` daily. Edit the paths
in it, then:

```bash
cp tools/com.neorgon.overworld.snapshot.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.neorgon.overworld.snapshot.plist
launchctl start com.neorgon.overworld.snapshot     # run once now to check
tail -f /tmp/overworld-snapshot.log
```

This is the piece that makes the archive complete. The site archives too, but
only while its tab is open.

## Tests

```bash
python3 tools/test_hbx.py       # 25 tests, ~4.5s
node --test tools/test_site.mjs # 12 tests, browser-free site modules
```
