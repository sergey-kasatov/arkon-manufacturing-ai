"""Run the Arkon plant live: one realistic incident every few minutes across all
seven modules, and a simulated crew that moves the incidents it raised.

This is the demo engine. `replay_events.py` fires a slice of one batch and
`drive_incident.py` walks one incident by hand; this script does both on a clock
so the store moves the way a plant does while somebody watches the Telegram
group, the cockpit and the executive view.

Four decisions are worth reading before the code.

**The events are real model output, re-timed.** Every emitted event is drawn from
the module's own published batch in `events/out/`, so the summary, the record id,
the prediction and the threshold are what the model said about a real engine,
truck, casting, strip, component, sheet or complaint cell. Nothing here invents a
defect. What the emitter changes is the timing and the simulated operational
context: `event_id` moves to the `arkon-2026-9xxxxx` series so a live event can be
told from a batch replay on sight, `event_time` becomes now, the shift follows the
clock, and `operational_context` names the emitter, the run and the batch event
it came from. Priorities are drawn with the module's published band mix as the
weights, so a module that mostly publishes P3 mostly raises P3 here too.

**Coverage is guaranteed by construction, not by chance.** The modules are visited
round-robin in a fixed order, so seven consecutive ticks cover all seven modules
and all four business domains. A random draw over modules could skip a department
for hours and would have to be checked; a cycle cannot.

**Every P1 and P2 sends a real Telegram card (DEFECT-8), so the emitter is
budgeted.** At most `--max-alerts-per-hour` alerting events go out; when the
budget is spent, the tick draws a non-alerting priority from the same module
instead of skipping, so the plant keeps moving and the department is still
covered. The substitution is recorded on the ledger line. The 24-hour dedup at
intake is respected from this side too: a record id and priority the emitter has
sent in the last 24 hours is not drawn again, because intake would answer
`duplicate_suppressed` and the tick would raise nothing.

**Nothing here rewinds anything.** The incident store, the transition log and
the escalation log are append-only and their counters live in n8n. A reset is
therefore an archive: the store files are moved aside inside the n8n container
and fresh empty files are created, the counters keep counting, and the emitter's
own dedup memory is kept so the 24-hour window at intake is still honoured after
the reset. The ledger under the state directory is the emitter's account of who
was told what and when: intake's answer per event, the incident id it created,
whether a card went to the alert group, who it was addressed to and who the
escalation contact is. That answer is the workflow's, not a delivery receipt;
the card itself is confirmed by a person reading the group, as the run log in
`n8n/README.md` records.

Stdlib only. A mini-project of its own: this file, `check_plant.py` and
`README.md` beside it. Runs from the laptop or as the `live-plant` service beside
the cockpit (`app/docker-compose.yml`).

Usage:
    python live_plant/plant.py tick --dry-run          # draw, validate, print, send nothing
    python live_plant/plant.py tick                    # one event plus one crew pass
    python live_plant/plant.py run                     # every ~10 minutes until stopped
    python live_plant/plant.py run --ticks 7 --interval 30 --max-alerts-per-hour 3
    python live_plant/plant.py status                  # coverage, budget, pools, the live store
    python live_plant/plant.py reset                   # print the archive plan
    python live_plant/plant.py reset --execute --host user@nas
"""

import argparse
import datetime
import json
import os
import pathlib
import random
import shlex
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "events"))
from validate_event import validate_event  # noqa: E402

BASE_URL = os.environ.get("ARKON_N8N_URL", "http://AK2101:5678")
EVENT_API = os.environ.get("ARKON_EVENT_API", BASE_URL + "/webhook/arkon-event")
STATUS_API = os.environ.get("ARKON_STATUS_API", BASE_URL + "/webhook/arkon-incident-status")
TRANSITION_API = os.environ.get("ARKON_TRANSITION_API", BASE_URL + "/webhook/arkon-incident-transition")
STATE_DIR = pathlib.Path(os.environ.get("ARKON_LIVE_PLANT_STATE", REPO / "live_plant" / "state"))
BATCH_DIR = REPO / "events" / "out"
ROSTER = REPO / "events" / "roster.json"

# The `arkon-2026-9` series marks a live emission. Each adapter owns a series
# (0 CMAPSS ... 6 NHTSA); 9 is the emitter's, so the event id on a Telegram card
# says on its own whether a batch was replayed or the plant is running.
EVENT_SERIES = "arkon-2026-9"

