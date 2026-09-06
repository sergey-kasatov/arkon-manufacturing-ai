"""The extract layer's two pure pieces: the plant clock and the CSV typing.

Both are small and both have already been the cause of a defect on a screen. The
clock because a board in Cologne printed UTC and read two hours behind the room; the
typing because Tableau reads `True` as a string and `TRUE` as a boolean.
"""

import datetime

import pytest

import build_extracts


@pytest.mark.parametrize(
    "utc,expected",
    [
        # Summer, CEST, UTC+2. This is the case the board was wrong about.
        ("2026-09-06T09:13:20.495Z", "06 Sep 11:13"),
        # Winter, CET, UTC+1. A hardcoded +2 offset would fail exactly here, which
        # is why the zone is named rather than added.
        ("2026-01-15T09:13:20Z", "15 Jan 10:13"),
        # The last minute before the spring change, and the first after it.
        ("2026-03-29T00:59:00Z", "29 Mar 01:59"),
        ("2026-03-29T01:00:00Z", "29 Mar 03:00"),
    ],
)
def test_the_plant_clock_follows_daylight_saving(utc, expected):
    assert build_extracts.local(utc) == expected


def test_an_offset_timestamp_is_converted_rather_than_relabelled():
    """A stamp that already carries +00:00 is the same instant as one carrying Z."""
    assert build_extracts.local("2026-09-06T09:13:20+00:00") == \
        build_extracts.local("2026-09-06T09:13:20Z")


def test_a_naive_timestamp_is_read_as_utc():
    """Everything the status API returns is UTC; a stamp without a zone is not an
    invitation to guess the local one."""
    assert build_extracts.local("2026-09-06T09:13:20") == "06 Sep 11:13"


@pytest.mark.parametrize("stamp", ["", None])
def test_an_empty_stamp_renders_as_an_empty_cell(stamp):
    assert build_extracts.local(stamp) == ""


def test_an_unparseable_stamp_passes_through_untouched():
    """Better a visibly odd cell than a silently dropped one: the raw UTC column is
    still beside it, so the reader can see what happened."""
    assert build_extracts.local("not a timestamp") == "not a timestamp"


def test_the_format_is_caller_supplied():
    assert build_extracts.local("2026-09-06T09:13:20Z", "%H:%M") == "11:13"
    assert build_extracts.local("2026-09-06T09:13:20Z", "%d %b %Y %H:%M") == "06 Sep 2026 11:13"


def test_booleans_are_written_in_the_form_tableau_types_as_boolean():
    """`True` is a two-value string to Tableau's CSV connector; `TRUE` is a boolean.
    The difference decides whether `IF [overdue] THEN` compiles at all."""
    typed = build_extracts._typed({"a": True, "b": False})
    assert typed == {"a": "TRUE", "b": "FALSE"}


def test_none_becomes_an_empty_cell_which_tableau_reads_as_null():
    assert build_extracts._typed({"a": None}) == {"a": None}


def test_numbers_and_strings_are_left_alone():
    row = {"i": 0, "f": 1.5, "s": "closed", "z": ""}
    assert build_extracts._typed(row) == row


def test_zero_is_not_confused_with_false():
    """Both are falsy in Python and only one of them is a boolean."""
    assert build_extracts._typed({"n": 0}) == {"n": 0}
    assert build_extracts._typed({"n": False}) == {"n": "FALSE"}


def test_the_lifecycle_sweep_covers_every_state_exactly_once():
    """The sweep asks the API one state at a time, which is what makes it complete
    and free of duplicates. A state missing here would silently drop incidents."""
    import lifecycle

    assert sorted(build_extracts.LIFECYCLE) == sorted(lifecycle.LIFECYCLE)
    assert len(build_extracts.LIFECYCLE) == len(set(build_extracts.LIFECYCLE))


def test_the_page_size_is_the_api_maximum():
    """Raised from 50 on 2026-09-06 because 50 had started truncating the dashboards,
    and a smaller page saved the server nothing: the workflow parses both JSONL files
    whole on every request regardless of what the caller asks for."""
    assert build_extracts.PAGE == 500


def test_the_plant_zone_is_named_rather_than_taken_from_the_machine():
    """An extract built on a laptop in another country still carries the plant's
    clock, and the board cannot change meaning if TZ is unset in a container."""
    assert str(build_extracts.PLANT_TZ) == "Europe/Berlin"
    assert isinstance(build_extracts.PLANT_TZ.utcoffset(datetime.datetime(2026, 7, 1)),
                      datetime.timedelta)
