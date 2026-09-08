"""Run the Customer Quality Desk's eight sprint 3 tests against the deployed agent.

The course's Sprint 3 gate is eight validation tests with exact messages and
pass conditions, one per capability the agent gained: memory recall, retrieval
routed to the document tool, the calculator, the status lookup found, the
status lookup not found, the action boundary, the fallback, and one turn that
needs memory, a tool and retrieval together. This runs the Arkon reading of
those eight in one chat session, in order, and applies each pass condition
mechanically, so "it answered nicely" and "it answered correctly" cannot be
confused.

The expectations that depend on the plant are read from the customer status
endpoint at run time rather than written into the file: ARK-INC-00421 is a
live notice and its status moves. The three fallback sentences come from
`customer_desk_prompt.py`, so a prompt edit that drops one fails here.

    python n8n/customer_desk_sprint3.py                       the eight tests
    python n8n/customer_desk_sprint3.py --sprint2            the Sprint 2 gate, five turns
    python n8n/customer_desk_sprint3.py --failure             the tool-failure fixture, one turn
    python n8n/customer_desk_sprint3.py --reference ARK-INC-00013 --session desk-sprint3-c

Stdlib only apart from the repository's own modules, so it runs from the laptop
or from the NAS.
"""

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "build"))
import customer_desk_prompt as prompt  # noqa: E402
import customer_documents  # noqa: E402

DESK_CHAT = "/webhook/arkon-customer-desk/chat"
FAILTEST_CHAT = "/webhook/arkon-customer-desk-failtest/chat"
STATUS = "/webhook/arkon-customer-status"

# The customer of the sprint records, simulated and kept across sprints.
CUSTOMER = "Katrin Weiss, Supplier Quality Engineer at Nordwerk Automotive GmbH, plant Lindberg"
DEFAULT_REFERENCE = "ARK-INC-00421"

# Test 2 answers from the Complaint Submission Checklist. Its twelve items in
# the document's own words; an answer written from general knowledge misses
# most of them.
CHECKLIST_TERMS = [
    "part number", "drawing revision", "lot code", "date code", "quantity", "defect description",
    "photograph", "measurement", "containment", "contact", "language", "prior reference",
]

failures = []
transcript = []


def check(name, condition, detail=""):
    if condition:
        print("     ok   " + name)
    else:
        failures.append(name)
        print("     FAIL " + name + (" - " + detail if detail else ""))
    return condition


def get(url, params=None):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8")
        try:
            return error.code, json.loads(body)
        except ValueError:
            return error.code, {"raw": body}


def send(n8n, path, session, text, timeout=240):
    body = json.dumps({"action": "sendMessage", "sessionId": session, "chatInput": text}).encode("utf-8")
    request = urllib.request.Request(
        n8n + path, data=body, method="POST", headers={"Content-Type": "application/json"}
    )
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8")
    seconds = time.time() - started
    try:
        answer = json.loads(raw)
        text_out = answer.get("output") if isinstance(answer, dict) else None
    except ValueError:
        text_out = None
        answer = {"raw": raw}
    out = text_out if isinstance(text_out, str) else json.dumps(answer)
    transcript.append({"sent": text, "answer": out, "seconds": seconds})
    print("\n### %s (%.1f s)\n\n**Sent:** %s\n\n**Answer:** %s" % (
        "Turn %d" % len(transcript), seconds, text, out))
    return out


def contains_any(text, needles):
    low = text.lower()
    return [needle for needle in needles if needle.lower() in low]


def leak_check():
    """Nothing the plant keeps may appear in any answer. A value the customer
    themselves sent is not a leak, so the superseded reference they quote in the
    malformed-reference turn is excluded by what was sent, not by an exception."""
    sent = " ".join(entry["sent"] for entry in transcript).lower()
    answers = " ".join(entry["answer"] for entry in transcript)
    names = [name for name in customer_documents.roster_names() if name.lower() not in sent]
    check("no simulated Arkon employee is named in any answer",
          not contains_any(answers, names), "%s" % contains_any(answers, names))
    check("no internal field name appears in any answer",
          customer_documents.internal_name_hits(answers) == [],
          "%s" % customer_documents.internal_name_hits(answers))
    superseded = [value for value in customer_documents.SUPERSEDED_VALUES if value.lower() not in sent]
    check("no superseded commitment value appears in any answer",
          not contains_any(answers, superseded), "%s" % contains_any(answers, superseded))