DEDUP_HOURS = 24
ALERTING = ("P1", "P2")

# Round-robin order. Consecutive ticks change department where the module count
# allows it: four of the seven modules are visual inspection, so one adjacent pair
# in that domain is unavoidable in a cycle of seven.
MODULES = [
    {"module": "cmapss_rul", "domain": "asset_reliability", "batch": "cmapss_events_full_fleet.jsonl"},
    {"module": "casting_cv", "domain": "visual_inspection", "batch": "casting_events.jsonl"},
    {"module": "scania_aps", "domain": "fleet_reliability", "batch": "scania_events.jsonl"},
    {"module": "neu_surface", "domain": "visual_inspection", "batch": "neu_events.jsonl"},
    {"module": "nhtsa_nlp", "domain": "field_quality", "batch": "nhtsa_events.jsonl"},
    {"module": "mvtec_anomaly", "domain": "visual_inspection", "batch": "mvtec_events.jsonl"},
    {"module": "gc10_detect", "domain": "visual_inspection", "batch": "gc10_events.jsonl"},
]

# What the crew does per tick, as probabilities. A P1 is acknowledged on the next
# tick most of the time, which at a ten-minute cadence is inside its fifteen-minute
# window; a P2 at 0.30 per tick is acknowledged inside its hour about nine times
# in ten, so the overdue block is never empty for long and never the whole store.
CREW = {
    "acknowledge": {"P1": 0.85, "P2": 0.30, "P3": 0.15, "P4": 0.05},
    "false_positive_from_new": 0.03,
    "contain": 0.35,
    "resolve_direct": 0.15,
    "false_positive_from_acknowledged": 0.08,
    "resolve": 0.35,
    "close": 0.40,
    "reopen": 0.04,
}

# One note per state and module, so the transition log reads as an operator's
# account. The closure note is the Quality Manager's, per SOP section 8.
NOTES = {
    "cmapss_rul": {
        "acknowledged": "picked up by the maintenance planner, test log pulled",
        "in_containment": "engine taken off the test schedule pending borescope inspection",
        "resolved": "borescope confirmed HPC blade wear, module swapped and re-run",
        "false_positive": "inspection found the sensor drifted, no wear on the unit",
    },
    "scania_aps": {
        "acknowledged": "truck held at the depot, workshop slot requested",
        "in_containment": "APS compressor and dryer under inspection at the workshop",
        "resolved": "air dryer cartridge replaced, road test passed",
        "false_positive": "pressure test within specification, truck released",
    },
    "casting_cv": {
        "acknowledged": "impeller quarantined for QC decision",
        "in_containment": "casting sectioned for porosity check",
        "resolved": "porosity confirmed, part scrapped and batch logged",
        "false_positive": "section clean, part released to machining",
    },
    "neu_surface": {
        "acknowledged": "coil flagged at the mill, strip sample taken",
        "in_containment": "coil held for surface inspection by eye",
        "resolved": "defect confirmed, affected length trimmed and coil downgraded",
        "false_positive": "surface checked by eye, within specification",
    },
    "mvtec_anomaly": {
        "acknowledged": "component pulled from the line for a look under magnification",
        "in_containment": "lot held pending inspection of the flagged component",
        "resolved": "defect confirmed on the component, part scrapped and lot released",
        "false_positive": "component within drawing tolerance, returned to the line",
    },
    "gc10_detect": {
        "acknowledged": "coil held before dispositioning, defect map printed",
        "in_containment": "sheet marked and coil routed to the inspection bay",
        "resolved": "defect located on the sheet, coil downgraded and dispatched",
        "false_positive": "no defect at the located position, coil dispositioned as prime",
    },
    "nhtsa_nlp": {
        "acknowledged": "manufacturer and component carried into the monthly review",
        "in_containment": "complaint sample read, fleet data requested from the OEM",
        "resolved": "movement confirmed against warranty data and passed to engineering",
        "false_positive": "reporting change at the OEM explains the movement, no fleet issue",
    },
}
CLOSE_NOTE = "reviewed and closed by the Quality Manager"
REOPEN_NOTE = "containment did not hold, incident reopened"

