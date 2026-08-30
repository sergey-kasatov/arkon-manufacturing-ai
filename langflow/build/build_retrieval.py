"""Give the procedure specialist the document store and take the rules out of its prompt.

Completes the Sprint 2 retrieval requirement on the existing canvas. Two nodes are
added - the custom OpenRouter embeddings and the Qdrant store in tool mode - and
one prompt is replaced. Nothing else on the canvas changes.

The store is reached as a tool rather than as a fixed retrieval chain in front of
the specialist. The specialist is already an agent, the canvas already gives its
siblings tools, and a tool lets the model search twice with different words when
the first query misses. A fixed chain retrieves once, on whatever the operator
happened to type.

Run after the sprint scripts and before layout_flow.py:

    python langflow/build/build_ingest_flow.py --deploy
    python langflow/build/build_retrieval.py
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
    r"C:\Users\kasser\AI-Brain\020 Projects\AI_Agents_2B_Meridian\build\document_store.md"
)
COLLECTION = "arkon-knowledge"
QDRANT_HOST = "qdrant"
# The course LS6 value. Raise it only on evidence from the validation re-run, so
# that any change is a measured tuning decision rather than a hedge.
RESULTS = 4

TOOL_OUTPUT = {
    "allows_loop": False, "cache": True, "display_name": "Toolset", "group_outputs": False,
    "method": "to_toolkit", "name": "component_as_tool", "selected": "Tool",
    "types": ["Tool"], "value": "__UNDEFINED__",
}


def spec(name):
    return json.loads((HERE / ("spec_%s.json" % name)).read_text(encoding="utf-8"))["spec"]


blocks = dict(
    re.findall(r"### BLOCK: (\w+)\n\n```text\n(.*?)\n```", PROMPTS.read_text(encoding="utf-8"), flags=re.S)
)
if "procedure_v2" not in blocks:
    raise SystemExit("prompt block procedure_v2 missing from " + str(PROMPTS))

flow = json.loads(FLOW.read_text(encoding="utf-8"))
nodes = {node["id"]: node for node in flow["data"]["nodes"]}
procedure = nodes["Agent-EXpSZ"]
# Re-runnable: a prompt change should not need the whole sprint chain replayed,
# and it must not add a second copy of the store.
already = "OpenRouterEmbeddings-emb01" in nodes
if already:
    for node_id in ("OpenRouterEmbeddings-emb01", "ext:qdrant:QdrantVectorStoreComponent@official-kb01"):
        nodes.pop(node_id)
    flow["data"]["edges"] = [
        edge for edge in flow["data"]["edges"]
        if edge["source"] in nodes and edge["target"] in nodes
    ]

embeddings = lfbuild.node_from_spec(
    spec("openrouterembeddings"), "OpenRouterEmbeddings-emb01", (-1250, -420),
    display_name="OpenRouter Embeddings",
)
knowledge = lfbuild.node_from_spec(
    spec("qdrant"), "ext:qdrant:QdrantVectorStoreComponent@official-kb01", (-1050, -60),
    values={
        "collection_name": COLLECTION,
        "host": QDRANT_HOST,
        "port": 6333,
        "distance_func": "Cosine",
        "number_of_results": RESULTS,
    },
    outputs=[TOOL_OUTPUT],
    selected_output="component_as_tool",
    tool_mode=True,
    type_name="QdrantVectorStoreComponent",
    display_name="Arkon Knowledge Base",
)
# An untouched SecretStrInput arrives as "", and qdrant-client reads any non-None
# api_key as Qdrant Cloud and switches to https. See build_ingest_flow.py.
api_key_field = knowledge["data"]["node"]["template"]["api_key"]
api_key_field["value"] = None
api_key_field["load_from_db"] = False

prompt_field = procedure["data"]["node"]["template"]["system_prompt"]
was = len(prompt_field["value"] or "")
prompt_field["value"] = blocks["procedure_v2"].strip()

flow["data"]["nodes"] = list(nodes.values()) + [embeddings, knowledge]
flow["data"]["edges"] = flow["data"]["edges"] + [
    lfbuild.edge(embeddings, "embeddings", knowledge, "embedding"),
    lfbuild.edge(knowledge, "component_as_tool", procedure, "tools"),
]
flow["description"] = (
    "MSIT Term 12 course 2B project. Conversational front end for the Arkon Quality "
    "Steering Cell: grounded retrieval over the Arkon documents, intent routing, a live "
    "incident lookup, a human approval gate in front of the escalation write path, and "
    "the shift briefing sub-flow invoked through Run Flow."
)

FLOW.write_text(json.dumps(flow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("wrote", FLOW.name)
print("nodes:", len(flow["data"]["nodes"]), " edges:", len(flow["data"]["edges"]))
print("procedure prompt: %d characters, was %d" % (len(prompt_field["value"]), was))
