"""The refresh loop's one decision: the workbook is rebuilt only on a good extract.

The two builders run as subprocesses, so they are replaced here by a runner that
answers from a script; nothing here reaches the Steering Cell or the Hyper API.
"""

from pathlib import Path

import refresh_loop as loop


def scripted(answers):
    """A runner that answers per builder name and records the order of calls."""
    calls = []

    def runner(command):
        name = Path(command[1]).name
        calls.append(name)
        return answers[name]

    return runner, calls


GOOD_EXTRACT = ("read 5 incidents\n\nas_of 2026-09-06T14:00:00.000Z\n"
                "complete: every incident the store matched was returned.")
GOOD_WORKBOOK = ("wrote x.twb\n  facts       : open 5, overdue 1, acknowledged 3 (2 in window), "
                 "as of 06 Sep 2026 14:00 UTC\nwrote x.twbx")
LOCKED = ("incidents.hyper is held open by another process (unable to drop database: could not "
          "delete the file). Close the workbook in Tableau first, or pass --skip-extracts.")


def test_a_good_tick_runs_the_extracts_and_then_the_workbook():
    runner, calls = scripted({"build_extracts.py": (True, GOOD_EXTRACT),
                              "build_workbook.py": (True, GOOD_WORKBOOK)})
    ok, message = loop.tick("http://store", python="py", runner=runner)
    assert ok
    assert calls == ["build_extracts.py", "build_workbook.py"]
    assert "as_of 2026-09-06T14:00:00.000Z" in message
    assert "open 5, overdue 1" in message


def test_a_store_that_does_not_answer_leaves_the_workbook_alone():
    runner, calls = scripted({
        "build_extracts.py": (False, "the Steering Cell did not answer (timed out). Nothing was written."),
        "build_workbook.py": (True, GOOD_WORKBOOK),
    })
    ok, message = loop.tick("http://store", python="py", runner=runner)
    assert not ok
    assert calls == ["build_extracts.py"]
    assert "Nothing was written" in message


def test_an_incomplete_extract_is_not_built_into_a_workbook():
    """build_extracts.py exits 1 when the API returned fewer rows than it matched. The
    CSVs are on disk but short, and a dashboard drawn from them would be short without
    saying so; the previous workbook is the better one to leave on screen."""
    runner, calls = scripted({
        "build_extracts.py": (False, "as_of 2026-09-06T14:00:00.000Z\nINCOMPLETE. The API returned "
                                     "fewer incidents than it matched for: closed (500 of 612)"),
        "build_workbook.py": (True, GOOD_WORKBOOK),
    })
    ok, message = loop.tick("http://store", python="py", runner=runner)
    assert not ok
    assert calls == ["build_extracts.py"]


def test_the_failure_line_is_the_exception_and_not_the_hex_context():
    """Measured 2026-09-06: the Hyper API prints its message and then a "Context: 0x..."
    line, and the first tick reported only the hex."""
    out = ("Traceback (most recent call last):\n  File x, line 1\n"
           "tableauhyperapi.hyperexception.HyperException: unable to drop database: could not "
           "delete the file: DatabaseId: \"hyper.file:D:/x/tableau/extracts/incidents.hyper\"\n"
           "Context: 0xfa6b0e2f")
    assert loop.reason(out).startswith("tableauhyperapi.hyperexception.HyperException: unable to drop")
    assert loop.reason("") == "no output"


def test_a_locked_extract_names_the_fix():
    runner, calls = scripted({"build_extracts.py": (True, GOOD_EXTRACT),
                              "build_workbook.py": (False, LOCKED)})
    ok, message = loop.tick("http://store", python="py", runner=runner)
    assert not ok
    assert calls == ["build_extracts.py", "build_workbook.py"]
    assert "Close the workbook in Tableau first" in message
    assert "open the .twbx instead" in message


def test_the_api_is_passed_to_the_extract_builder():
    seen = {}

    def runner(command):
        seen.setdefault(Path(command[1]).name, command)
        return True, GOOD_EXTRACT if "extracts" in command[1] else GOOD_WORKBOOK

    loop.tick("http://elsewhere:5678/webhook/arkon-incident-status", python="py", runner=runner)
    assert seen["build_extracts.py"][-2:] == ["--api", "http://elsewhere:5678/webhook/arkon-incident-status"]
    assert seen["build_workbook.py"] == ["py", str(loop.WORKBOOK)]
