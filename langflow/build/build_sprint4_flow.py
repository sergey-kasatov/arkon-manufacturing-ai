"""Refine the canvas into its Sprint 4 shape: the briefing gets its own branch.

DEFECT-3 is the only one of the three that still reproduces, and its fix is
structural. The shift briefing sub-flow was reached as a tool of the incident
specialist, so its fixed four-block output landed in an agent's context and came
back paraphrased on top of itself. It now has its own router route and reaches
its own Chat Output through a Run Flow node in normal mode, with no agent in
between - the same shape the out-of-scope branch already uses.

DEFECT-1 and DEFECT-2 no longer reproduce; both were closed by structural changes
made in Sprints 2 and 3 for other reasons. Sprint 4 validates them rather than
re-fixing them. The account is in the vault artifact.

Run after build_retrieval.py and before layout_flow.py:

    python langflow/build/build_sprint4_flow.py <briefing-flow-id>
    python langflow/build/layout_flow.py
"""

import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import lfbuild

HERE = pathlib.Path(__file__).parent
REPO = HERE.parent.parent
FLOW = REPO / "langflow" / "arkon_quality_assistant.json"
PROMPTS = pathlib.Path(
    r"C:\Users\kasser\AI-Brain\020 Projects\AI_Agents_2B_Meridian\build\sprint4_refinement.md"
)
BRIEFING_FLOW_NAME = "Arkon_Shift_Briefing"
BRIEFING_FLOW_ID = sys.argv[1] if len(sys.argv) > 1 else None
if not BRIEFING_FLOW_ID:
    raise SystemExit("pass the Arkon_Shift_Briefing flow id as the first argument")

# The sub-flow's own vertices, which is how a Run Flow node names its dynamic
# input and output outside tool mode. Both come from Langflow itself, via
# fetch_specs.py, not from guessing at the convention.
BRIEFING_INPUT = "ChatInput-brf01~input_value"
BRIEFING_OUTPUT = "ChatOutput-brf01~message"

blocks = dict(
    re.findall(r"### BLOCK: (\w+)\n\n```text\n(.*?)\n```", PROMPTS.read_text(encoding="utf-8"), flags=re.S)
)
for name in ("route_briefing", "route_incident_v2", "router_instructions_v2"):
    if name not in blocks:
        raise SystemExit("missing prompt block: " + name)


def spec(name):
    return json.loads((HERE / ("spec_%s.json" % name)).read_text(encoding="utf-8"))["spec"]


flow = json.loads(FLOW.read_text(encoding="utf-8"))
nodes = {node["id"]: node for node in flow["data"]["nodes"]}
router = nodes["SmartRouter-rt001"]
incident = nodes["Agent-inc01"]

# Re-runnable: drop anything a previous Sprint 4 run added, so a prompt edit does
# not need the whole sprint chain replayed.
for node_id in ("RunFlow-brf02", "ChatOutput-brf02"):
    nodes.pop(node_id, None)
# The tool-mode Run Flow is what the fix removes.
nodes.pop("RunFlow-brf01", None)
flow["data"]["edges"] = [
    edge for edge in flow["data"]["edges"]
    if edge["source"] in nodes and edge["target"] in nodes
]

# The new route is appended, not inserted: the router names its outputs by
# position, so inserting one would silently repoint every existing branch edge.
routes = router["data"]["node"]["template"]["routes"]["value"]
routes = [route for route in routes if route["route_category"] != "Shift briefing"]
by_category = {route["route_category"]: route for route in routes}
by_category["Incident status"]["route_description"] = blocks["route_incident_v2"].strip()
routes.append({
    "route_category": "Shift briefing",
    "route_description": blocks["route_briefing"].strip(),
    "route_message": "",
})
router["data"]["node"]["template"]["routes"]["value"] = routes
router["data"]["node"]["template"]["custom_prompt"]["value"] = blocks["router_instructions_v2"].strip()
router["data"]["node"]["outputs"] = lfbuild.router_outputs(routes, enable_else=False)
briefing_output = "category_%d_result" % (len(routes))

briefing = lfbuild.node_from_spec(
    spec("runflow_briefing"), "RunFlow-brf02", (-1050, 1900),
    values={
        "flow_name_selected": BRIEFING_FLOW_NAME,
        "flow_id_selected": BRIEFING_FLOW_ID,
        "cache_flow": False,
    },
    type_name="RunFlow",
    display_name="Shift Briefing Sub-flow",
)
# The dropdown renders as "Select an option" without its options list, even
# though the call resolves from flow_id_selected.
selector = briefing["data"]["node"]["template"]["flow_name_selected"]
selector["options"] = [BRIEFING_FLOW_NAME]
selector["options_metadata"] = [{"id": BRIEFING_FLOW_ID}]

briefing_answer = lfbuild.clone_node(
    nodes["ChatOutput-oos01"], "ChatOutput-brf02", (-600, 1900), display_name="Briefing Answer",
)

flow["data"]["nodes"] = list(nodes.values()) + [briefing, briefing_answer]
flow["data"]["edges"] = flow["data"]["edges"] + [
    lfbuild.edge(router, briefing_output, briefing, BRIEFING_INPUT),
    lfbuild.edge(briefing, BRIEFING_OUTPUT, briefing_answer, "input_value"),
]

flow["description"] = (
    "MSIT Term 12 course 2B project. Conversational front end for the Arkon Quality "
    "Steering Cell: grounded retrieval over the Arkon documents, five-way intent "
    "routing, a live incident lookup, a human approval gate in front of the escalation "
    "write path, and the shift briefing sub-flow on its own branch."
)

FLOW.write_text(json.dumps(flow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("wrote", FLOW.name)
print("nodes:", len(flow["data"]["nodes"]), " edges:", len(flow["data"]["edges"]))
print("routes:", [route["route_category"] for route in routes])
print("briefing branch:", briefing_output, "->", BRIEFING_INPUT)
print("incident specialist tools:",
      [edge["source"] for edge in flow["data"]["edges"] if edge["target"] == "Agent-inc01"])
