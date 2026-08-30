"""Build the Sprint 1 Arkon Quality Assistant flow from the course LS2 seed.

The instructor's own "LS2 Agent LangFlow Equivalent.json" is used as the
structural base so the canvas keeps the shape the course teaches: Chat Input ->
Agent -> Chat Output. Only the fields that carry a decision are changed, and the
system prompt is read out of the vault artifact so the two cannot drift.

Runs once. After the flow exists in Langflow, later sprints fetch the live flow,
modify it, and push it back.
"""

import json
import pathlib
import re

SEED = pathlib.Path(
    r"N:\-LEARNING\--Masterschool\12.3 Building AI Agents Visual Agent Builders"
    r" & Platform Landscape\Google Drive\LS2 Agent LangFlow Equivalent.json"
)
PROMPT_DOC = pathlib.Path(
    r"C:\Users\kasser\AI-Brain\020 Projects\AI_Agents_2B_Meridian\build\sprint1_system_prompt.md"
)
OUT = pathlib.Path(
    r"D:\-PROJECTS\--Portfolio\arkon-manufacturing-ai\langflow\arkon_quality_assistant.json"
)

# Pull the prompt out of the vault artifact, so the flow and the document agree
prompt_doc = PROMPT_DOC.read_text(encoding="utf-8")
blocks = re.findall(r"```text\n(.*?)\n```", prompt_doc, flags=re.S)
if len(blocks) != 1:
    raise SystemExit(f"expected exactly one text block in the prompt document, found {len(blocks)}")
system_prompt = blocks[0].strip()

flow = json.loads(SEED.read_text(encoding="utf-8"))
flow["name"] = "Arkon Quality Assistant"
flow["description"] = (
    "MSIT Term 12 course 2B project. Conversational front end for the Arkon Quality "
    "Steering Cell: quality procedure, incident context and model context for the "
    "on-shift operator. Sprint 1: base canvas and three-pillar system prompt."
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
