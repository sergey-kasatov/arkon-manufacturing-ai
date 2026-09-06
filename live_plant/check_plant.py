"""Run the live plant against a fake Steering Cell, before it meets the real one.

The emitter decides who gets a Telegram card and moves incidents in a store
that cannot be rewound, so the properties worth proving offline are the ones a
live run cannot afford to discover: that seven ticks really cover every module
and every department, that no record is drawn twice inside intake's 24-hour
window, that the alert budget holds, that the crew never asks the lifecycle for
a move it refuses and never touches an incident it did not raise, and that the
reset plan archives and never deletes.

The fake cell implements the same answers as the deployed workflows: contract
validation, dedup on record id plus priority for 24 hours, the four intake
outcomes, a status API filtered by lifecycle state, and a transition endpoint
that enforces charter 7.2 with a 409. Time is a fake clock the checks advance.

    python live_plant/check_plant.py
"""

import datetime
import json
import pathlib
import random
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "live_plant"))
sys.path.insert(0, str(REPO / "n8n" / "build"))
import plant as live_plant  # noqa: E402
from lifecycle import ALLOWED_TRANSITIONS  # noqa: E402

failures = 0


def check(name, condition, detail=""):
    global failures
    if condition:
        print("ok   " + name)
    else:
        failures += 1
        print("FAIL " + name + ("\n     " + str(detail) if detail else ""))


class Clock:
    def __init__(self, start):
        self.t = start

    def now(self):
        return self.t

    def advance(self, minutes):
        self.t = self.t + datetime.timedelta(minutes=minutes)


class FakeCell:
    """Intake, status and transitions, with the deployed workflows' answers."""

    def __init__(self, clock):
        self.clock = clock
        self.incidents = []
        self.transitions = []
        self.seen = {}
        self.counter = 0
        self.received_events = []
        self.transition_requests = []
        self.illegal = 0
        self.duplicates = 0

    def seed_incident(self, incident_id, event_id, priority, module, status="new"):
        self.counter += 1
        self.incidents.append({
            "incident_id": incident_id, "event_id": event_id, "priority": priority,
            "source_module": module, "status": status,
            "created_at": self.clock.now().isoformat(), "assigned_to": "D. Keller",
            "escalation_contact": "R. Ortiz", "summary": "seeded"})

    def post(self, url, payload=None, params=None):
        if url.endswith("arkon-event"):
            return self._intake(payload)
        if url.endswith("arkon-incident-transition"):
            return self._transition(params)
        return 404, {}

    def get(self, url, params=None):
        params = params or {}
        hits = [i for i in self.incidents if i["status"] == params.get("status")] if params.get("status") \
            else list(self.incidents)
        hits.sort(key=lambda i: i["created_at"], reverse=True)
        limit = int(params.get("limit", 5))
        page = hits[:limit]
        return 200, {"status": "ok" if hits else "no_match", "incidents": page,
                     "match_count": len(hits), "returned": len(page),
                     "store": {"total_incidents": len(self.incidents), "open_incidents": 0,
                               "overdue_incidents": 0, "incidents_by_status": {}}}

    def _intake(self, event):
        self.received_events.append(event)
        problems = live_plant.validate_event(event)
        if problems:
            return 400, {"status": "rejected", "errors": problems}
        key = event["evidence"]["record_id"] + "|" + event["priority"]
        now = self.clock.now()
        if key in self.seen and now - self.seen[key] < datetime.timedelta(hours=24):
            self.duplicates += 1
            self.seen[key] = now
            return 200, {"status": "duplicate_suppressed", "event_id": event["event_id"]}
        self.seen[key] = now
        self.counter += 1
        context = event.get("operational_context", {})
        incident = {
            "incident_id": "ARK-INC-%05d" % self.counter, "event_id": event["event_id"],
            "priority": event["priority"], "source_module": event["source_module"],
            "status": "new", "created_at": now.isoformat(),
            "assigned_to": context.get("assigned_to"), "escalation_contact": context.get("escalation_contact"),
            "summary": event["summary"]}
        self.incidents.append(incident)
        status = "incident_created_alert_sent" if event["priority"] in ("P1", "P2") else "incident_recorded"
        return 200, {"status": status, "incident_id": incident["incident_id"], "priority": event["priority"]}

    def _transition(self, params):
        self.transition_requests.append(dict(params))
        incident = next((i for i in self.incidents if i["incident_id"] == params["incident_id"]), None)
        if incident is None:
            return 404, {"status": "rejected", "errors": ["no such incident"]}
        allowed = ALLOWED_TRANSITIONS[incident["status"]]
        if params["to_status"] not in allowed:
            self.illegal += 1
            return 409, {"status": "rejected", "current_status": incident["status"], "allowed_next": allowed}
        record = {"incident_id": incident["incident_id"], "from_status": incident["status"],
                  "to_status": params["to_status"], "actor": params["actor"], "note": params["note"]}
        incident["status"] = params["to_status"]
        self.transitions.append(record)
        return 200, {"status": "transition_recorded", "transition_id": "ARK-TRN-%05d" % len(self.transitions),
                     "incident_id": incident["incident_id"], "from_status": record["from_status"],
                     "to_status": record["to_status"], "minutes_since_created": 1.0,
                     "acknowledged_within_window": True if params["to_status"] == "acknowledged" else None}


