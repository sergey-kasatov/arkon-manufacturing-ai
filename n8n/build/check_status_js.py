"""Run the status API's two Code nodes outside n8n, before deploying.

The endpoint's contract is what the assistant, the cockpit, the timers and the
Tableau extracts read, and since the move to the queryable store (charter 7.5)
it is answered from rows rather than from the logs. What is checked here: the
generator reproduces the tracked JSON; the wiring reaches the answer node on an
empty read and a 503 on a failed one; the query parser still accepts and
refuses what it did, and picks one table condition per query; and the answer
node, fed rows the store sync's own fold produced from logs written by hand,
answers every filter the way the contract promises.

    python n8n/build/check_status_js.py
"""

import json
import pathlib
import subprocess
import sys
import tempfile

import store_schema
from lifecycle import js_constants

BUILD = pathlib.Path(__file__).resolve().parent
N8N_DIR = BUILD.parent
WORKFLOW = N8N_DIR / "incident_status_api_v1.json"
SYNC_WORKFLOW = N8N_DIR / "store_sync_v1.json"
GENERATOR = BUILD / "build_status_workflow.py"

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
const makeDollar = (nodes) => (name) => {
  if (!(name in nodes)) throw new Error("the node asked for " + name + ", which this case did not stub");
  const value = nodes[name];
  const list = Array.isArray(value) ? value : [value];
  return { first: () => ({ json: list[0] }), all: () => list.map((json) => ({ json })) };
};
const parseQuery = (query) => parse(null, { first: () => ({ json: { query } }) })[0].json;

// -- the parser ----------------------------------------------------------
check("no filters is the newest page", parseQuery({}).db_filter, { column: "incident_id", condition: "isNotEmpty", value: "", return_all: false, limit: 5 });
check("an incident id is one exact row", parseQuery({ incident_id: "ark-inc-14" }).db_filter, { column: "incident_id", condition: "eq", value: "ARK-INC-00014", return_all: true, limit: 5 });
check("a status is one exact condition", parseQuery({ status: "NEW", limit: "500" }).db_filter, { column: "status", condition: "eq", value: "new", return_all: true, limit: 500 });
check("one priority is exact", parseQuery({ priority: "p1" }).db_filter.column, "priority");
check("an assignee is a contains match on the name", parseQuery({ assigned_to: "A.  Novak" }).db_filter, { column: "assigned_to", condition: "ilike", value: "A. Novak", return_all: true, limit: 5 });
check("assignee is the same parameter", parseQuery({ assignee: "A. Novak" }).db_filter.column, "assigned_to");
check("a concrete status outranks an assignee", parseQuery({ status: "new", assigned_to: "A. Novak" }).db_filter.column, "status");
check("open is not one condition, so the assignee carries the read", parseQuery({ status: "open", assigned_to: "A. Novak" }).db_filter.column, "assigned_to");
check("open expands to the three non-terminal states", parseQuery({ status: "open" }).query.status_set, ["new", "acknowledged", "in_containment"]);
check("open alone reads everything and filters after", parseQuery({ status: "open" }).db_filter, { column: "incident_id", condition: "isNotEmpty", value: "", return_all: true, limit: 5 });
check("open still echoes as it was asked", parseQuery({ status: "OPEN" }).query.status, "open");
check("a priority sort reads every match, not the newest page", parseQuery({ sort: "priority" }).db_filter.return_all, true);
check("an unknown sort is refused", parseQuery({ sort: "sideways" }).valid, false);
check("the default sort is recent", parseQuery({}).query.sort, "recent");
check("two priorities read everything and filter after", parseQuery({ priority: "P1,P2" }).db_filter, { column: "incident_id", condition: "isNotEmpty", value: "", return_all: true, limit: 5 });
check("a unit is a contains match on the normalised digits", parseQuery({ unit: "FD001-Unit-092" }).db_filter, { column: "unit", condition: "ilike", value: "92", return_all: true, limit: 5 });
check("a record id is a contains match", parseQuery({ record_id: "scania-aps-000056" }).db_filter.condition, "ilike");
check("status outranks a module filter", parseQuery({ status: "closed", source_module: "scania_aps" }).db_filter.column, "status");
check("the cap is 500", [parseQuery({ limit: "500" }).valid, parseQuery({ limit: "501" }).valid], [true, false]);
check("a bad status is refused with the lifecycle", parseQuery({ status: "exploded" }).errors[0].includes("new, acknowledged, in_containment, resolved, closed, false_positive"), true);
check("two errors at once", parseQuery({ priority: "P9", limit: "0" }).errors.length, 2);
check("a bad incident id is refused", parseQuery({ incident_id: "not-an-id" }).valid, false);
check("an unknown parameter is ignored", parseQuery({ colour: "blue" }).valid, true);
check("the failure affordance", parseQuery({ simulate_failure: "yes" }).simulate_failure, true);

