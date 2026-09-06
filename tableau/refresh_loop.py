"""Keep the Tableau workbook fresh: refresh the extracts and rebuild on an interval.

Tableau Public has no API and no live connection, so "live" for the published view
is a loop: read the store again every few minutes, rebuild the workbook with a new
"as of" stamp, and leave the one step a script cannot do, Save to Tableau Public
(a sign-in), to a person. This does everything up to that click.

    python tableau/refresh_loop.py            # every 10 minutes until Ctrl+C
    python tableau/refresh_loop.py --every 3  # every 3 minutes
    python tableau/refresh_loop.py --once     # one refresh, then exit

Each tick runs `build_extracts.py` (the Steering Cell must answer) and then
`build_workbook.py`, as subprocesses in that order, and writes one line per tick
to stdout and to `tableau/refresh_loop.log`: the store's as-of stamp, the facts the
generator printed, and the seconds it took. A tick that fails is logged and the
loop waits for the next one. The last good workbook stays on disk: the extract
builder writes nothing when the store does not answer, and the workbook is not
rebuilt on an extract the builder itself reported as failed or incomplete.

Two things to know before running it during a demo. Open the packaged `.twbx` in
Tableau, not the `.twb`: the `.twb` reads the `.hyper` files in `tableau/extracts/`
by path and holds them open, and the extract builder cannot rewrite a locked file,
so every tick would fail with the builder's own message. And Tableau does not
reload a file it has open: after a tick, open the `.twbx` again (File > Open
Recent) to see the new stamp, then Save to Tableau Public.

Stdlib only.
"""

import argparse
import datetime
import subprocess
import sys
import time
from pathlib import Path

TABLEAU_DIR = Path(__file__).resolve().parent
LOG = TABLEAU_DIR / "refresh_loop.log"
EXTRACTS = TABLEAU_DIR / "build_extracts.py"
WORKBOOK = TABLEAU_DIR / "build_workbook.py"

sys.path.insert(0, str(TABLEAU_DIR))
from build_extracts import DEFAULT_API  # noqa: E402


def run(command):
    """Run one builder; return (ok, its combined output)."""
    done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    return done.returncode == 0, (done.stdout + done.stderr).strip()


def reason(output):
    """The line that says why a builder stopped.

    A SystemExit message is the last line. A Hyper API exception ends with a
    "Context: 0x..." line AFTER its message, so those are dropped first; measured
    2026-09-06, when the first tick reported "Context: 0xfa6b0e2f" and nothing else.
    """
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    while lines and lines[-1].startswith("Context:"):
        lines.pop()
    return lines[-1] if lines else "no output"


def facts(output):
    """The lines worth keeping from a build: the as-of stamp, the facts line, and
    the extract builder's own completeness verdict."""
    kept = [line.strip() for line in output.splitlines()
            if line.strip().startswith(("as_of ", "facts", "INCOMPLETE", "complete:"))]
    return "; ".join(kept) if kept else reason(output)


def tick(api, python=sys.executable, runner=run):
    """One refresh: the extracts, then the workbook. Returns (ok, message).

    The workbook is rebuilt only on a good extract. `build_extracts.py` exits non-zero
    both when the store does not answer (nothing written) and when the API returned
    fewer rows than it matched (written, but short); in both cases the previous
    workbook is the better one to leave on screen.
    """
    started = time.monotonic()
    ok, out = runner([python, str(EXTRACTS), "--api", api])
    if not ok:
        return False, "extracts failed, workbook left as it was: %s" % reason(out)
    stamp = facts(out)
    ok, out = runner([python, str(WORKBOOK)])
    if not ok:
        why = reason(out)
        if ".hyper" in why and ("held open" in why or "delete" in why or "writable" in why):
            why += " (a workbook opened from the .twb holds the extracts; open the .twbx instead)"
        return False, "workbook failed after a good extract: %s" % why
    return True, "%s; %s; %.0f s" % (stamp, facts(out), time.monotonic() - started)


def log(message):
    line = "%s %s" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message)
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--every", type=float, default=10,
                        help="minutes between refreshes (default 10, about the plant's own pace)")
    parser.add_argument("--once", action="store_true", help="refresh once and exit")
    parser.add_argument("--api", default=DEFAULT_API, help="the status API (default: %(default)s)")
    args = parser.parse_args()

    ticks = good = 0
    log("started: every %g min, %s%s" % (args.every, args.api, ", once" if args.once else ""))
    try:
        while True:
            ok, message = tick(args.api)
            ticks += 1
            good += ok
            log(("ok   " if ok else "FAIL ") + message)
            if args.once:
                break
            time.sleep(args.every * 60)
    except KeyboardInterrupt:
        pass
    log("stopped: %d ticks, %d good" % (ticks, good))
    return 0 if good == ticks else 1


if __name__ == "__main__":
    sys.exit(main())