def make_plant(seed, clock, cell, **kwargs):
    state_dir = tempfile.mkdtemp(prefix="live_plant_check_")
    ledger = live_plant.Ledger(state_dir)
    pools = live_plant.load_pools(kwargs.pop("include_p4", False))
    return live_plant.Plant(ledger, pools, cell, random.Random(seed), clock=clock.now,
                            event_api="fake/arkon-event", status_api="fake/arkon-incident-status",
                            transition_api="fake/arkon-incident-transition", **kwargs)


START = datetime.datetime(2026, 9, 7, 8, 0, tzinfo=datetime.timezone.utc)

# -- coverage, validity and the emitter's labels ------------------------------
clock = Clock(START)
cell = FakeCell(clock)
plant = make_plant(1, clock, cell, max_alerts_per_hour=1000)
lines = []
for _ in range(14):
    lines.append(plant.tick())
    clock.advance(10)
first7 = lines[:7]
check("seven ticks cover all seven modules", {l["module"] for l in first7} == {m["module"] for m in live_plant.MODULES})
check("seven ticks cover all four domains", {l["domain"] for l in first7} == {m["domain"] for m in live_plant.MODULES})
check("fourteen ticks visit every module exactly twice",
      all(sum(1 for l in lines if l["module"] == m["module"]) == 2 for m in live_plant.MODULES))
check("every emitted event passed the real contract validator at intake",
      all(live_plant.validate_event(e) == [] for e in cell.received_events), len(cell.received_events))
check("event ids are the live series and increase",
      [e["event_id"] for e in cell.received_events] == ["arkon-2026-9%05d" % i for i in range(1, 15)])
ctx = [e["operational_context"] for e in cell.received_events]
check("operational context is labelled simulated and names the emitter, the run and the source event",
      all(c["context_origin"] == "simulated" and c["emitter"] == "live_plant" and c["emitter_run"] == 1
          and c["replayed_from"].startswith("arkon-2026-") and not c["replayed_from"].startswith("arkon-2026-9")
          for c in ctx))
check("the shift follows the clock (08:00 UTC is 10:00 Berlin, shift A)",
      all(c["shift"] == "A" for c in ctx if "shift" in c) and any("shift" in c for c in ctx))
check("the model's evidence is untouched",
      all(e["evidence"] == next(s for s in plant.pools[e["source_module"]][e["priority"]]
                                if s["event_id"] == e["operational_context"]["replayed_from"])["evidence"]
          for e in cell.received_events))