// -- rows, produced by the sync's own fold from logs written by hand ------
const T0 = "2026-09-07T06:00:00.000Z";
const at = (minutes) => new Date(Date.parse(T0) + minutes * 60000).toISOString();
const incident = (n, priority, module, recordId, extra) => JSON.stringify({
  incident_id: "ARK-INC-0000" + n, created_at: at(n), status: "new", priority,
  source_module: module, business_domain: module === "cmapss_rul" ? "asset_reliability" : "fleet_reliability",
  summary: "record " + recordId, recommended_action: "look", assigned_role: "Maintenance Planner",
  assigned_to: "M. Brandt", escalation_contact: "R. Ortiz",
  event: { event_id: "arkon-2026-90000" + n, risk_score: 0.5, context_origin: "real",
           evidence: { record_id: recordId, model_version: module + "_v1", prediction: 12, threshold: 25 },
           operational_context: { context_origin: "simulated" } },
  ...(extra || {}),
});
const step = (id, n, from, to, minutes) => JSON.stringify({
  transition_id: "ARK-TRN-0000" + id, recorded_at: at(minutes), incident_id: "ARK-INC-0000" + n,
  from_status: from, to_status: to, actor: "M. Brandt", note: "", context_origin: "simulated",
});
const storeText = [
  incident(1, "P1", "cmapss_rul", "FD001-Unit-092", { assigned_to: "A. Novak" }),
  incident(2, "P2", "cmapss_rul", "FD002-Unit-100", { assigned_to: "A. Novak" }),
  incident(3, "P3", "scania_aps", "SCANIA-APS-000056"),
  incident(4, "P2", "cmapss_rul", "FD001-Unit-ATTRTEST", { assigned_to: "P. Lindt" }),
].join("\n") + "\n";
const transitionsText = [
  step(1, 2, "new", "acknowledged", 30),
  step(2, 2, "acknowledged", "resolved", 90),
  step(3, 3, "new", "false_positive", 20),
].join("\n") + "\n";
const synced = fold(makeDollar({
  "Read Request": { rebuild: false, source: "command_line" },
  "Extract Store Text": { store_text: storeText },
  "Extract Transitions Text": { transitions_text: transitionsText },
  "Get Summary": [{}],
}))[0].json;
const rows = synced.incident_rows;
const summaryRow = synced.summary_row;

// The answer node, fed what the table would return for a query: the rows the
// one condition selects. This mirrors the data table's eq / ilike / isNotEmpty.
const select = (dbFilter) => {
  const value = String(dbFilter.value).toLowerCase();
  const hit = (row) => {
    const cell = row[dbFilter.column];
    if (dbFilter.condition === "isNotEmpty") return cell !== null && cell !== undefined;
    if (dbFilter.condition === "eq") return cell === dbFilter.value;
    if (dbFilter.condition === "ilike") return String(cell ?? "").toLowerCase().includes(value);
    throw new Error("unexpected condition " + dbFilter.condition);
  };
  const sorted = rows.filter(hit).sort((a, b) => b.created_at.localeCompare(a.created_at));
  return dbFilter.return_all ? sorted : sorted.slice(0, dbFilter.limit);
};
const ask = (query, options) => {
  const parsed = parseQuery(query);
  if (!parsed.valid) throw new Error("the case is invalid: " + parsed.errors.join("; "));
  const matches = select(parsed.db_filter);
  const open = rows.filter((row) => row.status === "new");
  const nodes = {
    "Parse Query": parsed,
    "Get Summary": [(options && options.summary) || summaryRow],
    "Get Matches": matches.length ? matches : [{}],
    "Get Open": open.length ? open : [{}],
  };
  return answer(makeDollar(nodes))[0].json;
};