# Charter 7.2, mirrored from n8n/build/lifecycle.py so the crew never asks for a
# move the endpoint would refuse. The endpoint stays the authority (409).
ALLOWED = {
    "new": ["acknowledged", "false_positive"],
    "acknowledged": ["in_containment", "resolved", "false_positive"],
    "in_containment": ["resolved", "false_positive"],
    "resolved": ["closed", "in_containment", "false_positive"],
}


# Time and transport, both injectable so the offline check can drive the emitter
# with a fake clock and a fake Steering Cell.
def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def local_shift(moment):
    """A 06:00 to 14:00, B 14:00 to 22:00, C 22:00 to 06:00, plant local time."""
    try:
        import zoneinfo
        local = moment.astimezone(zoneinfo.ZoneInfo("Europe/Berlin"))
    except Exception:
        local = moment.astimezone(datetime.timezone(datetime.timedelta(hours=2)))
    hour = local.hour
    return "A" if 6 <= hour < 14 else "B" if 14 <= hour < 22 else "C"


class HttpTransport:
    def post(self, url, payload=None, params=None):
        target = url + ("?" + urllib.parse.urlencode(params) if params else "")
        data = json.dumps(payload).encode("utf-8") if payload is not None else b""
        request = urllib.request.Request(target, data=data, method="POST",
                                         headers={"Content-Type": "application/json"})
        return self._send(request)

    def get(self, url, params=None):
        target = url + ("?" + urllib.parse.urlencode(params) if params else "")
        return self._send(urllib.request.Request(target))

    @staticmethod
    def _send(request):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read().decode("utf-8", errors="replace")
                return response.status, (json.loads(raw) if raw.strip() else {})
        except urllib.error.HTTPError as err:
            raw = err.read().decode("utf-8", errors="replace")
            try:
                return err.code, json.loads(raw)
            except json.JSONDecodeError:
                return err.code, {"raw": raw[:300]}
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            return 0, {"error": str(err)}


