"""Rebuild Arkon_Shift_Briefing with a visible retry loop and a per-incident loop.

Course 2B Week 3 names two capabilities the first version met in substance but not
in shape: a retry with a visible fallback after two retries (LS10), and iteration
over a list of records with one model call each (LS11). Both are built here, in the
sub-flow, so the assistant's own canvas is not touched.

**The briefing is where the retry belongs.** It is the unattended path: a scheduler
runs it at shift change with nobody watching, so a transient failure there has no
operator to ask again. The incident branch on the main canvas answers a person who
can retype the question, which is why it reports instead of retrying.

**Both mechanisms are Loops, and that is forced rather than chosen.** Three probes
on this Langflow 1.11.5 build, recorded in the handoff
`070 Agents/Logs/handoffs/term12-agent-projects.md` SESSION 26:

- a graph cycle does not execute at all, not even the shape Langflow's own If-Else
  documentation describes, through either run API;
- a node merging one live input with inputs from a stopped branch does not execute
  either, which is what killed the first build of this file: three conditional
  attempts converging on one resolve node produced a run with zero vertices and no
  error;
- a Loop body does execute, once per row, and aggregates.

So the attempts are rows of a plan and the retry is a Loop. The cost is that every
briefing issues all three calls; it is named in `arkon_retry_plan.py` and defended
there, and it does not extend to the escalation write, which is not retried at all.

The four-block output contract is unchanged. The per-incident readings feed the
NOTE block only; OPEN, OVERDUE and WATCH keep the fields they always had, so the
DEFECT-3 fix and the open DEFECT-6 are both untouched.

    python langflow/build/build_briefing_v2_flow.py
    python langflow/build/build_briefing_v2_flow.py --deploy
    python langflow/build/build_briefing_v2_flow.py --no-retry --deploy   # bisect
    python langflow/build/build_briefing_v2_flow.py --dead-url --deploy   # LS10 failure path
"""

import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import lfbuild
import prompts

HERE = pathlib.Path(__file__).parent
REPO = HERE.parent.parent
MAIN = REPO / "langflow" / "arkon_quality_assistant.json"
OUT = REPO / "langflow" / "arkon_shift_briefing.json"
HOST = "ResSak@AK2101"
REMOTE = "cd ~/arkon-tmp && python3 lf_api.py"
STATUS_API = "http://n8n.arkon.internal:5678/webhook/arkon-incident-status?limit=500"
DEAD_API = "http://n8n.arkon.internal:5678/webhook/arkon-incident-status-does-not-exist"
ATTEMPTS = 3

# One line per overdue incident, handed to the reading agent.
READING_PATTERN = (
    "Overdue incident on unit {unit}, record {record_id}, from module {source_module}. "
    "It is {age_minutes} minutes old against a {acknowledge_due_minutes} minute "
    "acknowledgement window, so it is {minutes_past_window} minutes past it. "
    "Status {status}, assigned to {assigned_to} ({assigned_role}). "
    "Detector summary: {summary} "
    "Recommended action on the record: {recommended_action}"
)


def spec(slug):
    return json.loads((HERE / ("spec_%s.json" % slug)).read_text(encoding="utf-8"))["spec"]


