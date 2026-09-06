"""Run the intake-outcome node outside n8n, before deploying (charter 7.6).

Three things are checked. The tracked workflow carries the patch exactly once:
`add_intake_outcomes.py` reports it as already patched, the four Respond nodes
continue to the outcome node and nowhere else, and the incident path is what it
was. Then the node's JS is taken out of the tracked file, the document that
actually gets imported, and run under node against cases written out by hand,
one per outcome and the edges around them. The harness throws on a reference to
a node that did not run, the way n8n does, which is what makes the Telegram
lookup a test rather than a decoration.

    python n8n/build/check_intake_outcome_js.py
"""

import json
import pathlib
import subprocess
import sys
import tempfile

N8N_DIR = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = N8N_DIR / "quality_steering_cell_v1.json"
PATCH = pathlib.Path(__file__).resolve().parent / "add_intake_outcomes.py"

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

// A run is a set of node outputs by name; asking for a node that did not run
// throws, as it does in n8n.
const run = (outputs) => {
  const $ = (name) => {
    if (!(name in outputs)) throw new Error("no data for node " + name + ": execute it first");
    return { first: () => ({ json: outputs[name] }) };
  };
  const items = outcome($, { first: () => ({ json: outputs["Respond"] ?? {} }) });
  const text = items[0].json.intake_outcome_jsonl;
  if (!text.endsWith("\n")) throw new Error("line is not newline-terminated");
  return JSON.parse(text.trim());
};

const body = (extra) => Object.assign({
  event_id: "arkon-2026-900500",
  event_time: "2026-09-06T21:30:00Z",
  source_module: "gc10_detect",
  business_domain: "visual_inspection",
  risk_type: "surface_defect",
  risk_score: 0.87,
  priority: "P2",
  summary: "Sheet x: 1 defect located",
  evidence: { record_id: "GC10-IMG_05_0001" },
  context_origin: "real",
  recommended_action: "Have QC look",
  status: "new",
  operational_context: { context_origin: "simulated", emitter: "live_plant", assigned_role: "QC Engineer" },
}, extra || {});

// -- rejected ------------------------------------------------------------
const rejected = run({
  "Event Intake": { body: { event_id: "arkon-test-1", priority: "P9" } },
  "Validate + Dedup + Incident": { valid: false, alert: false, duplicate: false, errors: ["missing field: evidence", "bad priority: P9"], event_id: "arkon-test-1" },
});
check("a contract violation is recorded as rejected", rejected.outcome, "rejected");
check("the reason joins the validator's errors", rejected.reason, "missing field: evidence; bad priority: P9");
check("the errors travel as a list", rejected.errors, ["missing field: evidence", "bad priority: P9"]);
check("a rejected event keeps its id", rejected.event_id, "arkon-test-1");
check("no record id means no dedup key", rejected.dedup_key, null);
check("a rejected event has no incident", rejected.incident_id, null);
check("a rejected event took no alert branch", rejected.alert_branch, false);
check("a rejected event carries no message id", rejected.telegram_message_id, null);

const bare = run({
  "Event Intake": { body: "not json at all" },
  "Validate + Dedup + Incident": { valid: false, alert: false, duplicate: false, errors: ["missing field: event_id"], event_id: null },
});
check("a body that is not an object still yields a line", bare.outcome, "rejected");
check("a body that is not an object has null fields", [bare.event_id, bare.record_id, bare.priority, bare.source_module], [null, null, null, null]);

// -- duplicate -----------------------------------------------------------
const duplicate = run({
  "Event Intake": { body: body() },
  "Validate + Dedup + Incident": { valid: true, duplicate: true, alert: false, incident: null, event_id: "arkon-2026-900500", priority: "P2" },
});
check("a repeat inside the window is recorded as suppressed", duplicate.outcome, "duplicate_suppressed");
check("the suppressed line names the dedup key", duplicate.dedup_key, "GC10-IMG_05_0001|P2");
check("the suppressed line has no incident", duplicate.incident_id, null);
check("the suppressed line carries the module and domain", [duplicate.source_module, duplicate.business_domain], ["gc10_detect", "visual_inspection"]);
check("the suppressed line names the emitter", duplicate.emitter, "live_plant");
check("the suppressed line labels the context", duplicate.context_origin, "simulated");
check("a suppressed event has a reason", duplicate.reason, "same record_id and priority inside the 24 h window");

// -- recorded, no alert --------------------------------------------------
const recorded = run({
  "Event Intake": { body: body({ priority: "P3" }) },
  "Validate + Dedup + Incident": { valid: true, duplicate: false, alert: false, incident: { incident_id: "ARK-INC-00300" }, event_id: "arkon-2026-900500", priority: "P3" },
});
check("a new incident is recorded", recorded.outcome, "recorded");
check("the recorded line names the incident", recorded.incident_id, "ARK-INC-00300");
check("a P3 took no alert branch", recorded.alert_branch, false);
check("a P3 has no message id and asked no Telegram node", recorded.telegram_message_id, null);
check("a recorded line has no reason", recorded.reason, null);
check("the priority is the event's", recorded.priority, "P3");