const all = ask({ limit: "10" });
check("no filter returns the newest page and the store count", [all.status, all.returned, all.match_count, all.incidents[0].incident_id], ["ok", 4, 4, "ARK-INC-00004"]);
check("the default page is five", ask({}).query.limit, 5);
const paged = ask({});
check("a short page reports the whole count", [paged.returned, paged.match_count], [4, 4]);
check("the per-incident projection has the contract's fields", Object.keys(all.incidents[0]).sort(), [...new Set(["acknowledge_due_minutes", "age_minutes", "assigned_role", "assigned_to", "business_domain", "created_at", "data_origin", "escalation_contact", "event_id", "evidence", "incident_id", "lifecycle", "model_version", "operational_context_origin", "overdue", "predicted_rul", "priority", "priority_threshold", "raised_as", "record_id", "recommended_action", "risk_score", "source_module", "status", "summary", "unit"])].sort());
check("every incident keeps its simulated-context label", all.incidents.every((i) => i.operational_context_origin === "simulated"), true);

const byStatus = ask({ status: "resolved" });
check("a status filter answers from the fold", [byStatus.match_count, byStatus.incidents[0].incident_id, byStatus.incidents[0].status, byStatus.incidents[0].raised_as], [1, "ARK-INC-00002", "resolved", "new"]);
check("the lifecycle block is decoded", [byStatus.incidents[0].lifecycle.transition_count, byStatus.incidents[0].lifecycle.history.length, byStatus.incidents[0].lifecycle.minutes_to_resolve], [2, 2, 88]);
check("a status with no members is no_match", ask({ status: "closed" }).status, "no_match");

check("a unit matches across zero padding", ask({ unit: "92" }).incidents.map((i) => i.incident_id), ["ARK-INC-00001"]);
check("a unit contains-match is narrowed to the exact unit", ask({ unit: "100" }).incidents.map((i) => i.incident_id), ["ARK-INC-00002"]);
check("a non-numeric unit matches by token", ask({ unit: "attrtest" }).incidents.map((i) => i.incident_id), ["ARK-INC-00004"]);
check("a record id matches case-insensitively", ask({ record_id: "scania-aps-000056" }).incidents.map((i) => i.incident_id), ["ARK-INC-00003"]);
check("a priority list is honoured", ask({ priority: "P1,P3" }).incidents.map((i) => i.priority), ["P3", "P1"]);
check("a module filter", ask({ source_module: "SCANIA_APS" }).match_count, 1);
check("combined filters", ask({ priority: "P2", unit: "100" }).incidents.map((i) => i.incident_id), ["ARK-INC-00002"]);
check("an unknown incident is no_match", ask({ incident_id: "ARK-INC-99999" }).status, "no_match");

// The assignee filter and the open expansion, DEFECT-11: without these the
// assistant answered "how many do I have" for the whole plant.
check("an assignee filter answers for that person only", ask({ assigned_to: "A. Novak" }).incidents.map((i) => i.incident_id), ["ARK-INC-00002", "ARK-INC-00001"]);
check("a surname finds the same person", ask({ assigned_to: "novak" }).match_count, 2);
check("a fragment of a name finds nobody", ask({ assigned_to: "ova" }).status, "no_match");
check("open is the three non-terminal states", ask({ status: "open" }).incidents.map((i) => i.incident_id), ["ARK-INC-00004", "ARK-INC-00001"]);
check("resolved is not open", ask({ status: "open", assigned_to: "A. Novak" }).incidents.map((i) => i.incident_id), ["ARK-INC-00001"]);
check("the matched set has its own summary", ask({ assigned_to: "A. Novak" }).match_summary, { total: 2, open: 1, overdue: 1, by_status: { resolved: 1, new: 1 }, by_priority: { P2: 1, P1: 1 } });
check("a newest-page read reports no matched summary", ask({}).match_summary, null);
check("the default order is newest first", ask({ priority: "P1,P2,P3", limit: "10" }).incidents.map((i) => i.incident_id), ["ARK-INC-00004", "ARK-INC-00003", "ARK-INC-00002", "ARK-INC-00001"]);
check("a priority sort is P1 first, oldest first inside a priority", ask({ priority: "P1,P2,P3", sort: "priority", limit: "10" }).incidents.map((i) => [i.incident_id, i.priority]), [["ARK-INC-00001", "P1"], ["ARK-INC-00002", "P2"], ["ARK-INC-00004", "P2"], ["ARK-INC-00003", "P3"]]);
check("the limit bounds the page, not the count", (() => { const r = ask({ priority: "P2", limit: "1" }); return [r.returned, r.match_count]; })(), [1, 2]);

