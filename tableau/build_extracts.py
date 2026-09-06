"""Build the Tableau extracts from the live Steering Cell.

Charter 7.5: "Tableau reads periodic extracts and serves as the executive KPI
view: open incidents by priority, response times, and trend Pareto. A live
Tableau connection would require a paid Tableau Server; extract refresh is the
documented portfolio boundary."

So this is the refresh. It writes tidy fact tables rather than pre-aggregated
answers, because a Pareto and a response-time distribution are different cuts of
the same rows and deciding them here would put the analysis in a Python script
that the workbook then has to agree with.

Every row comes from `GET /webhook/arkon-incident-status`, the same contract the
cockpit and the assistant read, so all three report the same state. In particular
the `status` column is the transition log folded onto the incident record: the
store itself says `new` for every incident and always will.

Stdlib only.

Usage:
    python tableau/build_extracts.py
    python tableau/build_extracts.py --api http://AK2101:5678/webhook/arkon-incident-status
"""

import argparse
import csv
import datetime
import json
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_API = "http://AK2101:5678/webhook/arkon-incident-status"
OUT = pathlib.Path(__file__).resolve().parent / "extracts"

# Charter 7.2. Every incident is in exactly one of these, which is what makes the
# per-state sweep below both complete and free of duplicates.
LIFECYCLE = ["new", "acknowledged", "in_containment", "resolved", "closed", "false_positive"]

# The status API has no pagination; that moves with the queryable store of charter
# 7.5. Asking per lifecycle state raises the ceiling without needing one, and the
# script says so if it ever hits it.
#
# Its maximum was raised from 50 to 500 on 2026-09-06, because 50 had started to
# truncate the dashboards: the live plant pushed closed incidents past it. The cap
# never was a load limit - the workflow reads both JSONL files whole on every request
# regardless - so it cost completeness and saved nothing.
PAGE = 500


def get(api, **params):
    url = api + "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        sys.exit("the Steering Cell did not answer (%s). Nothing was written." % err)


def collect(api):
    """Every incident, swept one lifecycle state at a time."""
    incidents = []
    truncated = []
    summary = None
    for state in LIFECYCLE:
        answer = get(api, status=state, limit=PAGE)
        if answer.get("status") not in ("ok", "no_match"):
            sys.exit("the lookup failed for status=%s: %s. Nothing was written."
                     % (state, answer.get("message", answer.get("errors"))))
        summary = summary or answer
        if answer.get("match_count", 0) > answer.get("returned", 0):
            truncated.append("%s (%d of %d)" % (state, answer["returned"], answer["match_count"]))
        incidents.extend(answer.get("incidents", []))
    return incidents, summary, truncated


def _typed(row):
    """Write booleans as TRUE and FALSE, which is the form Tableau's CSV
    connector types as Boolean rather than as a two-value string. None stays an
    empty cell, which it reads as Null."""
    return {k: ("TRUE" if v is True else "FALSE" if v is False else v) for k, v in row.items()}


