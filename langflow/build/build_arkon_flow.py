"""Build the first Arkon Quality Assistant canvas from a minimal seed flow.

The seed is a three-node Langflow export, Chat Input -> Agent -> Chat Output.
Only the fields that carry a decision are changed, and the system prompt comes
from `langflow/prompts/base.md` so the canvas and the prompt cannot drift.

The seed is not in this repository: point `ARKON_SEED_FLOW` at any Langflow
export with that shape, or export one from a new Langflow project.

Runs once. After the flow exists in Langflow, the later build scripts fetch the
live flow, modify it, and push it back.
"""

import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import prompts

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
OUT = REPO / "langflow" / "arkon_quality_assistant.json"

seed_env = os.environ.get("ARKON_SEED_FLOW")
if not seed_env:
    raise SystemExit(
        "set ARKON_SEED_FLOW to a Langflow export with Chat Input -> Agent -> Chat Output"
    )
SEED = pathlib.Path(seed_env)
if not SEED.is_file():
    raise SystemExit("ARKON_SEED_FLOW does not point at a file: %s" % SEED)

system_prompt = prompts.block("base_system_prompt")

flow = json.loads(SEED.read_text(encoding="utf-8"))
flow["name"] = "Arkon Quality Assistant"
flow["description"] = (
    "Conversational front end for the Arkon Quality Steering Cell: quality "
    "procedure, incident context and model context for the on-shift operator. "
    "First iteration: base canvas and three-pillar system prompt."
)
flow["endpoint_name"] = "arkon-quality-assistant"
flow.pop("id", None)

# Field changes that carry a decision, applied to the seeded Agent node
AGENT_VALUES = {
    "system_prompt": system_prompt,
    # No tools exist in Sprint 1, so the two bundled ones are switched off:
    # every node and every capability has to be justified by the business problem.
    "add_calculator_tool": False,
    "add_current_date_tool": False,
    # Memory window. 100 is the component default and far more than an operator
    # session needs; 20 messages is ten exchanges, which covers a shift handover
    # conversation while bounding what every turn pays for.
    "n_messages": 20,
}

patched = []
for node in flow["data"]["nodes"]:
    data = node["data"]
    template = data["node"]["template"]
    if data["type"] == "Agent":
        for key, value in AGENT_VALUES.items():
            if key not in template:
                raise SystemExit("agent template has no field " + key)
            template[key]["value"] = value
            patched.append(key)
    if data["type"] == "ChatInput":
        # The seed ships a sample question; an empty field is the honest default
        template["input_value"]["value"] = ""
        patched.append("input_value")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(flow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("wrote", OUT)
print("patched fields:", ", ".join(patched))
print("system prompt words:", len(system_prompt.split()))
