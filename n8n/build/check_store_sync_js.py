"""Run the store sync's fold-to-rows node outside n8n, before deploying.

The sync decides what every consumer of the status API will be told, so the
piece worth proving offline is the Code node that folds the two logs and emits
rows: which incidents get a row on an incremental run, that every row is flat
enough for a data table, that the summary agrees with the fold, and that a row
read back through the API's own decoder is the incident it came from.

Three things are checked. The generator reproduces the tracked JSON, so the
node under test is the node that gets imported. The wiring: three branches off
the fold in top-to-bottom order, rows before the summary, and every data table
node naming the table and key it should. Then the node's JS under node, against
logs written out by hand.

    python n8n/build/check_store_sync_js.py
"""

import json
import pathlib
import subprocess
import sys
import tempfile

import store_schema
from lifecycle import js_constants
from store_schema import INCIDENTS_TABLE, SUMMARY_TABLE, TRANSITIONS_TABLE

BUILD = pathlib.Path(__file__).resolve().parent
N8N_DIR = BUILD.parent
WORKFLOW = N8N_DIR / "store_sync_v1.json"
GENERATOR = BUILD / "build_store_sync_workflow.py"

CASES = r"""
// -- helpers -------------------------------------------------------------
let failures = 0;
const check = (name, actual, expected) => {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a !== e) {
    failures += 1;
    console.log("FAIL " + name + "\n  expected " + e + "\n  actual   " + a);
  } else {
    console.log("ok   " + name);
  }
};

// A $ that answers .first() and .all() the way n8n's does, from a map of node
// name to one item or a list of items.
const makeDollar = (nodes) => (name) => {
  if (!(name in nodes)) throw new Error("the node asked for " + name + ", which this case did not stub");
  const value = nodes[name];
  const list = Array.isArray(value) ? value : [value];
  return { first: () => ({ json: list[0] }), all: () => list.map((json) => ({ json })) };
};
const runFold = (nodes) => fold(makeDollar(nodes))[0].json;
const runRequest = (item) => readRequest(null, { first: () => ({ json: item }) })[0].json;

// -- the request node ----------------------------------------------------
check("a webhook body asking for a rebuild", runRequest({ headers: { host: "x" }, params: {}, query: {}, body: { rebuild: "true" } }), { rebuild: true, source: "webhook" });
check("a webhook body without the flag", runRequest({ headers: { host: "x" }, params: {}, query: {}, body: {} }), { rebuild: false, source: "webhook" });
check("a caller names its source", runRequest({ source: "steering_cell", rebuild: false }), { rebuild: false, source: "steering_cell" });
check("a caller cannot rebuild", runRequest({ source: "transition", rebuild: true }), { rebuild: true, source: "transition" });
check("an empty start is the command line", runRequest({}), { rebuild: false, source: "command_line" });

// -- two logs written by hand -------------------------------------------
const T0 = "2026-09-07T06:00:00.000Z";
const at = (minutes) => new Date(Date.parse(T0) + minutes * 60000).toISOString();
const incident = (n, priority, extra) => JSON.stringify({
  incident_id: "ARK-INC-0000" + n, created_at: at(n), status: "new", priority,
  source_module: "cmapss_rul", business_domain: "asset_reliability",
  summary: "unit " + n, recommended_action: "look", assigned_role: "Maintenance Planner",
  assigned_to: "M. Brandt", escalation_contact: "R. Ortiz",
  event: { event_id: "arkon-2026-90000" + n, risk_score: 0.5, context_origin: "real",
           evidence: { record_id: "FD001-Unit-09" + n, model_version: "cmapss_v1", prediction: 12, threshold: 25 },
           operational_context: { context_origin: "simulated" } },
  ...(extra || {}),
});
const step = (id, n, from, to, minutes) => JSON.stringify({
  transition_id: "ARK-TRN-0000" + id, recorded_at: at(minutes), incident_id: "ARK-INC-0000" + n,
  incident_priority: "P2", incident_created_at: at(n), from_status: from, to_status: to,
  actor: "M. Brandt", note: "", minutes_since_created: minutes - n, minutes_since_previous_transition: null,
  acknowledge_window_minutes: 60, acknowledged_within_window: to === "acknowledged" ? (minutes - n) <= 60 : null,
  context_origin: "simulated",
});
const storeText = [
  incident(1, "P1"),
  incident(2, "P2"),
  "{ this line is damaged",
  incident(3, "P3", { source_module: "scania_aps", event: { event_id: "arkon-2026-900003", risk_score: 0.9, context_origin: "real", evidence: { record_id: "SCANIA-APS-000056", model_version: "scania_v1", prediction: 0.0373, threshold: 0.02 }, operational_context: { context_origin: "simulated" } } }),
  "",
].join("\n");
const transitionsText = [
  step(1, 2, "new", "acknowledged", 30),
  step(2, 2, "acknowledged", "in_containment", 60),
  '{"to_status":"closed"}',
  step(3, 2, "in_containment", "resolved", 120),
  "not json",
  step(4, 2, "resolved", "closed", 180),
  step(5, 3, "new", "false_positive", 20),
].join("\n") + "\n";

const request = (rebuild, source) => ({ rebuild, source });
const inputs = (rebuild, summary) => ({
  "Read Request": request(rebuild, "command_line"),
  "Extract Store Text": { store_text: storeText },
  "Extract Transitions Text": { transitions_text: transitionsText },
  "Get Summary": summary === undefined ? [{}] : [summary],
});

// -- the initial run -----------------------------------------------------
const initial = runFold(inputs(false));
check("an initial run writes every incident", initial.incident_rows.map((r) => r.incident_id), ["ARK-INC-00001", "ARK-INC-00002", "ARK-INC-00003"]);
check("an initial run writes every readable transition", initial.transition_rows.map((r) => r.transition_id), ["ARK-TRN-00001", "ARK-TRN-00002", "ARK-TRN-00003", "ARK-TRN-00004", "ARK-TRN-00005"]);
check("the mode is initial", initial.summary_row.sync_mode, "initial");
check("every non-empty line counts, damaged or not", [initial.summary_row.incidents_lines, initial.summary_row.transitions_lines], [4, 7]);
check("damaged lines are counted, not thrown", [initial.summary_row.incidents_unreadable, initial.summary_row.transitions_unreadable], [1, 2]);
check("the ordinal is the line, not the row", initial.incident_rows.map((r) => r.store_line), [1, 2, 4]);
check("the transition ordinal skips the damaged lines too", initial.transition_rows.map((r) => r.log_line), [1, 2, 4, 6, 7]);

const byId = Object.fromEntries(initial.incident_rows.map((r) => [r.incident_id, r]));
check("the fold lands on the row", [byId["ARK-INC-00001"].status, byId["ARK-INC-00002"].status, byId["ARK-INC-00003"].status], ["new", "closed", "false_positive"]);
check("raised_as is always new", initial.incident_rows.map((r) => r.raised_as), ["new", "new", "new"]);
check("the KPIs are on the row", [byId["ARK-INC-00002"].minutes_to_acknowledge, byId["ARK-INC-00002"].minutes_to_resolve, byId["ARK-INC-00002"].minutes_to_close], [28, 118, 178]);
check("false_positive closes without an acknowledgement", [byId["ARK-INC-00003"].minutes_to_acknowledge, byId["ARK-INC-00003"].minutes_to_close], [null, 17]);
check("terminal is a boolean on the row", [byId["ARK-INC-00001"].is_terminal, byId["ARK-INC-00002"].is_terminal], [false, true]);
check("a CMAPSS record carries its unit and its RUL", [byId["ARK-INC-00001"].unit, byId["ARK-INC-00001"].predicted_rul, byId["ARK-INC-00001"].priority_threshold], ["091", 12, 25]);
check("a Scania record carries neither", [byId["ARK-INC-00003"].unit, byId["ARK-INC-00003"].predicted_rul], [null, null]);
check("the history is JSON text", JSON.parse(byId["ARK-INC-00002"].history_json).map((h) => h.to_status), ["acknowledged", "in_containment", "resolved", "closed"]);
check("the evidence is JSON text", JSON.parse(byId["ARK-INC-00001"].evidence_json).record_id, "FD001-Unit-091");

// Every row is flat and carries exactly the schema's columns.
const flatRow = (row) => Object.values(row).every((v) => v === null || ["string", "number", "boolean"].includes(typeof v));
check("incident rows are flat", initial.incident_rows.every(flatRow), true);
check("transition rows are flat", initial.transition_rows.every(flatRow), true);
check("the summary row is flat", flatRow(initial.summary_row), true);
check("incident rows carry the schema columns", initial.incident_rows.every((r) => JSON.stringify(Object.keys(r).sort()) === JSON.stringify(INCIDENT_COLUMNS.slice().sort())), true);
check("transition rows carry the schema columns", initial.transition_rows.every((r) => JSON.stringify(Object.keys(r).sort()) === JSON.stringify(TRANSITION_COLUMNS.slice().sort())), true);
check("the summary row carries the schema columns", JSON.stringify(Object.keys(initial.summary_row).sort()), JSON.stringify(SUMMARY_COLUMNS.slice().sort()));

// The summary, as the status API used to compute it.
check("total and open", [initial.summary_row.total_incidents, initial.summary_row.open_incidents], [3, 1]);
check("counts by status", JSON.parse(initial.summary_row.incidents_by_status_json), { new: 1, closed: 1, false_positive: 1 });
check("counts by priority", JSON.parse(initial.summary_row.incidents_by_priority_json), { P1: 1, P2: 1, P3: 1 });
check("the response times", JSON.parse(initial.summary_row.response_times_json), { acknowledged_incidents: 1, median_minutes_to_acknowledge: 28, acknowledged_within_window: 1, acknowledged_late: 0, closed_incidents: 2, median_minutes_to_close: 97.5 });
check("the transition totals", [initial.summary_row.total_transitions, initial.summary_row.incidents_with_transitions], [5, 2]);
check("the highest ids", [initial.summary_row.highest_incident_id, initial.summary_row.highest_transition_id], ["ARK-INC-00003", "ARK-TRN-00005"]);
check("the P1 is overdue by now", initial.summary_row.overdue_incidents, 1);
check("the written counts are on the summary", [initial.summary_row.incident_rows_written, initial.summary_row.transition_rows_written], [3, 5]);

// -- an incremental run --------------------------------------------------
// The previous sync had seen two incident lines and three transition lines.
const previous = { ...initial.summary_row, incidents_lines: 2, transitions_lines: 3 };
const incremental = runFold({ ...inputs(false, previous), "Read Request": request(false, "transition") });
check("the mode is incremental", incremental.summary_row.sync_mode, "incremental");
check("new incident lines and touched incidents get a row, nothing else", incremental.incident_rows.map((r) => r.incident_id), ["ARK-INC-00002", "ARK-INC-00003"]);
check("only the new transition lines become rows", incremental.transition_rows.map((r) => r.transition_id), ["ARK-TRN-00003", "ARK-TRN-00004", "ARK-TRN-00005"]);
check("the summary is still computed over everything", [incremental.summary_row.total_incidents, incremental.summary_row.total_transitions], [3, 5]);
check("the counters move to the end of both logs", [incremental.summary_row.incidents_lines, incremental.summary_row.transitions_lines], [4, 7]);
check("the source is recorded", incremental.summary_row.sync_source, "transition");

const quiet = runFold(inputs(false, initial.summary_row));
check("a run that finds nothing new writes no rows", [quiet.incident_rows.length, quiet.transition_rows.length], [0, 0]);
check("but still rewrites the summary", quiet.summary_row.total_incidents, 3);

// -- a rebuild -----------------------------------------------------------
const rebuild = runFold({ ...inputs(true, initial.summary_row), "Read Request": request(true, "webhook") });
check("a rebuild ignores the previous counters", [rebuild.incident_rows.length, rebuild.transition_rows.length, rebuild.summary_row.sync_mode], [3, 5, "rebuild"]);

// -- the row read back through the API's decoder -------------------------
const now = new Date(Date.parse(T0) + 240 * 60000);
const served = arkonRowToIncident(byId["ARK-INC-00002"], now);
check("the decoder returns the folded status and the raised status", [served.status, served.raised_as], ["closed", "new"]);
check("the decoder rebuilds the lifecycle block", [served.lifecycle.transition_count, served.lifecycle.is_terminal, served.lifecycle.minutes_to_close, served.lifecycle.history.length], [4, true, 178, 4]);
check("the decoder restores the evidence object", served.evidence.model_version, "cmapss_v1");
check("age and overdue are computed from the clock", [served.age_minutes, served.overdue], [238, false]);
const servedP1 = arkonRowToIncident(byId["ARK-INC-00001"], now);
check("a new P1 past its window is overdue", [servedP1.overdue, servedP1.acknowledge_due_minutes], [true, 15]);
check("the origin labels survive the round trip", [servedP1.data_origin, servedP1.operational_context_origin], ["real", "simulated"]);

console.log(failures === 0 ? "\nALL PASS" : "\n" + failures + " FAILURE(S)");
process.exit(failures === 0 ? 0 : 1);
"""


