"""Lay the Arkon Quality Assistant canvas out so a human can read it.

The positions were set node by node while building and never looked at, so
several nodes ended up stacked on top of each other. This puts them on a grid:
flow left to right in columns, tools in a band below the agents they feed.

Column pitch is 450 or 600, which clears the 320-wide node plus a gap. Vertical
spacing assumes an Agent is about 450 tall, an API Request 400, a router 450 and
a Chat Output 150.
"""

import json
import pathlib

FLOW = pathlib.Path(
    r"D:\-PROJECTS\--Portfolio\arkon-manufacturing-ai\langflow\arkon_quality_assistant.json"
)
BRIEFING_FLOW_ID = "063c6445-ef32-49e5-93a9-dc7764a40a48"

# x, y per node. Columns: input, router, branch heads, escalation pair, outputs.
# Tools sit in a band below, feeding upward into the agent that owns them.
LAYOUT = {
    "ChatInput-tKQ4d":     (-2100, 0),
    "SmartRouter-rt001":   (-1650, 0),

    "Agent-EXpSZ":         (-1050, -750),    # procedure
    "Agent-inc01":         (-1050, -150),    # incident status
    "HumanInput-esc01":    (-1050, 450),     # the approval gate

    "Agent-esc01":         (-600, 450),      # escalation, approve branch
    "Agent-dec01":         (-600, 1000),     # declined, reject branch

    "ChatOutput-KxTA8":    (-150, -750),
    "ChatOutput-inc01":    (-150, -150),
    "ChatOutput-oos01":    (-150, 150),
    "ChatOutput-esc01":    (-150, 450),
    "ChatOutput-dec01":    (-150, 1000),

    # The document store feeds the procedure specialist. It sits above the input
    # column rather than in the tool band below, because it is the only tool on
    # the top branch and dropping it down there would cross every other edge.
    "OpenRouterEmbeddings-emb01":                        (-2100, -1300),
    "ext:qdrant:QdrantVectorStoreComponent@official-kb01": (-1650, -750),

    # The shift briefing is its own branch since Sprint 4, not a tool: it goes
    # router -> sub-flow -> output with no agent in the path, which is what stops
    # its fixed format being paraphrased.
    "RunFlow-brf02":       (-1050, 2250),
    "ChatOutput-brf02":    (-150, 2250),

    "APIRequest-inc01":    (-1650, 700),     # tool of the incident specialist
    "APIRequest-esc01":    (-1050, 1550),    # tool of the escalation specialist
}

flow = json.loads(FLOW.read_text(encoding="utf-8"))
moved = []
for node in flow["data"]["nodes"]:
    if node["id"] not in LAYOUT:
        raise SystemExit("no layout position for " + node["id"])
    x, y = LAYOUT[node["id"]]
    node["position"] = {"x": x, "y": y}
    node.pop("measured", None)          # let the UI measure the node itself
    moved.append(node["id"])

# The Run Flow dropdown renders as "Select an option" because its options list is
# empty, even though the tool resolves correctly from flow_id_selected. Filling
# the list makes the canvas say which flow it calls.
for node in flow["data"]["nodes"]:
    if node["id"] == "RunFlow-brf02":
        field = node["data"]["node"]["template"]["flow_name_selected"]
        field["options"] = ["Arkon_Shift_Briefing"]
        field["options_metadata"] = [{"id": BRIEFING_FLOW_ID}]

flow["data"]["viewport"] = {"x": 0, "y": 0, "zoom": 0.5}

FLOW.write_text(json.dumps(flow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("laid out %d nodes" % len(moved))

# Report the grid so a collision is visible without opening the UI
HEIGHTS = {"Agent": 470, "SmartRouter": 470, "APIRequest": 420, "HumanInput": 370,
           "RunFlow": 370, "ChatInput": 210, "ChatOutput": 170,
           "QdrantVectorStoreComponent": 470, "OpenRouterEmbeddings": 370}
boxes = []
for node in flow["data"]["nodes"]:
    kind = node["data"]["type"]
    h = HEIGHTS.get(kind, 400)
    x, y = node["position"]["x"], node["position"]["y"]
    boxes.append((node["id"], x, y, x + 340, y + h))
for i, a in enumerate(boxes):
    for b in boxes[i + 1:]:
        if a[1] < b[3] and b[1] < a[3] and a[2] < b[4] and b[2] < a[4]:
            print("  OVERLAP:", a[0], "and", b[0])
print("collision check done")
