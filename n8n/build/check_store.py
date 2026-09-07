"""Check the queryable store against the logs it projects, run ON THE NAS.

The store sync (`build_store_sync_workflow.py`) keeps three n8n data tables
level with the two JSONL logs, and nothing else in the platform would notice if
it stopped: the status API would keep answering, from rows that were true an
hour ago. This script is the independent ruler. It reads n8n's database
read-only, re-folds the logs in Python (a second implementation of charter 7.2,
on purpose: a checker that reused the sync's own code would agree with every
mistake in it), and compares row by row.

    python3 check_store.py

Exit 0 when every incident row carries the status, the milestones and the
transition count the logs imply, every readable transition line has its row,
and the summary counters equal the line counts. Anything else is listed and
exits 1; the fix is one rebuild (`POST /webhook/arkon-store-sync` with
`{"rebuild": true}`) followed by this script again.
"""

import json
import pathlib
import sqlite3
import sys

DB = pathlib.Path("/volume1/docker/n8n/n8n_data/database.sqlite")
ARKON = pathlib.Path("/volume1/docker/arkon")
STORE = ARKON / "incidents.jsonl"
TRANSITIONS = ARKON / "incident_transitions.jsonl"

TABLES = ("arkon_incidents", "arkon_transitions", "arkon_store_summary")
TERMINAL = ("closed", "false_positive")

problems = []


def problem(text):
    problems.append(text)
    print("FAIL " + text)


def read_log(path):
    """(readable records with their 1-based ordinal, non-empty line count, unreadable count)."""
    records, lines, unreadable = [], 0, 0
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            lines += 1
            try:
                record = json.loads(line)
            except ValueError:
                unreadable += 1
                continue
            if not isinstance(record, dict) or not record.get("incident_id"):
                unreadable += 1
                continue
            records.append((record, lines))
    return records, lines, unreadable


def fold(incident, transitions):
    """Charter 7.2, independently: the last transition is the status, milestones
    are the first time each state was reached, false_positive closes."""
    steps = sorted(transitions, key=lambda t: str(t.get("recorded_at") or ""))
    status = str(steps[-1]["to_status"]).lower() if steps else str(incident.get("status") or "new").lower()

    def first(state):
        for step in steps:
            if str(step.get("to_status")).lower() == state:
                return step.get("recorded_at")
        return None

    return {
        "status": status,
        "transition_count": len(steps),
        "is_terminal": status in TERMINAL,
        "acknowledged_at": first("acknowledged"),
        "resolved_at": first("resolved"),
        "closed_at": first("closed") or first("false_positive"),
    }


def user_tables(connection):
    """Map each Arkon table name to the SQL table n8n keeps its rows in."""
    found = {}
    rows = connection.execute("select id, name from data_table").fetchall()
    sql_tables = {r[0] for r in connection.execute("select name from sqlite_master where type='table'").fetchall()}
    for table_id, name in rows:
        if name in TABLES:
            candidates = [t for t in sql_tables if t.endswith(table_id)]
            if len(candidates) != 1:
                problem("cannot find the SQL table for %s (id %s): %s" % (name, table_id, candidates))
                continue
            found[name] = candidates[0]
    return found


