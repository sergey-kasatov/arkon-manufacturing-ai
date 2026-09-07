"""Judge a live briefing's OPEN, OVERDUE and WATCH blocks against an independent computation.

DEFECT-9 was an ORDER defect: the five fields of every OVERDUE line were right in every
measured run and the lines still came out in a different sequence from one run to the
next. A checker that only counts lines cannot see that, so this one computes the three
blocks itself, from the status API, and compares line by line and in order.

Every run is bracketed: the status API is read immediately before and immediately after
the briefing, and the printed block passes when it equals the expectation from either
snapshot (the plant moves every few minutes, so the two can differ; a block that equals
neither is a real disagreement). The verdict per block:

    EXACT   the printed lines equal the expected lines, in order
    ORDER   the same lines, in a different order (the DEFECT-9 shape)
    FIELDS  different lines altogether

The rules are the ones `briefing_v2` states in prose and `arkon_briefing_assemble.py`
renders; they are implemented here a second time, from the API body, so the check is
not the component reading its own output.

    python langflow/build/check_briefing_blocks.py --runs 5
    python langflow/build/check_briefing_blocks.py --runs 3 --label before --out before.json
"""

import argparse
import json
import subprocess
import time
import urllib.request
from datetime import datetime

API = "http://AK2101:5678/webhook/arkon-incident-status?limit=500"
HOST = "ResSak@AK2101"
REMOTE = "cd ~/arkon-tmp && python3 lf_api.py"
ENDPOINT = "arkon-shift-briefing"
OPEN_STATUSES = ("new", "acknowledged", "in_containment")
CLOSING = "Operational context is simulated."


def probe():
    return json.loads(urllib.request.urlopen(API, timeout=45).read())


def num(value):
    return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)


def field(value):
    return "none" if value is None or (isinstance(value, str) and not value.strip()) else str(value).strip()


def expected(body):
    incidents = [i for i in body.get("incidents", []) if isinstance(i, dict)]
    counts = {}
    for item in incidents:
        if item.get("status") in OPEN_STATUSES:
            counts[item.get("priority") or "unset"] = counts.get(item.get("priority") or "unset", 0) + 1
    open_line = "%d open incidents (%s)" % (
        sum(counts.values()), ", ".join("%s: %d" % (k, counts[k]) for k in sorted(counts)) or "none by priority")

    overdue = sorted(
        [i for i in incidents if i.get("overdue")],
        key=lambda i: (-(i.get("age_minutes") if isinstance(i.get("age_minutes"), (int, float)) else 0), str(i.get("incident_id") or "")),
    )
    overdue_lines = [
        ", ".join([field(i.get("incident_id")), field(i.get("priority")), field(i.get("unit")),
                   num(i["age_minutes"]) if isinstance(i.get("age_minutes"), (int, float)) else "none",
                   field(i.get("assigned_to"))])
        for i in overdue
    ] or ["none"]

    watch = []
    for i in incidents:
        due, age = i.get("acknowledge_due_minutes"), i.get("age_minutes")
        if i.get("status") == "new" and not i.get("overdue") and isinstance(due, (int, float)) and isinstance(age, (int, float)):
            watch.append((due - age, str(i.get("incident_id") or ""), field(i.get("priority"))))
    watch.sort(key=lambda row: (row[0], row[1]))
    watch_lines = ["%s, %s, %s" % (row[1], row[2], num(row[0])) for row in watch[:3]] or ["none"]
    return {"open": open_line, "overdue": overdue_lines, "watch": watch_lines}


def parse(text):
    """Split a briefing into its blocks; tolerant of anything printed around it."""
    blocks, current = {"open": [], "overdue": [], "watch": [], "note": []}, None
    closing = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line == CLOSING:
            closing = True
            current = None
            continue
        for name in ("OPEN", "OVERDUE", "WATCH", "NOTE"):
            if line.upper().startswith(name + ":"):
                current = name.lower()
                line = line[len(name) + 1:].strip()
                break
        if current and line:
            blocks[current].append(line)
    return {
        "open": " ".join(blocks["open"]),
        "overdue": blocks["overdue"] or ["none"],
        "watch": blocks["watch"] or ["none"],
        "note": blocks["note"],
        "closing": closing,
    }


