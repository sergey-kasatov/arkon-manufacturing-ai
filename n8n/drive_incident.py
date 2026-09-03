"""Walk one incident along its lifecycle, printing what each step answered.

This is the demo tool for the complete incident path of charter section 9, the
counterpart of `replay_events.py` on the read-write side: that script raises
incidents, this one moves them. It is not a test. Every step it takes is a real
write that consumes a transition id and cannot be undone, which is exactly why
the contract suite in `incident_transition_probe.py` avoids the success path and
this file exists separately.

An incident can only be driven to a terminal state once. To rehearse the demo a
second time, raise a fresh incident first:

    python n8n/replay_events.py http://AK2101:5678/webhook/arkon-event \
        events/out/cmapss_events_full_fleet.jsonl --priority P3 --limit 1

Stdlib only.

Usage:
    python n8n/drive_incident.py ARK-INC-00013
    python n8n/drive_incident.py ARK-INC-00016 false_positive --actor "S. Kasatov"
    python n8n/drive_incident.py 13 acknowledged in_containment --dry-run
    python n8n/drive_incident.py ARK-INC-00021 --delay 45
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

TRANSITION_URL = "http://AK2101:5678/webhook/arkon-incident-transition"
STATUS_URL = "http://AK2101:5678/webhook/arkon-incident-status"

# The full path of charter 7.2, which is what the Phase 4 criterion asks for.
FULL_PATH = ["acknowledged", "in_containment", "resolved", "closed"]

# One note per state, so the transition log reads as an operator's account rather
# than as a sequence of status words. Overridden by --note.
NOTES = {
    "acknowledged": "picked up by the assigned planner",
    "in_containment": "unit pulled from the schedule pending inspection",
    "resolved": "inspection completed, part replaced",
    "closed": "reviewed and closed",
    "false_positive": "no defect found on inspection, kept for threshold tuning",
}


def post(url, params):
    request = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), data=b"", method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        raw = err.read().decode("utf-8", errors="replace")
        try:
            return err.code, json.loads(raw)
        except json.JSONDecodeError:
            return err.code, {"raw": raw[:300]}


def show_status(status_url, incident_id):
    url = status_url + "?" + urllib.parse.urlencode({"incident_id": incident_id, "limit": 1})
    with urllib.request.urlopen(url, timeout=30) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not body.get("incidents"):
        print("  the status API returns no such incident")
        return
    incident = body["incidents"][0]
    life = incident["lifecycle"]
    print("  status            %s (raised as %s, %d transition(s))"
          % (incident["status"], incident["raised_as"], life["transition_count"]))
    print("  minutes to ack    %s   (window %s, overdue now: %s)"
          % (life["minutes_to_acknowledge"], incident["acknowledge_due_minutes"], incident["overdue"]))
    print("  minutes to resolve %s" % life["minutes_to_resolve"])
    print("  minutes to close  %s" % life["minutes_to_close"])
    for step in life["history"]:
        print("    %s  %-14s -> %-14s  %s  %s"
              % (step["recorded_at"], step["from_status"], step["to_status"], step["actor"], step["note"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("incident_id", help="ARK-INC-00013, or a plain number")
    parser.add_argument("states", nargs="*", default=None,
                        help="lifecycle states to enter, in order (default: the full path to closed)")
    parser.add_argument("--actor", default="M. Brandt", help="who is making the transition")
    parser.add_argument("--note", default=None, help="one note for every step, instead of the per-state defaults")
    parser.add_argument("--url", default=TRANSITION_URL)
    parser.add_argument("--status-url", default=STATUS_URL)
    # Without a pause the four steps land inside one second and every KPI comes
    # out equal, which is true and reads as broken. A demo should space them.
    parser.add_argument("--delay", type=float, default=0.0,
                        help="seconds to wait between steps, so the timestamps differ")
    parser.add_argument("--dry-run", action="store_true", help="print the calls and write nothing")
    args = parser.parse_args()

    states = args.states or FULL_PATH
    print("incident %s, driving: %s" % (args.incident_id, " -> ".join(states)))
    print("before:")
    show_status(args.status_url, args.incident_id)
    print()

    if args.dry_run:
        for state in states:
            print("  would POST to_status=%s actor=%r note=%r"
                  % (state, args.actor, args.note or NOTES.get(state, "")))
        print("\ndry run, nothing written")
        return 0

    failed = 0
    for index, state in enumerate(states):
        if index and args.delay:
            time.sleep(args.delay)
        params = {
            "incident_id": args.incident_id,
            "to_status": state,
            "actor": args.actor,
            "note": args.note or NOTES.get(state, ""),
        }
        code, body = post(args.url, params)
        if code == 200 and body.get("status") == "transition_recorded":
            print("  %-14s HTTP %s  %s  %s -> %s after %s min%s"
                  % (state, code, body["transition_id"], body["from_status"], body["to_status"],
                     body["minutes_since_created"],
                     "" if body["acknowledged_within_window"] is None
                     else ("  within window" if body["acknowledged_within_window"] else "  OUTSIDE the window")))
        else:
            failed += 1
            print("  %-14s HTTP %s  %s" % (state, code, json.dumps(body)[:220]))
            break

    print("\nafter:")
    show_status(args.status_url, args.incident_id)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