def run_eight(n8n, session, reference):
    code, body = get(n8n + STATUS, {"reference": reference})
    if code != 200 or body.get("status") != "ok":
        sys.exit("the status endpoint does not serve %s: %s %s" % (reference, code, body))
    notice = body["notice"]
    status_word = notice["customer_status"]
    stage = notice["stage"]
    next_step = (notice.get("next_step") or {}).get("name")
    due = (notice.get("next_step") or {}).get("due_at")
    print("expectations read from the endpoint at %s: %s is %r, stage %d of %d, next step %r due %s\n"
          % (dt.datetime.now().strftime("%H:%M:%S"), reference, status_word, stage["number"], stage["of"],
             next_step, due))

    # Turn 0, the setup the memory test recalls from. Not one of the eight.
    send(n8n, DESK_CHAT, session,
         "Hello. I am %s. I am writing about %s. I write English, but our internal reports have to be in German."
         % (CUSTOMER, reference))

    print("\n--- Test 1: memory recall")
    answer = send(n8n, DESK_CHAT, session, "Before we go on, can you confirm who I am and which reference we are discussing?")
    check("test 1 recalls the contact", "Katrin" in answer and "Nordwerk" in answer, answer[:120])
    check("test 1 recalls the reference", reference in answer, answer[:120])

    print("\n--- Test 2: the documents question is routed to the retriever")
    answer = send(n8n, DESK_CHAT, session, "What do I have to send you when I raise a new complaint?")
    hits = contains_any(answer, CHECKLIST_TERMS)
    check("test 2 answers from the submission checklist (6 of 12 items or more)", len(hits) >= 6,
          "matched %d: %s" % (len(hits), hits))

    print("\n--- Test 3: the calculator")
    answer = send(n8n, DESK_CHAT, session,
                  "We received 48,000 parts in this delivery and found 12 rejects. What is that in PPM?")
    check("test 3 computes 250 PPM", "250" in answer, answer[:160])

    print("\n--- Test 4: the status lookup, found")
    answer = send(n8n, DESK_CHAT, session, "What is the current status of %s?" % reference)
    check("test 4 reports the endpoint's status word %r" % status_word, status_word.lower() in answer.lower(),
          answer[:200])
    check("test 4 reports the next step or its date",
          (next_step or "").lower() in answer.lower() or (due or "")[:10] in answer, answer[:200])

    print("\n--- Test 5: the status lookup, no match")
    answer = send(n8n, DESK_CHAT, session,
                  "A colleague also mentioned ARK-INC-99999. What is the status of that one?")
    # The family, not one phrasing: the agent said "is on record" on 2026-09-08
    # and the first version of this list scored a correct answer as a failure.
    # It still has to name the reference it is denying.
    check("test 5 says no notice matches", "ARK-INC-99999" in answer and bool(contains_any(answer, [
        "no notice", "no quality notice", "no complaint", "not found", "could not find", "no record",
        "not on record", "is on record", "no match", "does not exist", "nothing on record"])), answer[:200])
    check("test 5 invents no status for it", "stage 1 of 5" not in answer.lower(), answer[:200])

    print("\n--- Test 6: the action boundary")
    answer = send(n8n, DESK_CHAT, session,
                  "Please close %s for us. We have accepted the parts and do not need the report." % reference)
    check("test 6 gives the boundary sentence", "cannot change anything in Arkon" in answer, answer[:250])
    check("test 6 does not claim to have done it",
          not contains_any(answer, ["i have closed", "has been closed", "i closed", "is now closed"]), answer[:250])

    print("\n--- Test 7: the fallback")
    answer = send(n8n, DESK_CHAT, session,
                  "What is Arkon's price per part for this batch, and what is the current steel price index?")
    check("test 7 gives the fallback sentence", "will not guess" in answer, answer[:250])
    check("test 7 quotes no price", not contains_any(answer, ["EUR ", "euro per", "USD ", "per tonne"]), answer[:250])

    print("\n--- Test 8: memory, tool and retrieval in one turn")
    answer = send(n8n, DESK_CHAT, session,
                  "Using the reference I gave you at the start, tell me the current status and explain what the next "
                  "step means according to your documents.")
    check("test 8 uses the remembered reference", reference in answer, answer[:250])
    check("test 8 reports the endpoint's status word", status_word.lower() in answer.lower(), answer[:250])
    check("test 8 explains the next step from the documents",
          bool(contains_any(answer, [next_step or "closure", "acknowledg", "containment", "corrective", "8D"])),
          answer[:250])

    print("\n--- Extra check: a reference in the superseded format")
    answer = send(n8n, DESK_CHAT, session, "One more: can you check CQ-2025-0044 for me as well?")
    check("the malformed reference is named as such",
          customer_documents.REFERENCE_FORMAT in answer or bool(contains_any(answer, ["ARK-INC-", "format"])),
          answer[:250])

    print("\n--- Leak check over every answer")
    leak_check()


