"""Read macOS Reminders through osascript. One-way: Reminders -> Habitica.

Fields are separated by ASCII unit/record separators rather than tabs, because a
reminder body legitimately contains tabs and newlines and a TSV parse would
silently split one reminder into two.

First run raises the macOS Automation privacy prompt. If the user declines,
osascript exits non-zero with a -1743 error, which is surfaced as-is rather than
being retried.
"""

import subprocess

US = '\x1f'   # between fields
RS = '\x1e'   # between reminders

SCRIPT = r'''
on pad(n)
    set s to n as string
    if length of s is 1 then return "0" & s
    return s
end pad

on isoDate(d)
    return (year of d as string) & "-" & pad(month of d as integer) & "-" & pad(day of d) & ¬
        "T" & pad(hours of d) & ":" & pad(minutes of d) & ":00"
end isoDate

tell application "Reminders"
    set out to ""
    repeat with theList in lists
        set listName to name of theList
        repeat with r in (reminders in theList whose completed is false)
            set dueText to ""
            set dd to due date of r
            if dd is not missing value then set dueText to my isoDate(dd)
            set bodyText to body of r
            if bodyText is missing value then set bodyText to ""
            set out to out & listName & (ASCII character 31) & (name of r) & ¬
                (ASCII character 31) & dueText & (ASCII character 31) & bodyText & ¬
                (ASCII character 30)
        end repeat
    end repeat
    return out
end tell
'''


class RemindersError(RuntimeError):
    pass


def read_reminders(runner=None):
    """Return open reminders as dicts. `runner` is injectable for tests."""
    run = runner or _run_osascript
    raw = run(SCRIPT)
    items = []
    for chunk in raw.split(RS):
        if not chunk.strip():
            continue
        parts = chunk.split(US)
        if len(parts) < 4:
            continue
        list_name, name, due, body = parts[0], parts[1], parts[2], parts[3]
        items.append({
            'list': list_name.strip(),
            'text': name.strip(),
            'due': due.strip() or None,
            'notes': body.strip(),
        })
    return items


def _run_osascript(script):
    try:
        proc = subprocess.run(['osascript', '-e', script],
                              capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        raise RemindersError('osascript not found; this command is macOS only') from None
    if proc.returncode != 0:
        raise RemindersError(
            'osascript failed ({}): {}\n'
            'If this mentions -1743, grant Automation access to your terminal in '
            'System Settings -> Privacy & Security -> Automation.'
            .format(proc.returncode, proc.stderr.strip()))
    return proc.stdout


def to_todos(reminders, list_facets=None):
    """Map reminders onto Habitica to-do payloads.

    `list_facets` maps a Reminders list name to facet tags, so an existing
    "Groceries" list can arrive already carrying @errand and ?buy.
    """
    list_facets = list_facets or {}
    todos = []
    for item in reminders:
        tags = list(list_facets.get(item['list'], []))
        todos.append({
            'text': item['text'],
            'notes': item['notes'],
            'date': item['due'],
            'tags_by_name': tags,
            'source_list': item['list'],
        })
    return todos
