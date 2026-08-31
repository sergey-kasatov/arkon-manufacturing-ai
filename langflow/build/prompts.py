"""Load the canvas prompt blocks from `langflow/prompts/`.

Every prompt the canvas carries lives in a fenced `### BLOCK: name` section under
`langflow/prompts/`. The build scripts used to read those blocks out of an
absolute path to a personal knowledge base, which put that path into eight
tracked files and made none of them runnable on another machine. They read from
here instead, and the repository root is derived from this file's location.

    from prompts import load, block

    text = block("procedure_v2")
"""

import functools
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
PROMPT_DIR = REPO / "langflow" / "prompts"

BLOCK_RE = r"### BLOCK: (\w+)\n\n```text\n(.*?)\n```"


@functools.lru_cache(maxsize=1)
def load():
    """Return every block as {name: text}. A duplicate name is an error, not a win."""
    if not PROMPT_DIR.is_dir():
        raise SystemExit("no prompt directory at %s" % PROMPT_DIR)
    found, origin = {}, {}
    for path in sorted(PROMPT_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        for name, body in re.findall(BLOCK_RE, text, flags=re.S):
            if name in found:
                raise SystemExit(
                    "block %r is defined in both %s and %s" % (name, origin[name], path.name)
                )
            found[name], origin[name] = body, path.name
    if not found:
        raise SystemExit("no `### BLOCK:` sections found under %s" % PROMPT_DIR)
    return found


def block(name):
    """One block, stripped. Missing is an error so a rename cannot fail silently."""
    blocks = load()
    if name not in blocks:
        raise SystemExit(
            "no prompt block %r. Available: %s" % (name, ", ".join(sorted(blocks)))
        )
    return blocks[name].strip()


if __name__ == "__main__":
    for name, body in sorted(load().items()):
        print("%-26s %5d chars" % (name, len(body)))
