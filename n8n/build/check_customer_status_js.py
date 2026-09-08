"""Run the customer status API's two Code nodes outside n8n, before deploying.

The endpoint is the Customer Quality Desk's only window onto the incident
store, and the claim it carries is that nothing but the customer projection
can leave through it. What is checked here: the generator reproduces the
tracked JSON; the wiring reaches the answer node on an empty read and a 503
on a failed one; the parser accepts the three reference forms and refuses the
rest; the answer node, fed rows the store sync's own fold produced from logs
written by hand, serves exactly the eight customer fields for every lifecycle
status with the right commitment date; and neither the answer node's code nor
its output names an internal field or an internal value.

    python n8n/build/check_customer_status_js.py
"""

import json
import pathlib
import subprocess
import sys
import tempfile

import customer_projection
import store_schema
from lifecycle import js_constants

BUILD = pathlib.Path(__file__).resolve().parent
N8N_DIR = BUILD.parent
WORKFLOW = N8N_DIR / "customer_status_api_v1.json"
SYNC_WORKFLOW = N8N_DIR / "store_sync_v1.json"
GENERATOR = BUILD / "build_customer_status_workflow.py"

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
check("a missing reference is refused", [parseQuery({}).valid, parseQuery({}).errors[0].startsWith("reference is required")], [false, true]);
check("an empty reference is refused", parseQuery({ reference: "  " }).valid, false);
check("a malformed reference is refused", [parseQuery({ reference: "APP-8841" }).valid, parseQuery({ reference: "APP-8841" }).errors[0]], [false, "reference must look like ARK-INC-00348"]);
check("the padded form", parseQuery({ reference: "ARK-INC-00348" }).reference, "ARK-INC-00348");
check("the lower-case short form", parseQuery({ reference: "ark-inc-348" }).reference, "ARK-INC-00348");
check("a bare number", parseQuery({ reference: "348" }).reference, "ARK-INC-00348");
check("an internal filter is ignored, not honoured", Object.keys(parseQuery({ reference: "348", priority: "P1", assigned_to: "x" })).sort(), ["errors", "reference", "simulate_failure", "valid"]);
check("the failure affordance", parseQuery({ reference: "348", simulate_failure: "yes" }).simulate_failure, true);

// -- rows, produced by the sync's own fold from logs written by hand ------
const T0 = "2026-09-08T06:00:00.000Z";
const at = (minutes) => new Date(Date.parse(T0) + minutes * 60000).toISOString();
const incident = (n, priority) => JSON.stringify({
  incident_id: "ARK-INC-0000" + n, created_at: at(n), status: "new", priority,
  source_module: "cmapss_rul", business_domain: "asset_reliability",
  summary: "engine unit 92 predicted RUL 8 cycles", recommended_action: "Schedule inspection before the next operating window.",
  assigned_role: "Maintenance Planner", assigned_to: "M. Brandt", escalation_contact: "R. Ortiz",
  event: { event_id: "arkon-2026-90000" + n, risk_score: 0.91, context_origin: "real",
           evidence: { record_id: "FD001-Unit-092", model_version: "cmapss_rul_v1", prediction: 8, threshold: 10 },
           operational_context: { context_origin: "simulated" } },
});
const step = (id, n, from, to, minutes) => JSON.stringify({
  transition_id: "ARK-TRN-0000" + id, recorded_at: at(minutes), incident_id: "ARK-INC-0000" + n,
  from_status: from, to_status: to, actor: "M. Brandt", note: "containment did not hold", context_origin: "simulated",
});
const storeText = [
  incident(1, "P1"),   // new, inside its window
  incident(2, "P3"),   // new, no charter window
  incident(3, "P2"),   // acknowledged
  incident(4, "P2"),   // in containment, after a reopen
  incident(5, "P1"),   // resolved
  incident(6, "P2"),   // closed
  incident(7, "P3"),   // false positive
].join("\n") + "\n";
const transitionsText = [
  step(1, 3, "new", "acknowledged", 30),
  step(2, 4, "new", "acknowledged", 20),
  step(3, 4, "acknowledged", "in_containment", 40),
  step(4, 4, "in_containment", "resolved", 60),
  step(5, 4, "resolved", "in_containment", 100),
  step(6, 5, "new", "acknowledged", 15),
  step(7, 5, "acknowledged", "resolved", 90),
  step(8, 6, "new", "acknowledged", 25),
  step(9, 6, "acknowledged", "resolved", 50),
  step(10, 6, "resolved", "closed", 120),
  step(11, 7, "new", "false_positive", 45),
].join("\n") + "\n";
const synced = fold(makeDollar({
  "Read Request": { rebuild: false, source: "command_line" },
  "Extract Store Text": { store_text: storeText },
  "Extract Transitions Text": { transitions_text: transitionsText },
  "Get Summary": [{}],
}))[0].json;
const rows = synced.incident_rows;
const rowOf = (n) => rows.find((row) => row.incident_id === "ARK-INC-0000" + n);
const notice = (n, nowMinutes) => arkonCustomerProjection(rowOf(n), new Date(Date.parse(at(nowMinutes))));
const hours = (h) => h * 60;

