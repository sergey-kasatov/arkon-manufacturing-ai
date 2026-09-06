"""The executive view's generated content: the age bands, the status sentence and the
two thresholds the workbook ships baked in.

The sentence and the thresholds are computed at build time and written into the XML,
which is deliberate - the workbook ships WITH the extract it describes - but it also
means nothing at run time can catch them being wrong. This is where they are caught.

The generator imports `tableauhyperapi` to write the .hyper extracts, so these tests
skip where it is not installed rather than forcing a 40 MB dependency on anyone who
only wants to run the rest of the suite.
"""

import pytest

pytest.importorskip("tableauhyperapi",
                    reason="the workbook generator needs the Hyper API to import")

import build_workbook as gen  # noqa: E402  (after the skip, by design)


class FakeDatasource:
    """Just the attribute the pure functions read, so they can be tested without an
    extract on disk or a live Steering Cell behind it."""

    def __init__(self, rows):
        self.rows = rows


def incident(minutes_old, overdue=False, open_=True, acknowledged=False,
             priority="P2", ack_minutes="", due="60"):
    return {
        "age_minutes": str(minutes_old),
        "is_open": "TRUE" if open_ else "FALSE",
        "overdue": "TRUE" if overdue else "FALSE",
        "acknowledged_at": "2026-09-06T09:00:00Z" if acknowledged else "",
        "priority": priority,
        "minutes_to_acknowledge": str(ack_minutes) if ack_minutes != "" else "",
        "acknowledge_due_minutes": due,
    }


# --- age bands -------------------------------------------------------------

@pytest.mark.parametrize(
    "minutes,band",
    [
        (0, "under 1 h"), (59.9, "under 1 h"),
        (60, "1 to 4 h"), (239, "1 to 4 h"),
        (240, "4 to 24 h"), (1439, "4 to 24 h"),
        (1440, "1 to 3 d"), (4319, "1 to 3 d"),
        (4320, "over 3 d"), (99999, "over 3 d"),
    ],
)
def test_the_band_boundaries_are_closed_below_and_open_above(minutes, band):
    assert gen.band_of(minutes) == band


def test_the_bands_are_contiguous_and_cover_everything_from_zero():
    """A gap between two bands would drop incidents off the chart silently."""
    lows = [low for _name, low, _high in gen.AGE_BANDS]
    highs = [high for _name, _low, high in gen.AGE_BANDS]
    assert lows[0] == 0
    assert highs[-1] == float("inf")
    assert highs[:-1] == lows[1:]


def test_the_bands_match_the_cockpit_page():
    """Two executive views of one plant must not band the same incident differently.
    app/pages/00_executive.py carries the same list; this is the assertion that says
    so out loud, since nothing imports one from the other."""
    from pathlib import Path
    page = (Path(__file__).resolve().parent.parent / "app" / "pages" / "00_executive.py")
    text = page.read_text(encoding="utf-8")
    for name, low, high in gen.AGE_BANDS:
        assert '("%s", %d,' % (name, low) in text, name
        assert str(high) in text or high == float("inf")


# --- the status sentence ---------------------------------------------------

def test_the_sentence_names_the_oldest_band_and_the_freshest():
    rows = [incident(5000) for _ in range(20)] + [incident(30) for _ in range(5)]
    sentence = gen.status_sentence(FakeDatasource(rows))
    assert sentence.startswith("20 of 25 open incidents have been open more than three days")
    assert "The 5 raised in the last hour are being worked inside window." in sentence


def test_the_never_acknowledged_clause_needs_all_of_them():
    """One acknowledged incident in the band makes "none of them" false, and the
    clause has to disappear rather than round itself off."""
    rows = [incident(5000) for _ in range(19)] + [incident(5000, acknowledged=True)]
    assert "none of them ever acknowledged" not in gen.status_sentence(FakeDatasource(rows))

    rows = [incident(5000) for _ in range(20)]
    assert "none of them ever acknowledged" in gen.status_sentence(FakeDatasource(rows))


def test_the_freshest_clause_reports_a_breach_rather_than_reassuring():
    rows = [incident(5000) for _ in range(10)] + \
           [incident(30), incident(30, overdue=True), incident(30, overdue=True)]
    sentence = gen.status_sentence(FakeDatasource(rows))
    assert "include 2 already past window" in sentence
    assert "inside window" not in sentence


def test_the_sentence_collapses_to_one_clause_when_both_would_say_the_same():
    rows = [incident(30) for _ in range(4)]
    sentence = gen.status_sentence(FakeDatasource(rows))
    assert sentence.count(".") == 1
    assert "4 of 4 open incidents" in sentence