class Ledger:
    """The emitter's account, three files under one directory. Append-only."""

    def __init__(self, state_dir):
        self.dir = pathlib.Path(state_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.dir / "state.json"
        self.emitted_path = self.dir / "emitted.jsonl"
        self.transitions_path = self.dir / "transitions.jsonl"
        self.state = self._load_state()

    def _load_state(self):
        if self.state_path.exists():
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        # `seeded` is false until the first tick has read the store: a fresh
        # ledger on a second machine must not restart the live event numbering.
        return {"run_id": 1, "next_event_no": 1, "next_tick": 1, "cursor": 0, "resets": [], "seeded": False}

    def save_state(self):
        self.state_path.write_text(json.dumps(self.state, indent=2) + "\n", encoding="utf-8")

    @staticmethod
    def _read(path):
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    rows.append({"unreadable": True})
        return rows

    def emitted(self):
        return [r for r in self._read(self.emitted_path) if "unreadable" not in r]

    def transitions(self):
        return [r for r in self._read(self.transitions_path) if "unreadable" not in r]

    @staticmethod
    def _append(path, record):
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")

    def record_emission(self, record):
        self._append(self.emitted_path, record)

    def record_transition(self, record):
        self._append(self.transitions_path, record)

    def recent_keys(self, moment, hours=DEDUP_HOURS):
        """record_id|priority pairs intake would still suppress as duplicates."""
        edge = moment - datetime.timedelta(hours=hours)
        keys = set()
        for row in self.emitted():
            if row.get("intake_status") not in ("incident_created_alert_sent", "incident_recorded",
                                                "duplicate_suppressed"):
                continue
            at = parse_time(row.get("at"))
            if at and at >= edge:
                keys.add(row["record_id"] + "|" + row["priority"])
        return keys

    def alerts_in_last_hour(self, moment):
        edge = moment - datetime.timedelta(hours=1)
        count = 0
        for row in self.emitted():
            at = parse_time(row.get("at"))
            if row.get("alerted") and at and at >= edge:
                count += 1
        return count

    def own_incident_ids(self):
        return {r["incident_id"] for r in self.emitted() if r.get("incident_id")}


def parse_time(text):
    if not text:
        return None
    try:
        return datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None


def load_pools(include_p4=False):
    """Every module's published batch, grouped by priority."""
    pools = {}
    for entry in MODULES:
        path = BATCH_DIR / entry["batch"]
        if not path.exists():
            sys.exit("batch missing: %s (run the adapter in events/ first)" % path)
        by_priority = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if event["priority"] == "P4" and not include_p4:
                continue
            by_priority.setdefault(event["priority"], []).append(event)
        pools[entry["module"]] = by_priority
    return pools


class Plant:
    def __init__(self, ledger, pools, transport, rng, clock=now_utc,
                 max_alerts_per_hour=6, max_transitions_per_tick=3, crew_all=False,
                 event_api=EVENT_API, status_api=STATUS_API, transition_api=TRANSITION_API):
        self.ledger = ledger
        self.pools = pools
        self.transport = transport
        self.rng = rng
        self.clock = clock
        self.max_alerts = max_alerts_per_hour
        self.max_transitions = max_transitions_per_tick
        self.crew_all = crew_all
        self.event_api = event_api
        self.status_api = status_api
        self.transition_api = transition_api
        self.roster = json.loads(ROSTER.read_text(encoding="utf-8"))["roles"]

    # -- drawing one event -------------------------------------------------
    def draw(self, entry, moment):
        """Pick the priority by the published mix, then a record not sent in 24 h."""
        pool = self.pools[entry["module"]]
        recent = self.ledger.recent_keys(moment)
        budget_left = self.ledger.alerts_in_last_hour(moment) < self.max_alerts

        def available(priority):
            return [e for e in pool.get(priority, [])
                    if e["evidence"]["record_id"] + "|" + priority not in recent]

        priorities = [p for p in pool if available(p)]
        if not priorities:
            return None, None, "pool exhausted inside the %d h dedup window" % DEDUP_HOURS
        weights = [len(pool[p]) for p in priorities]
        drawn = self.rng.choices(priorities, weights=weights, k=1)[0]
        chosen, substituted = drawn, False
        if drawn in ALERTING and not budget_left:
            quiet = [p for p in priorities if p not in ALERTING]
            if not quiet:
                return None, drawn, "alert budget spent and the module has no non-alerting band"
            chosen = self.rng.choices(quiet, weights=[len(pool[p]) for p in quiet], k=1)[0]
            substituted = True
        event = self.rng.choice(available(chosen))
        return event, (drawn if substituted else None), None

    def stamp(self, source, entry, moment):
        """Re-time a batch event as a live one. The model's evidence is untouched."""
        event = json.loads(json.dumps(source))
        event["event_id"] = "%s%05d" % (EVENT_SERIES, self.ledger.state["next_event_no"])
        event["event_time"] = moment.isoformat(timespec="seconds").replace("+00:00", "Z")
        event["status"] = "new"
        role = self.roster[entry["domain"]]
        context = dict(source.get("operational_context") or {})
        context.update({
            "context_origin": "simulated",
            "assigned_role": role["role"],
            "assigned_to": self.rng.choice(role["people"]),
            "escalation_contact": self.roster["escalation"]["people"][0],
            "emitter": "live_plant",
            "emitter_run": self.ledger.state["run_id"],
            "replayed_from": source["event_id"],
        })
        if "shift" in context:
            context["shift"] = local_shift(moment)
        event["operational_context"] = context
        problems = validate_event(event)
        if problems:
            raise SystemExit("emitter built an invalid event %s: %s" % (event["event_id"], problems))
        return event

    def seed_event_numbering(self):
        """Continue the live series above whatever the store already holds.

        Two ledgers exist by design (the laptop's for bounded bursts, the NAS
        service's for demos) and a fresh one starts at 1. Intake does not reject a
        repeated event id, so nothing would fail; two incidents would simply share
        one. The status API ranks by recency and the live events are the newest,
        so the highest live number is in its first page whenever it matters.
        """
        state = self.ledger.state
        if state.get("seeded", True):
            return
        code, body = self.transport.get(self.status_api, {"limit": 50})
        if code != 200 or not isinstance(body, dict) or body.get("status") not in ("ok", "no_match"):
            print("         event numbering not seeded: status API answered %s; starting at %05d"
                  % (code, state["next_event_no"]))
            return
        highest = 0
        for incident in body.get("incidents") or []:
            event_id = str(incident.get("event_id", ""))
            if event_id.startswith(EVENT_SERIES) and event_id[len(EVENT_SERIES):].isdigit():
                highest = max(highest, int(event_id[len(EVENT_SERIES):]))
        state["next_event_no"] = max(state["next_event_no"], highest + 1)
        state["seeded"] = True
        self.ledger.save_state()

    # -- one tick ----------------------------------------------------------
    def tick(self, dry_run=False, crew=True):
        moment = self.clock()
        self.seed_event_numbering()
        state = self.ledger.state
        entry = MODULES[state["cursor"] % len(MODULES)]
        tick_no = state["next_tick"]
        source, drawn, reason = self.draw(entry, moment)
        line = {
            "at": moment.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "run_id": state["run_id"],
            "tick": tick_no,
            "module": entry["module"],
            "domain": entry["domain"],
            "cycle": state["cursor"] // len(MODULES) + 1,
        }
        if source is None:
            line.update({"skipped": reason, "drawn_priority": drawn})
            print("tick %d  %-14s skipped: %s" % (tick_no, entry["module"], reason))
        else:
            event = self.stamp(source, entry, moment)
            context = event["operational_context"]
            line.update({
                "priority": event["priority"],
                "drawn_priority": drawn or event["priority"],
                "substituted": drawn is not None,
                "record_id": event["evidence"]["record_id"],
                "event_id": event["event_id"],
                "replayed_from": source["event_id"],
                "summary": event["summary"],
                "assigned_to": context["assigned_to"],
                "assigned_role": context["assigned_role"],
                "escalation_contact": context["escalation_contact"],
                "shift": context.get("shift"),
            })
            if dry_run:
                print(json.dumps(event, indent=2))
                print("dry run: nothing sent, nothing recorded")
                return line
            code, body = self.transport.post(self.event_api, payload=event)
            status = body.get("status") if isinstance(body, dict) else None
            alerted = status == "incident_created_alert_sent"
            line.update({
                "http": code,
                "intake_status": status,
                "incident_id": body.get("incident_id") if isinstance(body, dict) else None,
                "alerted": alerted,
                "intake_body": None if status else body,
            })
            # Who was told what, and when. This is intake's answer, per DEFECT-8
            # a card confirmed by a person is a separate claim from this line.
            line["notification"] = {
                "channel": "telegram",
                "chat": "Arkon alert group",
                "addressed_to": context["assigned_to"],
                "role": context["assigned_role"],
                "escalation_contact": context["escalation_contact"],
                "sent_by": "quality_steering_cell_v1 alert branch",
                "at": line["at"],
                "delivery_confirmed": False,
            } if alerted else None
            print("tick %d  %-14s %s %-38s -> %s %s%s" % (
                tick_no, entry["module"], event["priority"], event["evidence"]["record_id"][:38],
                code, status, "  (card to %s)" % context["assigned_to"] if alerted else ""))
            if drawn:
                print("         alert budget spent, %s drawn as %s instead" % (drawn, event["priority"]))
            state["next_event_no"] += 1
        self.ledger.record_emission(line)
        state["cursor"] += 1
        state["next_tick"] += 1
        self.ledger.save_state()
        if crew and not dry_run:
            self.crew_pass(moment, tick_no)
        return line

    # -- the crew ----------------------------------------------------------
    def open_incidents(self):
        """Every non-terminal incident the crew may move, oldest first."""
        found = []
        for status in ("new", "acknowledged", "in_containment", "resolved"):
            code, body = self.transport.get(self.status_api, {"status": status, "limit": 50})
            if code != 200 or not isinstance(body, dict) or body.get("status") not in ("ok", "no_match"):
                print("         crew: status API answered %s %s, no transitions this tick"
                      % (code, body.get("status") if isinstance(body, dict) else body))
                return None
            found.extend(body.get("incidents") or [])
        own = self.ledger.own_incident_ids()
        if not self.crew_all:
            found = [i for i in found if str(i.get("event_id", "")).startswith(EVENT_SERIES)
                     or i.get("incident_id") in own]
        found.sort(key=lambda i: str(i.get("created_at", "")))
        return found

    def decide(self, incident):
        """One move for one incident, or None. Probabilities in CREW."""
        status = incident["status"]
        priority = incident["priority"]
        roll = self.rng.random()
        if status == "new":
            if roll < CREW["false_positive_from_new"]:
                return "false_positive"
            return "acknowledged" if self.rng.random() < CREW["acknowledge"].get(priority, 0.1) else None
        if status == "acknowledged":
            if roll < CREW["false_positive_from_acknowledged"]:
                return "false_positive"
            if roll < CREW["false_positive_from_acknowledged"] + CREW["resolve_direct"]:
                return "resolved"
            return "in_containment" if self.rng.random() < CREW["contain"] else None
        if status == "in_containment":
            return "resolved" if roll < CREW["resolve"] else None
        if status == "resolved":
            if roll < CREW["reopen"]:
                return "in_containment"
            return "closed" if self.rng.random() < CREW["close"] else None
        return None

    def crew_pass(self, moment, tick_no):
        incidents = self.open_incidents()
        if incidents is None:
            return []
        moves = []
        for incident in incidents:
            to_status = self.decide(incident)
            if to_status and to_status in ALLOWED.get(incident["status"], []):
                moves.append((incident, to_status))
        # Acknowledgements of alerting incidents first, because their windows are
        # the KPI; then the oldest work. The cap keeps the log plausible.
        rank = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
        moves.sort(key=lambda m: (0 if m[1] == "acknowledged" and m[0]["priority"] in ALERTING else 1,
                                  rank.get(m[0]["priority"], 9), str(m[0].get("created_at", ""))))
        done = []
        for incident, to_status in moves[: self.max_transitions]:
            module = incident.get("source_module", "")
            if to_status == "closed":
                actor, note = incident.get("escalation_contact") or "R. Ortiz", CLOSE_NOTE
            elif to_status == "in_containment" and incident["status"] == "resolved":
                actor, note = incident.get("assigned_to") or "operator", REOPEN_NOTE
            else:
                actor = incident.get("assigned_to") or "operator"
                note = NOTES.get(module, {}).get(to_status, "moved by the crew")
            params = {"incident_id": incident["incident_id"], "to_status": to_status,
                      "actor": actor, "note": note}
            code, body = self.transport.post(self.transition_api, params=params)
            record = {
                "at": moment.isoformat(timespec="seconds").replace("+00:00", "Z"),
                "run_id": self.ledger.state["run_id"],
                "tick": tick_no,
                "incident_id": incident["incident_id"],
                "module": module,
                "priority": incident["priority"],
                "from_status": incident["status"],
                "to_status": to_status,
                "actor": actor,
                "note": note,
                "http": code,
                "status": body.get("status") if isinstance(body, dict) else None,
                "transition_id": body.get("transition_id") if isinstance(body, dict) else None,
                "minutes_since_created": body.get("minutes_since_created") if isinstance(body, dict) else None,
                "acknowledged_within_window": body.get("acknowledged_within_window") if isinstance(body, dict) else None,
                "context_origin": "simulated",
            }
            self.ledger.record_transition(record)
            done.append(record)
            window = record["acknowledged_within_window"]
            print("         crew: %s %s -> %s by %s -> %s %s%s" % (
                incident["incident_id"], incident["status"], to_status, actor, code, record["status"],
                "" if window is None else ("  within window" if window else "  OUTSIDE the window")))
        return done


# -- running as a service ----------------------------------------------------
# `docker stop` sends SIGTERM and gives the process a grace period. A tick in
# flight finishes (its ledger line and the crew moves it has already made are
# real writes), then the loop exits cleanly instead of being killed mid-sleep.
STOP = {"requested": False, "signal": None}


def request_stop(signum=None, frame=None):
    STOP["requested"] = True
    STOP["signal"] = signum


def install_signal_handlers():
    for name in ("SIGTERM", "SIGINT"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), request_stop)


