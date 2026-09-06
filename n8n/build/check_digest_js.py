"""Run the daily digest's two Code nodes outside n8n, before deploying.

Same shape as check_overdue_js.py, for the same reasons: first assert that the
generator still reproduces its tracked JSON byte for byte, then take the JS out of
that tracked file - the document that actually gets imported - and run it under
node against cases written out by hand. Both Code nodes are covered, the compose
and the record, because the overdue timer's first live run (execution 7800,
2026-09-06) found a record defect that nothing offline had exercised.

One case reaches across workflows. The digest writes into the log the overdue
timer reads for its dedup and its numbering, so the timer's own selection node is
loaded from `overdue_escalation_v1.json` and run against a log holding a digest
record: it must select nothing extra and continue the number after the digest's.

    python n8n/build/check_digest_js.py
"""

import json
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lifecycle  # noqa: E402

N8N_DIR = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = N8N_DIR / "daily_digest_v1.json"
TIMER_WORKFLOW = N8N_DIR / "overdue_escalation_v1.json"
GENERATOR = pathlib.Path(__file__).resolve().parent / "build_digest_workflow.py"

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
const throws = (name, fn) => {
  try {
    fn();
    failures += 1;
    console.log("FAIL " + name + "\n  expected a throw");
  } catch (error) {
    console.log("ok   " + name + " (" + String(error.message).slice(0, 60) + ")");
  }
};

// One incident as the status API projects it, with only the fields the digest
// reads. `overdue` is the API's own flag; the digest never recomputes it.
const incident = (id, priority, ageMinutes, overdue, extra) => Object.assign({
  incident_id: id,
  priority: priority,
  age_minutes: ageMinutes,
  status: "new",
  overdue: overdue === true,
  summary: "summary of " + id,
  source_module: "cmapss_rul",
  assigned_role: "Maintenance Planner",
}, extra || {});

const SUMMARY = { open_incidents: 9, overdue_incidents: 2 };
const TIMES = {
  acknowledged_incidents: 139, median_minutes_to_acknowledge: 50.8,
  acknowledged_within_window: 56, acknowledged_late: 9,
  closed_incidents: 149, median_minutes_to_close: 157.5,
};
const page = (state, incidents, matchCount, overrides) => Object.assign({
  status: incidents.length ? "ok" : "no_match",
  as_of: "2026-09-07T05:05:00.000Z",
  query: { status: state },
  store: SUMMARY,
  response_times: TIMES,
  match_count: matchCount === undefined ? incidents.length : matchCount,
  returned: incidents.length,
  incidents: incidents,
}, overrides || {});

const NAMES = {
  new: "Read New Incidents",
  acknowledged: "Read Acknowledged Incidents",
  in_containment: "Read In-Containment Incidents",
};
const run = (pages, logText) => {
  const byName = {};
  for (const [state, name] of Object.entries(NAMES)) byName[name] = pages[state];
  const items = compose(
    (name) => ({ first: () => ({ json: byName[name] }) }),
    { first: () => ({ json: { notifications_text: logText || "" } }) }
  );
  return items[0].json;
};
const quiet = () => ({
  new: page("new", [], 0, { store: { open_incidents: 0, overdue_incidents: 0 } }),
  acknowledged: page("acknowledged", []),
  in_containment: page("in_containment", []),
});
const typical = () => ({
  new: page("new", [
    incident("ARK-INC-00001", "P1", 30, true),
    incident("ARK-INC-00002", "P2", 400, true),
    incident("ARK-INC-00003", "P2", 10, false),
    incident("ARK-INC-00004", "P3", 100, false, { source_module: "neu_surface" }),
    incident("ARK-INC-00005", "P3", 5000, false, { source_module: "gc10_detect" }),
    incident("ARK-INC-00006", "P3", 20, false),
  ]),
  acknowledged: page("acknowledged", [
    incident("ARK-INC-00007", "P2", 90, false, { status: "acknowledged" }),
    incident("ARK-INC-00008", "P1", 60, false, { status: "acknowledged" }),
  ]),
  in_containment: page("in_containment", [
    incident("ARK-INC-00009", "P2", 700, false, { status: "in_containment" }),
  ]),
});
const logLine = (record) => JSON.stringify(record);
const timerRecord = (incidentId, notificationId) => logLine({ notification_id: notificationId, incident_id: incidentId, trigger: "unacknowledged_window_elapsed" });
const digestRecord = (notificationId) => logLine({ notification_id: notificationId, incident_id: null, trigger: "daily_digest" });

