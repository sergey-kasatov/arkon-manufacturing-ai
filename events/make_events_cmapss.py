"""Convert CMAPSS test predictions into Arkon risk events, whole fleet.

Reads the prediction table produced by notebooks/01_timeseries/cmapss_full_fleet.py,
keeps the last cycle per engine (its current state), maps predicted RUL to a priority,
attaches simulated operational context (fixed seed, labelled), validates
every event, and writes JSONL for the n8n Quality Steering Cell.

Priority thresholds and the risk-score formula are owned by
docs/Project_Charter.md section 7.1.

Usage:
    python events/make_events_cmapss.py
"""

import json
import random
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from validate_event import validate_event

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRED_CSV = PROJECT_ROOT / "data" / "01_cmapss" / "processed" / "test_full_fleet_predictions.csv"
ROSTER_JSON = PROJECT_ROOT / "events" / "roster.json"
OUT_PATH = PROJECT_ROOT / "events" / "out" / "cmapss_events_full_fleet.jsonl"

RUL_CAP = 125
SEED = 42
MODEL_VERSION = "xgboost_full_fleet_v1"

# Priority mapping on predicted RUL in cycles - charter section 7.1
PRIORITY_THRESHOLDS = [(10, "P1"), (25, "P2"), (50, "P3")]
THRESHOLD = {"P1": 10, "P2": 25, "P3": 50, "P4": 50}
ACTION = {
    "P1": "Schedule immediate inspection before the next test run.",
    "P2": "Schedule inspection before the next operating window.",
    "P3": "Add the unit to the next planned maintenance slot.",
    "P4": "No action required; keep monitoring the trend.",
}


def priority_for(pred_rul: float) -> str:
    for threshold, priority in PRIORITY_THRESHOLDS:
        if pred_rul <= threshold:
            return priority
    return "P4"


# Load predictions - last cycle per engine is its current state
df = pd.read_csv(PRED_CSV)
# Unit numbers repeat across the four subsets, so group by both.
last = df[df["is_last_cycle"]].sort_values(["dataset", "unit"])

# Simulated operational context - fixed seed and labelling per charter section 5
rng = random.Random(SEED)
roster = json.loads(ROSTER_JSON.read_text(encoding="utf-8"))
planner = roster["roles"]["asset_reliability"]
manager = roster["roles"]["escalation"]

# Build and validate events
events = []
now = datetime.now(timezone.utc).isoformat(timespec="seconds")
for i, row in enumerate(last.itertuples(index=False), start=1):
    pred = float(row.pred_RUL)
    prio = priority_for(pred)
    event = {
        "event_id": f"arkon-2026-{i:06d}",
        "event_time": now,
        "source_module": "cmapss_rul",
        "business_domain": "asset_reliability",
        "risk_type": "maintenance",
        "risk_score": round(1 - min(max(pred, 0), RUL_CAP) / RUL_CAP, 4),
        "priority": prio,
        "summary": (
            f"Engine unit {int(row.unit)} of {row.dataset} predicted RUL {pred:.0f} cycles "
            f"(priority threshold {THRESHOLD[prio]})."
        ),
        "evidence": {
            "record_id": f"{row.dataset}-Unit-{int(row.unit):03d}",
            "model_version": MODEL_VERSION,
            "prediction": round(pred, 1),
            "threshold": THRESHOLD[prio],
            "test_label_rul": int(row.RUL),
        },
        "context_origin": "real",
        "recommended_action": ACTION[prio],
        "status": "new",
        "operational_context": {
            "context_origin": "simulated",
            "shift": rng.choice(["A", "B", "C"]),
            "test_cell": rng.randint(1, 4),
            "assigned_role": planner["role"],
            "assigned_to": rng.choice(planner["people"]),
            "escalation_contact": manager["people"][0],
        },
    }
    problems = validate_event(event)
    if problems:
        raise SystemExit(f"invalid event {event['event_id']}: {problems}")
    events.append(event)

# Write JSONL and report the priority breakdown
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
with open(OUT_PATH, "w", encoding="utf-8") as f:
    for event in events:
        f.write(json.dumps(event) + "\n")

counts = {p: 0 for p in ["P1", "P2", "P3", "P4"]}
for event in events:
    counts[event["priority"]] += 1
print(f"Wrote {len(events)} events -> {OUT_PATH.relative_to(PROJECT_ROOT)}")
print(f"Priority breakdown: {counts}")
