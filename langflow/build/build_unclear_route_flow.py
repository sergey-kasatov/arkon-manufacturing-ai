"""Give the router somewhere to put a message it cannot place.

The named gap after the briefing branch was that an underspecified question is answered as
an off-topic one. "And what about that one?" with no antecedent reached the
out-of-scope branch, so the operator was told the assistant does not handle that
subject when the truth was that it could not tell which subject was meant.
Nothing was invented, which is the behaviour that matters, but the reason was
wrong.

**Why a sixth route and not the Else output.** Smart Router does have one:
`enable_else_output`, off by default. Read in `llm_conditional_router.py` in the
running container, its branch returns the `Override Output` field if set and the
user's own input text otherwise, and `Override Output` is documented on the
component as replacing the output value for all routes rather than just Else. So
the Else branch cannot carry its own words without another node behind it, while
a route can: the out-of-scope branch already answers from a fixed `output_value`
with no model call. A sixth route costs the same and can say which piece is
missing.

The cost of either option is the same and it is not the building. A sixth
destination changes the classification surface for all five existing routes, so
the seven-exchange protocol runs again after this.

Run after build_briefing_branch_flow.py and before layout_flow.py:

    python langflow/build/build_unclear_route_flow.py
    python langflow/build/layout_flow.py
"""

import json
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import lfbuild
import prompts

HERE = pathlib.Path(__file__).parent
REPO = HERE.parent.parent
FLOW = REPO / "langflow" / "arkon_quality_assistant.json"
PROMPTS = prompts.PROMPT_DIR
HOST = "ResSak@AK2101"
REMOTE = "cd ~/arkon-tmp && python3 lf_api.py"

ROUTE_NAME = "Unclear request"


def blocks():
    return prompts.load()


def node_by_name(flow, display_name):
    for node in flow["data"]["nodes"]:
        if node["data"]["node"].get("display_name") == display_name:
            return node
    raise SystemExit("no node named %r on the canvas" % display_name)


def main():
    flow = json.loads(FLOW.read_text(encoding="utf-8"))
    text = blocks()
    for needed in ("route_unclear", "unclear_message", "router_instructions_v3"):
        if needed not in text:
            raise SystemExit("block %r missing from %s" % (needed, PROMPTS.name))

    nodes = {node["id"]: node for node in flow["data"]["nodes"]}
    router = node_by_name(flow, "Intent Router")
    template = router["data"]["node"]["template"]
    routes = template["routes"]["value"]

    if any(route["route_category"] == ROUTE_NAME for route in routes):
        print("the %r route is already on the canvas" % ROUTE_NAME)
        return

    # The new route goes last, so every existing category_N_result keeps its
    # number and no existing edge has to be rewired.
    routes.append({
        "route_category": ROUTE_NAME,
        "route_description": text["route_unclear"].strip(),
        "output_value": text["unclear_message"].strip(),
    })
    template["routes"]["value"] = routes
    template["custom_prompt"]["value"] = text["router_instructions_v3"].strip()
    router["data"]["node"]["outputs"] = lfbuild.router_outputs(routes, enable_else=False)
    unclear_output = "category_%d_result" % len(routes)

    # The out-of-scope output is the right shape to copy: a Chat Output fed a
    # fixed Route Message, so the branch answers with no model call at all.
    answer = lfbuild.clone_node(
        nodes["ChatOutput-oos01"], "ChatOutput-unc01", (-600, 2400),
        display_name="Unclear Answer",
    )

    flow["data"]["nodes"] = list(nodes.values()) + [answer]
    flow["data"]["edges"] = flow["data"]["edges"] + [
        lfbuild.edge(router, unclear_output, answer, "input_value"),
    ]

    FLOW.write_text(json.dumps(flow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote %s" % FLOW.name)
    print("nodes: %d  edges: %d" % (len(flow["data"]["nodes"]), len(flow["data"]["edges"])))
    print("routes: %s" % [route["route_category"] for route in routes])
    print("new output %s -> Unclear Answer" % unclear_output)

    if "--deploy" in sys.argv:
        subprocess.run(["ssh", HOST, "cat > /tmp/arkon_flow.json"],
                       input=FLOW.read_bytes(), check=True)
        result = subprocess.run(["ssh", HOST, "%s upsert /tmp/arkon_flow.json" % REMOTE],
                                capture_output=True, check=True)
        print(result.stdout.decode("utf-8", "replace").strip())


if __name__ == "__main__":
    main()
