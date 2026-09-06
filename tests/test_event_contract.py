"""The twelve-field risk event is the seam of the whole platform.

Seven models publish it and nothing downstream knows which model spoke, so a
regression in one adapter is invisible everywhere except here. These tests do two
things: they pin the validator's rules, and they run every event this repository
ships through it, which is the check that would actually catch a broken adapter.
"""

import copy
import json
from pathlib import Path

import pytest

import validate_event as contract

ROOT = Path(__file__).resolve().parent.parent
EVENT_FILES = sorted((ROOT / "events" / "out").glob("*.jsonl"))


def valid_event():
    """A minimal event that satisfies the contract, built fresh for each test."""
    return {
        "event_id": "arkon-2026-200001",
        "event_time": "2026-08-30T20:34:27+00:00",
        "source_module": "casting_cv",
        "business_domain": "visual_inspection",
        "risk_type": "surface_defect",
        "risk_score": 0.99,
        "priority": "P3",
        "summary": "Impeller flagged by visual inspection.",
        "evidence": {
            "record_id": "CASTING-CAST_DEF_0_1059",
            "model_version": "casting_resnet18_v1",
            "prediction": 0.99,
            "threshold": 0.0637,
        },
        "context_origin": "real",
        "recommended_action": "Quarantine the part.",
        "status": "new",
    }


def test_the_reference_event_is_valid():
    assert contract.validate_event(valid_event()) == []


@pytest.mark.parametrize("field", contract.REQUIRED_FIELDS)
def test_every_required_field_is_required(field):
    event = valid_event()
    del event[field]
    assert "missing field: %s" % field in contract.validate_event(event)


@pytest.mark.parametrize("field", contract.REQUIRED_EVIDENCE)
def test_every_required_evidence_field_is_required(field):
    event = valid_event()
    del event["evidence"][field]
    assert "missing evidence field: %s" % field in contract.validate_event(event)


@pytest.mark.parametrize(
    "field,bad",
    [
        ("source_module", "cmapss_rull"),
        ("business_domain", "assset_reliability"),
        ("priority", "P0"),
        ("status", "reopened"),
        ("context_origin", "synthetic"),
    ],
)
def test_closed_vocabularies_reject_a_near_miss(field, bad):
    """Near misses rather than nonsense: a typo in an adapter looks like this."""
    event = valid_event()
    event[field] = bad
    assert contract.validate_event(event), "%s=%r was accepted" % (field, bad)


@pytest.mark.parametrize("score", [-0.01, 1.01, "0.5", None])
def test_risk_score_must_be_a_number_in_the_unit_interval(score):
    event = valid_event()
    event["risk_score"] = score
    assert any("risk_score" in problem for problem in contract.validate_event(event))


@pytest.mark.parametrize("score", [0, 1, 0.5])
def test_risk_score_accepts_both_ends_of_the_interval(score):
    event = valid_event()
    event["risk_score"] = score
    assert contract.validate_event(event) == []


def test_event_id_must_carry_the_arkon_prefix():
    event = valid_event()
    event["event_id"] = "2026-200001"
    assert any("event_id" in problem for problem in contract.validate_event(event))


def test_event_time_must_be_iso_8601():
    event = valid_event()
    event["event_time"] = "30/08/2026 20:34"
    assert any("event_time" in problem for problem in contract.validate_event(event))


def test_a_zulu_timestamp_is_accepted():
    """The status API stamps Z rather than +00:00, and both are the same instant."""
    event = valid_event()
    event["event_time"] = "2026-08-30T20:34:27Z"
    assert contract.validate_event(event) == []


def test_operational_context_must_declare_itself_simulated():
    """Charter section 5: a demonstration field that is not labelled is the one way
    this project could quietly claim a fact about a real plant."""
    event = valid_event()
    event["operational_context"] = {"assigned_to": "A. Novak"}
    assert any("operational_context" in p for p in contract.validate_event(event))

    event["operational_context"]["context_origin"] = "simulated"
    assert contract.validate_event(event) == []


