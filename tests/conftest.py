"""Make the repository's modules importable without turning it into a package.

The project is a set of tools rather than a library: `events/`, `n8n/build/` and
`tableau/` are directories of scripts, not packages, and giving them `__init__.py`
files purely to satisfy a test runner would be tail-wagging-dog. Putting the four
directories on the path keeps the scripts exactly as they are.

The module names are unique across those directories, which is checked below so that
a future file called `config.py` in two places fails here rather than by importing
whichever one happened to be first.
"""

import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Directories holding modules under test. `app` is on the list because app/utils
# imports itself as `utils.config`, which only resolves from the app directory.
SOURCE_DIRS = [
    ROOT / "events",
    ROOT / "n8n" / "build",
    ROOT / "tableau",
    ROOT / "app",
]

_names = collections.Counter(
    path.stem
    for directory in SOURCE_DIRS
    for path in directory.glob("*.py")
)
_clashes = sorted(name for name, count in _names.items() if count > 1)
if _clashes:
    raise RuntimeError(
        "these module names appear in more than one source directory, so an import "
        "would silently pick one of them: %s" % ", ".join(_clashes)
    )

for directory in SOURCE_DIRS:
    sys.path.insert(0, str(directory))