def main():
    for name in ("briefing_v2", "incident_reading"):
        if name not in prompts.load():
            raise SystemExit("prompt block %r is missing" % name)

    main_flow = json.loads(MAIN.read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in main_flow["data"]["nodes"]}
    N = lfbuild.node_from_spec
    C = lfbuild.clone_node

    # The request path. The chat input feeds exactly one node, because
    # `sort_chat_inputs_first` refuses a graph whose chat input lands in two
    # layers; the request leaves the URL node again unchanged.
    chat_input = C(nodes["ChatInput-tKQ4d"], "ChatInput-brf01", (-1700, 120),
                   display_name="Briefing Request")
    url = N(spec("statusurl"), "ArkonStatusUrl-url01", (-1350, 120),
            values={"url": STATUS_API}, type_name="ArkonStatusUrl")

    # The retry: a plan of attempts, a loop over them, one call per row.
    plan = N(spec("retryplan"), "ArkonRetryPlan-pl01", (-1000, 480),
             values={"attempts": ATTEMPTS}, display_name="Retry plan",
             type_name="ArkonRetryPlan")
    retry_loop = N(spec("loop"), "LoopComponent-rt01", (-650, 480),
                   display_name="Status attempts", type_name="LoopComponent")
    attempt_url = N(spec("parser"), "ParserComponent-pu01", (-300, 840),
                    values={"pattern": "{url}"}, display_name="Attempt URL",
                    type_name="ParserComponent")
    counter = N(spec("retrycounter"), "ArkonRetryCounter-cn01", (50, 840),
                display_name="Attempt counter", type_name="ArkonRetryCounter")
    api = N(spec("apirequest"), "APIRequest-brf02", (400, 840),
            values={"method": "GET", "timeout": 30}, display_name="Incident Status API")
    gate = N(spec("statusgate"), "ArkonStatusGate-gt01", (750, 840),
             display_name="Answer gate", type_name="ArkonStatusGate")
    resolve = N(spec("statusresolve"), "ArkonStatusResolve-rv01", (-300, 480),
                display_name="Resolve attempts", type_name="ArkonStatusResolve")

    # The iteration: one model call per overdue incident.
    overdue = N(spec("overduelist"), "ArkonOverdueList-ov01", (50, 480),
                values={"limit": 0}, display_name="Overdue list",
                type_name="ArkonOverdueList")
    read_loop = N(spec("loop"), "LoopComponent-lp01", (400, 480),
                  display_name="Per incident", type_name="LoopComponent")
    parser = N(spec("parser"), "ParserComponent-ps01", (750, 200),
               values={"pattern": READING_PATTERN},
               display_name="Incident to text", type_name="ParserComponent")
    reader = C(nodes["Agent-inc01"], "Agent-rd01", (1100, 200),
               values={"system_prompt": prompts.block("incident_reading"), "max_iterations": 3},
               display_name="Per-incident reading")
    notes = N(spec("overduenotes"), "ArkonOverdueNotes-nt01", (750, 480),
              display_name="Overdue notes", type_name="ArkonOverdueNotes")

    # The briefing itself.
    compose = N(spec("briefinginput"), "ArkonBriefingInput-in01", (1100, 480),
                display_name="Briefing input", type_name="ArkonBriefingInput")
    briefing_agent = C(nodes["Agent-inc01"], "Agent-brf01", (1450, 480),
                       values={"system_prompt": prompts.block("briefing_v2"), "max_iterations": 5},
                       display_name="Shift Briefing")
    chat_output = C(nodes["ChatOutput-inc01"], "ChatOutput-brf01", (1800, 480),
                    display_name="Briefing")

    keep_retry = "--no-retry" not in sys.argv
    keep_loop = "--no-loop" not in sys.argv
    # --dead-url is the LS10 failure-path test: the same canvas, pointed at an
    # endpoint that does not exist, deployed under the probe name so the flow the
    # assistant calls is never the one being broken on purpose.
    dead = "--dead-url" in sys.argv
    if dead:
        url["data"]["node"]["template"]["url"]["value"] = DEAD_API
    probe = dead or not (keep_retry and keep_loop)

    E = lfbuild.edge
    node_list = [chat_input, url, overdue, notes, compose, briefing_agent, chat_output]
    edge_list = [
        E(chat_input, "message", url, "trigger"),
        E(url, "request", compose, "request"),
        E(notes, "notes", compose, "incident_notes"),
        E(compose, "briefing_input", briefing_agent, "input_value"),
        E(briefing_agent, "response", chat_output, "input_value"),
    ]

    if keep_retry:
        node_list += [plan, retry_loop, attempt_url, counter, api, gate, resolve]
        edge_list += [
            E(url, "endpoint", plan, "url"),
            E(plan, "plan", retry_loop, "data"),
            E(retry_loop, "item", attempt_url, "input_data"),
            E(attempt_url, "parsed_text", counter, "trigger"),
            E(counter, "passthrough", api, "url_input"),
            E(api, "data", gate, "response"),
            lfbuild.loop_back_edge(gate, "payload", retry_loop),
            E(retry_loop, "done", resolve, "attempts"),
            E(resolve, "payload", overdue, "payload"),
            E(resolve, "payload", compose, "status_payload"),
            E(resolve, "note", compose, "status_note"),
        ]
    else:
        # Bisect mode: one unretried call straight into the overdue list.
        node_list += [api, gate]
        edge_list += [
            E(url, "endpoint", api, "url_input"),
            E(api, "data", gate, "response"),
            E(gate, "payload", overdue, "payload"),
            E(gate, "payload", compose, "status_payload"),
            E(gate, "verdict", compose, "status_note"),
        ]

    if keep_loop:
        node_list += [read_loop, parser, reader]
        edge_list += [
            E(overdue, "overdue", read_loop, "data"),
            E(read_loop, "item", parser, "input_data"),
            E(parser, "parsed_text", reader, "input_value"),
            lfbuild.loop_back_edge(reader, "response", read_loop),
            E(read_loop, "done", notes, "summaries"),
            E(overdue, "overdue", notes, "incidents"),
        ]
    else:
        edge_list += [E(overdue, "overdue", notes, "incidents")]

    flow = {
        "name": "ZZ_Probe_Briefing" if probe else "Arkon_Shift_Briefing",
        "description": (
            "Shift handover briefing for the Arkon Quality Steering Cell: open incidents by "
            "priority, what is overdue, what is close to its window. The status lookup runs as "
            "a bounded retry loop, and every overdue incident is read on its own. Called by the "
            "Arkon Quality Assistant through Run Flow, and runnable on its own endpoint at "
            "shift change."
        ),
        "endpoint_name": "zz-probe-briefing" if probe else "arkon-shift-briefing",
        "data": {
            "nodes": node_list,
            "edges": edge_list,
            "viewport": {"x": 0, "y": 0, "zoom": 1},
        },
    }

    target = OUT.parent / "zz_probe_briefing.json" if probe else OUT
    target.write_text(json.dumps(flow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", target.name)
    print("nodes:", len(node_list), "edges:", len(edge_list))

    if "--deploy" in sys.argv:
        subprocess.run(["ssh", HOST, "cat > /tmp/arkon_briefing.json"],
                       input=target.read_bytes(), check=True)
        result = subprocess.run(["ssh", HOST, "%s upsert /tmp/arkon_briefing.json" % REMOTE],
                                capture_output=True, check=True)
        print(result.stdout.decode("utf-8", "replace").strip())


if __name__ == "__main__":
    main()