// -- a quiet plant is a digest too ---------------------------------------
const q = run(quiet(), "");
check("a quiet plant still produces one card", typeof q.digest_text, "string");
check("open is zero on a quiet plant", q.notification.open_incidents, 0);
check("the queue is zero on a quiet plant", q.notification.p3_queue, 0);
check("the card says the queue is empty", q.digest_text.includes("P3 queue for today's review: 0"), true);
check("the first id on an empty log is 00001", q.notification.notification_id, "ARK-NTF-00001");
check("a digest record carries no incident id", q.notification.incident_id, null);
check("a digest record names its trigger", q.notification.trigger, "daily_digest");
check("the card is not sent yet", q.notification.telegram_message_id, null);
check("the people are labelled simulated", q.notification.context_origin, "simulated");

// -- the counts, and where each one comes from ---------------------------
const t = run(typical(), "");
check("open per state is the page's match_count", t.notification.open_by_status, { new: 6, acknowledged: 2, in_containment: 1 });
check("open is the sum of the three states", t.notification.open_incidents, 9);
check("the summary's own open count is kept beside it", t.notification.store_open_incidents, 9);
check("open by priority spans all three pages", t.notification.open_by_priority, { P1: 2, P2: 4, P3: 3 });
check("overdue is the API's number", t.notification.overdue_incidents, 2);
check("overdue by priority counts the API's flags on the new page", t.notification.overdue_by_priority, { P1: 1, P2: 1, P3: 0 });
check("the P3 queue is what is still new", t.notification.p3_queue, 3);
check("the response times are the API's summary", t.notification.response_times, TIMES);
check("the as_of stamp is the API's", t.notification.as_of, "2026-09-07T05:05:00.000Z");
check("no page was truncated", t.notification.pages_truncated, false);
check("the card carries the open line", t.digest_text.includes("<b>Open: 9</b> (P1 2, P2 4, P3 3)"), true);
check("the card carries the state line", t.digest_text.includes("new 6, acknowledged 2, in containment 1"), true);
check("the card carries the overdue line", t.digest_text.includes("<b>Overdue: 2</b>"), true);
check("the card names the digest id", t.digest_text.includes("ARK-NTF-00001"), true);
check("the card carries the medians", t.digest_text.includes("median 50.8 min") && t.digest_text.includes("median 157.5 min"), true);

// -- order: the longest wait first, in both lists ------------------------
const at = (text, needle) => text.indexOf(needle);
check("the longest overdue wait is listed first", at(t.digest_text, "ARK-INC-00002") < at(t.digest_text, "ARK-INC-00001"), true);
check("the oldest P3 is listed first", at(t.digest_text, "ARK-INC-00005") < at(t.digest_text, "ARK-INC-00004") && at(t.digest_text, "ARK-INC-00004") < at(t.digest_text, "ARK-INC-00006"), true);
check("an age over a day reads in days and hours", t.digest_text.includes("3 d 11 h"), true);
check("an age under an hour reads in minutes", t.digest_text.includes("20 min"), true);
check("the P3 row names the module", t.digest_text.includes("ARK-INC-00005 gc10_detect, 3 d 11 h: summary of ARK-INC-00005"), true);

// -- the numbering is shared with the timer ------------------------------
const after = run(typical(), timerRecord("ARK-INC-00013", "ARK-NTF-00013") + "\n" + timerRecord("ARK-INC-00014", "ARK-NTF-00014") + "\n");
check("the id continues from the timer's highest", after.notification.notification_id, "ARK-NTF-00015");
const afterDigest = run(typical(), timerRecord("ARK-INC-00014", "ARK-NTF-00014") + "\n" + digestRecord("ARK-NTF-00015") + "\n");
check("the id continues from a digest's own record too", afterDigest.notification.notification_id, "ARK-NTF-00016");
const damaged = run(typical(), timerRecord("ARK-INC-00001", "ARK-NTF-00003") + "\n{not json\n");
check("a damaged log line does not stop the run", damaged.notification.notification_id, "ARK-NTF-00004");
check("a damaged log line is counted onto the record", damaged.notification.log_unreadable_lines, 1);
check("blank lines are not unreadable lines", run(typical(), "\n\n   \n").notification.log_unreadable_lines, 0);

