"""Generate the temporary Langflow canvases the Course 2B deck is screenshotted from.

A fit-to-view capture of the 19-node assistant canvas is unreadable, and Langflow
has neither a per-route colour nor a branch filter. So the pictures are built as
flows of their own from the real JSON, captured in the UI, and deleted again. The
deployed canvases are never edited: every flow written here is a copy named
``ZZ_Deck_*``.

- ``ZZ_Deck_Route_1_Procedure`` to ``ZZ_Deck_Route_6_Unclear``: one frame per
  route, holding Chat Input, the Intent Router with all six outputs (so the router
  looks the same in every frame) and the nodes reachable from that one route
  through to its Chat Output, tools included, laid out left to right.
- ``ZZ_Deck_Canvas_Coloured``: the whole canvas at its deployed positions, with a
  coloured Note behind each route (notes render behind nodes and carry a
  background colour; the palette is amber, blue, lime, neutral, rose, transparent).
- ``ZZ_Deck_Subflow``: the shift briefing sub-flow as it is deployed.

Route membership is computed from the edges (forward from the router output,
then back along tool edges) and checked against the explicit layout below, so a
node added to the canvas later is reported rather than silently left out of its
frame. The coloured canvas checks itself the same way: every node of a route must
sit inside one of its rectangles and no other node may touch them.

    python langflow/build/build_deck_canvases.py            # write the JSONs, report
    python langflow/build/build_deck_canvases.py --deploy   # upsert the eight flows, print their URLs
    python langflow/build/build_deck_canvases.py --delete   # remove every ZZ_Deck_* flow

Screenshots go to ``020 Projects/AI_Agents_2B_Meridian/build/submission/assets/`` under
the file names printed by ``--deploy``; the deck generator reads them by those names.
"""

import copy
import json
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).parent
REPO = HERE.parent.parent
MAIN = REPO / "langflow" / "arkon_quality_assistant.json"
SUBFLOW = REPO / "langflow" / "arkon_shift_briefing.json"
HOST = "ResSak@AK2101"
REMOTE = "cd ~/arkon-tmp && python3 lf_api.py"
UI = "http://AK2101:7860/flow/"
PREFIX = "ZZ_Deck_"

CHAT_INPUT = "ChatInput-tKQ4d"
ROUTER = "SmartRouter-rt001"
NODE_WIDTH = 320
TOOL_Y = 700  # the band below the main row; the router is 609 tall, so tools clear it

# Rendered node heights, read from the deployed canvas on 2026-09-07 (the UI writes
# them into `measured`; the repository JSON leaves them out so the UI re-measures).
HEIGHTS = {
    "ChatInput-tKQ4d": 207, "SmartRouter-rt001": 609, "APIRequest-inc01": 303,
    "Agent-EXpSZ": 431, "Agent-inc01": 431, "Agent-esc01": 431, "Agent-dec01": 431,
    "ChatOutput-KxTA8": 169, "ChatOutput-inc01": 169, "ChatOutput-esc01": 169,
    "ChatOutput-oos01": 169, "ChatOutput-dec01": 169, "ChatOutput-brf02": 169,
    "ChatOutput-unc01": 169, "HumanInput-esc01": 343, "APIRequest-esc01": 303,
    "OpenRouterEmbeddings-emb01": 305,
    "ext:qdrant:QdrantVectorStoreComponent@official-kb01": 295, "RunFlow-brf02": 321,
}