def split(line):
    return [part.strip() for part in line.split(",")]


def verdict(got, want_a, want_b, minute_field):
    """EXACT when every line matches in order, with the minute field allowed to sit anywhere
    between the two snapshots (age grows and remaining shrinks by the minute, and the flow's
    own API call lands somewhere between the brackets); ORDER when the same ids appear in a
    different sequence; FIELDS otherwise."""
    if got == want_a or got == want_b:
        return "EXACT"
    rows_a, rows_b = [split(l) for l in want_a], [split(l) for l in want_b]
    rows_g = [split(l) for l in got]
    if len(rows_g) == len(rows_a) == len(rows_b):
        exact = True
        for g, a, b in zip(rows_g, rows_a, rows_b):
            if len(g) != len(a) or [x for i, x in enumerate(g) if i != minute_field] != [x for i, x in enumerate(a) if i != minute_field]:
                exact = False
                break
            try:
                lo, hi = sorted((float(a[minute_field]), float(b[minute_field])))
                if not lo <= float(g[minute_field]) <= hi:
                    exact = False
                    break
            except ValueError:
                exact = False
                break
        if exact:
            return "EXACT"
    ids = lambda rows: sorted(r[0] for r in rows)
    if ids(rows_g) == ids(rows_a) or ids(rows_g) == ids(rows_b):
        return "ORDER"
    return "FIELDS"


def run(session, message):
    quoted = message.replace("'", "'\\''")
    started = time.time()
    result = subprocess.run(
        ["ssh", HOST, "%s run %s '%s' %s" % (REMOTE, ENDPOINT, quoted, session)], capture_output=True)
    return time.time() - started, result.stdout.decode("utf-8", "replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--label", default="check")
    ap.add_argument("--message", default="Give me the shift briefing.")
    ap.add_argument("--out", default=None, help="write every run's text and verdicts as JSON")
    args = ap.parse_args()

    records, failures = [], 0
    for index in range(1, args.runs + 1):
        session = "%s-%s-%d" % (args.label, datetime.now().strftime("%H%M%S"), index)
        before = probe()
        stamp = datetime.now().strftime("%H:%M:%S")
        elapsed, text = run(session, args.message)
        after = probe()
        exp_a, exp_b = expected(before), expected(after)
        got = parse(text)
        moved = "store moved between the brackets" if exp_a != exp_b else "store unchanged between the brackets"
        v = {
            "open": "EXACT" if got["open"] in (exp_a["open"], exp_b["open"]) else "FIELDS",
            "overdue": verdict(got["overdue"], exp_a["overdue"], exp_b["overdue"], minute_field=3),
            "watch": verdict(got["watch"], exp_a["watch"], exp_b["watch"], minute_field=2),
            "note_lines": len(got["note"]),
            "closing": got["closing"],
        }
        ok = v["open"] == "EXACT" and v["overdue"] == "EXACT" and v["watch"] == "EXACT" and v["note_lines"] == 1 and v["closing"]
        failures += 0 if ok else 1
        print("=== run %d  %s  %s  %.1f s  %s ===" % (index, session, stamp, elapsed, moved))
        print("  OPEN %-6s OVERDUE %-6s (%d lines)  WATCH %-6s (%d lines)  NOTE %d line(s)  closing %s  -> %s"
              % (v["open"], v["overdue"], len(got["overdue"]), v["watch"], len(got["watch"]), v["note_lines"], v["closing"], "PASS" if ok else "FAIL"))
        if v["overdue"] != "EXACT":
            print("  expected OVERDUE (before):", exp_a["overdue"][:4], "...")
            print("  printed  OVERDUE         :", got["overdue"][:4], "...")
        if v["watch"] != "EXACT":
            print("  expected WATCH:", exp_a["watch"], "| printed:", got["watch"])
        print("  NOTE:", " | ".join(got["note"])[:300])
        records.append({"run": index, "session": session, "started": stamp, "seconds": round(elapsed, 1),
                        "verdict": v, "text": text, "expected_before": exp_a, "expected_after": exp_b})

    print("\n%d run(s), %d failed" % (args.runs, failures))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(records, handle, indent=1, ensure_ascii=False)
        print("written", args.out)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
