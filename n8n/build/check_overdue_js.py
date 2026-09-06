"""Run the overdue selection outside n8n, before deploying.

Two things are checked, and the first one is here because of what happened to
`build_escalation_workflow.py`: it had silently stopped reproducing its own
tracked JSON, and regenerating it would have dropped a tested feature. So this
first asserts that running the generator leaves the tracked file byte-identical,
then takes the JS out of that tracked file - the document that actually gets
imported - and runs it under node against cases written out by hand.

The selection decides who gets a message in a real chat, and it is capped, so the
two failure modes worth catching offline are a run that notifies nobody when
something is overdue and a run that notifies the same incident twice.
The record builder is checked too, against the reply shape the Telegram node
actually returns: on the first live run (execution 7800, 2026-09-06) every record
carried a null message id because the code had read the Bot API envelope instead
of its `result`, and nothing offline had exercised that node.

    python n8n/build/check_overdue_js.py
"""

import json
import pathlib
import subprocess
import sys
import tempfile

N8N_DIR = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = N8N_DIR / "overdue_escalation_v1.json"
GENERATOR = pathlib.Path(__file__).resolve().parent / "build_overdue_workflow.py"

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

// One incident as the status API projects it, with only the fields the selection
// reads. `overdue` and `acknowledge_due_minutes` are the API's own, computed from
// lifecycle.py; this node must never recompute them.
const incident = (id, ageMinutes, overdue, priority) => ({
  incident_id: id,
  created_at: "2026-09-05T08:00:00.000Z",
  age_minutes: ageMinutes,
  status: "new",
  priority: priority || "P2",
  summary: "summary of " + id,
  acknowledge_due_minutes: priority === "P1" ? 15 : 60,
  overdue: overdue,
  assigned_to: "L. Fischer",
  assigned_role: "Field Quality Analyst",
  escalation_contact: "R. Ortiz",
});

const api = (incidents, matchCount) => ({
  status: "ok",
  incidents: incidents,
  match_count: matchCount === undefined ? incidents.length : matchCount,
  returned: incidents.length,
});

const run = (apiResponse, logText) =>
  select(
    (name) => ({ first: () => ({ json: apiResponse }) }),
    { first: () => ({ json: { notifications_text: logText } }) }
  );

const logLine = (id, notificationId) =>
  JSON.stringify({ notification_id: notificationId, incident_id: id });

// -- what is selected ----------------------------------------------------
const none = run(api([incident("ARK-INC-00001", 120, false)]), "");
check("an incident the API does not call overdue is not selected", none.length, 0);

const one = run(api([incident("ARK-INC-00001", 120, true)]), "");
check("an overdue incident is selected", one.length, 1);
check("the first id on an empty log is 00001", one[0].json.notification.notification_id, "ARK-NTF-00001");
check("the record names the incident", one[0].json.notification.incident_id, "ARK-INC-00001");
check("minutes overdue is age minus the window", one[0].json.notification.minutes_overdue, 60);
check("the person is labelled simulated", one[0].json.notification.context_origin, "simulated");
check("the card is not sent yet", one[0].json.notification.telegram_message_id, null);

// -- dedup ---------------------------------------------------------------
const already = run(api([incident("ARK-INC-00001", 120, true)]), logLine("ARK-INC-00001", "ARK-NTF-00001"));
check("an incident already in the log is not selected again", already.length, 0);

const mixed = run(
  api([incident("ARK-INC-00001", 120, true), incident("ARK-INC-00002", 90, true)]),
  logLine("ARK-INC-00001", "ARK-NTF-00007")
);
check("only the un-notified incident is selected", mixed.map((i) => i.json.notification.incident_id), ["ARK-INC-00002"]);
check("the id continues from the highest in the log", mixed[0].json.notification.notification_id, "ARK-NTF-00008");

// -- the cap, and the order it applies in --------------------------------
const many = run(
  api([
    incident("ARK-INC-00001", 100, true),
    incident("ARK-INC-00002", 400, true),
    incident("ARK-INC-00003", 200, true),
    incident("ARK-INC-00004", 300, true),
  ]),
  ""
);
check("a run sends at most the cap", many.length, 3);
check(
  "the longest wait goes out first",
  many.map((i) => i.json.notification.incident_id),
  ["ARK-INC-00002", "ARK-INC-00004", "ARK-INC-00003"]
);
check("a capped run says so", many[0].json.notification.selection_capped, true);
check("a capped run records how many were waiting", many[0].json.notification.candidates_overdue, 4);
check("ids are consecutive inside one run", many.map((i) => i.json.notification.notification_id), ["ARK-NTF-00001", "ARK-NTF-00002", "ARK-NTF-00003"]);
check("an uncapped run says so", one[0].json.notification.selection_capped, false);

// -- the log the selection reads back ------------------------------------
const damaged = run(api([incident("ARK-INC-00002", 120, true)]), logLine("ARK-INC-00001", "ARK-NTF-00003") + "\n{not json\n");
check("a damaged log line does not stop the run", damaged.length, 1);
check("a damaged log line is counted onto the record", damaged[0].json.notification.log_unreadable_lines, 1);
check("a damaged line does not lose the readable dedup entry", damaged[0].json.notification.incident_id, "ARK-INC-00002");