def test_operational_context_may_be_absent():
    event = valid_event()
    assert "operational_context" not in event
    assert contract.validate_event(event) == []


def test_a_missing_field_short_circuits_before_the_type_checks():
    """Documented behaviour worth pinning: with a field absent the validator returns
    only the absences, so a caller never sees a type error about a field that is not
    there. A change here would make the other tests read differently."""
    event = valid_event()
    del event["priority"]
    event["risk_score"] = "not a number"
    assert contract.validate_event(event) == ["missing field: priority"]


def test_there_are_event_files_to_check():
    """Guards the parametrisation below: an empty glob would make it pass vacuously."""
    assert len(EVENT_FILES) == 8, [p.name for p in EVENT_FILES]


@pytest.mark.parametrize("path", EVENT_FILES, ids=lambda p: p.stem)
def test_every_shipped_event_satisfies_the_contract(path):
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert events, "%s is empty" % path.name
    problems = [
        (event.get("event_id", "<no id>"), contract.validate_event(event))
        for event in events
    ]
    bad = [(event_id, errors) for event_id, errors in problems if errors]
    assert not bad, "%d of %d events invalid: %s" % (len(bad), len(events), bad[:3])


@pytest.mark.parametrize("path", EVENT_FILES, ids=lambda p: p.stem)
def test_event_ids_are_unique_within_a_file(path):
    ids = [json.loads(line)["event_id"]
           for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    duplicates = {i for i in ids if ids.count(i) > 1}
    assert not duplicates, sorted(duplicates)[:5]


def _events(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def test_each_module_owns_its_own_id_block():
    """The Steering Cell stores by event_id, so a collision between two MODULES would
    make one incident overwrite another rather than raise anything. What prevents it
    is that each module emits from its own hundred-thousand block, which is checked
    here rather than assumed.

    Note what this does NOT assert: that no id appears twice across all eight files.
    Two of them are cmapss - an FD001-only baseline that docs/Model_Card_CMAPSS_RUL.md
    records as superseded, and the full-fleet run that replaced it - so they share the
    cmapss block by design and are never replayed together. A test written the other
    way round fails on that pair and says nothing about the risk it was aimed at."""
    blocks = {}
    for path in EVENT_FILES:
        for event in _events(path):
            block = int(event["event_id"].rsplit("-", 1)[1]) // 100000
            module = event["source_module"]
            blocks.setdefault(module, set()).add(block)
            assert blocks[module] == {block}, "%s emits into more than one block" % module

    owner = {}
    for module, module_blocks in blocks.items():
        block = module_blocks.pop()
        assert block not in owner, "%s and %s share block %d" % (module, owner[block], block)
        owner[block] = module
    assert len(owner) == len(contract.SOURCE_MODULES) == 7


def test_the_two_cmapss_files_are_one_module_and_only_one_of_them_is_live():
    """The overlap above is only safe while this holds."""
    superseded, live = [p for p in EVENT_FILES if p.stem.startswith("cmapss")]
    assert superseded.name == "cmapss_events_FD001.jsonl"
    assert live.name == "cmapss_events_full_fleet.jsonl"
    assert {e["source_module"] for e in _events(superseded)} == {"cmapss_rul"}
    assert {e["source_module"] for e in _events(live)} == {"cmapss_rul"}

    card = (ROOT / "docs" / "Model_Card_CMAPSS_RUL.md").read_text(encoding="utf-8")
    assert "Supersedes" in card and "FD001-only baseline" in card


def test_every_source_module_in_the_contract_ships_events():
    """A module named in the contract but publishing nothing would be a claim the
    repository makes and does not keep."""
    shipped = {event["source_module"] for path in EVENT_FILES for event in _events(path)}
    assert shipped == contract.SOURCE_MODULES


def test_the_validator_does_not_mutate_the_event():
    event = valid_event()
    before = copy.deepcopy(event)
    contract.validate_event(event)
    assert event == before