# One frame per route: number, name suffix, router output, note colour, label,
# caption, and the layout of every node in the frame (Chat Input and the router
# are always at the same two places so the frames line up side by side).
ROUTES = [
    {
        "number": 1, "suffix": "Procedure", "output": "category_1_result", "colour": "blue",
        "label": "Quality procedure",
        "caption": "Procedure Specialist with the Qdrant document store as its tool; the answer names its source.",
        "layout": {
            CHAT_INPUT: (0, 0), ROUTER: (450, 0),
            "Agent-EXpSZ": (900, 0), "ChatOutput-KxTA8": (1350, 0),
            "OpenRouterEmbeddings-emb01": (450, TOOL_Y),
            "ext:qdrant:QdrantVectorStoreComponent@official-kb01": (900, TOOL_Y),
        },
    },
    {
        "number": 2, "suffix": "Incident", "output": "category_2_result", "colour": "amber",
        "label": "Incident status",
        "caption": "Incident Specialist with the live status API as its tool; found, empty, bad request and failed stay distinct.",
        "layout": {
            CHAT_INPUT: (0, 0), ROUTER: (450, 0),
            "Agent-inc01": (900, 0), "ChatOutput-inc01": (1350, 0),
            "APIRequest-inc01": (900, TOOL_Y),
        },
    },
    {
        "number": 3, "suffix": "Escalation", "output": "category_3_result", "colour": "rose",
        "label": "Escalation request",
        "caption": "The approval gate: Approve reaches the one write, the escalation record API; Reject answers with the reason.",
        "layout": {
            CHAT_INPUT: (0, 0), ROUTER: (450, 0),
            "HumanInput-esc01": (900, 0),
            "Agent-esc01": (1350, 0), "ChatOutput-esc01": (1800, 0),
            "Agent-dec01": (1350, TOOL_Y), "ChatOutput-dec01": (1800, TOOL_Y),
            "APIRequest-esc01": (900, TOOL_Y),
        },
    },
    {
        "number": 4, "suffix": "OutOfScope", "output": "category_4_result", "colour": "neutral",
        "label": "Out of scope",
        "caption": "A fixed reply saying what the assistant covers; no model call.",
        "layout": {CHAT_INPUT: (0, 0), ROUTER: (450, 0), "ChatOutput-oos01": (900, 200)},
    },
    {
        "number": 5, "suffix": "Briefing", "output": "category_5_result", "colour": "lime",
        "label": "Shift briefing",
        "caption": "Run Flow into the Arkon_Shift_Briefing sub-flow; no agent in the path, so the four blocks are never reworded.",
        "layout": {
            CHAT_INPUT: (0, 0), ROUTER: (450, 0),
            "RunFlow-brf02": (900, 0), "ChatOutput-brf02": (1350, 0),
        },
    },
    {
        "number": 6, "suffix": "Unclear", "output": "category_6_result", "colour": "transparent",
        "label": "Unclear request",
        "caption": "A fixed reply naming the missing piece (incident id, document, action); no model call.",
        "layout": {CHAT_INPUT: (0, 0), ROUTER: (450, 0), "ChatOutput-unc01": (900, 200)},
    },
]

# The coloured whole canvas: rectangles (x1, y1, x2, y2) per route in the deployed
# coordinate system, 40 px around the nodes. A route whose nodes are not one block
# (the tool band sits below the agents) gets one rectangle per block, all in the
# route's colour; the first carries the label, the others a short continuation.
RECTS = {
    1: [((-2140, -1340, 210, -280), None)],
    2: [((-1090, -190, -690, 320), None),
        ((-690, -190, 210, 110), "the Incident Answer"),
        ((-1690, 660, -1290, 1040), "the Incident Specialist's tool: the live status API")],
    3: [((-1090, 410, 210, 1470), None),
        ((-1090, 1510, -690, 1890), "the Escalation Specialist's tool: the escalation record API")],
    4: [((-190, 120, 210, 360), None)],
    5: [((-1090, 2210, 210, 2610), None)],
    6: [((-190, 1560, 210, 1810), None)],
}

SCREENSHOTS = {
    "Route": "langflow_route_{number}_{slug}.png",
    "Canvas_Coloured": "langflow_canvas_coloured.png",
    "Subflow": "langflow_briefing_subflow.png",
}


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def route_members(flow, output_name):
    """Nodes reachable from one router output, plus the tools feeding them."""
    edges = flow["data"]["edges"]
    members = {e["target"] for e in edges
               if e["source"] == ROUTER and e["data"]["sourceHandle"]["name"] == output_name}
    grown = True
    while grown:
        grown = False
        for e in edges:
            if e["source"] in members and e["target"] not in members and e["target"] != ROUTER:
                members.add(e["target"])
                grown = True
            if e["target"] in members and e["source"] not in members and e["source"] not in (ROUTER, CHAT_INPUT):
                members.add(e["source"])
                grown = True
    return members | {CHAT_INPUT, ROUTER}