check("every line on the ledger carries intake's answer and the incident id",
      all(l.get("intake_status") in ("incident_created_alert_sent", "incident_recorded") and l.get("incident_id")
          for l in lines))
alerted = [l for l in lines if l["alerted"]]
check("a card is recorded as a notification with addressee, role and escalation contact, unconfirmed",
      all(l["notification"] and l["notification"]["addressed_to"] == l["assigned_to"]
          and l["notification"]["escalation_contact"] == "R. Ortiz"
          and l["notification"]["delivery_confirmed"] is False for l in alerted) and alerted, len(alerted))
check("a recorded P3 carries no notification",
      all(l["notification"] is None for l in lines if l["priority"] == "P3"))

# -- no duplicates inside the dedup window ------------------------------------
clock = Clock(START)
cell = FakeCell(clock)
plant = make_plant(2, clock, cell, max_alerts_per_hour=1000)
rows = []
for _ in range(140):
    rows.append(plant.tick(crew=False))
    clock.advance(10)
check("140 ticks in 23 h: intake saw no duplicate", cell.duplicates == 0, cell.duplicates)
check("140 ticks in 23 h: nothing skipped", not any(r.get("skipped") for r in rows),
      [r["skipped"] for r in rows if r.get("skipped")][:3])
keys = [r["record_id"] + "|" + r["priority"] for r in rows]
check("140 record-priority keys are distinct", len(set(keys)) == len(keys))

# -- the alert budget --------------------------------------------------------
clock = Clock(START)
cell = FakeCell(clock)
plant = make_plant(3, clock, cell, max_alerts_per_hour=2)
rows = []
for _ in range(30):
    rows.append(plant.tick(crew=False))
    clock.advance(1)
check("with a budget of 2 per hour, 30 ticks in 30 minutes send at most 2 cards",
      sum(1 for r in rows if r["alerted"]) <= 2, sum(1 for r in rows if r["alerted"]))
check("the rest of the ticks still raised something", all(r.get("incident_id") for r in rows))
check("a substituted tick says which priority the mix drew",
      any(r["substituted"] and r["drawn_priority"] in ("P1", "P2") and r["priority"] not in ("P1", "P2") for r in rows))
check("substituted ticks are the only non-drawn priorities",
      all((r["drawn_priority"] == r["priority"]) != r["substituted"] for r in rows))
check("coverage holds under the budget", {r["module"] for r in rows} == {m["module"] for m in live_plant.MODULES})

# -- the published mix -------------------------------------------------------
clock = Clock(START)
cell = FakeCell(clock)
plant = make_plant(4, clock, cell, max_alerts_per_hour=1000)
mvtec = next(m for m in live_plant.MODULES if m["module"] == "mvtec_anomaly")
draws = [plant.draw(mvtec, clock.now())[0]["priority"] for _ in range(400)]
share = draws.count("P2") / len(draws)
check("MVTec draws P2 at about its published share (262 of 309)", 0.76 <= share <= 0.94, share)
cmapss = next(m for m in live_plant.MODULES if m["module"] == "cmapss_rul")
check("P4 is not drawn unless asked for", "P4" not in plant.pools["cmapss_rul"])
plant_p4 = make_plant(4, clock, cell, max_alerts_per_hour=1000, include_p4=True)
check("--include-p4 admits the CMAPSS P4 band and no other module has one",
      "P4" in plant_p4.pools["cmapss_rul"] and all("P4" not in plant_p4.pools[m["module"]]
                                                   for m in live_plant.MODULES if m["module"] != "cmapss_rul"))

# -- the crew ----------------------------------------------------------------
clock = Clock(START)
cell = FakeCell(clock)
cell.seed_incident("ARK-INC-00001", "arkon-2026-000082", "P1", "cmapss_rul")
plant = make_plant(5, clock, cell, max_alerts_per_hour=1000, max_transitions_per_tick=3)
for _ in range(80):
    plant.tick()
    clock.advance(10)
