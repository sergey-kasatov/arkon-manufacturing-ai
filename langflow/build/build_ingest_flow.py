"""Build the Arkon knowledge ingestion flow.

The Arkon documents into the Qdrant collection `arkon-knowledge`, one lane per
document, each lane stamping its own `source` value onto every chunk it produces.
The set is `DOCUMENTS` below and nothing else counts them, because a count
written into prose is a claim that ages.

The shape is the standard RAG ingestion flow - read, split, embed, store, with
the store's own search output wired to a Chat Output - with two changes, both
forced by what the components actually do:

- The embedding component is ours. Nothing Langflow ships can reach OpenRouter's
  embedding models; the reason is written at the top of
  `langflow/components/openrouter_embeddings.py`.
- One lane per document instead of one File node holding all four. A File node
  given several files emits a DataFrame whose only provenance column is the
  resolved container path, `/app/langflow/<user-uuid>/<name>.md`, and an answer
  citing that is worse than an answer citing nothing. A lane per document buys a
  human-readable source name for the price of nodes on a flow that runs rarely.

Run it from the repository root:

    python langflow/build/fetch_specs.py
    python langflow/build/build_ingest_flow.py
    python langflow/build/build_ingest_flow.py --deploy   # upload, upsert, ingest
"""

import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import lfbuild

HERE = pathlib.Path(__file__).parent
REPO = HERE.parent.parent
FLOW = REPO / "langflow" / "arkon_knowledge_ingest.json"
HOST = "ResSak@AK2101"
REMOTE = "cd ~/arkon-tmp && python3 lf_api.py"

FLOW_NAME = "Arkon_Knowledge_Ingest"
ENDPOINT = "arkon-knowledge-ingest"
COLLECTION = "arkon-knowledge"
# The container name resolves inside the shared msit network. It also has to be
# in LANGFLOW_SSRF_ALLOWED_HOSTS: the Qdrant component runs the same private-IP
# guard that blocked the n8n call.
QDRANT_HOST = "qdrant"
QDRANT_PORT = 6333
# Kept deliberately at the conventional starting values: 1000 characters with a
# 200 overlap. Any change belongs in the validation record with its evidence.
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200

# repo path -> (upload name, source label written into every chunk's metadata)
DOCUMENTS = [
    ("docs/Project_Charter.md", "Arkon_Project_Charter.md", "Arkon Project Charter"),
    ("docs/Steering_Cell_SOP.md", "Quality_Steering_Cell_SOP.md", "Quality Steering Cell SOP"),
    ("docs/Model_Card_CMAPSS_RUL.md", "CMAPSS_RUL_Model_Card.md", "CMAPSS RUL Model Card"),
    # Phase 2, added 2026-08-30. This is the claim the store was built for: a new
    # module is added by writing its model card and dropping it in here, not by
    # editing a prompt.
    ("docs/Model_Card_Scania_APS.md", "Scania_APS_Model_Card.md", "Scania APS Model Card"),
    ("docs/Model_Card_Casting_CV.md", "Casting_Defect_Model_Card.md", "Casting Defect Model Card"),
    # Phase 2, added 2026-09-01. Fourth module, second in the visual_inspection
    # domain, and the seventh document in the store.
    ("docs/Model_Card_NEU_Surface.md", "NEU_Surface_Model_Card.md", "NEU Surface Defect Model Card"),
    ("events/README.md", "Arkon_Event_Contract.md", "Arkon Event Contract"),
]


def spec(name):
    return json.loads((HERE / ("spec_%s.json" % name)).read_text(encoding="utf-8"))["spec"]


def ssh(command, stdin=None):
    """Run a command on the NAS. stdin is bytes, so nothing is newline-translated.

    Passing text through here once turned every LF into CRLF and put 200 stray
    bytes into an uploaded document.
    """
    result = subprocess.run(["ssh", HOST, command], input=stdin, capture_output=True)
    if result.returncode != 0:
        raise SystemExit("ssh failed: %s\n%s" % (command, result.stderr.decode("utf-8", "replace")[-2000:]))
    return result.stdout.decode("utf-8")


