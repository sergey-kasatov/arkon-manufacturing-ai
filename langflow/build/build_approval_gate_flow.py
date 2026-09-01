"""Refine the Arkon Quality Assistant canvas into its approval-gate shape.

Adds the human approval gate in front of the escalation write, the escalation
record API as the specialist's tool, a declined branch, and the shift briefing
sub-flow invoked through Run Flow. Everything the routing build added stays in place.
"""

import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import lfbuild
import prompts

SCRATCH = pathlib.Path(__file__).parent
REPO = pathlib.Path(__file__).resolve().parent.parent.parent
FLOW = REPO / "langflow" / "arkon_quality_assistant.json"
PROMPTS = prompts.PROMPT_DIR
ESCALATION_API = "http://n8n.arkon.internal:5678/webhook/arkon-escalation"
BRIEFING_FLOW_NAME = "Arkon_Shift_Briefing"
BRIEFING_FLOW_ID = sys.argv[1] if len(sys.argv) > 1 else None
if not BRIEFING_FLOW_ID:
    raise SystemExit("pass the Arkon_Shift_Briefing flow id as the first argument")

blocks = prompts.load()
for name in ("escalation_v2", "declined"):
    if name not in blocks:
        raise SystemExit("missing prompt block: " + name)


def spec(name):
    return json.loads((SCRATCH / ("spec_%s.json" % name)).read_text(encoding="utf-8"))["spec"]


flow = json.loads(FLOW.read_text(encoding="utf-8"))
nodes = {node["id"]: node for node in flow["data"]["nodes"]}
router = nodes["SmartRouter-rt001"]
incident = nodes["Agent-inc01"]
escalation = nodes["Agent-esc01"]

TOOL_OUTPUT = {
    "allows_loop": False, "cache": True, "display_name": "Toolset", "group_outputs": False,
    "method": "to_toolkit", "name": "component_as_tool", "selected": "Tool",
    "types": ["Tool"], "value": "__UNDEFINED__",
}

# The approval gate. Its prompt is fed from the router, so the human reviews the
# operator's own words, and both branches carry that text to their specialist.
gate = lfbuild.node_from_spec(
    spec("humaninput"),
    "HumanInput-esc01",
    (-1050, 460),
    values={
        "decisions": ["Approve", "Reject"],
        # One hour, not the three-day default: an escalation approval that can wait
        # three days is not an escalation. The fallback branch is off, see the
        # named gap recorded when the gate was added.
        "timeout": {"value": 1, "unit": "Hours"},
        "enable_fallback": False,
    },
    outputs=[
        {"allows_loop": False, "cache": True, "display_name": "Approve", "group_outputs": True,
         "method": "route_branch", "name": "branch_approve", "selected": "Message",
         "types": ["Message"], "value": "__UNDEFINED__"},
        {"allows_loop": False, "cache": True, "display_name": "Reject", "group_outputs": True,
         "method": "route_branch", "name": "branch_reject", "selected": "Message",
         "types": ["Message"], "value": "__UNDEFINED__"},
    ],
    display_name="Escalation Approval",
)

escalation_api = lfbuild.node_from_spec(
    spec("apirequest"),
    "APIRequest-esc01",
    (-1050, 900),
    values={"method": "POST", "url_input": ESCALATION_API, "timeout": 30},
    outputs=[TOOL_OUTPUT],
    selected_output="component_as_tool",
    tool_mode=True,
    display_name="Escalation Record API",
)

briefing = lfbuild.node_from_spec(
    spec("runflow"),
    "RunFlow-brf01",
    (-1250, 900),
    values={"flow_name_selected": BRIEFING_FLOW_NAME, "flow_id_selected": BRIEFING_FLOW_ID,
            "cache_flow": False},
    outputs=[TOOL_OUTPUT],
    selected_output="component_as_tool",
    tool_mode=True,
    display_name="Shift Briefing Sub-flow",
)

declined = lfbuild.clone_node(
    escalation, "Agent-dec01", (-620, 700),
    values={"system_prompt": blocks["declined"].strip()},
    display_name="Escalation Declined",
)
declined_out = lfbuild.clone_node(nodes["ChatOutput-esc01"], "ChatOutput-dec01", (-260, 700),
                                  display_name="Declined Answer")

escalation["data"]["node"]["template"]["system_prompt"]["value"] = blocks["escalation_v2"].strip()
# A broken tool should cost five model calls and a clear failure, not the default
# fifteen and a graph recursion error. Found the hard way, and recorded when the gate was added.
escalation["data"]["node"]["template"]["max_iterations"]["value"] = 5
escalation["position"] = {"x": -620, "y": 440}
nodes["ChatOutput-esc01"]["position"] = {"x": -260, "y": 440}

flow["data"]["nodes"] = list(nodes.values()) + [gate, escalation_api, briefing, declined, declined_out]

# The routing build wired the router straight into the escalation specialist. That edge is
# replaced by the gate: router -> approval -> approve branch -> specialist.
kept = [
    edge for edge in flow["data"]["edges"]
    if not (edge["source"] == "SmartRouter-rt001" and edge["target"] == "Agent-esc01")
]
if len(kept) != len(flow["data"]["edges"]) - 1:
    raise SystemExit("expected exactly one router-to-escalation edge to replace")

E = lfbuild.edge
flow["data"]["edges"] = kept + [
    E(router, "category_3_result", gate, "prompt"),
    E(gate, "branch_approve", escalation, "input_value"),
    E(gate, "branch_reject", declined, "input_value"),
    E(escalation_api, "component_as_tool", escalation, "tools"),
    E(briefing, "component_as_tool", incident, "tools"),
    E(declined, "response", declined_out, "input_value"),
]

flow["description"] = (
    "Conversational front end for the Arkon Quality "
    "Steering Cell: intent routing, a live incident lookup, a human approval "
    "gate in front of the escalation write path, and the shift briefing sub-flow invoked "
    "through Run Flow."
)

FLOW.write_text(json.dumps(flow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("wrote", FLOW)
print("nodes:", len(flow["data"]["nodes"]), " edges:", len(flow["data"]["edges"]))
for node in flow["data"]["nodes"]:
    print("   %-24s %s" % (node["id"], node["data"]["node"].get("display_name")))