// -- the caps, and the counts that survive them --------------------------
const many = typical();
for (let i = 10; i < 25; i += 1) many.new.incidents.push(incident("ARK-INC-000" + i, "P3", 1000 + i, false));
many.new.returned = many.new.incidents.length;
many.new.match_count = many.new.incidents.length;
for (let i = 30; i < 37; i += 1) many.new.incidents.push(incident("ARK-INC-000" + i, "P2", 2000 + i, true));
many.new.returned = many.new.incidents.length;
many.new.match_count = many.new.incidents.length;
const capped = run(many, "");
check("the queue count is stated in full", capped.notification.p3_queue, 18);
check("the queue lists at most ten rows", capped.notification.p3_listed, 10);
check("the card says how many queue rows are not listed", capped.digest_text.includes("and 8 more"), true);
check("the overdue list is at most five rows", capped.notification.overdue_listed, 5);
check("the card says how many overdue rows are not listed", capped.digest_text.includes("and 4 more"), true);

// -- a page cut by the API's limit is recorded, not hidden ---------------
const cut = typical();
cut.new.match_count = 600;
const truncated = run(cut, "");
check("a truncated page is recorded", truncated.notification.pages_truncated, true);
check("the state count is still the API's match_count", truncated.notification.open_by_status.new, 600);
check("the card says the lists are short", truncated.digest_text.includes("Note: a state exceeded the status API page"), true);

// -- the card fits Telegram, whatever the store holds --------------------
const wide = typical();
for (let i = 0; i < 5; i += 1) wide.new.incidents.push(incident("ARK-INC-0010" + i, "P2", 3000 + i, true, { assigned_role: "R".repeat(900) }));
wide.new.returned = wide.new.incidents.length;
wide.new.match_count = wide.new.incidents.length;
const shed = run(wide, "");
check("an oversized card is shed to under the cap", shed.digest_text.length <= 3900, true);
check("overdue rows are shed before queue rows", shed.notification.overdue_listed < 5 && shed.notification.p3_listed === 3, true);

// -- escaping ------------------------------------------------------------
const marked = typical();
marked.new.incidents[3].summary = "Rate <5% & rising";
const escaped = run(marked, "");
check("a summary is HTML escaped before it meets the markup", escaped.digest_text.includes("Rate &lt;5% &amp; rising"), true);
check("the raw summary never reaches the card", escaped.digest_text.includes("<5%"), false);

// -- a page that cannot be trusted stops the run -------------------------
const rejected = typical();
rejected.acknowledged = { status: "rejected", query: { status: "acknowledged" }, errors: ["x"] };
throws("a rejected page throws rather than composing", () => run(rejected, ""));
const foreign = typical();
foreign.in_containment.query.status = "resolved";
throws("a page answering a different state throws", () => run(foreign, ""));
const missing = typical();
missing.new = undefined;
throws("a missing page throws", () => run(missing, ""));

// -- the record, after the card ------------------------------------------
const notification = run(typical(), timerRecord("ARK-INC-00014", "ARK-NTF-00014") + "\n").notification;
const recordOf = (reply) => record(
  (name) => ({ first: () => ({ json: { notification: notification } }) }),
  { first: () => ({ json: reply }) }
);
const envelope = { ok: true, result: { message_id: 95, chat: { id: -5481573875, title: "Arkon Quality Alerts" }, date: 1788757500 } };
const written = JSON.parse(recordOf(envelope)[0].json.notifications_jsonl.trim());
check("the record carries Telegram's own message id", written.telegram_message_id, 95);
check("the record's sent_at is Telegram's own date", written.sent_at, "2026-09-07T05:05:00.000Z");
check("the record's chat id is the one Telegram answered with", written.telegram_chat_id, "-5481573875");
check("the record keeps the digest's number", written.notification_id, "ARK-NTF-00015");
check("the record keeps the empty incident id", written.incident_id, null);
check("the record keeps its trigger", written.trigger, "daily_digest");
check("one newline-terminated line", recordOf(envelope)[0].json.notifications_jsonl.endsWith("\n") && recordOf(envelope)[0].json.notified === 1, true);
check("a reply that already is the result object still reads", JSON.parse(recordOf(envelope.result)[0].json.notifications_jsonl.trim()).telegram_message_id, 95);
const bare = JSON.parse(recordOf({})[0].json.notifications_jsonl.trim());
check("an empty reply records a null id rather than failing", bare.telegram_message_id, null);
check("an empty reply still stamps sent_at", typeof bare.sent_at, "string");

