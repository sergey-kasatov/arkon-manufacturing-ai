"""Convert NHTSA field-quality trend cells into Arkon risk events.

Reads the cell table produced by
notebooks/04_nlp/01_nhtsa_complaints/03_nhtsa_modeling.ipynb, maps the size of each
movement to a priority, attaches simulated operational context (fixed seed, labelled),
validates every event, and writes JSONL for the n8n Quality Steering Cell. Seventh
adapter, same contract, and the first that needed no change to the contract at all:
`nhtsa_nlp` was already in the `source_module` enum of both arkon_event_schema.json and
validate_event.py, and `field_quality` was already an unused business domain with a role
behind it in roster.json.

Four things differ from the six adapters before it, and every one of them follows from
the same fact: this module does not inspect anything.

**The event is about a signal, not a part.** Every other Arkon module publishes a
measurement of a physical thing it looked at: an engine's remaining life, a truck's
service record, a photograph of a casting, a steel sheet. A complaint is a report
written by a member of the public about their own vehicle, and nothing in this dataset
verifies any of it. So `evidence.record_id` names a manufacturer, a component and a
month rather than a part, and `context_origin` stays `real` because the complaints are
real, while the summary says in words that the module is reporting what people wrote.

**One event per trend cell, not per complaint.** The held-out year holds 60,039
complaints. Publishing one event each would be four times everything the incident store
has ever held, which is Scania's 15,222 suppressed P4 events in another costume. A field
quality function does not act on one report; it acts when a rate moves. So the
classifier's predictions are aggregated into manufacturer-component-month cells, each
cell is tested against its own trailing baseline, and only the cells that move more than
that baseline can explain are published. 3,080 cells were tested and 25 published.

**Priority says how big the movement is and never how certain it is.** The band edge is
declared rather than calibrated, for the third module running and the third distinct
reason: the rule needed thirty flagged calibration cells to answer from and the
calibration window produced five. Worse, the run measured whether the ordering carries
any information at all and found it does not: the Spearman correlation between the risk
score and whether the label-driven trend confirms the cell is -0.056, and above a 0.80
edge the ordering inverts. A very large ratio is more often the classifier misreading
one manufacturer than the fleet actually moving. The events therefore carry
`evidence.band_basis: declared` and the summary states the size, not a confidence.

**Priority never comes from the reported harm.** Each complaint carries CRASH, FIRE,
INJURED and DEATHS fields, and they look like a severity. They are not: they are what
the person filing said happened, unverified by anyone, and they are an input to this
module rather than an output of it. Ranking events by them would be the module asserting
a safety judgement it has no basis for, which is the rule NEU and MVTec both set. The
counts ride in `evidence.reported_harm` so a person can see them, labelled as reported.

There is no P1 because P1 in charter section 7.1 means safety-relevant and this module
cannot judge safety. There is no P4 because only cells that cleared the gate are
published at all.

Usage:
    python events/make_events_nhtsa.py
"""

import json
import random
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from validate_event import validate_event

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CELL_JSON = PROJECT_ROOT / "data" / "07_nhtsa_complaints" / "processed" / "test_nhtsa_trend_cells.json"
META_JSON = PROJECT_ROOT / "models" / "checkpoints" / "nhtsa" / "nhtsa_nlp_meta.json"
ROSTER_JSON = PROJECT_ROOT / "events" / "roster.json"
OUT_PATH = PROJECT_ROOT / "events" / "out" / "nhtsa_events.jsonl"

SEED = 42
MODEL_VERSION = "nhtsa_tfidf_ovr_v1"

ACTION = {
    "P2": ("Have field quality look at this manufacturer and component before the next "
           "monthly review. The complaint rate moved further than its own recent history "
           "explains, and the module cannot say whether the vehicles or the reporting "
           "changed."),
    "P3": ("Record the movement against this manufacturer and component and carry it into "
           "the monthly field-quality review."),
}


def slug(text):
    """A record id segment: upper case, no spaces, no characters that need escaping."""
    keep = [c if c.isalnum() else "-" for c in text.upper()]
    out = "".join(keep)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


def priority_for(risk_score, band_edge):
    """The size of the movement decides. The reported harm never does."""
    return "P2" if risk_score >= band_edge else "P3"


