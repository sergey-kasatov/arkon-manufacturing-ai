"""Convert Scania APS predictions into Arkon risk events.

Reads the prediction table produced by notebooks/02_ml/scania_aps.py, maps the
predicted failure probability to a priority, attaches simulated operational
context (fixed seed, labelled), validates every event, and writes JSONL for the
n8n Quality Steering Cell. The same shape as events/make_events_cmapss.py, and
deliberately so: a second module that publishes the same contract is what makes
the Steering Cell a platform rather than one model's plumbing.

Two things differ from the CMAPSS adapter, and both are decisions rather than
details.

**Only flagged records produce an event.** CMAPSS publishes one event per engine
because the fleet is 707 engines and the operator watches all of them, so a P4
"nothing to do" event is a dashboard row worth having. Here the test set is
16,000 service records and 738 are flagged. Publishing 15,262 P4 events would
bury the incident store to say nothing. The denominator is not lost: it is
printed on every run and recorded in the model card.

**The priority bands are confidence bands, not threshold distances.** The
cost-optimal decision threshold is very low, because a missed APS failure costs
fifty times a needless workshop check, so most flags are precautionary rather
than confident. A flag at probability 0.004 and a flag at 0.99 are the same
decision - check the truck - and very different conversations, and collapsing
them into one priority would waste the operator's fifteen-minute P1 window on
precautionary checks. Bands and their justification are in
docs/Model_Card_Scania_APS.md; the charter requires each module to document its
own mapping next to the model (section 7.1).

Usage:
    python events/make_events_scania.py
"""

import json
import random
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from validate_event import validate_event

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRED_CSV = PROJECT_ROOT / "data" / "02_scania" / "processed" / "test_scania_predictions.csv"
META_JSON = PROJECT_ROOT / "models" / "checkpoints" / "scania" / "scania_aps_meta.json"
ROSTER_JSON = PROJECT_ROOT / "events" / "roster.json"
OUT_PATH = PROJECT_ROOT / "events" / "out" / "scania_events.jsonl"

SEED = 42
MODEL_VERSION = "scania_xgboost_v1"

# Confidence bands on the predicted failure probability. The decision threshold
# itself comes from the model metadata, so this file cannot drift from the model.
P1_MIN = 0.90  # a confident APS failure prediction
P2_MIN = 0.50  # more likely than not

ACTION = {
    "P1": "Hold the truck and book the workshop before the next run.",
    "P2": "Book an APS check within the shift.",
    "P3": "Add an APS check to the next planned service slot.",
}


def priority_for(probability, threshold):
    if probability >= P1_MIN:
        return "P1"
    if probability >= P2_MIN:
        return "P2"
    if probability >= threshold:
        return "P3"
    return None  # below the decision threshold: no event


def main():
    meta = json.loads(META_JSON.read_text(encoding="utf-8"))
    threshold = float(meta["chosen_threshold"])
    frame = pd.read_csv(PRED_CSV)

    rng = random.Random(SEED)
    roster = json.loads(ROSTER_JSON.read_text(encoding="utf-8"))
    engineer = roster["roles"]["fleet_reliability"]
    manager = roster["roles"]["escalation"]

    events = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for row in frame.itertuples(index=False):
        probability = float(row.failure_probability)
        priority = priority_for(probability, threshold)
        if priority is None:
            continue
        index = len(events) + 1
        event = {
            "event_id": "arkon-2026-1%05d" % index,
            "event_time": now,
            "source_module": "scania_aps",
            "business_domain": "fleet_reliability",
            "risk_type": "component_failure",
            "risk_score": round(probability, 4),
            "priority": priority,
            "summary": (
                "Truck record %d flagged for the air pressure system, failure probability %.3f "
                "(decision threshold %.4f)." % (int(row.row_id), probability, threshold)
            ),
            "evidence": {
                "record_id": "SCANIA-APS-%06d" % int(row.row_id),
                "model_version": MODEL_VERSION,
                "prediction": round(probability, 4),
                "threshold": round(threshold, 4),
                "test_label_class": "pos" if int(row.true_class) == 1 else "neg",
            },
            "context_origin": "real",
            "recommended_action": ACTION[priority],
            "status": "new",
            "operational_context": {
                "context_origin": "simulated",
                "depot": rng.choice(["North", "South", "East"]),
                "assigned_role": engineer["role"],
                "assigned_to": rng.choice(engineer["people"]),
                "escalation_contact": manager["people"][0],
            },
        }
        problems = validate_event(event)
        if problems:
            raise SystemExit("invalid event %s: %s" % (event["event_id"], problems))
        events.append(event)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")

    counts = {"P1": 0, "P2": 0, "P3": 0, "P4": 0}
    for event in events:
        counts[event["priority"]] += 1
    print("Read %d records, %d above the decision threshold %.4f"
          % (len(frame), len(events), threshold))
    print("Wrote %d events -> %s" % (len(events), OUT_PATH.relative_to(PROJECT_ROOT)))
    print("Priority breakdown: %s" % counts)
    print("Records below the threshold and deliberately not published: %d"
          % (len(frame) - len(events)))


if __name__ == "__main__":
    main()