def node_named(workflow, name):
    hits = [n for n in workflow["nodes"] if n["name"] == name]
    if len(hits) != 1:
        raise SystemExit("expected one node named %r, found %d" % (name, len(hits)))
    return hits[0]


def check_generator_reproduces():
    before = WORKFLOW.read_bytes()
    result = subprocess.run([sys.executable, str(GENERATOR)], capture_output=True, text=True, cwd=str(BUILD))
    after = WORKFLOW.read_bytes()
    if result.returncode != 0:
        WORKFLOW.write_bytes(before)
        raise SystemExit("the generator failed:\n" + result.stdout + result.stderr)
    if before != after:
        WORKFLOW.write_bytes(before)
        raise SystemExit("DRIFT: the generator does not reproduce the tracked %s (restored)" % WORKFLOW.name)
    print("ok   the generator reproduces the tracked file byte for byte")


def check_wiring(workflow):
    fold_targets = [t["node"] for t in workflow["connections"]["Fold Store"]["main"][0]]
    if fold_targets != ["Incident Rows", "Transition Rows", "Summary Row"]:
        raise SystemExit("the fold does not feed the three branches in order: %s" % fold_targets)
    ys = [node_named(workflow, name)["position"][1] for name in fold_targets]
    if ys != sorted(ys) or len(set(ys)) != 3:
        raise SystemExit("the branches are not laid out top to bottom, so v1 order would not run rows before the summary: %s" % ys)
    expect = {
        "Upsert Incidents": (INCIDENTS_TABLE, "incident_id"),
        "Upsert Transitions": (TRANSITIONS_TABLE, "transition_id"),
        "Upsert Summary": (SUMMARY_TABLE, "key"),
    }
    for name, (table, key) in expect.items():
        params = node_named(workflow, name)["parameters"]
        if params["operation"] != "upsert" or params["dataTableId"]["value"] != table or params["dataTableId"]["mode"] != "name":
            raise SystemExit("%s does not upsert into %s by name" % (name, table))
        if params["filters"]["conditions"][0]["keyName"] != key or params["columns"]["mappingMode"] != "autoMapInputData":
            raise SystemExit("%s does not match on %s with auto-mapped columns" % (name, key))
    for name, table in (("Create Incidents Table", INCIDENTS_TABLE), ("Create Transitions Table", TRANSITIONS_TABLE), ("Create Summary Table", SUMMARY_TABLE)):
        params = node_named(workflow, name)["parameters"]
        declared = [(c["name"], c["type"]) for c in params["columns"]["column"]]
        if declared != store_schema.TABLES[table] or params["options"] != {"createIfNotExists": True}:
            raise SystemExit("%s does not declare the schema of %s, or would fail on an existing table" % (name, table))
    if node_named(workflow, "Get Summary").get("alwaysOutputData") is not True:
        raise SystemExit("Get Summary must emit an item when no summary row exists yet")
    for name in ("Wipe Incidents", "Wipe Transitions", "Wipe Summary"):
        if node_named(workflow, name).get("alwaysOutputData") is not True:
            raise SystemExit("%s must emit an item when the table is already empty" % name)
    settings = workflow["settings"]
    if settings.get("saveDataSuccessExecution") != "none" or settings.get("saveDataErrorExecution") != "all":
        raise SystemExit("successful runs must not be stored as executions, failed ones must")
    if node_named(workflow, "Sync Request")["parameters"]["responseMode"] != "lastNode":
        raise SystemExit("the webhook must answer with the last node, there is no Respond node in this workflow")
    trigger = node_named(workflow, "When Executed by Another Workflow")["parameters"]
    if [v["name"] for v in trigger["workflowInputs"]["values"]] != ["source", "rebuild"]:
        raise SystemExit("the execute trigger does not declare source and rebuild")
    print("ok   three branches in order, tables and keys as the schema says, no execution data on success")


def main():
    check_generator_reproduces()
    workflow = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    check_wiring(workflow)

    fold_js = node_named(workflow, "Fold Store")["parameters"]["jsCode"]
    request_js = node_named(workflow, "Read Request")["parameters"]["jsCode"]
    harness = (
        "function fold($) {\n%s\n}\n"
        "function readRequest($, $input) {\n%s\n}\n"
        "%s\n%s\n%s\n%s"
        % (fold_js, request_js, js_constants(), store_schema.js_column_lists(), store_schema.ROW_TO_API_JS, CASES)
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "check.js"
        path.write_text(harness, encoding="utf-8")
        result = subprocess.run(["node", str(path)], capture_output=True, text=True)
    print(result.stdout, end="")
    if result.stderr.strip():
        print(result.stderr, file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
