"""Validate Arkon risk events against the shared contract.

The formal contract lives in arkon_event_schema.json. This module implements
the same rules with stdlib only, so any pipeline can validate events without
extra dependencies.

Usage:
    python events/validate_event.py events/out/cmapss_events_FD001.jsonl
"""

import json
import sys
from datetime import datetime
from pathlib import Path

PRIORITIES = {"P1", "P2", "P3", "P4"}
STATUSES = {"new", "acknowledged", "in_containment", "resolved", "closed", "false_positive"}
SOURCE_MODULES = {"cmapss_rul", "scania_aps", "casting_cv", "nhtsa_nlp"}
BUSINESS_DOMAINS = {"asset_reliability", "fleet_reliability", "visual_inspection", "field_quality"}
CONTEXT_ORIGINS = {"real", "simulated"}

REQUIRED_FIELDS = [
    "event_id", "event_time", "source_module", "business_domain", "risk_type",
    "risk_score", "priority", "summary", "evidence", "context_origin",
    "recommended_action", "status",
]
REQUIRED_EVIDENCE = ["record_id", "model_version", "prediction", "threshold"]


def validate_event(event: dict) -> list:
    """Return a list of problems; an empty list means the event is valid."""
    errors = []
    for field in REQUIRED_FIELDS:
        if field not in event:
            errors.append(f"missing field: {field}")
    if errors:
        return errors

    if not isinstance(event["event_id"], str) or not event["event_id"].startswith("arkon-"):
        errors.append("event_id must be a string like arkon-YYYY-NNNNNN")
    try:
        datetime.fromisoformat(str(event["event_time"]).replace("Z", "+00:00"))
    except ValueError:
        errors.append("event_time is not ISO 8601")
    if event["source_module"] not in SOURCE_MODULES:
        errors.append(f"unknown source_module: {event['source_module']}")
    if event["business_domain"] not in BUSINESS_DOMAINS:
        errors.append(f"unknown business_domain: {event['business_domain']}")
    if not isinstance(event["risk_score"], (int, float)) or not 0 <= event["risk_score"] <= 1:
        errors.append("risk_score must be a number in [0, 1]")
    if event["priority"] not in PRIORITIES:
        errors.append(f"priority must be one of {sorted(PRIORITIES)}")
    if event["status"] not in STATUSES:
        errors.append(f"status must be one of {sorted(STATUSES)}")
    if event["context_origin"] not in CONTEXT_ORIGINS:
        errors.append("context_origin must be real or simulated")
    if not isinstance(event["evidence"], dict):
        errors.append("evidence must be an object")
    else:
        for field in REQUIRED_EVIDENCE:
            if field not in event["evidence"]:
                errors.append(f"missing evidence field: {field}")

    # Simulated demonstration fields must always be labelled (charter section 5)
    context = event.get("operational_context")
    if context is not None:
        if not isinstance(context, dict) or context.get("context_origin") != "simulated":
            errors.append("operational_context must carry context_origin: simulated")

    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"file not found: {path}")
        return 2

    # Accept one JSON object, a JSON list, or JSONL (one object per line)
    text = path.read_text(encoding="utf-8").strip()
    if path.suffix == ".jsonl":
        events = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        loaded = json.loads(text)
        events = loaded if isinstance(loaded, list) else [loaded]

    bad = 0
    for event in events:
        problems = validate_event(event)
        if problems:
            bad += 1
            print(f"INVALID {event.get('event_id', '<no id>')}: {'; '.join(problems)}")

    print(f"{len(events) - bad}/{len(events)} events valid")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
