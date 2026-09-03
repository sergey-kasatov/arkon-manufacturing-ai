"""Run the lifecycle fold and the state machine outside n8n, before deploying.

The fold of `lifecycle.py` is injected verbatim into three workflows, and it is
the piece that decides what status an incident has. A mistake in it is not a
failed request: it is a wrong status served with a 200, which is the failure mode
this project keeps naming and has no way to notice from the outside.

So this checks two things. First that the JS in the generated workflow JSON is
the JS in `lifecycle.py`, character for character, because everything below tests
the source rather than the file that gets imported. Then that the fold and the
machine behave, under node, on cases written out by hand.

    python n8n/build/check_lifecycle_js.py
"""

import json
import os
import pathlib
import subprocess
import sys
import tempfile

from lifecycle import ALLOWED_TRANSITIONS, FOLD_JS, LIFECYCLE, js_constants

N8N_DIR = pathlib.Path(__file__).resolve().parent.parent

# The fold rides in these workflows. Each entry names the Code node carrying it.
CARRIERS = [
    ("incident_transition_v1.json", "Build Transition Record"),
    ("incident_status_api_v1.json", "Filter Incidents"),
    ("escalation_record_v1.json", "Build Escalation Record"),
]

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

const T0 = "2026-09-03T10:00:00.000Z";
const incident = { incident_id: "ARK-INC-00001", created_at: T0, status: "new", priority: "P2" };
const at = (minutes) => new Date(Date.parse(T0) + minutes * 60000).toISOString();
const step = (from, to, minutes) => ({
  transition_id: "ARK-TRN-x",
  incident_id: "ARK-INC-00001",
  recorded_at: at(minutes),
  from_status: from,
  to_status: to,
  actor: "probe",
  note: "",
});
const fold = (steps) => arkonFold(incident, { "ARK-INC-00001": steps });

// -- the fold ------------------------------------------------------------
const empty = fold([]);
check("no transitions leaves the stored status", empty.status, "new");
check("no transitions means no KPI", [empty.minutes_to_acknowledge, empty.closed_at], [null, null]);
check("no transitions is not terminal", empty.is_terminal, false);

const acked = fold([step("new", "acknowledged", 30)]);
check("one transition is the current status", acked.status, "acknowledged");
check("time to acknowledge is measured from created_at", acked.minutes_to_acknowledge, 30);
check("an acknowledged incident is not terminal", acked.is_terminal, false);

const full = fold([
  step("new", "acknowledged", 12),
  step("acknowledged", "in_containment", 45),
  step("in_containment", "resolved", 180),
  step("resolved", "closed", 240),
]);
check("the full path ends closed", full.status, "closed");
check("closed is terminal", full.is_terminal, true);
check("three KPIs from four transitions", [full.minutes_to_acknowledge, full.minutes_to_resolve, full.minutes_to_close], [12, 180, 240]);
check("history keeps every step", full.transition_count, 4);

// A closing outcome is closed OR false_positive. Counting only "closed" would
// drop every incident the review threw out, which is the population the
// threshold tuning of charter 7.2 is supposed to learn from.
const fp = fold([step("new", "false_positive", 20)]);
check("false_positive is a closing outcome", fp.minutes_to_close, 20);
check("false_positive is terminal", fp.is_terminal, true);
check("false_positive without acknowledgement has no ack time", fp.minutes_to_acknowledge, null);

// The reopen edge. resolved -> in_containment -> resolved happens when a
// containment did not hold, and the KPI must keep the FIRST resolution rather
// than sliding forward every time the incident bounces.
const reopened = fold([
  step("new", "acknowledged", 10),
  step("acknowledged", "in_containment", 20),
  step("in_containment", "resolved", 60),
  step("resolved", "in_containment", 90),
  step("in_containment", "resolved", 150),
  step("resolved", "closed", 200),
]);
check("a reopened incident still closes", reopened.status, "closed");
check("the KPI keeps the first resolution", reopened.minutes_to_resolve, 60);
check("and the real closure", reopened.minutes_to_close, 200);

