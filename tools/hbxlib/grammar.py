"""The tag grammar: four facets encoded as sigil-prefixed Habitica tags.

Habitica has no location field and no custom fields, so zone, area, horizon and
kind all have to live in tag *names*. The sigil is not decoration. Habitica's
tag list is flat and alphabetically sorted, so a leading sigil clusters each
facet together inside the mobile app and the home-screen widget, which is where
most capture actually happens.

Kept deliberately small and pure so js/grammar.js can mirror it line for line.
"""

import re
import unicodedata
from collections import OrderedDict

SIGILS = OrderedDict((
    ('@', 'zone'),      # where it can be done
    ('+', 'area'),      # which life it belongs to
    ('!', 'horizon'),   # how urgent it is
    ('*', 'time'),      # what part of the day it belongs to
    ('?', 'kind'),      # what shape of action
))
FACET_SIGIL = {facet: sigil for sigil, facet in SIGILS.items()}
FACETS = tuple(SIGILS.values())

# `time` is a late addition and it came from data, not from design. A real
# account carried "Routine: morning", "Routine: night", "Chores: morning" and
# "Routine: any time". The first pass left those alone on the grounds that
# time of day is not urgency, which was right about horizon and wrong about the
# grammar: for someone whose account is mostly dailies, when in the day a thing
# belongs is the primary way they already group their own work.

# A token is a whole word: sigil, then a letter or digit, then word characters.
# Anchored so ordinary punctuation never matches ("milk?" is not a kind tag).
TOKEN_RE = re.compile(r'^([@+!*?])([a-z0-9][a-z0-9-]*)$', re.IGNORECASE)

DEFAULT_VOCAB = OrderedDict((
    ('zone', ['home', 'office', 'errand', 'mall', 'anywhere']),
    ('area', ['work', 'personal', 'health', 'money']),
    ('horizon', ['now', 'week', 'month', 'someday']),
    ('time', ['morning', 'midday', 'evening', 'night', 'anytime']),
    ('kind', ['buy', 'call', 'read', 'fix', 'decide']),
))

# Seeds for suggesting a facet for an existing free-form tag. A word appearing
# under two facets is reported as ambiguous rather than silently assigned.
FACET_SEEDS = {
    'zone': ['home', 'house', 'office', 'desk', 'errand', 'errands', 'mall', 'store',
             'shop', 'market', 'supermarket', 'gym', 'outside', 'downtown', 'city',
             'anywhere', 'online', 'computer', 'phone', 'commute', 'car',
             'chore', 'chores', 'cleaning'],
    'area': ['work', 'job', 'career', 'personal', 'life', 'health', 'fitness', 'money',
             'finance', 'finances', 'budget', 'family', 'study', 'school', 'admin',
             'home', 'house', 'side-project', 'hobby',
             'exercise', 'gaming', 'games', 'tech', 'development', 'dev', 'skill',
             'skills', 'inventory', 'organization', 'wellness', 'learning', 'studying'],
    'horizon': ['now', 'today', 'urgent', 'asap', 'soon', 'week', 'weekly', 'month',
                'monthly', 'quarter', 'someday', 'later', 'backlog', 'waiting', 'blocked'],
    'time': ['morning', 'mornings', 'am', 'midday', 'noon', 'afternoon', 'evening',
             'night', 'nightly', 'bedtime', 'anytime', 'any-time'],
    'kind': ['buy', 'purchase', 'shopping', 'call', 'email', 'message', 'read', 'write',
             'watch', 'fix', 'repair', 'decide', 'review', 'plan', 'learn', 'ask',
             'research', 'clean', 'pay',
             'learning', 'studying', 'chore', 'chores', 'cleaning'],
}

# Words appearing under two facets are ambiguous ON PURPOSE. 'chore' is both a
# place you do things (@home) and a shape of action (?chore); 'learning' is both
# a life area and a thing you do. Listing them twice sends them to the plan's
# review list instead of letting the proposer pick.
#
# Deliberately absent: 'routine'. A real account carried "Routine: morning",
# "Routine: night" and "Routine: any time", which encode time of day. That is
# not horizon (horizon is urgency, not the clock) and it is not any other facet
# either. Those tags are doing a job the grammar does not model, so the proposer
# leaves them alone rather than inventing a home for them.


def normalise(value):
    """Reduce any tag name to a legal facet value: ^[a-z0-9][a-z0-9-]*$.

    Anything outside that set becomes a hyphen, because a value that does not
    match TOKEN_RE produces a tag the parser cannot read back. That is not
    hypothetical: a real account carried "Health + Wellness", and collapsing
    only whitespace left the embedded "+" in the slug.

    Accents are folded rather than stripped, so "Organizacion" and
    "Organizaci\u00f3n" reach the same value instead of the second losing a letter.
    """
    folded = unicodedata.normalize('NFKD', str(value or '').strip().lower())
    folded = ''.join(ch for ch in folded if not unicodedata.combining(ch))
    # One pass is enough: the + already collapses a run of illegal characters
    # into a single hyphen, so there is never a doubled hyphen to squeeze.
    return re.sub(r'[^a-z0-9]+', '-', folded).strip('-')


def facet_of(tag_name):
    """('zone', 'errand') for '@errand'; None for a tag outside the grammar."""
    match = TOKEN_RE.match((tag_name or '').strip())
    if not match:
        return None
    return SIGILS[match.group(1)], match.group(2).lower()


def tag_for(facet, value):
    """'zone', 'errand' -> '@errand'."""
    if facet not in FACET_SIGIL:
        raise KeyError('unknown facet {!r}; expected one of {}'.format(facet, FACETS))
    return FACET_SIGIL[facet] + normalise(value)


def parse_text(text):
    """Split capture text into its prose and its facets.

    'buy coffee filters @errand ?buy !week'
        -> ('buy coffee filters', {'zone': 'errand', 'kind': 'buy', 'horizon': 'week'})

    A repeated facet keeps the last value, matching how the UI reads left to right.
    """
    words, facets = [], OrderedDict()
    for word in (text or '').split():
        match = TOKEN_RE.match(word)
        if match:
            facets[SIGILS[match.group(1)]] = match.group(2).lower()
        else:
            words.append(word)
    return ' '.join(words).strip(), facets


def format_text(prose, facets):
    """Inverse of parse_text, emitting facets in declared order."""
    parts = [prose.strip()]
    for facet in FACETS:
        if facets.get(facet):
            parts.append(tag_for(facet, facets[facet]))
    return ' '.join(p for p in parts if p)


def suggest_facets(tag_name):
    """Candidate facets for a free-form tag, with the word that triggered each.

    Returns a list of (facet, matched_seed). Length > 1 means genuinely ambiguous
    ('home' is both a zone and a life area); the caller must not pick for the user.
    """
    existing = facet_of(tag_name)
    if existing:
        return [(existing[0], 'already in grammar')]

    slug = normalise(tag_name)
    words = set(slug.split('-')) | {slug}
    hits = []
    for facet in FACETS:
        for seed in FACET_SEEDS[facet]:
            if seed in words:
                hits.append((facet, seed))
                break
    return hits
