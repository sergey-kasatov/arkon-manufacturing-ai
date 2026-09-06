"""Choose the assistant's model by measuring it, not by reading about it.

The assistant's job is to answer from the incident store and from ten documents and
to add nothing. That is a grounding and instruction-following task rather than a
reasoning one, so the property to compare is discipline: does it produce the link
when it should, withhold it when it should not, refuse when the sources do not
settle the question, and above all NOT invent a system, a source or an action that
the record it was handed does not mention.

The last one is not hypothetical. On 2026-09-05 the deployed model, asked about an
NHTSA complaint-rate incident, drafted an operator note reading "cross-reference
with vehicle report telemetry to isolate variance"; that module reads public
complaint narratives and there is no telemetry anywhere near it. The prompt was
tightened, and this battery keeps that exact case as check 1 so a model change is
measured against the failure that motivated it rather than against a benchmark
somebody else ran.

Every check is mechanical, so the comparison has no opinion in it. What it cannot
see is prose quality; read the transcripts it writes for that.

    py langflow/build/compare_models.py --list
    py langflow/build/compare_models.py google/gemini-3.8-flash anthropic/claude-haiku-4.5
    py langflow/build/compare_models.py --set google/gemini-3.8-flash

The canvas is restored to the model it started with unless --keep is given, so an
interrupted comparison does not leave the deployment on a candidate.
"""

import argparse
import datetime
import json
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
FLOW = REPO / "langflow" / "arkon_quality_assistant.json"
HOST = "ResSak@AK2101"
REMOTE = "cd ~/arkon-tmp && python3"

# The five LLM nodes. The router is listed and NOT changed by default: it picks one
# of six branches from a short prompt, which is the one job on this canvas the
# cheapest tier is genuinely sized for, and leaving it alone keeps the comparison
# about the two nodes whose errors reach an operator's permanent record.
SPECIALISTS = ["Procedure Specialist", "Incident Specialist"]
ROUTER = "Intent Router"
ESCALATION = ["Escalation Specialist", "Escalation Declined"]

OUT = REPO / "langflow" / "model_comparison.md"

# Four questions with mechanically checkable answers. `open_id` and `closed_id` are
# filled in at run time from the live store, so the battery cannot go stale against
# a moving plant.
BATTERY = [
    {
        "key": "open incident, link and a grounded note",
        "ask": "what is {open_id} doing right now",
        "checks": [
            ("names the incident", lambda t, c: c["open_id"] in t),
            ("gives the operator link", lambda t, c: "steering_cell?incident=" + c["open_id"] in t),
            ("invents no source", lambda t, c: not re.search(
                r"telemetr|telematic|sensor read|vehicle data|scada|plc\b|dashcam", t, re.I)),
        ],
    },
    {
        "key": "closed incident, no link",
        "ask": "what is the status of {closed_id}",
        "checks": [
            ("names the incident", lambda t, c: c["closed_id"] in t),
            ("says it is closed", lambda t, c: "closed" in t.lower()),
            ("withholds the link", lambda t, c: "steering_cell?incident=" not in t),
        ],
    },
    {
        "key": "procedure, names where it is done",
        "ask": "how does an assignee acknowledge an incident, and where do they do it",
        "checks": [
            ("names the cockpit page", lambda t, c: "steering_cell" in t),
            # Both windows, however the model chooses to write the second one. The
            # first version of this check demanded "60" or "one hour" and marked a
            # correct answer wrong for saying "1 hour", which is the same defect
            # this project keeps meeting from the other side: a checker's verdict is
            # a claim too, and a rule that only matches one wording accuses innocent
            # answers while looking rigorous.
            ("gives the window", lambda t, c: "15" in t and re.search(
                r"\b60\b|\b1 hour|\bone hour|\ban hour", t, re.I) is not None),
            ("does not claim the card has buttons", lambda t, c: not re.search(
                r"button on the (alert )?card|tap (the )?(acknowledge|button) (on|in) telegram", t, re.I)),
        ],
    },
    {
        # Added 2026-09-06 after a smoke test on a question the battery did not
        # cover. "Open" is not a value the status filter takes and the parameter is
        # single-valued, unlike priority; the model discovered that by being
        # rejected four times and narrated every attempt to the operator - "I'm
        # sorry, I made a mistake in the status filter", three more apologies, then
        # a correct answer. The answer was right and the reply told its reader the
        # system was broken. Both halves are checked: the filter has to be got
        # right, and the working out has to stay out of the reply.
        "key": "a filter the API does not take, handled quietly",
        "ask": "which P1 incidents are open right now",
        "checks": [
            ("answers about P1", lambda t, c: "P1" in t),
            ("does not narrate its retries", lambda t, c: not re.search(
                r"i'?m sorry|my apolog|i made a mistake|let me correct|i will try (again|one more)"
                r"|still having trouble|rejecting my", t, re.I)),
            ("stays short", lambda t, c: len(t.strip()) < 2500),
        ],
    },
    {
        "key": "outside the sources, refuses exactly",
        "ask": "what is the recall rate of the casting model on the night shift in building 4",
        "checks": [
            ("uses the exact refusal", lambda t, c:
                "I do not have that in the Arkon sources available to me" in t),
            ("adds nothing after it", lambda t, c: len(t.strip()) < 200),
        ],
    },
]


