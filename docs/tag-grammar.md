# Tag grammar v2

Habitica has **no location field and no custom fields**. Every dimension
Overworld shows, zone included, is encoded in the *name* of a Habitica tag. This
document is the contract between three things that must not drift apart:

| Where | File |
|---|---|
| The site | `js/grammar.js` |
| The CLI | `tools/hbxlib/grammar.py` |
| Here | the vocabulary and the rules |

Change one, change all three.

## Facets

Five facets. A task carries at most one value of each.

| Facet | Sigil | Answers | Starting vocabulary |
|---|---|---|---|
| Zone | `@` | Where can this be done | `@home` `@office` `@errand` `@mall` `@anywhere` |
| Area | `+` | Which life is this | `+work` `+personal` `+health` `+money` |
| Horizon | `!` | How urgent is it | `!now` `!week` `!month` `!someday` |
| Time | `*` | What part of the day | `*morning` `*midday` `*evening` `*night` `*anytime` |
| Kind | `?` | What shape of action | `?buy` `?call` `?read` `?fix` `?decide` |

### Why `time` exists, and why it did not at first

v1 had four facets and deliberately refused to model time of day, on the
grounds that horizon covers "when" and time of day is not urgency. That
reasoning was right about horizon and wrong about the grammar.

The account this was built against already carried `Routine: morning`,
`Routine: night`, `Chores: morning` and `Routine: any time`, all applied to
dailies. For an account that is mostly dailies rather than to-dos, when in the
day something belongs is not a refinement of urgency, it is the *primary* way
the work is already grouped. v1 would have left four of eighteen tags
permanently outside the grammar and called that correct.

Horizon and time answer different questions and both are kept: `!now *evening`
is a coherent pair, meaning urgent and done after work.

## Why a sigil rather than a prefix word

Habitica's tag list is flat and sorted alphabetically, in the web app and in the
mobile app both. A leading sigil clusters each facet into one contiguous run, so
the scheme stays readable **in the tool where capture actually happens**, the
phone widget, and not only in Overworld. A `zone-` word prefix would sort all
four facets together under z, which is the same information arranged uselessly.

## Parsing rules

A word counts as a facet token only when it matches `^[@+!?][a-z0-9][a-z0-9-]*$`
as a whole whitespace-delimited word. Consequences worth stating:

- `is the milk off?` stays prose. The `?` is not at the start of a word.
- `@Corner Store` does not work; the value cannot contain a space. Write
  `@corner-store`. `tagFor()` normalises for you when you go through the CLI.
- A repeated facet keeps the **last** value, matching left-to-right reading.
- Case is not significant on input. Everything is stored lowercase.

## `@anywhere` is special

A mission tagged `@anywhere` appears in **every** zone filter, not in a zone of
its own. It is for work that has no location constraint, like a phone call. Use
it deliberately: tagging everything `@anywhere` makes the zone board useless in
exactly the way an untagged account already is.

## Unzoned missions are shown, not hidden

A task with no zone appears under "Unzoned" on the board. Dropping it would make
the grammar's own failure invisible, which is the opposite of what Hygiene is
for.

## Extending the vocabulary

Add values freely; the facets themselves are fixed at four. A new zone is just a
new tag name, and both implementations pick it up with no code change. If you
find yourself wanting a fifth facet, that is a real change: edit `grammar.js`,
`grammar.py` and this table together, and bump the version at the top.

## Migrating an existing account

Never by hand, and never in bulk from the browser:

```bash
python3 tools/hbx.py snapshot                    # archive first
python3 tools/hbx.py plan -o plan.json           # proposes, writes nothing
$EDITOR plan.json                                # resolve the review list
python3 tools/hbx.py apply --plan plan.json      # preview, offline
python3 tools/hbx.py apply --plan plan.json --apply
```

The proposer maps a free-form tag onto a facet only when the match is
unambiguous. `Work` matches one facet, so it becomes `+work`. `home` matches
both zone and area, so it lands in the plan's `review` list with both candidates
and is skipped by `apply` until you decide. Guessing there would rewrite real
tasks on a coin flip, and the wrong choice is invisible afterwards.