def test_closed_incidents_are_not_counted_as_open():
    rows = [incident(5000, open_=False) for _ in range(50)] + [incident(30)]
    assert "1 of 1 open incidents" in gen.status_sentence(FakeDatasource(rows))


def test_an_empty_store_says_so_rather_than_dividing_by_zero():
    sentence = gen.status_sentence(FakeDatasource([incident(30, open_=False)]))
    assert sentence == ("Nothing is open. Every incident in the store has been "
                        "closed or dismissed.")


# --- the two baked-in thresholds -------------------------------------------

def test_the_bullet_threshold_is_the_nth_largest_acknowledgement():
    rows = [incident(10, ack_minutes=m) for m in (5, 10, 20, 40, 80, 160)]
    assert gen.bullet_threshold(FakeDatasource(rows), rows=3) == 40


def test_the_bullet_threshold_keeps_exactly_the_rows_it_promises():
    values = [5, 10, 20, 40, 80, 160]
    rows = [incident(10, ack_minutes=m) for m in values]
    cut = gen.bullet_threshold(FakeDatasource(rows), rows=4)
    assert len([v for v in values if v >= cut]) == 4


def test_no_threshold_is_written_when_the_store_is_smaller_than_the_cap():
    """A filter that happens to keep everything is a filter that lies about why."""
    rows = [incident(10, ack_minutes=m) for m in (5, 10)]
    assert gen.bullet_threshold(FakeDatasource(rows), rows=6) is None


def test_incidents_without_a_window_are_not_candidates():
    """P3 carries no response window, so it has no ratio and no row; counting it
    toward the cap would push a real breach off the chart."""
    rows = [incident(10, ack_minutes=999, due="", priority="P3") for _ in range(5)]
    rows += [incident(10, ack_minutes=m) for m in (5, 10, 20)]
    assert gen.bullet_threshold(FakeDatasource(rows), rows=2) == 10


def test_the_feed_cutoff_is_the_nth_most_recent_transition():
    rows = [{"recorded_at": "2026-09-06T09:0%d:00Z" % i} for i in range(6)]
    assert gen.feed_cutoff(FakeDatasource(rows), rows=3) == "2026-09-06T09:03:00Z"


def test_the_feed_cutoff_keeps_exactly_the_rows_it_promises():
    stamps = ["2026-09-06T09:0%d:00Z" % i for i in range(6)]
    rows = [{"recorded_at": s} for s in stamps]
    cut = gen.feed_cutoff(FakeDatasource(rows), rows=4)
    assert len([s for s in stamps if s >= cut]) == 4


def test_no_feed_cutoff_when_there_are_fewer_transitions_than_rows():
    rows = [{"recorded_at": "2026-09-06T09:00:00Z"}]
    assert gen.feed_cutoff(FakeDatasource(rows), rows=6) is None


# --- layout arithmetic -----------------------------------------------------

def test_the_band_budget_sums_to_the_canvas():
    """bands() normalises whatever it is handed, so a budget that does not add up
    rescales every box instead of failing. The generator asserts this at build time;
    this is the same assertion where it can be seen."""
    heights = [84, 44, 150, 330, 236, 56]
    assert sum(heights) == gen.DASH_H == 900
    assert gen.DASH_W == 1600


def test_bands_partition_the_full_height_without_a_gap():
    boxes = gen.bands([84, 44, 150, 330, 236, 56])
    assert boxes[0].y == 0
    for earlier, later in zip(boxes, boxes[1:]):
        assert earlier.y + earlier.h == later.y
    assert boxes[-1].y + boxes[-1].h == 100000


def test_split_partitions_a_box_without_a_gap():
    box = gen.bands([100])[0]
    left, right = gen.split(box, [62, 38])
    assert left.x == box.x
    assert left.x + left.w == right.x
    assert right.x + right.w == box.x + box.w


def test_the_bullet_cap_puts_the_window_tick_where_it_can_be_seen():
    """At a cap of 4 the tick sits a quarter of the way along. The reason there is a
    cap at all: this store spans 0 to about 9,000 minutes against windows of 15 and
    60, so an unfixed axis puts every tick inside a pixel of the left edge."""
    assert gen.BULLET_CAP == 4.0


def test_escaping_covers_every_character_that_would_break_the_xml():
    assert gen.esc("a & b") == "a &amp; b"
    assert "<" not in gen.esc("<script>")
    assert "'" not in gen.esc("it's")


def test_ids_are_stable_across_runs():
    """The .twb is checked for being byte-identical over two builds, which only holds
    if the uuids are derived rather than generated."""
    assert gen.stable_uuid("KPI Overdue") == gen.stable_uuid("KPI Overdue")
    assert gen.stable_uuid("KPI Overdue") != gen.stable_uuid("KPI Open")