def purge_uploads():
    """Delete any stored copy of a document we are about to upload.

    /api/v2/files does not overwrite. Uploading a name that is already there
    stores it as "<name> (1)", so every deploy used to add another copy, rewrite
    the File paths in the flow JSON, and leave the superseded document sitting in
    the store where a later build or a hand edit in the UI could pick it up
    again. Deleting first makes the stored path stable across deploys and takes
    the old document out of reach.
    """
    wanted = {name.rsplit(".", 1)[0] for _, name, _ in DOCUMENTS}
    listing = json.loads(ssh("%s raw GET /api/v2/files" % REMOTE))
    files = listing if isinstance(listing, list) else listing.get("files", [])
    for entry in files:
        # a re-upload is stored as "Name (1)", so match the stem as well
        stem = entry["name"].split(" (")[0]
        if stem in wanted:
            ssh("%s raw DELETE /api/v2/files/%s" % (REMOTE, entry["id"]))
            print("  removed  %-34s %7d bytes" % (entry["name"], entry["size"]))


def upload_documents():
    """Put each document into the Langflow file store and return its stored path."""
    purge_uploads()
    stored = []
    for repo_path, upload_name, label in DOCUMENTS:
        source = REPO / repo_path
        if not source.exists():
            raise SystemExit("missing document: %s" % source)
        ssh("cat > '/tmp/%s'" % upload_name, stdin=source.read_bytes())
        answer = json.loads(ssh("%s upload '/tmp/%s'" % (REMOTE, upload_name)))
        if not answer["path"].endswith("/" + upload_name):
            raise SystemExit("stored under an unexpected path, purge did not take: %s" % answer["path"])
        stored.append(answer["path"])
        print("  uploaded %-34s %7d bytes  source=%s" % (upload_name, answer["size"], label))
    return stored


def reveal(node, *fields):
    """Mark operation-specific fields visible, the way the UI would.

    Table Operations hides every field that does not belong to the chosen
    operation, and the parameter handler skips hidden fields. Setting only the
    values leaves new_column_name as None, so the store ends up with a metadata
    key literally named None: no error, no warning, and a document store whose
    source labels are all missing.
    """
    template = node["data"]["node"]["template"]
    for field in fields:
        template[field]["show"] = True


def clear_qdrant_api_key(node):
    """Leave the Qdrant API key genuinely unset, not set to an empty string.

    An untouched SecretStrInput arrives as "", the component passes it through
    because it filters on None, and qdrant-client reads any non-None api_key as
    "this is Qdrant Cloud" and switches the scheme to https. The local store
    speaks plain http on 6333, so the run dies with
    "[SSL: RECORD_LAYER_FAILURE] record layer failure", which points at
    certificates and has nothing to do with them.
    """
    field = node["data"]["node"]["template"]["api_key"]
    field["value"] = None
    field["load_from_db"] = False