const blanks = run(api([incident("ARK-INC-00001", 120, true)]), "\n\n   \n");
check("blank lines are not unreadable lines", blanks[0].json.notification.log_unreadable_lines, 0);

// -- the page cap of the API ---------------------------------------------
const truncated = run(api([incident("ARK-INC-00001", 120, true)], 80), "");
check("a truncated page is recorded", truncated[0].json.notification.selection_truncated, true);
check("a complete page is recorded as complete", one[0].json.notification.selection_truncated, false);

// -- the card ------------------------------------------------------------
const marked = incident("ARK-INC-00001", 120, true);
marked.summary = "Rate <5% & rising";
const escaped = run(api([marked]), "");
check(
  "the summary is HTML escaped before it meets the markup",
  escaped[0].json.alert_text.includes("Rate &lt;5% &amp; rising"),
  true
);
check("the raw summary never reaches the card", escaped[0].json.alert_text.includes("<5%"), false);
check("the card names the notification id", escaped[0].json.alert_text.includes("ARK-NTF-00001"), true);

// -- nothing to do -------------------------------------------------------
check("an empty store selects nobody", run(api([]), "").length, 0);

// -- the record, after the card ------------------------------------------
// The Telegram node returns the Bot API envelope, `{ ok, result }`, with the
// message id, the chat and the date inside `result`. This is the shape read out
// of execution 7800 on 2026-09-06, the first live run, and the record must take
// its evidence from there.
const sentItems = (replies) => ({ all: () => replies.map((json) => ({ json })) });
const selectedItems = (ids) => ({
  all: () => ids.map((id) => ({
    json: { notification: { notification_id: "ARK-NTF-0000" + id, incident_id: "ARK-INC-0000" + id, telegram_chat_id: "-5481573875", sent_at: null } },
  })),
});
const envelope = { ok: true, result: { message_id: 83, chat: { id: -5481573875, title: "Arkon Quality Alerts" }, date: 1788723914 } };
const recorded = record(() => selectedItems([1]), sentItems([envelope]));
const firstRecord = JSON.parse(recorded[0].json.notifications_jsonl.trim().split("\n")[0]);
check("the record carries Telegram's own message id", firstRecord.telegram_message_id, 83);
check("the record's sent_at is Telegram's own date", firstRecord.sent_at, "2026-09-06T19:45:14.000Z");
check("the record's chat id is the one Telegram answered with", firstRecord.telegram_chat_id, "-5481573875");
check("one newline-terminated line per card", recorded[0].json.notifications_jsonl.endsWith("\n") && recorded[0].json.notified === 1, true);
const bare = record(() => selectedItems([2]), sentItems([envelope.result]));
check("a reply that already is the result object still reads", JSON.parse(bare[0].json.notifications_jsonl.trim()).telegram_message_id, 83);
const empty = record(() => selectedItems([3]), sentItems([{}]));
check("an empty reply records a null id rather than failing", JSON.parse(empty[0].json.notifications_jsonl.trim()).telegram_message_id, null);

console.log(failures === 0 ? "\nALL PASS" : "\n" + failures + " FAILURE(S)");
process.exit(failures === 0 ? 0 : 1);
"""


def code_body(workflow, node_name):
    for node in workflow["nodes"]:
        if node["name"] == node_name:
            return node["parameters"]["jsCode"]
    raise SystemExit("no node named %s in %s" % (node_name, WORKFLOW.name))


# The generator must still generate the file it is named after. This is the check
# that build_escalation_workflow.py failed silently in September 2026.
before = WORKFLOW.read_bytes()
subprocess.run([sys.executable, str(GENERATOR)], check=True, capture_output=True)
after = WORKFLOW.read_bytes()
if before != after:
    raise SystemExit(
        "the generator no longer reproduces %s: the tracked file was stale, and it "
        "has just been rewritten. Read the diff before trusting either version." % WORKFLOW.name
    )
print("ok   the generator reproduces the tracked workflow byte for byte")

workflow = json.loads(after.decode("utf-8"))
select_js = code_body(workflow, "Select Overdue Incidents")
record_js = code_body(workflow, "Build Notification Records")

# The selection reads $input and $('Read Alerting Incidents'), and the record
# builder reads $input and $('Select Overdue Incidents'), so each runs here as a
# function of exactly those two, which is also the whole of its interface to n8n.
harness = "function select($, $input) {\n%s\n}\nfunction record($, $input) {\n%s\n}\n%s" % (
    select_js, record_js, CASES)

with tempfile.TemporaryDirectory() as tmp:
    path = pathlib.Path(tmp) / "check.js"
    path.write_text(harness, encoding="utf-8")
    result = subprocess.run(["node", str(path)], capture_output=True, text=True)

print(result.stdout, end="")
if result.stderr.strip():
    print(result.stderr, file=sys.stderr)
sys.exit(result.returncode)