// -- the projection, status by status --------------------------------------
const SERVED = __SERVED_FIELDS__;
check("a notice serves exactly the customer fields", Object.keys(notice(1, 10)).sort(), SERVED.slice().sort());

const p1 = notice(1, 10);
check("a new P1 is received, stage 1 of 5", [p1.customer_status, p1.stage], ["Received", { number: 1, of: STAGE_COUNT, name: "Received and logged" }]);
check("its acknowledgement is due at the charter window", p1.next_step, { name: "Acknowledgement by the Arkon quality team", due_at: at(1 + 15), overdue: false });
check("and overdue once the window has lapsed", notice(1, 17).next_step.overdue, true);
check("received_at and last_update_at are the intake time", [p1.received_at, p1.last_update_at, p1.closed_at], [at(1), at(1), null]);

check("a new P3 gets the desk's one business day", notice(2, 10).next_step.due_at, at(2 + hours(24)));

const ack = notice(3, 35);
check("acknowledged is under investigation, stage 2", [ack.customer_status, ack.stage.number, ack.stage.name], ["Under investigation", 2, "Investigation opened"]);
check("the containment decision counts from the acknowledgement", ack.next_step, { name: "Containment decision", due_at: at(30 + hours(24)), overdue: false });
check("last_update_at is the acknowledgement", ack.last_update_at, at(30));

const cont = notice(4, 110);
check("a reopened containment is stage 3 again", [cont.customer_status, cont.stage.number], ["Containment in place", 3]);
check("and its commitment counts from the reopening, not the first containment", cont.next_step.due_at, at(100 + hours(240)));

const res = notice(5, 95);
check("resolved is corrective action implemented, stage 4", [res.customer_status, res.stage.number, res.next_step.name, res.next_step.due_at], ["Corrective action implemented", 4, "Effectiveness check and closure", at(90 + hours(120))]);

const closed = notice(6, 200);
check("closed is stage 5 with no next step", [closed.customer_status, closed.stage, closed.next_step, closed.closed_at], ["Closed", { number: 5, of: STAGE_COUNT, name: "Closed" }, null, at(120)]);

const fp = notice(7, 200);
check("a false positive closes with no defect confirmed", [fp.customer_status, fp.stage.number, fp.next_step, fp.closed_at], ["Closed, no defect confirmed", 5, null, at(45)]);

// -- the output restriction, as a string test over every notice --------------
const INTERNAL_VALUES = ["M. Brandt", "R. Ortiz", "FD001-Unit-092", "cmapss", "asset_reliability", "0.91", "RUL", "Maintenance Planner", "containment did not hold", "arkon-2026", "P1", "P2", "P3", "ARK-TRN"];
const INTERNAL_NAMES = __INTERNAL_NAMES__;
for (let n = 1; n <= 7; n += 1) {
  const text = JSON.stringify(notice(n, 200));
  const leakedValues = INTERNAL_VALUES.filter((value) => text.includes(value));
  const leakedNames = INTERNAL_NAMES.filter((name) => text.includes('"' + name + '"'));
  check("notice " + n + " leaks no internal value or field", [leakedValues, leakedNames], [[], []]);
}