def build(stored_paths):
    nodes, edges = [], []
    # Below the last lane, computed rather than fixed: a hard-coded y collided
    # with lane 5 the moment two more documents were added, and the overlap
    # check in this file is what caught it.
    embeddings = lfbuild.node_from_spec(
        spec("openrouterembeddings"), "OpenRouterEmbeddings-emb01",
        (-700, len(DOCUMENTS) * 520 + 80),
        display_name="OpenRouter Embeddings",
    )
    store = lfbuild.node_from_spec(
        spec("qdrant"), "ext:qdrant:QdrantVectorStoreComponent@official-qd001", (-250, 780),
        values={
            "collection_name": COLLECTION,
            "host": QDRANT_HOST,
            "port": QDRANT_PORT,
            "distance_func": "Cosine",
            "number_of_results": 4,
        },
        type_name="QdrantVectorStoreComponent",
        display_name="Arkon Knowledge Store",
    )
    clear_qdrant_api_key(store)
    answer = lfbuild.node_from_spec(
        spec("chatoutput"), "ChatOutput-ing01", (170, 780), display_name="Ingest Result",
    )
    nodes += [embeddings, store, answer]
    edges += [
        lfbuild.edge(embeddings, "embeddings", store, "embedding"),
        lfbuild.edge(store, "search_results", answer, "input_value"),
    ]

    for index, ((repo_path, upload_name, label), stored) in enumerate(zip(DOCUMENTS, stored_paths), start=1):
        top = (index - 1) * 520
        reader = lfbuild.node_from_spec(
            spec("file"), "File-doc%d" % index, (-1560, top),
            values={
                "path": [stored],
                # The default deletes the uploaded file once the run is over, which
                # turns a repeatable ingestion into a single-use one.
                "delete_server_file_after_processing": False,
            },
            display_name=label,
        )
        # A file field is read from template["path"]["file_path"], not from its
        # value: see param_handler.process_file_value. Setting only the value
        # produces a node that looks configured in the JSON and then fails at run
        # time with "No files to process", which reads like a missing upload.
        reader["data"]["node"]["template"]["path"]["file_path"] = [stored]
        splitter = lfbuild.node_from_spec(
            spec("splittext"), "SplitText-doc%d" % index, (-1160, top),
            # clean_output keeps only the text and drops the source Message's own
            # fields, which is the opposite of the component default and is required
            # rather than tidy. A File node's Raw Content output is a Message, so
            # without it every chunk inherits run_id, flow_id, timestamp, a column
            # literally named None (which crashes the store's id hashing on
            # sort_keys), and a per-run timestamp that would change the content
            # hash and re-insert every chunk on every run.
            values={"chunk_size": CHUNK_SIZE, "chunk_overlap": CHUNK_OVERLAP, "clean_output": True},
            display_name="Split: %s" % label,
        )
        stamp = lfbuild.node_from_spec(
            spec("tableops"), "DataFrameOperations-doc%d" % index, (-760, top),
            values={
                "operation": [{"name": "Add Column", "icon": "plus"}],
                "new_column_name": "source",
                "new_column_value": label,
            },
            display_name="Source: %s" % label,
        )
        reveal(stamp, "new_column_name", "new_column_value")
        nodes += [reader, splitter, stamp]
        edges += [
            lfbuild.edge(reader, "message", splitter, "data_inputs"),
            lfbuild.edge(splitter, "dataframe", stamp, "df"),
            lfbuild.edge(stamp, "output", store, "ingest_data"),
        ]

    return {
        "name": FLOW_NAME,
        "endpoint_name": ENDPOINT,
        "description": (
            "Ingestion side of the Arkon document store. Reads the Arkon source "
            "documents, splits them at %d characters with a %d overlap, stamps each chunk "
            "with the name of the document it came from, and writes them to the Qdrant "
            "collection %s. The embedding component is custom because no shipped one can "
            "reach OpenRouter." % (CHUNK_SIZE, CHUNK_OVERLAP, COLLECTION)
        ),
        "is_component": False,
        "locked": False,
        "tags": [],
        "data": {"nodes": nodes, "edges": edges, "viewport": {"x": 0, "y": 0, "zoom": 0.5}},
    }


def overlapping(nodes):
    """Report any pair of node boxes that overlap, the way layout_flow.py does."""
    boxes = [(n["id"], n["position"]["x"], n["position"]["y"],
              n["measured"]["width"], n["measured"]["height"]) for n in nodes]
    clashes = []
    for i, (aid, ax, ay, aw, ah) in enumerate(boxes):
        for bid, bx, by, bw, bh in boxes[i + 1:]:
            if ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah:
                clashes.append((aid, bid))
    return clashes


if __name__ == "__main__":
    deploy = "--deploy" in sys.argv
    if deploy:
        print("uploading documents")
        paths = upload_documents()
    else:
        existing = json.loads(FLOW.read_text(encoding="utf-8")) if FLOW.exists() else None
        paths = None
        if existing:
            paths = [
                node["data"]["node"]["template"]["path"]["value"][0]
                for node in existing["data"]["nodes"] if node["id"].startswith("File-doc")
            ]
        if not paths:
            raise SystemExit("no stored paths yet: run once with --deploy")
        # build() zips DOCUMENTS against these paths, and zip stops at the shorter
        # one. Adding a document and building without --deploy therefore used to
        # write a flow silently missing its lane: no error, no warning, and an
        # ingest that loads one document fewer than the list says.
        if len(paths) != len(DOCUMENTS):
            raise SystemExit(
                "%d documents but %d stored paths. The new one has never been uploaded; "
                "run with --deploy." % (len(DOCUMENTS), len(paths)))

    flow = build(paths)
    clashes = overlapping(flow["data"]["nodes"])
    if clashes:
        raise SystemExit("overlapping nodes: %s" % clashes)
    FLOW.write_text(json.dumps(flow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote %s: %d nodes, %d edges" % (FLOW.name, len(flow["data"]["nodes"]), len(flow["data"]["edges"])))

    if deploy:
        ssh("cat > /tmp/ingest_flow.json", stdin=FLOW.read_bytes())
        print(ssh("%s upsert /tmp/ingest_flow.json" % REMOTE).strip())