check("the crew never asked for a move the lifecycle refuses", cell.illegal == 0, cell.illegal)
check("the crew moved something", len(cell.transitions) > 20, len(cell.transitions))
legacy = next(i for i in cell.incidents if i["incident_id"] == "ARK-INC-00001")
check("the legacy incident the emitter did not raise was never touched", legacy["status"] == "new")
closes = [t for t in cell.transitions if t["to_status"] == "closed"]
check("closures are the Quality Manager's and say so",
      closes and all(t["actor"] == "R. Ortiz" and t["note"] == live_plant.CLOSE_NOTE for t in closes), len(closes))
acks = [t for t in cell.transitions if t["to_status"] == "acknowledged"]
check("acknowledgements are made by the assignee with the module's own note",
      acks and all(t["actor"] != "R. Ortiz" and t["note"] != "moved by the crew" for t in acks))
outcomes = {t["to_status"] for t in cell.transitions}
check("the run reached every lifecycle state, false positives included",
      outcomes >= {"acknowledged", "in_containment", "resolved", "closed", "false_positive"}, outcomes)
per_tick = {}
for record in plant.ledger.transitions():
    per_tick[record["tick"]] = per_tick.get(record["tick"], 0) + 1
check("no tick exceeded the transition cap", max(per_tick.values()) <= 3, max(per_tick.values()))
ordered = True
for tick in per_tick:
    moves = [t for t in plant.ledger.transitions() if t["tick"] == tick]
    seen_other = False
    for move in moves:
        is_ack = move["to_status"] == "acknowledged" and move["priority"] in ("P1", "P2")
        if is_ack and seen_other:
            ordered = False
        if not is_ack:
            seen_other = True
check("inside a tick, alerting acknowledgements go first", ordered)

clock = Clock(START)
cell = FakeCell(clock)
cell.seed_incident("ARK-INC-00001", "arkon-2026-000082", "P1", "cmapss_rul")
plant = make_plant(6, clock, cell, max_alerts_per_hour=1000, crew_all=True)
for _ in range(10):
    plant.tick()
    clock.advance(10)
legacy = next(i for i in cell.incidents if i["incident_id"] == "ARK-INC-00001")
check("--crew-all lets the crew move the legacy backlog", legacy["status"] != "new", legacy["status"])

# -- the crew survives a status API outage ------------------------------------
class DownCell(FakeCell):
    def get(self, url, params=None):
        return 503, {"status": "unavailable"}


clock = Clock(START)
cell = DownCell(clock)
plant = make_plant(7, clock, cell, max_alerts_per_hour=1000)
line = plant.tick()
check("a 503 from the status API raises the event and moves nothing", line.get("incident_id")
      and not cell.transition_requests)

# -- determinism -------------------------------------------------------------
def sequence(seed):
    clock = Clock(START)
    cell = FakeCell(clock)
    plant = make_plant(seed, clock, cell, max_alerts_per_hour=1000)
    out = []
    for _ in range(21):
        row = plant.tick(crew=False)
        out.append((row["module"], row["priority"], row["record_id"], row["assigned_to"]))
        clock.advance(10)
    return out


check("the same seed and clock give the same plant", sequence(11) == sequence(11))
check("a different seed gives a different plant", sequence(11) != sequence(12))

# -- an exhausted pool is skipped, not crashed --------------------------------
clock = Clock(START)
cell = FakeCell(clock)
plant = make_plant(8, clock, cell, max_alerts_per_hour=1000)
for event in [e for p in plant.pools["nhtsa_nlp"].values() for e in p]:
    plant.ledger.record_emission({"at": clock.now().isoformat(), "intake_status": "incident_recorded",
                                  "record_id": event["evidence"]["record_id"], "priority": event["priority"]})
