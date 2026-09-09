"""Re-validate all six routes in one session, with a wall-clock time on every turn.

The presentation quotes what the assistant does and how long an operator waits
for it. Both numbers go stale: the plant moves every few minutes and the model
gateway's latency is not a constant. So this runs the whole demo sequence in one
session on the day of the talk and prints the timings beside the answers.

The turns are the six demo prompts plus the memory follow-up and the
refusal-with-the-capability-present reserve, in demo order, so the run doubles
as a rehearsal. Since 2026-09-09 it also carries the five identity turns of
DEFECT-11 and DEFECT-12, which only mean anything with the operator line the
cockpit prepends, so they type it.

    python langflow/build/revalidate_routes.py --incident ARK-INC-00014

`--baseline` measures the ssh round trip on its own first, so the reported turn
times can be read as the flow's time plus a known constant rather than as the
flow's time.
"""

import argparse
import json
import pathlib
import subprocess
import time

HOST = "ResSak@AK2101"
FLOW = "Arkon Quality Assistant"
# What the cockpit's You-are selector prepends to a question. Typed here so the
# identity turns can be run from the command line at all.
OPERATOR_LINE = "[operator: A. Novak, QC Engineer]"


def ssh(command):
    return subprocess.run(["ssh", HOST, command], capture_output=True)


def baseline(samples=3):
    times = []
    for _ in range(samples):
        started = time.time()
        ssh("true")
        times.append(time.time() - started)
    return sum(times) / len(times)


def turn(message, session, decision=None):
    quoted = message.replace("'", "'\\''")
    command = "cd ~/arkon-tmp && python3 lf_v2.py run '%s' '%s' %s" % (FLOW, quoted, session)
    if decision:
        command += " %s" % decision
    started = time.time()
    result = ssh(command)
    elapsed = time.time() - started
    return elapsed, result.stdout.decode("utf-8", "replace").strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--incident", default="ARK-INC-00014", help="an open incident id, read from the cockpit on the day")
    parser.add_argument("--session", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--baseline", action="store_true")
    args = parser.parse_args()

    session = args.session or "reval-%s" % time.strftime("%H%M%S")
    incident = args.incident

    turns = [
        ("1", "Quality procedure",
         "How accurate is the CMAPSS remaining useful life model, and what makes an incident P1?", None),
        ("1b", "Same session, memory",
         "And how long do I have to acknowledge one of those?", None),
        ("2", "Incident status",
         "What is %s doing right now?" % incident, None),
        ("3", "Shift briefing",
         "Give me the shift briefing.", None),
        ("4", "Escalation, approved",
         "Escalate %s to the Quality Manager, the RUL is still falling." % incident, "Approve"),
        ("4b", "Refusal with the capability present",
         "Escalate %s to the Quality Manager, and acknowledge and close it too." % incident, "Approve"),
        ("5", "Unclear request", "Escalate it.", None),
        ("5b", "Unclear request, operator line set",
         "%s Escalate it." % OPERATOR_LINE, None),
        ("6", "Out of scope", "Where do I submit my vacation request?", None),
        # The identity turns. The cockpit prepends the operator line itself; here
        # it is typed, which is the same string the page sends and the only way to
        # exercise the route from the command line.
        ("7", "Mine, counted", "%s How many issues do I have now?" % OPERATOR_LINE, None),
        ("8", "Mine, ordered", "%s What is my top list to solve?" % OPERATOR_LINE, None),
        ("9", "Who am I", "%s Who am I?" % OPERATOR_LINE, None),
        ("9b", "Mine, with nobody selected", "How many issues do I have now?", None),
    ]

    overhead = None
    if args.baseline:
        overhead = baseline()
        print("ssh round trip, mean of 3: %.2f s\n" % overhead)

    records = []
    print("session %s, incident %s, %s\n" % (session, incident, time.strftime("%Y-%m-%d %H:%M:%S")))
    for number, route, message, decision in turns:
        elapsed, answer = turn(message, session, decision)
        net = "" if overhead is None else "  (flow about %.1f s)" % max(0.0, elapsed - overhead)
        print("=" * 78)
        print("turn %s  %s   %.1f s%s" % (number, route, elapsed, net))
        print("-" * 78)
        print("> %s" % message)
        print(answer)
        print()
        records.append({
            "turn": number, "route": route, "prompt": message,
            "decision": decision, "seconds": round(elapsed, 1), "answer": answer,
        })

    print("=" * 78)
    print("%-5s %-42s %s" % ("turn", "route", "seconds"))
    for record in records:
        print("%-5s %-42s %.1f" % (record["turn"], record["route"], record["seconds"]))

    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps({"session": session, "incident": incident,
                        "ssh_overhead_seconds": overhead, "turns": records}, indent=2),
            encoding="utf-8")
        print("\nwritten to %s" % args.out)


if __name__ == "__main__":
    main()
