"""Convert GC10 steel sheet defect detections into Arkon risk events.

Reads the prediction table produced by
notebooks/03_cv/04_gc10_steel_defects/03_gc10_modeling.ipynb, maps the best
detection on a sheet to a priority, attaches simulated operational context (fixed
seed, labelled), validates every event, and writes JSONL for the n8n Quality
Steering Cell. Sixth adapter, same contract; the Steering Cell handles it unchanged.

Three things differ from the five adapters before it.

**The event carries a list.** Every other module publishes one measurement per
record: a remaining useful life, a failure probability, an anomaly score. A
detector publishes n boxes on one sheet, and 35 per cent of the sheets in this
dataset carry more than one, up to eleven. The event is still one per sheet, with
the boxes inside `evidence.detections`.

The contract needed no change for that. `evidence` is declared with
`additionalProperties: true` in arkon_event_schema.json and validate_event.py
checks only that the four required keys are present, so a list fits where it
stands. The one closed enum that did change is `source_module`, which gained
`gc10_detect` in both files, exactly as neu_surface and mvtec_anomaly did.

**One event per sheet rather than one per box, and the reason is downstream.** The
Steering Cell deduplicates on `record_id` plus `priority` for 24 hours. One event
per box would give up to eleven events carrying one sheet identity and usually one
priority, so ten of the eleven would be suppressed as duplicates of a defect they
are not. That is the MVTec identity defect arriving by a different route, and it
was cheaper to avoid than to find. A sheet is also the unit an operator disposes
of: eleven defects on one sheet is one decision, not eleven.

**A sheet with nothing on it publishes nothing, and that is not a pass.** Casting,
Scania and MVTec suppress their negative case because a sound part is the normal
one. This module suppresses its silent case for a different reason and the
distinction belongs on the record: GC10 contains no sheet anyone certified clean,
the module was fitted and scored only on sheets that carry a defect, so it has
never seen sound steel. "No detection" is a failure to find, not a statement that
the sheet is good. Reasoning in docs/Model_Card_GC10_Detection.md section 6.

Priority comes from the confidence of the best box and never from the defect class,
which is the NEU precedent, and never from the defect's size, which would be a
severity claim this module cannot support: a large water spot is cosmetic and a
small crease may not be.

Usage:
    python events/make_events_gc10.py
"""

import json
import random
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from validate_event import validate_event

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRED_JSON = PROJECT_ROOT / "data" / "06_gc10" / "processed" / "test_gc10_predictions.json"
META_JSON = PROJECT_ROOT / "models" / "checkpoints" / "gc10" / "gc10_cv_meta.json"
ROSTER_JSON = PROJECT_ROOT / "events" / "roster.json"
OUT_PATH = PROJECT_ROOT / "events" / "out" / "gc10_events.jsonl"

SEED = 42
MODEL_VERSION = "gc10_fasterrcnn_v1"

ACTION = {
    "P2": ("Have QC look at the located defect before the coil is dispositioned. The model "
           "found something and is not confident enough about what it is for the answer to "
           "be recorded unchecked."),
    "P3": "Record the located defect against the coil and continue.",
}


def priority_for(best_score, band_edge):
    """The best box on the sheet decides. The defect class and its size never do."""
    return "P3" if best_score >= band_edge else "P2"