def expand_output(node):
    """Show Chat Output nodes in full: the repository export keeps them collapsed
    (showNode false), and a collapsed pill truncates its own name to "Procedure A...".
    The deployed canvas shows them expanded, so the pictures match the demo."""
    if node["id"].startswith("ChatOutput-"):
        node["data"]["showNode"] = True


def frame(flow, route):
    """One route's nodes at the frame layout, with only the edges inside the frame."""
    members = route_members(flow, route["output"])
    laid_out = set(route["layout"])
    if members != laid_out:
        raise SystemExit("route %d: reachable %s, laid out %s"
                         % (route["number"], sorted(members - laid_out), sorted(laid_out - members)))
    nodes = []
    for node in flow["data"]["nodes"]:
        if node["id"] in members:
            node = copy.deepcopy(node)
            x, y = route["layout"][node["id"]]
            node["position"] = {"x": x, "y": y}
            node.pop("measured", None)
            node["selected"] = False
            expand_output(node)
            nodes.append(node)
    edges = [copy.deepcopy(e) for e in flow["data"]["edges"]
             if e["source"] in members and e["target"] in members]
    name = "%sRoute_%d_%s" % (PREFIX, route["number"], route["suffix"])
    return {
        "name": name,
        "description": "Deck frame, route %d of the Arkon Quality Assistant: %s. Temporary, delete after the screenshot."
                       % (route["number"], route["label"]),
        "endpoint_name": name.lower().replace("_", "-"),
        "data": {"nodes": nodes, "edges": edges, "viewport": {"x": 0, "y": 0, "zoom": 0.5}},
    }


def note(node_id, rect, colour, text):
    """A Langflow note: type noteNode, colour in the template, size on the envelope.

    The shape is the one Langflow's own starter projects carry (read out of the
    running image on 2026-09-07): ``width``/``height`` plus ``measured`` on the node
    envelope, ``backgroundColor`` under ``data.node.template``.
    """
    x1, y1, x2, y2 = rect
    width, height = x2 - x1, y2 - y1
    return {
        "id": node_id,
        "type": "noteNode",
        "position": {"x": x1, "y": y1},
        "data": {
            "id": node_id,
            "type": "note",
            "node": {
                "description": text,
                "display_name": "",
                "documentation": "",
                "template": {"backgroundColor": colour},
            },
        },
        "width": width,
        "height": height,
        "measured": {"width": width, "height": height},
        "dragging": False,
        "resizing": False,
        "selected": False,
    }


def box(node):
    x, y = node["position"]["x"], node["position"]["y"]
    return (x, y, x + NODE_WIDTH, y + HEIGHTS[node["id"]])


def inside(inner, outer):
    return inner[0] >= outer[0] and inner[1] >= outer[1] and inner[2] <= outer[2] and inner[3] <= outer[3]