// -- the timer reads a log the digest has written into ------------------
// The timer's own selection node, out of overdue_escalation_v1.json. A digest
// record must not count as a notified incident and must advance the numbering.
const api = { status: "ok", incidents: [
  { incident_id: "ARK-INC-00001", age_minutes: 500, status: "new", priority: "P2", overdue: true, acknowledge_due_minutes: 60, summary: "s", created_at: "2026-09-05T08:00:00.000Z" },
  { incident_id: "ARK-INC-00002", age_minutes: 400, status: "new", priority: "P2", overdue: true, acknowledge_due_minutes: 60, summary: "s", created_at: "2026-09-05T08:00:00.000Z" },
], match_count: 2, returned: 2 };
const selected = select(
  (name) => ({ first: () => ({ json: api }) }),
  { first: () => ({ json: { notifications_text: timerRecord("ARK-INC-00001", "ARK-NTF-00014") + "\n" + digestRecord("ARK-NTF-00015") + "\n" } }) }
);
check("the timer still skips the incident it notified", selected.map((i) => i.json.notification.incident_id), ["ARK-INC-00002"]);
check("the timer does not treat a digest record as a notified incident", selected.length, 1);
check("the timer numbers after the digest's record", selected[0].json.notification.notification_id, "ARK-NTF-00016");

console.log(failures === 0 ? "\nALL PASS" : "\n" + failures + " FAILURE(S)");
process.exit(failures === 0 ? 0 : 1);
"""


def code_body(workflow, node_name):
    for node in workflow["nodes"]:
        if node["name"] == node_name:
            return node["parameters"]["jsCode"]
    raise SystemExit("no node named %s" % node_name)


def node_named(workflow, node_name):
    for node in workflow["nodes"]:
        if node["name"] == node_name:
            return node
    raise SystemExit("no node named %s" % node_name)


# The generator must still generate the file it is named after.
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
timer = json.loads(TIMER_WORKFLOW.read_text(encoding="utf-8"))

# The three reads must cover exactly the open states of the lifecycle, or the
# digest's "open" is a different number from the API's.
asked = [
    next(p["value"] for p in node["parameters"]["queryParameters"]["parameters"] if p["name"] == "status")
    for node in workflow["nodes"] if node["type"] == "n8n-nodes-base.httpRequest"
]
if asked != lifecycle.OPEN_STATUSES:
    raise SystemExit("the reads ask for %s, lifecycle.py says open is %s" % (asked, lifecycle.OPEN_STATUSES))
print("ok   the three reads are exactly the open states of lifecycle.py")

# A schedule without a fixed hour and minute fires at a stable random time, and
# an unpinned timezone is America/New_York on this instance.
interval = node_named(workflow, "Digest Timer")["parameters"]["rule"]["interval"][0]
if interval.get("field") != "days" or "triggerAtHour" not in interval or "triggerAtMinute" not in interval:
    raise SystemExit("the digest timer is not pinned to a clock time: %s" % interval)
if workflow["settings"].get("timezone") != "Europe/Berlin":
    raise SystemExit("the workflow timezone is not pinned: %s" % workflow["settings"])
print("ok   the timer is pinned to %02d:%02d %s" % (interval["triggerAtHour"], interval["triggerAtMinute"], workflow["settings"]["timezone"]))

compose_js = code_body(workflow, "Compose Digest")
record_js = code_body(workflow, "Build Digest Record")
select_js = code_body(timer, "Select Overdue Incidents")

# Each Code node reads $input and $('...'), so each runs here as a function of
# exactly those two, which is also the whole of its interface to n8n.
harness = (
    "function compose($, $input) {\n%s\n}\n"
    "function record($, $input) {\n%s\n}\n"
    "function select($, $input) {\n%s\n}\n%s"
) % (compose_js, record_js, select_js, CASES)

with tempfile.TemporaryDirectory() as tmp:
    path = pathlib.Path(tmp) / "check.js"
    path.write_text(harness, encoding="utf-8")
    result = subprocess.run(["node", str(path)], capture_output=True, text=True)

print(result.stdout, end="")
if result.stderr.strip():
    print(result.stderr, file=sys.stderr)
sys.exit(result.returncode)