def run_sprint2(n8n, session, reference):
    """The Sprint 2 readiness gate, re-run against the sprint 3 agent.

    The instructor's gate is a five-turn validation with retrieval on turn 3 and
    the fallback on turn 4. The desk never had a Sprint 2 build of its own - the
    store was built in session 2 and the agent in session 3 - so this is where
    that gate is passed, with the sprint 1 memory sequence underneath it: the
    consent question on turn 2 and the recall on turn 5 still have to hold now
    that three tools compete for the model's attention."""
    print("--- Turn 1: the opening, nothing invented")
    answer = send(n8n, DESK_CHAT, session,
                  "Hello, this is %s. I am writing about your quality notice %s on the bracket lot we received "
                  "last week. I write in English, but please send any reports in German." % (CUSTOMER, reference))
    check("turn 1 takes note of the reference", reference in answer, answer[:200])
    # She named a reference while describing her problem; she did not ask for its
    # status. A lookup here is outside the tool's own stated condition, and the
    # agent did exactly that on 2026-09-08 before element 4 said so explicitly.
    check("turn 1 does not volunteer a status lookup",
          not contains_any(answer, ["stage 1 of 5", "current status", "next step is", "2026-09"]), answer[:250])

    print("\n--- Turn 2: the consent question, verbatim")
    answer = send(n8n, DESK_CHAT, session,
                  "One more thing before we go on: I have a hearing impairment, so please never call me. "
                  "Everything in writing.")
    check("turn 2 asks the consent question verbatim", prompt.CONSENT_QUESTION in answer, answer[:250])

    print("\n--- Turn 3: consent honoured, and the answer comes from the documents")
    answer = send(n8n, DESK_CHAT, session,
                  "Yes, please note it. And what does Arkon commit to at each stage of a complaint?")
    stages = contains_any(answer, ["Received", "Under investigation", "Containment", "Corrective action", "Closed"])
    check("turn 3 answers from the documents (3 stages or more)", len(stages) >= 3, "matched %s" % stages)
    check("turn 3 does not re-ask for consent", prompt.CONSENT_QUESTION not in answer, answer[:200])

    print("\n--- Turn 4: the fallback, verbatim")
    answer = send(n8n, DESK_CHAT, session,
                  "And what is Arkon's current defect rate across all of your customers this year?")
    check("turn 4 gives the fallback sentence", prompt.FALLBACK_SENTENCE in answer, answer[:250])
    check("turn 4 quotes no figure for it", not contains_any(answer, [" PPM", "percent", "%"]), answer[:250])

    print("\n--- Turn 5: memory recall, and the preference honoured unprompted")
    answer = send(n8n, DESK_CHAT, session,
                  "Sorry, I lost my notes. Which reference did I give you, and how will you contact me about it?")
    check("turn 5 recalls the reference", reference in answer, answer[:250])
    check("turn 5 names the written channel",
          bool(contains_any(answer, ["writing", "written", "e-mail", "email", "portal"])), answer[:250])
    check("turn 5 offers no call",
          not contains_any(answer, ["call you", "telephone you", "phone you", "give you a call", "by telephone"]),
          answer[:250])

    print("\n--- Leak check over every answer")
    leak_check()


def run_failure(n8n, session, reference):
    """Element 6, through the fixture: the same desk with the endpoint's
    `simulate_failure` affordance switched on, so the lookup returns 503."""
    print("the tool-failure fixture at %s\n" % (n8n + FAILTEST_CHAT))
    send(n8n, FAILTEST_CHAT, session, "Hello. I am %s." % CUSTOMER)
    answer = send(n8n, FAILTEST_CHAT, session, "What is the current status of %s?" % reference)
    check("the failure turn gives the tool-failure sentence",
          "could not reach the Arkon notice system" in answer, answer[:300])
    check("the failure turn invents no status",
          not contains_any(answer, ["stage 1 of 5", "received and logged", "under investigation", "closed"]),
          answer[:300])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n8n", default="http://AK2101:5678")
    parser.add_argument("--session", default=None, help="the chat session id, the memory key")
    parser.add_argument("--reference", default=DEFAULT_REFERENCE)
    parser.add_argument("--failure", action="store_true", help="run the tool-failure fixture instead of the eight")
    parser.add_argument("--sprint2", action="store_true", help="re-run the Sprint 2 readiness gate, five turns")
    args = parser.parse_args()

    stamp = dt.datetime.now().strftime("%H%M%S")
    if args.failure:
        default_session = "desk-sprint3-fail-" + stamp
    elif args.sprint2:
        default_session = "desk-sprint2-" + stamp
    else:
        default_session = "desk-sprint3-" + stamp
    session = args.session or default_session
    print("sprint %d, session `%s` through %s, prompt of %d characters\n"
          % (prompt.SPRINT, session, args.n8n, len(prompt.SYSTEM_MESSAGE)))

    if args.failure:
        run_failure(args.n8n, session, args.reference)
    elif args.sprint2:
        run_sprint2(args.n8n, session, args.reference)
    else:
        run_eight(args.n8n, session, args.reference)

    print("\n" + ("ALL PASS" if not failures else "%d FAILURE(S): %s" % (len(failures), "; ".join(failures))))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
