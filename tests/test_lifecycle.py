"""Charter 7.2, the incident state machine.

Three deployed workflows read this file and inject it into their Code nodes, so a
change here reaches the transition endpoint, the status API and the escalation record
at once. That is the point of keeping it in one place, and it is also why the machine
is worth pinning: nothing else in the repository would notice an edge going missing.

These are properties of the machine rather than a transcription of it. A test that
merely repeats ALLOWED_TRANSITIONS back would pass for any edit that changed both.
"""

import json

import pytest

import lifecycle


def test_every_state_is_reachable_from_new():
    """An unreachable state is a state the plant can never be in, which means either
    a dead branch in three workflows or a missing edge."""
    seen = {"new"}
    frontier = ["new"]
    while frontier:
        for target in lifecycle.ALLOWED_TRANSITIONS[frontier.pop()]:
            if target not in seen:
                seen.add(target)
                frontier.append(target)
    assert seen == set(lifecycle.LIFECYCLE)


def test_terminal_states_have_no_exits():
    for status in lifecycle.TERMINAL_STATUSES:
        assert lifecycle.ALLOWED_TRANSITIONS[status] == [], status


def test_every_state_has_a_rule_and_every_target_is_a_known_state():
    assert set(lifecycle.ALLOWED_TRANSITIONS) == set(lifecycle.LIFECYCLE)
    for source, targets in lifecycle.ALLOWED_TRANSITIONS.items():
        assert len(targets) == len(set(targets)), "%s repeats a target" % source
        for target in targets:
            assert target in lifecycle.LIFECYCLE, "%s -> %s" % (source, target)
            assert target != source, "%s transitions to itself" % source


def test_new_is_written_by_intake_and_never_requested():
    """The Steering Cell writes `new`; an operator asking for it would be asking to
    un-acknowledge an incident, which is not a move the audit trail should carry."""
    assert "new" not in lifecycle.REQUESTABLE_STATUSES
    assert set(lifecycle.REQUESTABLE_STATUSES) == set(lifecycle.LIFECYCLE) - {"new"}
    for targets in lifecycle.ALLOWED_TRANSITIONS.values():
        assert "new" not in targets


def test_open_is_new_plus_acknowledged_plus_in_containment():
    """`resolved` is deliberately not open, and three surfaces depend on that reading:
    the status API's open_incidents, the cockpit queue and the executive cards."""
    assert lifecycle.OPEN_STATUSES == ["new", "acknowledged", "in_containment"]
    assert "resolved" not in lifecycle.OPEN_STATUSES
    assert not set(lifecycle.OPEN_STATUSES) & set(lifecycle.TERMINAL_STATUSES)
    assert set(lifecycle.OPEN_STATUSES) | set(lifecycle.TERMINAL_STATUSES) | {"resolved"} \
        == set(lifecycle.LIFECYCLE)


def test_the_reopen_edge_exists_and_is_the_only_one_that_goes_backwards():
    """resolved -> in_containment is the containment that did not hold. It is also
    the reason every KPI is computed from the FIRST time a milestone is reached
    rather than the last, so it must not be removed without that changing too."""
    order = {status: i for i, status in enumerate(lifecycle.LIFECYCLE)}
    backwards = [
        (source, target)
        for source, targets in lifecycle.ALLOWED_TRANSITIONS.items()
        for target in targets
        if order[target] < order[source]
    ]
    assert backwards == [("resolved", "in_containment")]


def test_false_positive_is_reachable_from_every_non_terminal_state():
    """A wrong call can be recognised at any point before the incident is finished."""
    for status in lifecycle.LIFECYCLE:
        if status in lifecycle.TERMINAL_STATUSES:
            continue
        assert "false_positive" in lifecycle.ALLOWED_TRANSITIONS[status], status


def test_acknowledgement_windows_exist_only_where_the_charter_gives_one():
    """P3 and P4 have no window, which is why the bullet chart has no row for them
    and why a zero there would be a lie rather than a gap."""
    assert lifecycle.ACK_WINDOW_MINUTES == {"P1": 15, "P2": 60}
    assert lifecycle.ACK_WINDOW_MINUTES["P1"] < lifecycle.ACK_WINDOW_MINUTES["P2"]


def test_js_constants_round_trip_to_the_same_machine():
    """The deployed workflows read the machine as injected JS. If the serialisation
    ever diverged from the Python, the workflows and this file would disagree while
    both looked right."""
    declarations = lifecycle.js_constants()
    parsed = {}
    for line in declarations.splitlines():
        name, _, value = line.partition(" = ")
        parsed[name.replace("const ", "")] = json.loads(value.rstrip(";"))

    assert parsed["LIFECYCLE"] == lifecycle.LIFECYCLE
    assert parsed["OPEN_STATUSES"] == lifecycle.OPEN_STATUSES
    assert parsed["TERMINAL_STATUSES"] == lifecycle.TERMINAL_STATUSES
    assert parsed["REQUESTABLE_STATUSES"] == lifecycle.REQUESTABLE_STATUSES
    assert parsed["ALLOWED_TRANSITIONS"] == lifecycle.ALLOWED_TRANSITIONS
    assert parsed["ACK_WINDOW_MINUTES"] == lifecycle.ACK_WINDOW_MINUTES


def test_js_constants_can_be_prefixed_without_changing_the_values():
    prefixed = lifecycle.js_constants(prefix="ARK_")
    assert "const ARK_LIFECYCLE = " in prefixed
    assert json.dumps(lifecycle.LIFECYCLE) in prefixed


@pytest.mark.parametrize("status", ["closed", "false_positive"])
def test_a_terminal_state_is_terminal_in_both_places_that_say_so(status):
    """TERMINAL_STATUSES and the empty transition list are two statements of one fact
    and the fold reads the first while the endpoint enforces the second."""
    assert status in lifecycle.TERMINAL_STATUSES
    assert lifecycle.ALLOWED_TRANSITIONS[status] == []