def write(name, rows, fields):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(_typed(row) for row in rows)
    print("  %-24s %4d rows" % (name, len(rows)))
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default=DEFAULT_API)
    args = parser.parse_args()

    incidents, summary, truncated = collect(args.api)
    as_of = summary.get("as_of") or datetime.datetime.now(datetime.timezone.utc).isoformat()
    store = summary.get("store", {})
    times = summary.get("response_times", {})

    print("read %d incidents from %s" % (len(incidents), args.api))

    # One row per incident. Flat, with the lifecycle timings alongside, so the
    # workbook needs no join for the response-time views.
    rows = []
    for item in incidents:
        life = item.get("lifecycle") or {}
        rows.append({
            "incident_id": item["incident_id"],
            "created_at": item["created_at"],
            "priority": item["priority"],
            "status": item["status"],
            "raised_as": item.get("raised_as"),
            "is_open": item["status"] in ("new", "acknowledged", "in_containment"),
            "is_terminal": life.get("is_terminal"),
            "overdue": item["overdue"],
            "age_minutes": item["age_minutes"],
            "acknowledge_due_minutes": item["acknowledge_due_minutes"],
            "minutes_to_acknowledge": life.get("minutes_to_acknowledge"),
            "minutes_to_resolve": life.get("minutes_to_resolve"),
            "minutes_to_close": life.get("minutes_to_close"),
            "transition_count": life.get("transition_count"),
            "acknowledged_at": life.get("acknowledged_at"),
            "resolved_at": life.get("resolved_at"),
            "closed_at": life.get("closed_at"),
            "source_module": item["source_module"],
            "business_domain": item["business_domain"],
            "assigned_to": item["assigned_to"],
            "assigned_role": item["assigned_role"],
            "escalation_contact": item["escalation_contact"],
            "record_id": item["record_id"],
            "risk_score": item["risk_score"],
            "model_version": item["model_version"],
            "event_id": item["event_id"],
            "data_origin": item["data_origin"],
            "operational_context_origin": item["operational_context_origin"],
            "summary": item["summary"],
            "recommended_action": item["recommended_action"],
        })
    rows.sort(key=lambda r: r["incident_id"])
    print("writing to %s" % OUT)
    write("incidents.csv", rows, list(rows[0]) if rows else ["incident_id"])

    # One row per transition. This is the table that did not exist before the
    # lifecycle write path, and it is what a response-time view is actually made of.
    steps = []
    for item in incidents:
        for step in (item.get("lifecycle") or {}).get("history", []):
            steps.append({
                "transition_id": step.get("transition_id"),
                "incident_id": item["incident_id"],
                "recorded_at": step.get("recorded_at"),
                "from_status": step.get("from_status"),
                "to_status": step.get("to_status"),
                "actor": step.get("actor"),
                "note": step.get("note"),
                "priority": item["priority"],
                "source_module": item["source_module"],
                "business_domain": item["business_domain"],
            })
    steps.sort(key=lambda s: (s["recorded_at"] or "", s["incident_id"]))
    write("transitions.csv", steps,
          ["transition_id", "incident_id", "recorded_at", "from_status", "to_status", "actor",
           "note", "priority", "source_module", "business_domain"])

    # One row, the snapshot. Its purpose is the as_of stamp and the KPI figures
    # the API computed, so a workbook can show what it was told rather than a
    # number it recomputed and might have recomputed differently.
    snapshot = [{
        "as_of": as_of,
        "total_incidents": store.get("total_incidents"),
        "open_incidents": store.get("open_incidents"),
        "overdue_incidents": store.get("overdue_incidents"),
        "total_transitions": (summary.get("transitions") or {}).get("total_transitions"),
        "incidents_with_transitions": (summary.get("transitions") or {}).get("incidents_with_transitions"),
        "acknowledged_incidents": times.get("acknowledged_incidents"),
        "median_minutes_to_acknowledge": times.get("median_minutes_to_acknowledge"),
        "acknowledged_within_window": times.get("acknowledged_within_window"),
        "acknowledged_late": times.get("acknowledged_late"),
        "closed_incidents": times.get("closed_incidents"),
        "median_minutes_to_close": times.get("median_minutes_to_close"),
        "extract_complete": not truncated,
    }]
    write("store_summary.csv", snapshot, list(snapshot[0]))

    # One row per module per metric, long format, so a workbook can put seven
    # heterogeneous modules on one axis without a column per metric.
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "app"))
    from utils import modules as registry

    metrics = []
    for key in registry.ORDER:
        module = registry.MODULES[key]
        for label, value in registry.headline(key):
            metrics.append({
                "module": key,
                "title": module["title"],
                "source_module": module["source_module"],
                "business_domain": module["business_domain"],
                "metric": label,
                "value": value,
            })
    write("module_metrics.csv", metrics,
          ["module", "title", "source_module", "business_domain", "metric", "value"])

    print("\nas_of %s" % as_of)
    if truncated:
        print("INCOMPLETE. The API returned fewer incidents than it matched for: "
              + "; ".join(truncated)
              + "\nThe cap is 50 per lifecycle state with no pagination. Raising it is the move "
                "to a queryable store, charter 7.5.")
        return 1
    print("complete: every incident the store matched was returned.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
