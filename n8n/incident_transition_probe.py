"""Contract test for the Arkon Incident Transition API, the lifecycle write path.

Same discipline as `escalation_probe.py`: every case here must NOT reach the
store. The endpoint appends a transition and consumes an id, so a suite that
exercised the success path would move a real incident along its lifecycle every
time it ran, and a test that changes the thing it measures is not worth keeping.
The success path belongs to an operator, and to the demo of charter section 9.

One case does need a real incident, and it is the case this endpoint exists for:
a transition the lifecycle does not allow from where the incident actually is.
The probe finds its own subject rather than naming one - it asks the status API
for an incident that is still `new` and then requests `closed`, which the machine
refuses from there. That keeps the suite valid as the store fills up, in the same
way the status probe asserts invariants rather than a snapshot.

If the store holds no `new` incident at all, that case is skipped and says so.
Skipping is correct rather than convenient: a store where everything has been
closed is a store this case cannot be run against without writing to it.

Stdlib only.

Usage:
    python n8n/incident_transition_probe.py
    python n8n/incident_transition_probe.py http://AK2101:5678/webhook/arkon-incident-transition
"""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_URL = "http://AK2101:5678/webhook/arkon-incident-transition"
STATUS_URL = "http://AK2101:5678/webhook/arkon-incident-status"

# An id far outside the range the demo store uses. Every case that would
# otherwise be valid points at this, so a passing suite writes nothing even if
# the endpoint were to lose its existence check.
ABSENT_INCIDENT = "ARK-INC-00099"


def call(base, params):
    """POST the parameters as a query string, the way the agent's tool would."""
    url = base + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, data=b"", method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        raw = err.read().decode("utf-8", errors="replace")
        try:
            return err.code, json.loads(raw)
        except json.JSONDecodeError:
            return err.code, {"raw": raw[:200]}


def find_new_incident(status_url):
    """Ask the status API for an incident that is still new, or None."""
    url = status_url + "?" + urllib.parse.urlencode({"status": "new", "limit": 1})
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError):
        return None
    incidents = body.get("incidents") or []
    return incidents[0]["incident_id"] if incidents else None


VALID = {
    "incident_id": ABSENT_INCIDENT,
    "to_status": "acknowledged",
    "actor": "transition-probe",
    "note": "contract probe, never intended to be recorded",
}


def case(name, params, expect_code, expect_status, must_contain=None):
    return (name, params, expect_code, expect_status, must_contain)


def build_cases(new_incident):
    cases = [
        # The designed failure path, in all three spellings.
        case("simulated failure", dict(VALID, simulate_failure="1"), 503, "unavailable",
             "simulated failure requested by the caller"),
        case("simulated failure, true", dict(VALID, simulate_failure="true"), 503, "unavailable", None),
        case("simulated failure, yes", dict(VALID, simulate_failure="yes"), 503, "unavailable", None),
        case("simulate off is not on", dict(VALID, simulate_failure="0"), 404, "rejected", None),
        case("simulate absent is off", VALID, 404, "rejected", None),

        # Validation runs first, so a malformed request cannot ride the simulated
        # failure past the contract and cannot consume a transition id either.
        case("validation beats simulate", dict(VALID, to_status="banana", simulate_failure="1"),
             400, "rejected", "to_status must be one of"),
        case("incident_id missing", {k: v for k, v in VALID.items() if k != "incident_id"},
             400, "rejected", "incident_id is required"),
        case("incident_id malformed", dict(VALID, incident_id="engine 92"), 400, "rejected",
             "must look like ARK-INC-00014"),
        case("to_status missing", {k: v for k, v in VALID.items() if k != "to_status"},
             400, "rejected", "to_status is required"),
        case("to_status unknown", dict(VALID, to_status="quarantined"), 400, "rejected",
             "to_status must be one of"),

        # new is refused with its own reason rather than the generic list: it is
        # the intake state, and a caller asking for it has misread the endpoint.
        case("to_status new is refused", dict(VALID, to_status="new"), 400, "rejected",
             "written by the Steering Cell"),

        case("note too long", dict(VALID, note="x" * 501), 400, "rejected", "at most 500 characters"),

        # A plain number and a short id both normalise to the padded form, and
        # the refusal names the normalised id back.
        case("plain number normalises", dict(VALID, incident_id="99"), 404, "rejected", ABSENT_INCIDENT),
        case("short id normalises", dict(VALID, incident_id="ARK-INC-99"), 404, "rejected", ABSENT_INCIDENT),

        # A transition against an incident that is not in the store is refused.
        case("unknown incident", VALID, 404, "rejected", "no transition was recorded"),
    ]

    if new_incident:
        # 409 rather than 400: the request is well formed and the incident is
        # real, but the lifecycle does not allow this jump from where it is. A
        # caller has to be able to tell "you asked wrong" from "you are too late".
        cases.append(
            case("illegal jump from new", dict(VALID, incident_id=new_incident, to_status="closed"),
                 409, "rejected", "the lifecycle allows only")
        )
        cases.append(
            case("and the refusal names the state", dict(VALID, incident_id=new_incident, to_status="resolved"),
                 409, "rejected", "is new")
        )
    return cases


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    status_url = sys.argv[2] if len(sys.argv) > 2 else STATUS_URL

    new_incident = find_new_incident(status_url)
    if new_incident:
        print("subject for the illegal-transition cases: %s (currently new)\n" % new_incident)
    else:
        print("no incident is currently new; the two illegal-transition cases are skipped\n")

    cases = build_cases(new_incident)
    passed = 0

    for name, params, expect_code, expect_status, must_contain in cases:
        code, body = call(base, params)
        text = json.dumps(body)
        problems = []
        if code != expect_code:
            problems.append("HTTP %s, expected %s" % (code, expect_code))
        if body.get("status") != expect_status:
            problems.append("status %r, expected %r" % (body.get("status"), expect_status))
        if must_contain and must_contain not in text:
            problems.append("answer does not mention %r" % must_contain)
        # No case in this suite may ever record anything.
        if "transition_id" in text:
            problems.append("THE STORE WAS WRITTEN: " + text[:160])

        if problems:
            print("FAIL  %-30s %s" % (name, "; ".join(problems)))
        else:
            passed += 1
            message = body.get("message") or "; ".join(body.get("errors", []))
            print("PASS  %-30s HTTP %s  %s" % (name, code, message[:74]))

    print("\n%d/%d passed" % (passed, len(cases)))
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
