"""Build the Arkon_Shift_Briefing sub-flow.

A small three-node flow: chat input, a briefing agent holding the incident status
API as a tool, chat output. It is a sub-flow because it is used from more than one
place - the assistant calls it through Run Flow, and it has its own endpoint so a
scheduler can run it at shift change with no chat agent involved.

The name carries no spaces on purpose: Run Flow builds the tool name from it, and
a tool name with spaces is rejected by OpenAI-compatible tool APIs.
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
MAIN = REPO / "langflow" / "arkon_quality_assistant.json"
OUT = REPO / "langflow" / "arkon_shift_briefing.json"
PROMPTS = prompts.PROMPT_DIR
STATUS_API = "http://n8n.arkon.internal:5678/webhook/arkon-incident-status"

blocks = prompts.load()
if "briefing" not in blocks:
    raise SystemExit("briefing block missing from the Sprint 3 artifact")

main = json.loads(MAIN.read_text(encoding="utf-8"))
nodes = {node["id"]: node for node in main["data"]["nodes"]}

chat_input = lfbuild.clone_node(nodes["ChatInput-tKQ4d"], "ChatInput-brf01", (-1200, 200),
                                display_name="Briefing Request")
agent = lfbuild.clone_node(
    nodes["Agent-inc01"], "Agent-brf01", (-820, 200),
    values={"system_prompt": blocks["briefing"].strip()},
    display_name="Shift Briefing",
)
chat_output = lfbuild.clone_node(nodes["ChatOutput-inc01"], "ChatOutput-brf01", (-440, 200),
                                 display_name="Briefing")

api_tool_output = {
    "allows_loop": False, "cache": True, "display_name": "Toolset", "group_outputs": False,
    "method": "to_toolkit", "name": "component_as_tool", "selected": "Tool",
    "types": ["Tool"], "value": "__UNDEFINED__",
}
api_request = lfbuild.node_from_spec(
    json.loads((SCRATCH / "spec_apirequest.json").read_text(encoding="utf-8"))["spec"],
    "APIRequest-brf01",
    (-820, 560),
    values={"method": "GET", "url_input": STATUS_API, "timeout": 30},
    outputs=[api_tool_output],
    selected_output="component_as_tool",
    tool_mode=True,
    display_name="Incident Status API",
)

E = lfbuild.edge
flow = {
    "name": "Arkon_Shift_Briefing",
    "description": (
        "Shift handover briefing for the Arkon Quality Steering Cell: open incidents by "
        "priority, what is overdue, what is close to its window. Called by the Arkon "
        "Quality Assistant through Run Flow, and runnable on its own endpoint at shift "
        "change."
    ),
    "endpoint_name": "arkon-shift-briefing",
    "data": {
        "nodes": [chat_input, agent, api_request, chat_output],
        "edges": [
            E(chat_input, "message", agent, "input_value"),
            E(api_request, "component_as_tool", agent, "tools"),
            E(agent, "response", chat_output, "input_value"),
        ],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    },
}

OUT.write_text(json.dumps(flow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("wrote", OUT)
print("nodes:", len(flow["data"]["nodes"]), "edges:", len(flow["data"]["edges"]))