plant.ledger.state["cursor"] = next(i for i, m in enumerate(live_plant.MODULES) if m["module"] == "nhtsa_nlp")
row = plant.tick(crew=False)
check("a module whose pool is spent inside the window is skipped with a reason",
      row.get("skipped", "").startswith("pool exhausted"), row)
nxt = plant.tick(crew=False)
check("and the cursor still moves on to the next module", nxt["module"] == "mvtec_anomaly", nxt["module"])

# -- a fresh ledger continues the series the store already holds ---------------
clock = Clock(START)
cell = FakeCell(clock)
cell.seed_incident("ARK-INC-00050", "arkon-2026-900012", "P3", "gc10_detect")
cell.seed_incident("ARK-INC-00051", "arkon-2026-000004", "P3", "cmapss_rul")
plant = make_plant(10, clock, cell, max_alerts_per_hour=1000)
row = plant.tick(crew=False)
check("a fresh ledger numbers its first event above the highest live id in the store",
      row["event_id"] == "arkon-2026-900013", row["event_id"])
check("and remembers that it was seeded", plant.ledger.state["seeded"] is True)
clock = Clock(START)
cell = DownCell(clock)
plant = make_plant(10, clock, cell, max_alerts_per_hour=1000)
row = plant.tick(crew=False)
check("with the status API down the numbering starts at 1 and stays unseeded for the next tick",
      row["event_id"] == "arkon-2026-900001" and plant.ledger.state["seeded"] is False)

# -- dry run -----------------------------------------------------------------
clock = Clock(START)
cell = FakeCell(clock)
plant = make_plant(9, clock, cell)
before = plant.ledger.state["next_event_no"]
import io, contextlib, time  # noqa: E401,E402
with contextlib.redirect_stdout(io.StringIO()):
    plant.tick(dry_run=True)
check("a dry run sends nothing, records nothing and consumes no event number",
      not cell.received_events and not plant.ledger.emitted() and plant.ledger.state["next_event_no"] == before)

# -- the service loop stops cleanly ------------------------------------------
class Args:
    interval, jitter, ticks, no_crew = 600, 0.0, 0, True
    max_alerts_per_hour, max_transitions_per_tick = 1000, 3


clock = Clock(START)
cell = FakeCell(clock)
plant = make_plant(13, clock, cell, max_alerts_per_hour=1000)
live_plant.STOP.update({"requested": False, "signal": None})
live_plant.request_stop(15, None)
with contextlib.redirect_stdout(io.StringIO()):
    live_plant.cmd_run(plant, Args())
check("a stop request already pending makes the loop exit without a tick", len(cell.received_events) == 0)

live_plant.STOP.update({"requested": False, "signal": None})
original_tick = plant.tick


def tick_then_stop(**kwargs):
    row = original_tick(**kwargs)
    live_plant.request_stop(15, None)
    return row


plant.tick = tick_then_stop
started = time.monotonic()
with contextlib.redirect_stdout(io.StringIO()):
    live_plant.cmd_run(plant, Args())
check("a stop request during a tick finishes that tick and exits without sleeping the interval",
      len(cell.received_events) == 1 and time.monotonic() - started < 5, time.monotonic() - started)
live_plant.STOP.update({"requested": False, "signal": None})

# -- the reset plan ----------------------------------------------------------
script = live_plant.reset_script("2026-09-07T080000Z")
check("the reset archives under a stamped directory", "/data/arkon/_archive/2026-09-07T080000Z" in script)
check("the reset never deletes", "rm " not in script and "rm\t" not in script)
check("the reset moves and re-creates each store file that exists",
      all("mv /data/arkon/%s.jsonl" % n in script and "touch /data/arkon/%s.jsonl" % n in script
          for n in live_plant.RESET_FILES))
check("the reset stops at the first error", script.startswith("set -e"))

print()
print("%d failure(s)" % failures if failures else "all checks passed")
sys.exit(1 if failures else 0)