def touches(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def coloured(flow):
    """The deployed canvas with one coloured note block per route behind the nodes."""
    by_id = {node["id"]: node for node in flow["data"]["nodes"]}
    owner = {}
    for route in ROUTES:
        for node_id in route_members(flow, route["output"]) - {CHAT_INPUT, ROUTER}:
            owner[node_id] = route["number"]
    notes, problems = [], []
    for route in ROUTES:
        n = route["number"]
        rects = RECTS[n]
        mine = [by_id[i] for i, r in owner.items() if r == n]
        for node in mine:
            if not any(inside(box(node), rect) for rect, _ in rects):
                problems.append("route %d: %s is not inside any of its rectangles" % (n, node["id"]))
        for rect, _ in rects:
            for node in flow["data"]["nodes"]:
                if owner.get(node["id"]) != n and touches(box(node), rect):
                    problems.append("route %d: rectangle %s touches %s" % (n, rect, node["id"]))
        for index, (rect, continuation) in enumerate(rects, start=1):
            if continuation is None:
                text = "## %d  %s\n\n%s" % (n, route["label"], route["caption"])
            else:
                text = "**%d  %s**, %s" % (n, route["label"], continuation)
            notes.append(note("note-r%d%s" % (n, chr(96 + index)), rect, route["colour"], text))
    if problems:
        raise SystemExit("coloured canvas:\n  " + "\n  ".join(problems))
    nodes = notes + [copy.deepcopy(node) for node in flow["data"]["nodes"]]  # notes first: behind
    for node in nodes[len(notes):]:
        node["selected"] = False
        expand_output(node)
    name = PREFIX + "Canvas_Coloured"
    return {
        "name": name,
        "description": "Deck frame: the whole Arkon Quality Assistant canvas with one colour per route. Temporary, delete after the screenshot.",
        "endpoint_name": "zz-deck-canvas-coloured",
        "data": {"nodes": nodes, "edges": copy.deepcopy(flow["data"]["edges"]),
                 "viewport": {"x": 0, "y": 0, "zoom": 0.25}},
    }


def subflow_copy(flow):
    name = PREFIX + "Subflow"
    out = copy.deepcopy(flow)
    out["name"] = name
    out["description"] = "Deck frame: the Arkon_Shift_Briefing sub-flow as deployed. Temporary, delete after the screenshot."
    out["endpoint_name"] = "zz-deck-subflow"
    return out


def ssh(command, stdin=None):
    result = subprocess.run(["ssh", HOST, command], input=stdin, capture_output=True)
    if result.returncode != 0:
        raise SystemExit("ssh failed: %s\n%s" % (command, result.stderr.decode("utf-8", "replace")[-2000:]))
    return result.stdout.decode("utf-8", "replace")


def deployed_flows():
    flows = {}
    for line in ssh("%s list" % REMOTE).splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].startswith(PREFIX):
            flows[parts[1]] = parts[0]
    return flows


def screenshot_name(flow_name):
    kind = flow_name[len(PREFIX):]
    if kind.startswith("Route_"):
        _, number, suffix = kind.split("_", 2)
        return SCREENSHOTS["Route"].format(number=number, slug=suffix.lower())
    return SCREENSHOTS[kind]


def main():
    if "--delete" in sys.argv:
        flows = deployed_flows()
        for name, flow_id in sorted(flows.items()):
            print(ssh("%s delete %s" % (REMOTE, flow_id)).strip(), name)
        print("%d deck flows deleted" % len(flows))
        return

    main_flow = load(MAIN)
    flows = [frame(main_flow, route) for route in ROUTES]
    flows.append(coloured(main_flow))
    flows.append(subflow_copy(load(SUBFLOW)))

    out_dir = pathlib.Path(tempfile.mkdtemp(prefix="arkon_deck_"))
    for flow in flows:
        path = out_dir / (flow["name"] + ".json")
        path.write_text(json.dumps(flow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("%-28s %2d nodes %2d edges  -> %s" % (flow["name"], len(flow["data"]["nodes"]),
                                                    len(flow["data"]["edges"]), screenshot_name(flow["name"])))
    print("written to", out_dir)

    if "--deploy" not in sys.argv:
        return
    for flow in flows:
        remote = "/tmp/deck_%s.json" % flow["name"]
        ssh("cat > %s" % remote, stdin=(out_dir / (flow["name"] + ".json")).read_bytes())
        print(ssh("%s upsert %s" % (REMOTE, remote)).strip())
    print()
    print("Open each canvas, press fit view, screenshot, save under assets/ as named:")
    for name, flow_id in sorted(deployed_flows().items()):
        print("  %s%s   %-28s -> %s" % (UI, flow_id, name, screenshot_name(name)))


if __name__ == "__main__":
    main()