def main():
    meta = json.loads(META_JSON.read_text(encoding="utf-8"))
    table = json.loads(CELL_JSON.read_text(encoding="utf-8"))
    operating = meta["operating_point"]

    # The two files are written by the same notebook run and can still drift apart if one
    # is regenerated alone. An event built from a stale threshold is wrong in a way
    # nothing downstream checks. Same guard as the GC10 and MVTec adapters.
    for name, in_meta, in_table in (
            ("band edge", operating["band_edge"], table["band_edge"]),
            ("corrected alpha", meta["trend"]["corrected_alpha"], table["corrected_alpha"])):
        if abs(float(in_meta) - float(in_table)) > 1e-9:
            raise SystemExit(
                "%s disagrees: %s in the metrics file, %s in the cell table. One of the "
                "two files is stale; re-run notebook 03." % (name, in_meta, in_table))
    if meta["model_version"] != table["model_version"]:
        raise SystemExit("model version disagrees between the two files")

    band_edge = float(operating["band_edge"])
    rng = random.Random(SEED)
    roster = json.loads(ROSTER_JSON.read_text(encoding="utf-8"))
    analyst = roster["roles"]["field_quality"]
    manager = roster["roles"]["escalation"]

    events = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for cell in table["cells"]:
        risk_score = float(cell["risk_score"])
        priority = priority_for(risk_score, band_edge)
        month = cell["month"]
        pretty_month = "%s-%s" % (month[:4], month[4:])

        event = {
            "event_id": "arkon-2026-6%05d" % (len(events) + 1),
            "event_time": now,
            "source_module": "nhtsa_nlp",
            "business_domain": "field_quality",
            # The component the trend is about, so risk_type varies between this
            # module's own events. NEU was the first to do that, GC10 the second.
            "risk_type": cell["component"],
            "risk_score": round(risk_score, 4),
            "priority": priority,
            "summary": (
                "%s, %s in %s: %d complaints classified to this component against %.1f "
                "expected from its own trailing baseline, %.1f times the rate. Public "
                "complaint reports, not an inspection."
                % (cell["manufacturer"], cell["component"], pretty_month,
                   cell["observed"], cell["expected"], cell["ratio"])
            ),
            "evidence": {
                # Manufacturer, component and month together are the unit that was
                # tested, so the identity is unique over everything this module varies.
                # The MVTec adapter shipped 309 events with 82 identities by naming only
                # part of what its dataset varied, and every adapter since checks.
                "record_id": "NHTSA-%s-%s-%s" % (slug(cell["manufacturer"]),
                                                 slug(cell["component"]), month),
                "model_version": MODEL_VERSION,
                # The count that fired, which is what a reader wants first.
                "prediction": int(cell["observed"]),
                # The count its own history predicted. `prediction` and `threshold` are
                # the two required numeric keys, and here they are two counts rather
                # than a score and a cut, which the contract permits.
                "threshold": round(float(cell["expected"]), 3),
                "threshold_basis": table.get("baseline_basis", meta["trend"]["baseline"]),
                "ratio": cell["ratio"],
                "band_edge": round(band_edge, 4),
                "band_basis": operating["band_basis"],
                "p_value": cell["p_value"],
                "corrected_alpha": table["corrected_alpha"],
                "cells_tested": table["cells_tested"],
                "manufacturer": cell["manufacturer"],
                "component": cell["component"],
                "month": month,
                "month_complaints": cell["month_complaints"],
                "baseline_flagged": cell["baseline_flagged"],
                "baseline_complaints": cell["baseline_complaints"],
                "baseline_months": cell["baseline_months"],
                # The honesty check the other six adapters cannot run: the identical
                # trend procedure over the held-out labels instead of the predictions.
                # False does not mean the cell is wrong, it means the labels do not
                # confirm it, and 48 per cent of this batch is in that position.
                "label_reference_agrees": cell["label_reference_agrees"],
            },
            "context_origin": "real",
            "recommended_action": ACTION[priority],
            "status": "new",
            "operational_context": {
                "context_origin": "simulated",
                "review_cycle": "monthly",
                "assigned_role": analyst["role"],
                "assigned_to": rng.choice(analyst["people"]),
                "escalation_contact": manager["people"][0],
            },
        }
        problems = validate_event(event)
        if problems:
            raise SystemExit("invalid event %s: %s" % (event["event_id"], problems))
        events.append(event)

    # A deduplication key is a claim that two records describe the same thing, and the
    # contract asks for a record id rather than a unique one, so the adapter checks.
    identities = Counter(event["evidence"]["record_id"] for event in events)
    collisions = {key: n for key, n in identities.items() if n > 1}
    if collisions:
        raise SystemExit("record ids are not unique: %s" % collisions)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")

    counts = Counter(event["priority"] for event in events)
    by_component = Counter(event["risk_type"] for event in events)
    groups = Counter((event["evidence"]["manufacturer"], event["evidence"]["month"])
                     for event in events)
    agreeing = sum(1 for e in events if e["evidence"]["label_reference_agrees"])
    trend = meta["trend"]

    print("Tested %d manufacturer-component-month cells in the held-out year; %d cleared"
          % (trend["cells_tested"], len(events)))
    print("the gate at a corrected alpha of %.2e and are published. Every other cell moved"
          % table["corrected_alpha"])
    print("no further than its own trailing baseline explains, and publishes nothing.")
    print("Wrote %d events -> %s" % (len(events), OUT_PATH.relative_to(PROJECT_ROOT)))
    print("Priority breakdown: %s" % dict(sorted(counts.items())))
    print("Band edge %.2f, %s. The band says how large the movement is, never how certain."
          % (band_edge, operating["band_basis"]))
    print("Label-driven trend confirms %d of %d (%.0f%%); the module publishes %.0f%% of"
          % (agreeing, len(events), 100 * agreeing / max(1, len(events)),
             100 * trend["agreement_recall"]))
    print("what that reference flags.")
    print("%d events across %d manufacturer-month groups, largest %d: one cause can move"
          % (len(events), len(groups), max(groups.values()) if groups else 0))
    print("several cells at once, so these alerts are not independent.")
    print("Record ids are unique: %d ids for %d events" % (len(identities), len(events)))
    print("Components published: %s" % dict(by_component.most_common()))


if __name__ == "__main__":
    main()
