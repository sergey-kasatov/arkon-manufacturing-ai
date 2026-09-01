"""Convert NEU steel surface defect classifications into Arkon risk events.

Reads the prediction table produced by
notebooks/03_cv/02_neu_steel_defects/03_neu_modeling.ipynb, maps the model's
confidence to a priority, attaches simulated operational context (fixed seed,
labelled), validates every event, and writes JSONL for the n8n Quality Steering
Cell. Fourth adapter, same contract; the Steering Cell handles it unchanged.

Three things differ from the other three adapters.

**Every classified surface produces an event.** Casting and Scania publish only
what they flag, because a pass is the normal case and publishing it would bury
the incident store. NEU-DET has no good-surface class at all: every one of its
six classes is a defect, so there is no negative case to suppress. This adapter
therefore behaves like the CMAPSS one, which publishes one event per test engine.

**The event carries a defect type**, which the other three do not. `risk_type` is
the predicted class rather than a fixed string, and the evidence object carries
the full six-way probability vector, so a consumer can see the runner-up.

**Priority comes from confidence alone, never from the defect class.** Ranking
crazing against inclusion against pitted surface by severity would need
metallurgical judgement this project does not have, and an invented ranking would
be worse than none. What the module can honestly say is how sure it is:

    confidence >= 0.90   the defect type is logged against the coil, P3
    confidence <  0.90   the model cannot name it and a person must, P2

**And that band edge is declared rather than calibrated.** The intended rule was
to take the lowest confidence at which the accepted predictions on the selection
set are right at least 99 per cent of the time. The model classified all 216
selection images correctly, so every threshold met the target and the rule
returned 0.0, which would put every image in the confident band and leave P2
permanently empty. 0.90 is an Arkon assumption in the same sense as casting's
cost ratios, and it is read from the metrics file rather than written here so the
two cannot drift apart. Full reasoning in docs/Model_Card_NEU_Surface.md section 5.

Usage:
    python events/make_events_neu.py
"""

import json
import random
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from validate_event import validate_event

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRED_NPZ = PROJECT_ROOT / "data" / "04_neu" / "processed" / "test_neu_predictions.npz"
META_JSON = PROJECT_ROOT / "models" / "checkpoints" / "neu" / "neu_cv_meta.json"
ROSTER_JSON = PROJECT_ROOT / "events" / "roster.json"
OUT_PATH = PROJECT_ROOT / "events" / "out" / "neu_events.jsonl"

SEED = 42
MODEL_VERSION = "neu_resnet18_v1"

ACTION = {
    "P2": ("Have QC classify the defect by eye before the coil is dispositioned. The "
           "model is not confident enough for its answer to be recorded unchecked."),
    "P3": "Record the defect type against the coil and continue.",
}


def priority_for(confidence, threshold):
    """Confidence decides the priority. The defect class never does."""
    return "P3" if confidence >= threshold else "P2"


def main():
    meta = json.loads(META_JSON.read_text(encoding="utf-8"))
    threshold = float(meta["operating_point"]["confidence_threshold"])
    declared = bool(meta["operating_point"]["rule_degenerated"])

    data = np.load(PRED_NPZ, allow_pickle=False)
    paths = data["paths"]
    probabilities = data["probabilities"]
    predicted = data["predicted_label"]
    confidence = data["confidence"]
    truth = data["true_label"]
    classes = [str(name) for name in data["classes"]]

    rng = random.Random(SEED)
    roster = json.loads(ROSTER_JSON.read_text(encoding="utf-8"))
    qc = roster["roles"]["visual_inspection"]
    manager = roster["roles"]["escalation"]

    events = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for index, path in enumerate(paths):
        score = float(confidence[index])
        priority = priority_for(score, threshold)
        defect = classes[int(predicted[index])]
        # The image file name is the surface identity; it is the only stable key
        # this dataset carries.
        surface = Path(str(path)).stem
        # Relative to the repository root. An absolute path is this machine's
        # directory layout, it resolves nowhere else, and an event is meant to be
        # readable by whoever receives it.
        try:
            image_path = Path(str(path)).resolve().relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            image_path = Path(str(path)).name
        event = {
            "event_id": "arkon-2026-3%05d" % (len(events) + 1),
            "event_time": now,
            "source_module": "neu_surface",
            "business_domain": "visual_inspection",
            # The defect type, not a fixed string. Casting publishes surface_defect
            # for every event it emits; this module knows which defect it is.
            "risk_type": defect,
            "risk_score": round(score, 4),
            "priority": priority,
            "summary": (
                "Strip surface %s classified as %s, confidence %.3f (band edge %.2f)."
                % (surface, defect, score, threshold)
            ),
            "evidence": {
                "record_id": "NEU-%s" % surface.upper(),
                "model_version": MODEL_VERSION,
                "prediction": round(score, 4),
                "threshold": round(threshold, 4),
                "threshold_basis": "declared" if declared else "calibrated",
                "defect_class": defect,
                "image_path": image_path,
                # The whole distribution, so a consumer can see the runner-up
                # rather than only the winner.
                "class_probabilities": {
                    name: round(float(probabilities[index][position]), 4)
                    for position, name in enumerate(classes)
                },
                "test_label_class": classes[int(truth[index])],
            },
            "context_origin": "real",
            "recommended_action": ACTION[priority],
            "status": "new",
            "operational_context": {
                "context_origin": "simulated",
                "line": rng.choice(["Mill-1", "Mill-2"]),
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
    by_class = {}
    for event in events:
        counts[event["priority"]] += 1
        by_class[event["risk_type"]] = by_class.get(event["risk_type"], 0) + 1
    print("Read %d classified surfaces, all of them published: this dataset has no"
          % len(paths))
    print("good-surface class, so there is no pass to leave unreported.")
    print("Wrote %d events -> %s" % (len(events), OUT_PATH.relative_to(PROJECT_ROOT)))
    print("Priority breakdown: %s" % counts)
    print("Band edge %.2f, %s" % (threshold, "declared" if declared else "calibrated"))
    print("Defect types published: %s"
          % dict(sorted(by_class.items(), key=lambda item: -item[1])))


if __name__ == "__main__":
    main()