// Lines arrive in whatever order the log holds them; the fold sorts by time.
const shuffled = fold([step("acknowledged", "resolved", 90), step("new", "acknowledged", 15)]);
check("the fold sorts by recorded_at", shuffled.status, "resolved");
check("and reads the earlier one as the acknowledgement", shuffled.minutes_to_acknowledge, 15);

// -- the parser ----------------------------------------------------------
const parsed = arkonTransitionsById(
  JSON.stringify(step("new", "acknowledged", 5)) + "\n" +
  "{ this is not json\n" +
  '{"to_status":"closed"}\n' +
  "\n"
);
check("a damaged line is counted, not thrown", parsed.unreadable, 2);
check("and the good line still lands", (parsed.byId["ARK-INC-00001"] ?? []).length, 1);

// -- the machine ---------------------------------------------------------
check("closed is terminal in the machine", ALLOWED_TRANSITIONS["closed"], []);
check("false_positive is terminal in the machine", ALLOWED_TRANSITIONS["false_positive"], []);
check("new can only be acknowledged or thrown out", ALLOWED_TRANSITIONS["new"], ["acknowledged", "false_positive"]);
check("nothing may re-enter new", LIFECYCLE.filter((s) => (ALLOWED_TRANSITIONS[s] ?? []).includes("new")), []);
check("every state in the machine is in the lifecycle", Object.keys(ALLOWED_TRANSITIONS).filter((s) => !LIFECYCLE.includes(s)), []);
check("every lifecycle state is in the machine", LIFECYCLE.filter((s) => ALLOWED_TRANSITIONS[s] === undefined), []);
check(
  "every edge points at a real state",
  Object.values(ALLOWED_TRANSITIONS).flat().filter((s) => !LIFECYCLE.includes(s)),
  []
);
// Every non-terminal state has to be able to reach a closing outcome, or an
// incident can enter a state it cannot leave without anybody noticing.
const reaches = (start) => {
  const seen = new Set([start]);
  const queue = [start];
  while (queue.length) {
    for (const next of ALLOWED_TRANSITIONS[queue.shift()] ?? []) {
      if (!seen.has(next)) {
        seen.add(next);
        queue.push(next);
      }
    }
  }
  return seen.has("closed") || seen.has("false_positive");
};
check("every open state can still be closed", LIFECYCLE.filter((s) => !TERMINAL_STATUSES.includes(s) && !reaches(s)), []);

console.log(failures === 0 ? "\nall checks passed" : "\n" + failures + " check(s) failed");
process.exit(failures === 0 ? 0 : 1);
"""


def main():
    # The tests below run lifecycle.py's source. That is only a test of the
    # deployed workflow if the generator injected it unchanged, so prove it.
    injected = js_constants() + FOLD_JS
    for filename, node_name in CARRIERS:
        path = N8N_DIR / filename
        if not path.exists():
            print("MISSING " + filename + " - run its build script first")
            return 1
        nodes = {n["name"]: n for n in json.loads(path.read_text(encoding="utf-8"))["nodes"]}
        if node_name not in nodes:
            print("MISSING node " + node_name + " in " + filename)
            return 1
        if injected not in nodes[node_name]["parameters"]["jsCode"]:
            print("DRIFT " + filename + " / " + node_name + " does not carry lifecycle.py verbatim")
            return 1
        print("ok   " + filename + " / " + node_name + " carries lifecycle.py verbatim", flush=True)

    script = injected + CASES
    handle, name = tempfile.mkstemp(suffix=".js")
    os.close(handle)
    try:
        pathlib.Path(name).write_text(script, encoding="utf-8")
        return subprocess.run(["node", name]).returncode
    finally:
        os.unlink(name)


if __name__ == "__main__":
    sys.exit(main())