def main():
    meta = json.loads(META_JSON.read_text(encoding="utf-8"))
    table = json.loads(PRED_JSON.read_text(encoding="utf-8"))
    operating = meta["operating_point"]

    # The two files are written by the same notebook run and can still drift apart if
    # one is regenerated alone. A disagreement means one of them is stale, and an
    # event built from a stale threshold is wrong in a way nothing downstream checks.
    for name, in_meta, in_table in (
            ("band edge", operating["band_edge"], table["band_edge"]),
            ("detection threshold", operating["detection_threshold"],
             table["detection_threshold"])):
        if abs(float(in_meta) - float(in_table)) > 1e-4:
            raise SystemExit(
                "%s disagrees: %s in the metrics file, %s in the prediction table. "
                "One of the two files is stale; re-run notebook 03." % (name, in_meta, in_table))

    band_edge = float(operating["band_edge"])
    detection_threshold = float(operating["detection_threshold"])

    rng = random.Random(SEED)
    roster = json.loads(ROSTER_JSON.read_text(encoding="utf-8"))
    qc = roster["roles"]["visual_inspection"]
    manager = roster["roles"]["escalation"]

    events, silent = [], 0
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for sheet in table["sheets"]:
        detections = sheet["detections"]
        if not detections:
            # Nothing above the detection threshold. The module has made no claim about
            # this sheet, which is not the same as calling it sound, so it publishes
            # nothing rather than a P4 it could not defend.
            silent += 1
            continue

        best = detections[0]                     # the table is written score-descending
        score = float(best["score"])
        priority = priority_for(score, band_edge)
        width, height = sheet["image_size"]
        classes_present = Counter(d["class_name"] for d in detections)

        event = {
            "event_id": "arkon-2026-5%05d" % (len(events) + 1),
            "event_time": now,
            "source_module": "gc10_detect",
            "business_domain": "visual_inspection",
            # The defect type of the best box, not a fixed string. This is the second
            # module whose risk_type varies between its own events; NEU is the first.
            "risk_type": best["class_name"],
            "risk_score": round(score, 4),
            "priority": priority,
            "summary": (
                "Sheet %s: %d defect%s located, best is %s at %.3f (band edge %.2f)."
                % (sheet["stem"], len(detections), "" if len(detections) == 1 else "s",
                   best["class_name"], score, band_edge)
            ),
            "evidence": {
                # The file stem carries the coil and the frame, so it is unique over
                # everything this dataset varies. The MVTec adapter learned that the
                # hard way by shipping 309 events with 82 identities.
                "record_id": "GC10-%s" % sheet["stem"].upper(),
                "model_version": MODEL_VERSION,
                "prediction": round(score, 4),
                "threshold": round(band_edge, 4),
                "threshold_basis": operating["band_basis"],
                "defect_class": best["class_name"],
                "defect_count": len(detections),
                "classes_present": dict(sorted(classes_present.items(),
                                               key=lambda item: -item[1])),
                # The whole list, so a consumer can see every defect on the sheet and
                # where each one is, rather than only the one that set the priority.
                "detections": [
                    {"class_name": d["class_name"],
                     "class_id": d["class_id"],
                     "score": d["score"],
                     "box_xyxy": d["box"],
                     "area_fraction": round(
                         (d["box"][2] - d["box"][0]) * (d["box"][3] - d["box"][1])
                         / (width * height), 5)}
                    for d in detections],
                # The second operating point, carried so a consumer knows what was
                # filtered out before the list above was built.
                "detection_threshold": round(detection_threshold, 4),
                "detection_threshold_basis": operating["threshold_basis"],
                "image_path": sheet["image_path"],
                "image_size": sheet["image_size"],
                "coil": sheet["source"],
                # The held-out labels, for the same honesty check the other adapters
                # carry: what the annotation says is on this sheet.
                "test_label_classes": sorted({t["class_name"] for t in sheet["truth"]}),
            },
            "context_origin": "real",
            "recommended_action": ACTION[priority],
            "status": "new",
            "operational_context": {
                "context_origin": "simulated",
                "line": rng.choice(["Press-1", "Press-2"]),
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

    # A deduplication key is a claim that two records describe the same thing. The
    # contract asks for a record id and not for a unique one, so the adapter checks.
    identities = Counter(event["evidence"]["record_id"] for event in events)
    collisions = {key: n for key, n in identities.items() if n > 1}
    if collisions:
        raise SystemExit("record ids are not unique: %s" % collisions)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")

    counts = {"P1": 0, "P2": 0, "P3": 0, "P4": 0}
    by_class = Counter()
    boxes = 0
    for event in events:
        counts[event["priority"]] += 1
        by_class[event["risk_type"]] += 1
        boxes += event["evidence"]["defect_count"]
    scored = len(table["sheets"])
    print("Read %d scored sheets. %d carry a box above %.2f and are published; %d carry none"
          % (scored, len(events), detection_threshold, silent))
    print("and publish nothing, because a detector that found nothing has made no claim.")
    print("Wrote %d events -> %s" % (len(events), OUT_PATH.relative_to(PROJECT_ROOT)))
    print("Priority breakdown: %s" % counts)
    print("Band edge %.2f, %s. Detection threshold %.2f, %s."
          % (band_edge, operating["band_basis"], detection_threshold,
             operating["threshold_basis"]))
    print("%d boxes ride inside %d events, %.2f per sheet, most on one sheet %d"
          % (boxes, len(events), boxes / max(1, len(events)),
             max(event["evidence"]["defect_count"] for event in events) if events else 0))
    print("Record ids are unique: %d ids for %d events" % (len(identities), len(events)))
    print("Defect types published: %s" % dict(by_class.most_common()))


if __name__ == "__main__":
    main()