def pause(seconds):
    """Sleep in one-second steps so a stop request is honoured within a second."""
    deadline = time.monotonic() + max(1.0, seconds)
    while not STOP["requested"] and time.monotonic() < deadline:
        time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))


def stamp():
    return datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


# -- commands ----------------------------------------------------------------
def cmd_run(plant, args):
    ticks = 0
    install_signal_handlers()
    print("%s  live plant: every %ds (+-%d%%), alert budget %d/h, crew cap %d/tick, run %d. "
          "Ctrl-C or SIGTERM stops after the tick in flight."
          % (stamp(), args.interval, int(args.jitter * 100), args.max_alerts_per_hour,
             args.max_transitions_per_tick, plant.ledger.state["run_id"]), flush=True)
    while not STOP["requested"]:
        print("%s  tick" % stamp(), flush=True)
        plant.tick(crew=not args.no_crew)
        ticks += 1
        if args.ticks and ticks >= args.ticks:
            break
        if STOP["requested"]:
            break
        wait = args.interval * (1 + plant.rng.uniform(-args.jitter, args.jitter))
        print("%s  next tick in %d s" % (stamp(), int(wait)), flush=True)
        pause(wait)
    print("%s  stopped after %d tick(s)%s" % (
        stamp(), ticks, "" if STOP["signal"] is None else " on signal %s" % STOP["signal"]), flush=True)
    return 0


