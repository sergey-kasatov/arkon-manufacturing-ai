"""Refine the Arkon Quality Assistant canvas into its routing shape.

Takes the base flow and adds intent routing, three specialists and the live
incident lookup. The base Agent and Chat Output are kept and become the
procedure branch, so the canvas is the refined original rather than a rebuild.

Prompts and route descriptions are read from `langflow/prompts/` by block name.
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
# A dotted host is mandatory: Langflow's API Request validates with
# validators.url(), which rejects a bare Docker service name.
STATUS_API = "http://n8n.arkon.internal:5678/webhook/arkon-incident-status"

# Read the named prompt blocks out of langflow/prompts/
blocks = prompts.load()
expected = {"route_procedure", "route_incident", "route_escalation", "route_out_of_scope",
            "router_instructions", "procedure", "incident", "escalation", "out_of_scope"}
missing = expected - set(blocks)
if missing:
    raise SystemExit("prompt blocks missing from the artifact: " + ", ".join(sorted(missing)))


def spec(name):
    return json.loads((SCRATCH / ("spec_%s.json" % name)).read_text(encoding="utf-8"))["spec"]


flow = json.loads(FLOW.read_text(encoding="utf-8"))
nodes = {node["id"]: node for node in flow["data"]["nodes"]}
chat_input = nodes["ChatInput-tKQ4d"]
agent_seed = nodes["Agent-EXpSZ"]
output_seed = nodes["ChatOutput-KxTA8"]
model_value = agent_seed["data"]["node"]["template"]["model"]["value"]

# Router table. Route order fixes the output names category_1..category_3.
routes = [
    {"route_category": "Quality procedure",
     "route_description": blocks["route_procedure"].strip(),
     "output_value": ""},
    {"route_category": "Incident status",
     "route_description": blocks["route_incident"].strip(),
     "output_value": ""},
    {"route_category": "Escalation request",
     "route_description": blocks["route_escalation"].strip(),
     "output_value": ""},
    # The fourth route answers directly: a Route Message makes the branch emit
    # this text instead of the question, so no agent runs on the out-of-scope path.
    {"route_category": "Out of scope",
     "route_description": blocks["route_out_of_scope"].strip(),
     "output_value": blocks["out_of_scope"].strip()},
]

router = lfbuild.node_from_spec(
    spec("smartrouter"),
    "SmartRouter-rt001",
    (-1250, 180),
    values={
        "model": model_value,
        "routes": routes,
        # Else is off: its branch echoes the operator's own question back. The
        # additional instructions below make "Out of scope" the catch-all instead.
        "enable_else_output": False,
        "custom_prompt": blocks["router_instructions"].strip(),
    },
    outputs=lfbuild.router_outputs(routes, enable_else=False),
    display_name="Intent Router",
)

# The API Request runs in tool mode: the incident specialist builds the URL from
# the operator's question, which is the whole point of a live lookup.
api_tool_output = {
    "allows_loop": False,
    "cache": True,
    "display_name": "Toolset",
    "group_outputs": False,
    "method": "to_toolkit",
    "name": "component_as_tool",
    "selected": "Tool",
    "types": ["Tool"],
    "value": "__UNDEFINED__",
}
api_request = lfbuild.node_from_spec(
    spec("apirequest"),
    "APIRequest-inc01",
    (-1250, 640),
    values={"method": "GET", "url_input": STATUS_API, "timeout": 30},
    outputs=[api_tool_output],
    selected_output="component_as_tool",
    tool_mode=True,
    display_name="Incident Status API",
)

# The base agent becomes the procedure specialist, in place
procedure = lfbuild.clone_node(
    agent_seed, "Agent-EXpSZ", (-850, -160),
    values={"system_prompt": blocks["procedure"].strip()},
    display_name="Procedure Specialist",
)
incident = lfbuild.clone_node(
    agent_seed, "Agent-inc01", (-850, 180),
    values={"system_prompt": blocks["incident"].strip()},
    display_name="Incident Specialist",
)
escalation = lfbuild.clone_node(
    agent_seed, "Agent-esc01", (-850, 460),
    values={"system_prompt": blocks["escalation"].strip()},
    display_name="Escalation Specialist",
)

procedure_out = lfbuild.clone_node(output_seed, "ChatOutput-KxTA8", (-450, -160),
                                   display_name="Procedure Answer")
incident_out = lfbuild.clone_node(output_seed, "ChatOutput-inc01", (-450, 180),
                                  display_name="Incident Answer")
escalation_out = lfbuild.clone_node(output_seed, "ChatOutput-esc01", (-450, 460),
                                    display_name="Escalation Answer")
scope_out = lfbuild.clone_node(output_seed, "ChatOutput-oos01", (-850, 720),
                               display_name="What I can help with")

chat_input["position"] = {"x": -1600, "y": 180}

flow["data"]["nodes"] = [
    chat_input, router, api_request,
    procedure, incident, escalation,
    procedure_out, incident_out, escalation_out, scope_out,
]

E = lfbuild.edge
flow["data"]["edges"] = [
    E(chat_input, "message", router, "input_text"),
    E(router, "category_1_result", procedure, "input_value"),
    E(router, "category_2_result", incident, "input_value"),
    E(router, "category_3_result", escalation, "input_value"),
    E(router, "category_4_result", scope_out, "input_value"),
    E(api_request, "component_as_tool", incident, "tools"),
    E(procedure, "response", procedure_out, "input_value"),
    E(incident, "response", incident_out, "input_value"),
    E(escalation, "response", escalation_out, "input_value"),
]

flow["description"] = (
    "Conversational front end for the Arkon Quality "
    "Steering Cell: intent routing through a Smart Router, three specialists "
    "with non-overlapping prompts, and a live incident lookup against the n8n incident "
    "status API with designed failure behaviour."
)

FLOW.write_text(json.dumps(flow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("wrote", FLOW)
print("nodes:", len(flow["data"]["nodes"]), " edges:", len(flow["data"]["edges"]))
for node in flow["data"]["nodes"]:
    print("   %-24s %s" % (node["id"], node["data"]["node"].get("display_name")))