// -- recorded, alerted ---------------------------------------------------
const envelope = { ok: true, result: { message_id: 104, chat: { id: -5481573875 }, date: 1788737400 } };
const alerted = run({
  "Event Intake": { body: body() },
  "Validate + Dedup + Incident": { valid: true, duplicate: false, alert: true, incident: { incident_id: "ARK-INC-00301" }, event_id: "arkon-2026-900500", priority: "P2" },
  "Telegram Alert": envelope,
});
check("a P2 took the alert branch", alerted.alert_branch, true);
check("the alerted line carries Telegram's own message id", alerted.telegram_message_id, 104);
const bareReply = run({
  "Event Intake": { body: body() },
  "Validate + Dedup + Incident": { valid: true, duplicate: false, alert: true, incident: { incident_id: "ARK-INC-00302" }, event_id: "arkon-2026-900500", priority: "P2" },
  "Telegram Alert": envelope.result,
});
check("a reply that already is the result object still reads", bareReply.telegram_message_id, 104);
const noReply = run({
  "Event Intake": { body: body() },
  "Validate + Dedup + Incident": { valid: true, duplicate: false, alert: true, incident: { incident_id: "ARK-INC-00303" }, event_id: "arkon-2026-900500", priority: "P2" },
});
check("a missing Telegram output never fails the line", noReply.outcome, "recorded");
check("a missing Telegram output records a null id", noReply.telegram_message_id, null);

// -- the execution id ----------------------------------------------------
check("without $execution the id is null", recorded.execution_id, null);
globalThis.$execution = { id: 7900 };
const withExecution = run({
  "Event Intake": { body: body({ priority: "P3" }) },
  "Validate + Dedup + Incident": { valid: true, duplicate: false, alert: false, incident: { incident_id: "ARK-INC-00304" }, event_id: "arkon-2026-900500", priority: "P3" },
});
delete globalThis.$execution;
check("with $execution the id is recorded as a string", withExecution.execution_id, "7900");
check("received_at is an ISO timestamp", /^\d{4}-\d{2}-\d{2}T/.test(recorded.received_at), true);

console.log(failures === 0 ? "\nALL PASS" : "\n" + failures + " FAILURE(S)");
process.exit(failures === 0 ? 0 : 1);
"""


def node_named(workflow, name):
    hits = [n for n in workflow["nodes"] if n["name"] == name]
    if len(hits) != 1:
        raise SystemExit("expected one node named %r, found %d" % (name, len(hits)))
    return hits[0]


workflow = json.loads(WORKFLOW.read_text(encoding="utf-8"))

# The patch is in the tracked file exactly once, and applying it again is a no-op.
result = subprocess.run([sys.executable, str(PATCH), str(WORKFLOW)], capture_output=True, text=True)
if result.returncode != 0 or "already patched, nothing written" not in result.stdout:
    raise SystemExit("the tracked workflow does not carry the patch exactly once:\n%s%s" % (result.stdout, result.stderr))
print("ok   the tracked workflow carries the intake-outcome patch, and the patch is idempotent on it")

# The wiring: every Respond node ends in the outcome node and nowhere else, and
# the incident path itself is untouched.
targets = {}
for source in ("Respond Invalid", "Respond Duplicate", "Respond Recorded", "Respond Alerted"):
    outs = workflow["connections"].get(source, {}).get("main", [])
    targets[source] = [t["node"] for out in outs for t in out]
if any(t != ["Build Intake Outcome"] for t in targets.values()):
    raise SystemExit("the Respond nodes do not all continue to the outcome node alone: %s" % targets)
incident_path = [t["node"] for out in workflow["connections"]["Append Incident Record"]["main"] for t in out]
if incident_path != ["Alert?"]:
    raise SystemExit("the incident path changed: Append Incident Record -> %s" % incident_path)
append = node_named(workflow, "Append Intake Log")
if append["parameters"] != {"operation": "write", "fileName": "/data/arkon/intake_outcomes.jsonl", "options": {"append": True}}:
    raise SystemExit("the append node is not an append to the intake log: %s" % append["parameters"])
print("ok   the four Respond nodes continue to the outcome node alone; the incident path is untouched")

outcome_js = node_named(workflow, "Build Intake Outcome")["parameters"]["jsCode"]
harness = "function outcome($, $input) {\n%s\n}\n%s" % (outcome_js, CASES)

with tempfile.TemporaryDirectory() as tmp:
    path = pathlib.Path(tmp) / "check.js"
    path.write_text(harness, encoding="utf-8")
    result = subprocess.run(["node", str(path)], capture_output=True, text=True)

print(result.stdout, end="")
if result.stderr.strip():
    print(result.stderr, file=sys.stderr)
sys.exit(result.returncode)