def cmd_status(plant, args):
    ledger = plant.ledger
    moment = plant.clock()
    rows = [r for r in ledger.emitted() if r.get("run_id") == ledger.state["run_id"]]
    print("run %d, %d tick(s) recorded, next event %s%05d"
          % (ledger.state["run_id"], len(rows), EVENT_SERIES, ledger.state["next_event_no"]))
    by_module, by_domain = {}, {}
    for row in rows:
        by_module[row["module"]] = by_module.get(row["module"], 0) + 1
        by_domain[row["domain"]] = by_domain.get(row["domain"], 0) + 1
    print("coverage by module: %s" % json.dumps(by_module))
    print("coverage by domain: %s" % json.dumps(by_domain))
    outcomes = {}
    for row in rows:
        key = row.get("intake_status") or ("skipped" if row.get("skipped") else "unsent")
        outcomes[key] = outcomes.get(key, 0) + 1
    print("intake outcomes: %s" % json.dumps(outcomes))
    print("alerts in the last hour: %d of %d budget; substitutions this run: %d"
          % (ledger.alerts_in_last_hour(moment), plant.max_alerts,
             sum(1 for r in rows if r.get("substituted"))))
    recent = ledger.recent_keys(moment)
    for entry in MODULES:
        pool = plant.pools[entry["module"]]
        left = {p: sum(1 for e in pool[p] if e["evidence"]["record_id"] + "|" + p not in recent) for p in pool}
        print("pool %-14s %s" % (entry["module"], json.dumps(left)))
    transitions = [t for t in ledger.transitions() if t.get("run_id") == ledger.state["run_id"]]
    recorded = sum(1 for t in transitions if t.get("status") == "transition_recorded")
    print("crew: %d transition(s) attempted, %d recorded" % (len(transitions), recorded))
    if ledger.state.get("resets"):
        print("resets: %s" % json.dumps(ledger.state["resets"][-3:]))
    code, body = plant.transport.get(plant.status_api, {"limit": 1})
    if code == 200 and isinstance(body, dict) and "store" in body:
        store, times = body["store"], body.get("response_times", {})
        print("live store: %d incident(s), %d open, %d overdue, by status %s, median ack %s min, transitions %d"
              % (store["total_incidents"], store["open_incidents"], store["overdue_incidents"],
                 json.dumps(store["incidents_by_status"]), times.get("median_minutes_to_acknowledge"),
                 body.get("transitions", {}).get("total_transitions", 0)))
    else:
        print("live store: status API answered %s" % code)
    return 0