// -- the answer node end to end ---------------------------------------------
const ask = (reference, matches) => answer(makeDollar({
  "Parse Reference": parseQuery({ reference }),
  "Get Reference": matches.length ? matches : [{}],
}))[0].json;
const found = ask("ark-inc-3", [rowOf(3)]);
check("a known reference answers ok with its notice", [found.status, found.reference, found.notice.customer_status, Object.keys(found).sort()], ["ok", "ARK-INC-00003", "Under investigation", ["as_of", "message", "notice", "reference", "status"]]);
const missing = ask("ARK-INC-99999", []);
check("an unknown reference is no_match, with the reference and no notice", [missing.status, missing.reference, missing.notice, missing.message], ["no_match", "ARK-INC-99999", null, "No quality notice or complaint with reference ARK-INC-99999 is on record."]);
check("a row for another reference is never served", ask("ARK-INC-00002", [rowOf(3)]).status, "no_match");

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
    for name in ("Get Summary", "Get Reference"):
        node = node_named(workflow, name)
        if node.get("alwaysOutputData") is not True or node.get("onError") != "continueErrorOutput":
            raise SystemExit("%s must emit an item on an empty read and route a failed one to a 503" % name)
        error_target = [t["node"] for t in workflow["connections"][name]["main"][1]]
        if not error_target or not error_target[0].startswith("Respond"):
            raise SystemExit("%s's error output does not reach a Respond node" % name)
    reference = node_named(workflow, "Get Reference")
    if reference.get("executeOnce") is not True:
        raise SystemExit("Get Reference must run once, not once per row of the read before it")
    condition = reference["parameters"]["filters"]["conditions"][0]
    if condition["keyName"] != "incident_id" or condition["condition"] != "eq" or not str(condition["keyValue"]).startswith("={{"):
        raise SystemExit("Get Reference must read exactly the one row the parsed reference names")
    if len(reference["parameters"]["filters"]["conditions"]) != 1:
        raise SystemExit("Get Reference must carry one condition, the reference")
    if workflow["settings"].get("saveDataSuccessExecution") != "none":
        raise SystemExit("successful reads must not be stored as executions")
    codes = {n["name"]: n["parameters"]["options"].get("responseCode") for n in workflow["nodes"] if n["type"].endswith("respondToWebhook")}
    if codes["Respond Bad Request"] != 400 or any(codes[n] != 503 for n in codes if "Unavailable" in n or "Not Synced" in n):
        raise SystemExit("the four answers must keep their HTTP codes: 400 rejected, 503 unavailable")
    print("ok   empty reads reach the answer, failed reads answer 503, one row is read per call")


def check_code_names_nothing_internal(workflow):
    code = node_named(workflow, "Project For Customer")["parameters"]["jsCode"]
    leaked = [name for name in customer_projection.INTERNAL_NAMES if name in code]
    if leaked:
        raise SystemExit("the answer node's code names internal fields, so a later edit could serve them: %s" % ", ".join(leaked))
    print("ok   the answer node's code names no internal field")


def main():
    check_generator_reproduces()
    workflow = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    check_wiring(workflow)
    check_code_names_nothing_internal(workflow)
    if not SYNC_WORKFLOW.exists():
        raise SystemExit("the sync workflow is missing; run build_store_sync_workflow.py first")
    sync = json.loads(SYNC_WORKFLOW.read_text(encoding="utf-8"))

    cases = CASES.replace("__SERVED_FIELDS__", json.dumps(customer_projection.SERVED_FIELDS)) \
        .replace("__INTERNAL_NAMES__", json.dumps(customer_projection.INTERNAL_NAMES))
    harness = (
        "function parse($, $input) {\n%s\n}\n"
        "function answer($) {\n%s\n}\n"
        "function fold($) {\n%s\n}\n"
        "%s\n%s\n%s\n%s\n%s"
        % (
            node_named(workflow, "Parse Reference")["parameters"]["jsCode"],
            node_named(workflow, "Project For Customer")["parameters"]["jsCode"],
            node_named(sync, "Fold Store")["parameters"]["jsCode"],
            js_constants(),
            store_schema.js_column_lists(),
            customer_projection.js_constants().replace("const TERMINAL_STATUSES", "const CUSTOMER_TERMINAL_STATUSES"),
            customer_projection.PROJECTION_JS,
            cases,
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
