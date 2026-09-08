"""Probe the deployed Arkon Customer Status API against the incident status API.

Asserts the endpoint's contract on the live store rather than a snapshot of
it: the four answers keep their codes, a served notice carries exactly the
customer fields, and, for one real reference, every served value agrees with
the internal record the incident status API holds for the same incident,
while none of that record's internal values appears in the customer answer.
Stdlib only, so it runs from the laptop or from the NAS.

    python n8n/customer_status_probe.py http://AK2101:5678/webhook/arkon-customer-status
    python n8n/customer_status_probe.py http://AK2101:5678/webhook/arkon-customer-status --reference ARK-INC-00013
"""

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "build"))
from customer_projection import COMMITMENT_HOURS, CUSTOMER_STAGES, DEFAULT_ACK_HOURS, SERVED_FIELDS  # noqa: E402

failures = 0


def check(name, condition, detail=""):
    global failures
    if condition:
        print("ok   " + name)
    else:
        failures += 1
        print("FAIL " + name + (" - " + detail if detail else ""))


def get(url, params=None):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8")
        try:
            return error.code, json.loads(body)
        except ValueError:
            return error.code, {"raw": body}


def parse_iso(text):
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("customer_url", help="the customer status endpoint")
    parser.add_argument("--internal", default=None,
                        help="the incident status API (default: the same host, arkon-incident-status)")
    parser.add_argument("--reference", default=None, help="a reference to cross-check (default: the newest incident)")
    args = parser.parse_args()
    internal = args.internal or args.customer_url.rsplit("/", 1)[0] + "/arkon-incident-status"

    code, body = get(args.customer_url)
    check("no reference answers 400 rejected", code == 400 and body.get("status") == "rejected", "%s %s" % (code, body))
    code, body = get(args.customer_url, {"reference": "APP-8841"})
    check("a malformed reference answers 400 with the expected form",
          code == 400 and body.get("errors") == ["reference must look like ARK-INC-00348"], "%s %s" % (code, body))
    code, body = get(args.customer_url, {"reference": "ARK-INC-00001", "simulate_failure": "true"})
    check("simulate_failure answers 503 unavailable", code == 503 and body.get("status") == "unavailable", "%s %s" % (code, body))
    code, body = get(args.customer_url, {"reference": "ARK-INC-99999"})
    check("an unknown reference answers 200 no_match with no notice",
          code == 200 and body.get("status") == "no_match" and body.get("notice") is None, "%s %s" % (code, body))

    # The reference to cross-check: given, or the newest incident the internal API serves.
    reference = args.reference
    if reference is None:
        code, newest = get(internal, {"limit": "1"})
        check("the internal API answers", code == 200 and newest.get("incidents"), "%s" % code)
        if not (code == 200 and newest.get("incidents")):
            return finish()
        reference = newest["incidents"][0]["incident_id"]
    code, record = get(internal, {"incident_id": reference})
    check("the internal record of %s is readable" % reference, code == 200 and record.get("match_count") == 1, "%s" % code)
    if not (code == 200 and record.get("match_count") == 1):
        return finish()
    incident = record["incidents"][0]

    # Asked in the lower-case form, so the normalisation is exercised on the live path too.
    code, body = get(args.customer_url, {"reference": reference.lower()})
    check("a known reference answers 200 ok", code == 200 and body.get("status") == "ok", "%s %s" % (code, body))
    notice = body.get("notice") or {}
    check("the notice serves exactly the customer fields", sorted(notice.keys()) == sorted(SERVED_FIELDS),
          "got %s" % sorted(notice.keys()))
    check("the reference and the intake time agree with the record",
          notice.get("reference") == incident["incident_id"] and notice.get("received_at") == incident["created_at"])
    stage = CUSTOMER_STAGES[incident["status"]]
    check("the customer status is the vocabulary's word for %s" % incident["status"],
          notice.get("customer_status") == stage["customer_status"] and notice.get("stage", {}).get("number") == stage["stage"],
          "got %s" % notice.get("customer_status"))

    history = incident["lifecycle"]["history"]
    entered_at = history[-1]["recorded_at"] if history else incident["created_at"]
    check("last_update_at is the last transition, or intake", notice.get("last_update_at") == entered_at,
          "got %s, expected %s" % (notice.get("last_update_at"), entered_at))
    if stage["next_step"] is None:
        check("a closed notice promises no next step", notice.get("next_step") is None and notice.get("closed_at") is not None)
    else:
        window = COMMITMENT_HOURS[incident["status"]]
        hours = window if isinstance(window, float) else window.get(incident["priority"], DEFAULT_ACK_HOURS)
        expected_due = parse_iso(entered_at) + dt.timedelta(hours=hours)
        due = notice.get("next_step", {}).get("due_at")
        check("the commitment date is the stage entry plus the window (%s h)" % hours,
              due is not None and abs((parse_iso(due) - expected_due).total_seconds()) < 1,
              "got %s, expected %s" % (due, expected_due.isoformat()))
        as_of = parse_iso(body["as_of"])
        check("overdue is measured against as_of", notice["next_step"]["overdue"] == (as_of > expected_due))

    # The output restriction: nothing the internal record holds beyond the shared
    # timestamps and the id may appear in the customer answer.
    text = json.dumps(body)
    internal_values = [
        incident.get("assigned_to"), incident.get("escalation_contact"), incident.get("record_id"),
        incident.get("summary"), incident.get("recommended_action"), incident.get("source_module"),
        incident.get("business_domain"), incident.get("event_id"), incident.get("model_version"),
        incident.get("priority"), incident.get("assigned_role"),
    ]
    leaked = [value for value in internal_values if value and str(value) in text]
    check("no internal value of the record appears in the customer answer", not leaked, "leaked %s" % leaked)
    return finish()


def finish():
    print("\nALL PASS" if failures == 0 else "\n%d FAILURE(S)" % failures)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