RESET_FILES = ["incidents", "incident_transitions", "escalations", "incident_notifications", "intake_outcomes"]


def reset_script(stamp):
    """Archive the store inside the n8n container and start it empty.

    Only files that exist are moved and re-created, and nothing is deleted: the
    archive keeps every line under /data/arkon/_archive/<stamp>/. `touch` runs as
    the container user, which is what the append node needs (it cannot create a
    file, README trap 3).
    """
    lines = ["set -e", "d=/data/arkon/_archive/%s" % stamp, 'mkdir -p "$d"']
    for name in RESET_FILES:
        lines.append('if [ -f /data/arkon/%s.jsonl ]; then mv /data/arkon/%s.jsonl "$d/%s.jsonl"; '
                     'touch /data/arkon/%s.jsonl; fi' % (name, name, name, name))
    lines.append('echo archived to "$d":; ls -l "$d"; echo live:; ls -l /data/arkon/*.jsonl')
    return "\n".join(lines)


def cmd_reset(plant, args):
    stamp = plant.clock().strftime("%Y-%m-%dT%H%M%SZ")
    script = reset_script(stamp)
    host = args.host or os.environ.get("ARKON_NAS_SSH")
    remote = "docker exec n8n sh -c " + shlex.quote(script)
    print("reset plan (archive, never delete):\n")
    print("  ssh %s %s\n" % (host or "<user>@<nas>", shlex.quote(remote)))
    print("  then the intake counters keep counting (ids continue), the emitter keeps its\n"
          "  %d h dedup memory, and run %d becomes run %d.\n"
          % (DEDUP_HOURS, plant.ledger.state["run_id"], plant.ledger.state["run_id"] + 1))
    if not args.execute:
        print("printed only. Add --execute (and --host or ARKON_NAS_SSH) to run it.")
        return 0
    if not host:
        sys.exit("--execute needs --host user@nas or ARKON_NAS_SSH in the environment")
    result = subprocess.run(["ssh", "-o", "BatchMode=yes", host, remote], capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        sys.exit("reset failed with exit code %d; the store was not verified" % result.returncode)
    code, body = plant.transport.get(plant.status_api, {"limit": 1})
    store = body.get("store", {}) if isinstance(body, dict) else {}
    if code != 200 or store.get("total_incidents") != 0:
        sys.exit("archive ran but the status API still reports %s incident(s) (HTTP %s)"
                 % (store.get("total_incidents"), code))
    state = plant.ledger.state
    state["resets"].append({"at": stamp, "archive": "/data/arkon/_archive/%s" % stamp,
                            "closed_run": state["run_id"]})
    state["run_id"] += 1
    state["cursor"] = 0
    plant.ledger.save_state()
    print("store empty per the status API; emitter now on run %d" % state["run_id"])
    return 0


def build(args):
    ledger = Ledger(args.state_dir)
    rng = random.Random(args.seed)
    return Plant(ledger, load_pools(args.include_p4), HttpTransport(), rng,
                 max_alerts_per_hour=args.max_alerts_per_hour,
                 max_transitions_per_tick=args.max_transitions_per_tick,
                 crew_all=args.crew_all,
                 event_api=args.event_api, status_api=args.status_api, transition_api=args.transition_api)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["tick", "run", "status", "reset"])
    parser.add_argument("--state-dir", default=str(STATE_DIR), help="ledger directory (default %s)" % STATE_DIR)
    parser.add_argument("--seed", type=int, default=None, help="fix the random draw, for a reproducible demo")
    parser.add_argument("--interval", type=float, default=600, help="seconds between ticks (run)")
    parser.add_argument("--jitter", type=float, default=0.2, help="fraction of the interval to vary by (run)")
    parser.add_argument("--ticks", type=int, default=0, help="stop after N ticks (run); 0 = until stopped")
    parser.add_argument("--max-alerts-per-hour", type=int, default=6,
                        help="cap on P1/P2 events per hour, each of which is a real Telegram card")
    parser.add_argument("--max-transitions-per-tick", type=int, default=3)
    parser.add_argument("--include-p4", action="store_true",
                        help="draw P4 too (only CMAPSS publishes any; recorded, no alert)")
    parser.add_argument("--no-crew", action="store_true", help="raise incidents only, move nothing")
    parser.add_argument("--crew-all", action="store_true",
                        help="let the crew move incidents this emitter did not raise (the legacy backlog)")
    parser.add_argument("--dry-run", action="store_true", help="tick: build and print the event, send nothing")
    parser.add_argument("--execute", action="store_true", help="reset: run the archive over SSH")
    parser.add_argument("--host", default=None, help="reset: user@nas for SSH (or ARKON_NAS_SSH)")
    parser.add_argument("--event-api", default=EVENT_API)
    parser.add_argument("--status-api", default=STATUS_API)
    parser.add_argument("--transition-api", default=TRANSITION_API)
    args = parser.parse_args()

    plant = build(args)
    if args.command == "tick":
        plant.tick(dry_run=args.dry_run, crew=not args.no_crew)
        return 0
    if args.command == "run":
        return cmd_run(plant, args)
    if args.command == "status":
        return cmd_status(plant, args)
    return cmd_reset(plant, args)


if __name__ == "__main__":
    sys.exit(main())