def ssh(command, **kwargs):
    return subprocess.run(["ssh", HOST, command], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", **kwargs)


def load():
    return json.loads(FLOW.read_text(encoding="utf-8"))


def node(flow, display_name):
    for item in flow["data"]["nodes"]:
        if item["data"]["node"].get("display_name") == display_name:
            return item
    raise SystemExit("no node named %r on the canvas" % display_name)


def current_model(flow, display_name):
    value = node(flow, display_name)["data"]["node"]["template"]["model"]["value"]
    return value[0]["name"] if value else None


def set_model(flow, names, model):
    """Point the named nodes at `model`, keeping the field's shape intact.

    The `options` list in a saved flow holds only whatever was last chosen: the
    component refreshes it from OpenRouter in the browser, so it is a UI
    affordance rather than a gate, and the model id is what actually reaches
    ChatOpenAI. The stored option is rewritten alongside the value so the canvas
    does not open showing a name it is not using.
    """
    for display_name in names:
        field = node(flow, display_name)["data"]["node"]["template"]["model"]
        for entry in field["value"]:
            entry["name"] = model
        for entry in field.get("options") or []:
            if isinstance(entry, dict):
                entry["name"] = model
                meta = entry.get("metadata") or {}
                if "reasoning_models" in meta:
                    meta["reasoning_models"] = [model]


def deploy(flow):
    FLOW.write_text(json.dumps(flow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    push = subprocess.run(["ssh", HOST, "cat > /tmp/arkon_flow.json"],
                          input=FLOW.read_bytes(), capture_output=True)
    if push.returncode:
        raise SystemExit("could not ship the flow: " + push.stderr.decode("utf-8", "replace")[:300])
    result = ssh("%s lf_api.py upsert /tmp/arkon_flow.json" % REMOTE)
    if result.returncode:
        raise SystemExit("upsert failed: " + (result.stderr or result.stdout)[:400])
    return result.stdout.strip()


def ask(question, session):
    """One turn through the v2 workflows API, which is the only one this canvas takes.

    Returns (branch, text, error). The error matters more than it looks: the first
    version of this script returned only the text, and a run that failed outright
    came back as an empty string that the battery then SCORED. Four of the eleven
    checks are negative - invents no source, withholds the link, claims no button,
    adds nothing - and an empty string passes every one of them, so two models that
    never executed were both reported at 4 of 11 and their identical scores were the
    only hint that anything was wrong. A checker that rewards silence is worse than
    no checker. An answer that did not arrive is now a hard failure of every check in
    its case, and the reason is printed and written into the report.
    """
    quoted = question.replace('"', '\\"')
    result = ssh('%s lf_v2.py run "Arkon Quality Assistant" "%s" %s' % (REMOTE, quoted, session))
    body = result.stdout or ""
    lines = [line for line in body.splitlines() if not line.startswith("[status")]
    branch = ""
    if lines and lines[0].startswith("[") and lines[0].endswith("]"):
        branch = lines.pop(0).strip("[]")
    text = "\n".join(lines).strip()

    if result.returncode or not text:
        blob = (body + "\n" + (result.stderr or "")).strip()
        # OpenRouter's own refusals are the interesting failures, so lift them out
        # of the traceback rather than reporting "empty answer".
        for pattern in (r"Model blocked by guardrail[^\"\\\n]*",
                        r"\d+ endpoints out of \d+ requested are available[^\"\\\n]*",
                        r"\"code\":\"[A-Z_]+\"",
                        r"HTTP \d+ on [A-Z]+ [^\s]+"):
            found = re.search(pattern, blob)
            if found:
                return branch, text, found.group(0)
        return branch, text, ("exit %d" % result.returncode) if result.returncode else "empty answer"
    return branch, text, None


def live_ids():
    """One open and one closed incident, taken from the store at run time."""
    import urllib.request

    base = "http://AK2101:5678/webhook/arkon-incident-status"
    out = {}
    for key, query in (("open_id", "?status=new&limit=1"), ("closed_id", "?status=closed&limit=1")):
        with urllib.request.urlopen(base + query, timeout=60) as response:
            answer = json.loads(response.read().decode("utf-8"))
        if not answer.get("incidents"):
            raise SystemExit("the store has no %s incident to test against" % key.split("_")[0])
        out[key] = answer["incidents"][0]["incident_id"]
    return out


def run_battery(model, context, stamp):
    rows, transcript = [], []
    for index, case in enumerate(BATTERY):
        question = case["ask"].format(**context)
        # The model belongs in the session id, and leaving it out invalidated a
        # whole comparison before it was noticed. Langflow keys chat memory by
        # session, so two models sharing one session share the first one's turn as
        # history: on 2026-09-06 a head-to-head returned four byte-identical answers
        # from two different models, which is impossible and was the only reason the
        # run was questioned at all. Two models scoring the same is a result; two
        # models producing the same characters is a bug.
        session = "modelcheck-%s-%s-%d" % (stamp, re.sub(r"[^a-z0-9]+", "-", model.lower()), index)
        branch, answer, error = ask(question, session)
        if error:
            # No answer arrived, so nothing is scored. See the docstring on ask().
            passed = [(label, False) for label, _ in case["checks"]]
        else:
            passed = []
            for label, check in case["checks"]:
                try:
                    passed.append((label, bool(check(answer, context))))
                except Exception:
                    passed.append((label, False))
        rows.append({"case": case["key"], "branch": branch, "checks": passed, "error": error,
                     "score": 0 if error else sum(1 for _, ok in passed if ok),
                     "of": len(passed)})
        transcript.append((model, question, branch, answer, error))
        print("    %-42s %s  %s" % (
            case["key"],
            "FAILED" if error else "%d/%d" % (rows[-1]["score"], rows[-1]["of"]),
            error if error else (", ".join(l for l, ok in passed if not ok) or "all")))
        if error:
            # One guardrail refusal is the same as four; do not pay for the rest.
            for remaining in BATTERY[index + 1:]:
                rows.append({"case": remaining["key"], "branch": "", "error": "not attempted",
                             "checks": [(l, False) for l, _ in remaining["checks"]],
                             "score": 0, "of": len(remaining["checks"])})
            break
    return rows, transcript


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("models", nargs="*", help="OpenRouter model ids to compare")
    parser.add_argument("--set", dest="only_set", help="set this model on the specialists and stop")
    parser.add_argument("--all-nodes", action="store_true",
                        help="also change the router and the escalation nodes")
    parser.add_argument("--keep", action="store_true",
                        help="leave the last candidate deployed instead of restoring")
    parser.add_argument("--list", action="store_true", help="print the deployed models and stop")
    args = parser.parse_args()

    flow = load()
    if args.list:
        for name in [ROUTER] + SPECIALISTS + ESCALATION:
            print("%-24s %s" % (name, current_model(flow, name)))
        return 0

    targets = SPECIALISTS + ([ROUTER] + ESCALATION if args.all_nodes else [])
    before = current_model(flow, "Incident Specialist")

    if args.only_set:
        set_model(flow, targets, args.only_set)
        print(deploy(flow))
        print("set %s on: %s" % (args.only_set, ", ".join(targets)))
        return 0

    if not args.models:
        parser.error("give at least one model id, or --set, or --list")

    context = live_ids()
    print("testing against %s (open) and %s (closed)" % (context["open_id"], context["closed_id"]))
    stamp = datetime.datetime.now().strftime("%H%M%S")

    results, transcripts = {}, []
    for model in args.models:
        print("\n  %s" % model)
        set_model(flow, targets, model)
        deploy(flow)
        rows, lines = run_battery(model, context, stamp)
        results[model] = rows
        transcripts.extend(lines)

    if not args.keep:
        set_model(flow, targets, before)
        deploy(flow)
        print("\nrestored %s" % before)

    total = {m: (sum(r["score"] for r in rows), sum(r["of"] for r in rows))
             for m, rows in results.items()}
    print("\n%-40s %s" % ("model", "checks passed"))
    for model, (score, out_of) in sorted(total.items(), key=lambda kv: -kv[1][0]):
        print("%-40s %d of %d" % (model, score, out_of))

    write_report(results, context, transcripts)
    print("\nwrote %s" % OUT.relative_to(REPO))
    return 0


def write_report(results, context, transcripts):
    when = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# Which model the assistant runs on, measured",
        "",
        "Run by `langflow/build/compare_models.py` on %s, against the live store" % when,
        "(open incident `%s`, closed incident `%s`)." % (context["open_id"], context["closed_id"]),
        "",
        "Every check is mechanical. What they cannot see is whether the prose is any good;",
        "the transcripts below are there to be read for that.",
        "",
        "| Model | " + " | ".join(case["key"] for case in BATTERY) + " | Total |",
        "|---|" + "---|" * (len(BATTERY) + 1),
    ]
    for model, rows in results.items():
        cells = ["%d/%d" % (r["score"], r["of"]) for r in rows]
        total = sum(r["score"] for r in rows)
        of = sum(r["of"] for r in rows)
        lines.append("| `%s` | %s | **%d of %d** |" % (model, " | ".join(cells), total, of))

    lines += ["", "## What each check failed on", ""]
    for model, rows in results.items():
        errors = [(r["case"], r["error"]) for r in rows if r.get("error")]
        if errors:
            lines.append("**`%s`**: no answer arrived, so nothing was scored. %s" % (
                model, "; ".join("%s - %s" % (case, why) for case, why in errors)))
            lines.append("")
            continue
        failed = [(r["case"], label) for r in rows for label, ok in r["checks"] if not ok]
        lines.append("**`%s`**: %s" % (
            model,
            "nothing failed." if not failed
            else "; ".join("%s - %s" % (case, label) for case, label in failed)))
        lines.append("")

    lines += ["## Transcripts", ""]
    for model, question, branch, answer, error in transcripts:
        lines += ["### `%s` - %s" % (model, question), "",
                  "_Branch: %s_" % (branch or "not reported"), ""]
        if error:
            lines += ["**No answer arrived: %s**" % error, ""]
        lines += ["```text", answer or "(nothing)", "```", ""]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