// The summary block: the sync's numbers, and overdue from the clock.
const store = all.store;
check("the store summary comes from the summary row", [store.total_incidents, store.open_incidents, store.incidents_by_status, store.incidents_by_priority], [4, 2, { new: 2, resolved: 1, false_positive: 1 }, { P1: 1, P2: 2, P3: 1 }]);
check("overdue is counted live from the new incidents", store.overdue_incidents, 2);
check("the summary names its sync", [store.projection.startsWith("n8n data tables"), store.sync_mode, typeof store.sync_lag_seconds], [true, "initial", "number"]);
check("the transitions block", [all.transitions.total_transitions, all.transitions.incidents_with_transitions, all.transitions.unreadable_lines], [3, 2, 0]);
check("the response times", all.response_times, { acknowledged_incidents: 1, median_minutes_to_acknowledge: 28, acknowledged_within_window: 1, acknowledged_late: 0, closed_incidents: 1, median_minutes_to_close: 17 });
check("the record-of-truth paths are still named", [store.path, all.transitions.path], ["/data/arkon/incidents.jsonl", "/data/arkon/incident_transitions.jsonl"]);

// The CMAPSS-only fields.
const p1 = ask({ incident_id: "1" }).incidents[0];
check("a CMAPSS record serves its RUL and threshold", [p1.predicted_rul, p1.priority_threshold, p1.unit], [12, 25, "092"]);
const scania = ask({ incident_id: "3" }).incidents[0];
check("a Scania record serves neither", [scania.predicted_rul, scania.priority_threshold, scania.unit, scania.evidence.record_id], [null, null, null, "SCANIA-APS-000056"]);

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
    for name in ("Get Summary", "Get Open", "Get Matches"):
        node = node_named(workflow, name)
        if node.get("alwaysOutputData") is not True or node.get("onError") != "continueErrorOutput":
            raise SystemExit("%s must emit an item on an empty read and route a failed one to a 503" % name)
        error_target = [t["node"] for t in workflow["connections"][name]["main"][1]]
        if not error_target or not error_target[0].startswith("Respond"):
            raise SystemExit("%s's error output does not reach a Respond node" % name)
    for name in ("Get Open", "Get Matches"):
        if node_named(workflow, name).get("executeOnce") is not True:
            raise SystemExit("%s must run once, not once per row of the read before it" % name)
    matches = node_named(workflow, "Get Matches")["parameters"]
    condition = matches["filters"]["conditions"][0]
    if not all(str(condition[k]).startswith("={{") for k in ("keyName", "condition", "keyValue")):
        raise SystemExit("Get Matches must take its one condition from the parsed query")
    if matches.get("orderByColumn") != "created_at" or matches.get("orderByDirection") != "DESC":
        raise SystemExit("Get Matches must return the newest rows first")
    if workflow["settings"].get("saveDataSuccessExecution") != "none":
        raise SystemExit("successful reads must not be stored as executions")
    print("ok   empty reads reach the answer, failed reads answer 503, the newest rows come first")


def main():
    check_generator_reproduces()
    workflow = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    check_wiring(workflow)
    if not SYNC_WORKFLOW.exists():
        raise SystemExit("the sync workflow is missing; run build_store_sync_workflow.py first")
    sync = json.loads(SYNC_WORKFLOW.read_text(encoding="utf-8"))

    harness = (
        "function parse($, $input) {\n%s\n}\n"
        "function answer($) {\n%s\n}\n"
        "function fold($) {\n%s\n}\n"
        "%s\n%s\n%s"
        % (
            node_named(workflow, "Parse Query")["parameters"]["jsCode"],
            node_named(workflow, "Answer Query")["parameters"]["jsCode"],
            node_named(sync, "Fold Store")["parameters"]["jsCode"],
            js_constants(),
            store_schema.js_column_lists(),
            CASES,
        )
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
