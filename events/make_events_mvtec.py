"""Convert MVTec AD anomaly scores into Arkon risk events.

Reads the prediction table produced by
notebooks/03_cv/03_mvtec_anomaly/03_mvtec_modeling.ipynb, maps each flagged part
to a priority, attaches simulated operational context (fixed seed, labelled),
validates every event, and writes JSONL for the n8n Quality Steering Cell. Fifth
adapter, same contract; the Steering Cell handles it unchanged.

Three things differ from the other four adapters.

**There are four models behind one event stream.** grid, metal_nut, screw and
transistor are four imaging setups with four memory banks and four thresholds,
so the threshold an event carries depends on which category produced it. The
category rides in `evidence.category` and every event names the threshold it was
judged against.

**Only flagged parts produce an event.** Like casting and Scania and unlike
CMAPSS and NEU, a sound part is the normal case and publishing every pass would
bury the incident store. The suppressed count is printed on every run and
recorded in the model card.

**The priority says how unusual, never how dangerous.** This module is fitted on
sound parts alone and has never seen a defect, so it has no basis for ranking a
scratch against a bent lead. What it can say is whether any sound part it held
out ever scored this high:

    score above the ceiling    no held-out sound part reached this, P2
    score above the threshold  inside the range sound parts reach, P3

Both edges are quantiles of the calibration set, which contains no defect. There
is no P1 band, deliberately: P1 in the charter means safety-relevant, and this
module cannot judge severity. Full reasoning in
docs/Model_Card_MVTec_Anomaly.md section 5.

**The scalar the contract carries** is bounded without saturating:

    risk_score = score / (score + threshold)

so the threshold sits at exactly 0.5 for every category, whatever its raw
distances look like. The raw distance rides in `evidence.prediction` so ranking
above the band is not lost.

Usage:
    python events/make_events_mvtec.py
"""

import json
import random
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from validate_event import validate_event

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRED_NPZ = PROJECT_ROOT / "data" / "05_mvtec" / "processed" / "test_mvtec_predictions.npz"
META_JSON = PROJECT_ROOT / "models" / "checkpoints" / "mvtec" / "mvtec_cv_meta.json"
ROSTER_JSON = PROJECT_ROOT / "events" / "roster.json"
OUT_PATH = PROJECT_ROOT / "events" / "out" / "mvtec_events.jsonl"

SEED = 42
MODEL_VERSION = "mvtec_patchcore_v1"

# Which line photographs which component. Simulated, like every other operational
# field in this project, and labelled as such inside the event.
LINE = {"grid": "Comp-1", "metal_nut": "Comp-2", "screw": "Comp-3", "transistor": "Comp-4"}

ACTION = {
    "P2": ("Pull the part and inspect it this shift. No sound part in the held-out set "
           "scored this high, so the model has no precedent for accepting it."),
    "P3": ("Queue the part for review. It is above the flagging threshold but inside the "
           "range sound parts reach, so a person decides."),
}


def priority_for(score, threshold, ceiling):
    """How unusual the part is, never how dangerous. None means do not publish."""
    if score > ceiling:
        return "P2"
    if score > threshold:
        return "P3"
    return None


def main():
    meta = json.loads(META_JSON.read_text(encoding="utf-8"))
    operating = meta["operating_point"]["per_category"]
    image_size = meta["image_size"]

    data = np.load(PRED_NPZ, allow_pickle=False)
    paths = data["paths"]
    categories = data["category"]
    defects = data["defect"]
    scores = data["score"]
    risks = data["risk"]
    thresholds = data["threshold"]
    ceilings = data["ceiling"]
    truth = data["true_label"]
    flagged_area = data["flagged_area"]

    rng = random.Random(SEED)
    roster = json.loads(ROSTER_JSON.read_text(encoding="utf-8"))
    qc = roster["roles"]["visual_inspection"]
    manager = roster["roles"]["escalation"]

    events = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for index in range(len(paths)):
        category = str(categories[index])
        score = float(scores[index])
        threshold = float(thresholds[index])
        ceiling = float(ceilings[index])
        priority = priority_for(score, threshold, ceiling)
        if priority is None:
            continue
        # The threshold in the table and the threshold in the metrics file are written
        # by the same run; disagreeing would mean one of the two files is stale.
        recorded = float(operating[category]["threshold"])
        if abs(recorded - threshold) > 1e-4:
            raise SystemExit("threshold mismatch for %s: table %.4f, metrics file %.4f"
                             % (category, threshold, recorded))
        # The image file name repeats across categories AND across the defect-type
        # folders inside one category, because MVTec numbers from 000 in every
        # folder. grid/test/bent/000.png and grid/test/broken/000.png are two
        # different parts, so the identity has to carry all three parts of the path.
        # Category alone left 309 events sharing 82 record ids, and the Steering
        # Cell dedups on record_id plus priority, so 203 flagged parts would have
        # been suppressed as duplicates of each other.
        defect_type = str(defects[index])
        part = "%s-%s-%s" % (category, defect_type, Path(str(paths[index])).stem)
        event = {
            "event_id": "arkon-2026-4%05d" % (len(events) + 1),
            "event_time": now,
            "source_module": "mvtec_anomaly",
            "business_domain": "visual_inspection",
            # A fixed string, unlike NEU. This module detects that a part is unlike the
            # sound ones; it cannot name what is wrong with it.
            "risk_type": "component_anomaly",
            "risk_score": round(float(risks[index]), 4),
            "priority": priority,
            "summary": (
                "Component %s flagged as anomalous, score %.3f against a threshold of "
                "%.3f and a sound-part ceiling of %.3f." % (part, score, threshold, ceiling)
            ),
            "evidence": {
                "record_id": "MVTEC-%s" % part.upper(),
                "model_version": "%s_%s" % (MODEL_VERSION, category),
                "prediction": round(score, 4),
                "threshold": round(threshold, 4),
                "threshold_basis": "declared false-alarm budget on held-out sound parts",
                "ceiling": round(ceiling, 4),
                "category": category,
                # Share of the feature grid above the threshold: how much of the frame
                # the module considers anomalous, not a calibrated defect area.
                "flagged_area_fraction": round(float(flagged_area[index]), 4),
                "image_path": str(paths[index]),
                "image_size": image_size,
                "test_label_class": "defect" if int(truth[index]) == 1 else "good",
                "test_defect_type": defect_type,
            },
            "context_origin": "real",
            "recommended_action": ACTION[priority],
            "status": "new",
            "operational_context": {
                "context_origin": "simulated",
                "line": LINE[category],
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
    by_category = {}
    for event in events:
        counts[event["priority"]] += 1
        key = event["evidence"]["category"]
        by_category[key] = by_category.get(key, 0) + 1
    published = np.array([priority_for(float(scores[i]), float(thresholds[i]),
                                       float(ceilings[i])) is not None
                          for i in range(len(paths))])
    print("Read %d scored parts across %d categories, %d above their own threshold"
          % (len(paths), len(set(categories.tolist())), len(events)))
    print("Wrote %d events -> %s" % (len(events), OUT_PATH.relative_to(PROJECT_ROOT)))
    print("Priority breakdown: %s" % counts)
    print("Events per category: %s" % dict(sorted(by_category.items())))
    print("Parts judged sound and deliberately not published: %d" % int((~published).sum()))
    print("Defective parts the module did not flag, so no event exists for them: %d"
          % int((~published & (truth == 1)).sum()))
    print("Sound parts published as a false alarm: %d" % int((published & (truth == 0)).sum()))


if __name__ == "__main__":
    main()
