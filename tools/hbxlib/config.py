"""Credential and archive-path resolution.

Two rules live here and nowhere else:

  * credentials are read from the environment, never from a command-line flag,
    because flags land in shell history and in `ps` output;
  * the archive root is refused if it resolves inside a cloud-sync folder.

The second is not paranoia. `hbx snapshot` runs from launchd and appends to
JSONL files; iCloud, Dropbox, OneDrive and Google Drive resolve a concurrent
write by forking the file into a silent `name 2.jsonl` copy. An append-only
archive that has been forked loses records without ever raising.
"""

import os
from pathlib import Path

DEFAULT_ARCHIVE = Path.home() / '.local' / 'share' / 'overworld'
CONFIG_ENV = Path.home() / '.config' / 'hbx' / 'env'

# Path fragments that mean "a sync daemon owns this directory".
# Checked against the fully resolved path, so a firmlinked ~/Documents is caught.
CLOUD_MARKERS = (
    'Library/Mobile Documents',          # iCloud Drive
    'com~apple~CloudDocs',               # iCloud Drive, container form
    'Library/CloudStorage',              # macOS 12+ mount point for Dropbox/OneDrive/Drive
    'Dropbox',
    'OneDrive',
    'Google Drive',
    'GoogleDrive',
)


class ConfigError(RuntimeError):
    """Raised for a missing credential or an unusable archive root."""


def _parse_env_file(path):
    """Read a KEY=VALUE file. Ignores blanks, comments and `export ` prefixes."""
    values = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        if line.startswith('export '):
            line = line[len('export '):]
        key, _, value = line.partition('=')
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load_env(extra_files=None):
    """Merge credential sources, nearest first: os.environ wins over any file."""
    merged = {}
    for path in reversed(list(extra_files or []) + [CONFIG_ENV, Path.cwd() / '.env']):
        merged.update(_parse_env_file(path))
    merged.update({k: v for k, v in os.environ.items() if k.startswith('HABITICA_')})
    return merged


def resolve_credentials(env=None):
    """Return (user_id, api_token) or raise ConfigError naming what is missing.

    HABITICA_TOKEN is accepted as an alias for HABITICA_API_TOKEN so an existing
    .env keeps working, but the user id has no alias: Habitica authenticates on
    two headers and there is no way to derive one from the other.
    """
    env = load_env() if env is None else env
    user_id = env.get('HABITICA_USER_ID') or env.get('HABITICA_USER')
    token = env.get('HABITICA_API_TOKEN') or env.get('HABITICA_TOKEN')

    missing = [name for name, value in
               (('HABITICA_USER_ID', user_id), ('HABITICA_API_TOKEN', token)) if not value]
    if missing:
        raise ConfigError(
            'missing {}.\n'
            'Both values are at Habitica -> Settings -> Site Data -> API.\n'
            'Put them in the environment, a .env in this directory, or {}.'
            .format(' and '.join(missing), CONFIG_ENV)
        )
    return user_id, token


def assert_not_cloud_synced(path):
    """Raise ConfigError if `path` resolves inside a cloud-sync folder.

    Resolves first: `~/Documents` is a plain directory on this machine but is a
    firmlink into `Library/Mobile Documents` whenever macOS "Desktop & Documents
    Folders" sync is switched on, and the unresolved path looks identical.
    """
    resolved = Path(path).expanduser().resolve()
    parts = resolved.parts
    for marker in CLOUD_MARKERS:
        needle = marker.split('/')
        for i in range(len(parts) - len(needle) + 1):
            if list(parts[i:i + len(needle)]) == needle:
                raise ConfigError(
                    'archive root {} is inside a cloud-synced folder ({}).\n'
                    'Sync daemons fork concurrently-written files into silent copies, '
                    'and an append-only archive that gets forked loses records without '
                    'erroring.\nSet OVERWORLD_ARCHIVE to a path outside it, for example {}.'
                    .format(resolved, marker, DEFAULT_ARCHIVE)
                )
    return resolved


def archive_root(override=None):
    """Resolve the archive root, refusing a cloud-synced location."""
    raw = override or os.environ.get('OVERWORLD_ARCHIVE') or DEFAULT_ARCHIVE
    return assert_not_cloud_synced(raw)