def main():
    connection = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    connection.row_factory = sqlite3.Row
    tables = user_tables(connection)
    for name in TABLES:
        if name not in tables:
            problem("data table %s does not exist" % name)
    if problems:
        return 1

    incidents, incident_lines, incidents_unreadable = read_log(STORE)
    transitions, transition_lines, transitions_unreadable = read_log(TRANSITIONS)
    by_incident = {}
    for record, _ in transitions:
        by_incident.setdefault(str(record["incident_id"]), []).append(record)

    # The summary row.
    summary = connection.execute("select * from %s" % tables["arkon_store_summary"]).fetchall()
    if len(summary) != 1:
        problem("expected one summary row, found %d" % len(summary))
        return 1
    summary = dict(summary[0])
    print("summary: synced %s (%s, %s), %s incident lines, %s transition lines" % (
        summary["synced_at"], summary["sync_mode"], summary["sync_source"],
        summary["incidents_lines"], summary["transitions_lines"]))
    if int(summary["incidents_lines"]) != incident_lines:
        problem("the summary saw %s incident lines, the log has %d: a write since the last sync?" % (summary["incidents_lines"], incident_lines))
    if int(summary["transitions_lines"]) != transition_lines:
        problem("the summary saw %s transition lines, the log has %d: a write since the last sync?" % (summary["transitions_lines"], transition_lines))
    if int(summary["incidents_unreadable"]) != incidents_unreadable or int(summary["transitions_unreadable"]) != transitions_unreadable:
        problem("unreadable counts differ: summary %s/%s, logs %d/%d" % (summary["incidents_unreadable"], summary["transitions_unreadable"], incidents_unreadable, transitions_unreadable))
    if int(summary["total_incidents"]) != len(incidents):
        problem("the summary counts %s incidents, the log has %d readable" % (summary["total_incidents"], len(incidents)))

    # Incident rows against the Python fold.
    rows = {r["incident_id"]: dict(r) for r in connection.execute("select * from %s" % tables["arkon_incidents"]).fetchall()}
    print("incident rows: %d in the table, %d readable lines in the log" % (len(rows), len(incidents)))
    if len(rows) != len(incidents):
        problem("row count %d differs from the log's %d readable incidents" % (len(rows), len(incidents)))
    counts = {}
    mismatches = 0
    for incident, line in incidents:
        incident_id = incident["incident_id"]
        expected = fold(incident, by_incident.get(incident_id, []))
        counts[expected["status"]] = counts.get(expected["status"], 0) + 1
        row = rows.get(incident_id)
        if row is None:
            problem("no row for %s" % incident_id)
            continue
        for key, value in expected.items():
            actual = row.get(key)
            if key == "is_terminal":
                actual = bool(actual)
            if actual != value:
                mismatches += 1
                if mismatches <= 10:
                    problem("%s.%s is %r in the table, the logs say %r" % (incident_id, key, actual, value))
        if int(row.get("store_line") or 0) != line:
            mismatches += 1
            if mismatches <= 10:
                problem("%s is line %d of the log, the row says %s" % (incident_id, line, row.get("store_line")))
        if row.get("raised_as") != "new":
            problem("%s raised_as is %r" % (incident_id, row.get("raised_as")))
    if mismatches > 10:
        problem("... and %d more mismatches" % (mismatches - 10))
    if mismatches == 0:
        print("ok   every incident row carries the status, milestones, count and line the logs imply")
    by_status = json.loads(summary["incidents_by_status_json"] or "{}")
    if by_status != counts:
        problem("incidents_by_status %s differs from the fold's %s" % (by_status, counts))
    else:
        print("ok   incidents_by_status agrees with the fold: %s" % counts)

    # Transition rows against the log.
    transition_rows = {r["transition_id"]: dict(r) for r in connection.execute("select * from %s" % tables["arkon_transitions"]).fetchall()}
    print("transition rows: %d in the table, %d readable lines in the log" % (len(transition_rows), len(transitions)))
    if len(transition_rows) != len(transitions):
        problem("transition row count %d differs from the log's %d" % (len(transition_rows), len(transitions)))
    missing = 0
    for record, line in transitions:
        row = transition_rows.get(record.get("transition_id"))
        if row is None:
            missing += 1
            if missing <= 5:
                problem("no row for %s" % record.get("transition_id"))
            continue
        if int(row.get("log_line") or 0) != line or row.get("to_status") != record.get("to_status") or row.get("incident_id") != record.get("incident_id"):
            problem("%s differs from its log line" % record.get("transition_id"))
    if missing > 5:
        problem("... and %d more missing transition rows" % (missing - 5))
    if not missing:
        print("ok   every readable transition line has its row")
    duplicates = connection.execute(
        "select transition_id, count(*) from %s group by transition_id having count(*) > 1" % tables["arkon_transitions"]).fetchall()
    if duplicates:
        problem("duplicate transition rows: %s" % [tuple(d) for d in duplicates[:5]])
    duplicates = connection.execute(
        "select incident_id, count(*) from %s group by incident_id having count(*) > 1" % tables["arkon_incidents"]).fetchall()
    if duplicates:
        problem("duplicate incident rows: %s" % [tuple(d) for d in duplicates[:5]])

    print("\n" + ("STORE LEVEL WITH THE LOGS" if not problems else "%d PROBLEM(S)" % len(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
