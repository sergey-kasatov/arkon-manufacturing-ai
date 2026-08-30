"""Convert casting-defect predictions into Arkon risk events.

Reads the prediction table produced by
notebooks/03_cv/01_casting_defects/casting_cv.py, maps the predicted defect
probability to a priority, attaches simulated operational context (fixed seed,
labelled), validates every event, and writes JSONL for the n8n Quality Steering
Cell. Third adapter, same contract; the Steering Cell handles it unchanged.

Like the Scania adapter and unlike the CMAPSS one, only flagged parts produce an
event. A pass on an inspection line is the normal case and publishing 255 "part
is fine" events per batch would bury the incident store. The denominator is
printed on every run and recorded in the model card.

**The priority bands run the opposite way to the other two modules, and that is
the point.** Confidence-descending bands were built first and produced 447 P1
events out of one 715-image batch, which is 447 immediate alerts each with a
fifteen-minute acknowledgement window. That is a pager storm, not a triage.

What the numbers say, measured on the test batch:

    probability >= 0.99   447 parts, 447 of them genuinely defective
    operating point..0.99  13 parts,   6 of them genuinely defective
    below the point       255 parts,   0 of them defective

A confident defect is the routine case and the operator already knows what to do
with it: quarantine, log it against the batch, move on. The **uncertain** band is
where the line actually stops, because the part can be neither passed nor
scrapped without a person, and the model is near a coin flip there. So the
uncertain band gets the higher priority and the shorter clock. This module emits
no P1 at all in version 1, and the reason is in the model card.

Priority bands and their justification are in docs/Model_Card_Casting_CV.md; the
charter requires each module to document its own mapping next to the model
(section 7.1).

Usage:
    python events/make_events_casting.py
"""

import json
import random
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from validate_event import validate_event

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRED_NPZ = PROJECT_ROOT / "data" / "03_casting" / "processed" / "test_casting_predictions.npz"
META_JSON = PROJECT_ROOT / "models" / "checkpoints" / "casting" / "casting_cv_meta.json"
ROSTER_JSON = PROJECT_ROOT / "events" / "roster.json"
OUT_PATH = PROJECT_ROOT / "events" / "out" / "casting_events.jsonl"

SEED = 42
MODEL_VERSION = "casting_resnet18_v1"

# Confidence bands on the predicted defect probability. Read the docstring before
# changing these: they descend the opposite way to the other two modules on
# purpose, and the reason is in the numbers, not in taste.
CONFIDENT = 0.99  # the model is certain, and on the test batch it was right 447 of 447

ACTION = {
    "P2": ("Stop the part and have QC decide. The model is not confident, so it can be "
           "neither passed nor scrapped without a person."),
    "P3": "Quarantine the part and log the defect against the batch.",
}


def priority_for(probability, threshold):
    if probability >= CONFIDENT:
        return "P3"  # routine scrap: queued, reviewed daily, no push alert
    if probability >= threshold:
        return "P2"  # uncertain: a human is blocking, acknowledge within the hour
    return None      # below the operating point: the part passes, no event


def main():
    meta = json.loads(META_JSON.read_text(encoding="utf-8"))
    # The 25:1 operating point is the shipped one, per the model card.
    threshold = float(meta["operating_points"]["missed_defect_costs_25x"]["threshold"])

    data = np.load(PRED_NPZ, allow_pickle=False)
    paths = data["paths"]
    probabilities = data["defect_probability"]
    truth = data["true_label"]
    defect_index = int(meta["classes"]["def_front"])

    rng = random.Random(SEED)
    roster = json.loads(ROSTER_JSON.read_text(encoding="utf-8"))
    qc = roster["roles"]["visual_inspection"]
    manager = roster["roles"]["escalation"]

    events = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for path, probability, label in zip(paths, probabilities, truth):
        probability = float(probability)
        priority = priority_for(probability, threshold)
        if priority is None:
            continue
        index = len(events) + 1
        # The image file name is the part identity; it is the only stable key
        # this dataset carries.
        part = Path(str(path)).stem
        # Relative to the repository root. The absolute path is this machine's
        # directory layout, it resolves nowhere else, and an event is meant to be
        # readable by whoever receives it.
        try:
            image_path = Path(str(path)).resolve().relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            image_path = Path(str(path)).name
        event = {
            "event_id": "arkon-2026-2%05d" % index,
            "event_time": now,
            "source_module": "casting_cv",
            "business_domain": "visual_inspection",
            "risk_type": "surface_defect",
            "risk_score": round(probability, 4),
            "priority": priority,
            "summary": (
                "Impeller %s flagged by visual inspection, defect probability %.3f "
                "(operating point %.4f)." % (part, probability, threshold)
            ),
            "evidence": {
                "record_id": "CASTING-%s" % part.upper(),
                "model_version": MODEL_VERSION,
                "prediction": round(probability, 4),
                "threshold": round(threshold, 4),
                "image_path": image_path,
                "test_label_class": "def" if int(label) == defect_index else "ok",
            },
            "context_origin": "real",
            "recommended_action": ACTION[priority],
            "status": "new",
            "operational_context": {
                "context_origin": "simulated",
                "line": rng.choice(["Cast-1", "Cast-2"]),
                "shift": rng.choice(["A", "B", "C"]),
                "assigned_role": qc["role"],
                "assigned_to": rng.choice(qc["people"]),
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
    print("Read %d inspected parts, %d above the operating point %.4f"
          % (len(paths), len(events), threshold))
    print("Wrote %d events -> %s" % (len(events), OUT_PATH.relative_to(PROJECT_ROOT)))
    print("Priority breakdown: %s" % counts)
    print("Parts that passed and are deliberately not published: %d"
          % (len(paths) - len(events)))


if __name__ == "__main__":
    main()
