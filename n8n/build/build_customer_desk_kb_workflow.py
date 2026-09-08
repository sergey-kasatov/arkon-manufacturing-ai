"""Build the Arkon Customer Desk Knowledge Base n8n workflow JSON.

The document store of the Customer Quality Desk (2026-09-08): the three
customer documents of `customer_documents.py`, chunked and embedded into the
Qdrant collection `arkon-customer-desk`, plus a retrieval endpoint over the
same collection through the same embedding node the desk agent will query it
with, so the in-store retrieval test measures the path the agent takes.

Two webhooks in one workflow, both LAN and Tailscale only:

    POST /webhook/arkon-customer-desk-ingest   drop the collection, ingest the three documents
    GET  /webhook/arkon-customer-desk-search?q=  the top-k passages for a query, with sources

The texts are injected verbatim from `docs/customer/` at build time, so the
tracked workflow is the record of what the collection holds and
`tests/test_generators.py` fails when a document changes without a rebuild.
The ingest drops the collection first because the Qdrant insert node appends
under fresh point ids on every run: a second run without the drop is a
doubled store, silently.
"""

import json
import pathlib

from customer_documents import CHUNK_OVERLAP, CHUNK_SIZE, COLLECTION, EMBEDDING_MODEL, TOP_K, read_included

OUT = pathlib.Path(__file__).resolve().parent.parent / "customer_desk_kb_v1.json"

WORKFLOW_ID = "arkonCustDeskKB1"
INGEST_PATH = "arkon-customer-desk-ingest"
SEARCH_PATH = "arkon-customer-desk-search"
# The container name resolves inside the shared msit network, the same way the
# Qdrant credential reaches it; read from the container on 2026-09-08.
QDRANT_URL = "http://qdrant:6333"

# Credentials by id, as they exist on the instance (the tracked file carries
# ids and names only, never secrets; `n8n import:workflow` binds them).
QDRANT_CREDENTIAL = {"qdrantApi": {"id": "arkonQdrantLocal", "name": "Arkon Qdrant (local)"}}
GEMINI_CREDENTIAL = {"googlePalmApi": {"id": "GTyPBCXuMAicqhEB", "name": "Google Gemini(PaLM) Api account"}}

DOCUMENTS = read_included()

CUSTOMER_DOCUMENTS_JS = (
    r"""// Arkon Customer Desk Knowledge Base - the documents a customer may read.
// Injected verbatim from docs/customer/ by the generator, so the tracked
// workflow is the record of what the collection holds. One item per document;
// the loader stamps the source label on every chunk it makes from it.
const DOCUMENTS = """
    + json.dumps(DOCUMENTS, ensure_ascii=True, indent=2)
    + r""";

return DOCUMENTS.map((document) => ({
  json: {
    source: document.source,
    title: document.title,
    characters: document.text.length,
    text: document.text,
  },
}));
"""
)

COUNT_INGESTED_JS = r"""// Arkon Customer Desk Knowledge Base - the ingest answer.
// What was offered to the store, by document; the collection itself is
// measured by the probe, which counts the points Qdrant holds per source
// rather than trusting this node.
const offered = $("Customer Documents").all().map((item) => ({
  source: item.json.source,
  title: item.json.title,
  characters: item.json.characters,
}));
return [
  {
    json: {
      status: "ok",
      collection: "__COLLECTION__",
      documents: offered,
      items_emitted: $input.all().length,
      ingested_at: new Date().toISOString(),
    },
  },
];
""".replace("__COLLECTION__", COLLECTION)

COLLECT_PASSAGES_JS = r"""// Arkon Customer Desk Knowledge Base - the retrieval answer.
// The store in load mode emits one item per passage; collapse them into one
// answer carrying the source label and the score of each, so the retrieval
// test can say which document answered and how confidently.
const query = $("Search Request").first().json.query?.q ?? "";
const passages = $input.all()
  .filter((item) => item.json && (item.json.document || item.json.pageContent || item.json.page_content))
  .map((item, index) => {
    const document = item.json.document ?? item.json;
    return {
      rank: index + 1,
      source: document.metadata?.source ?? null,
      title: document.metadata?.title ?? null,
      score: item.json.score ?? null,
      characters: (document.pageContent ?? document.page_content ?? "").length,
      text: document.pageContent ?? document.page_content ?? "",
    };
  });
return [{ json: { status: "ok", collection: "__COLLECTION__", query, count: passages.length, passages } }];
""".replace("__COLLECTION__", COLLECTION)


def code_node(node_id, name, position, js):
    return {
        "id": node_id,
        "name": name,
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": position,
        "parameters": {"jsCode": js},
    }


def respond_node(node_id, name, position):
    return {
        "id": node_id,
        "name": name,
        "type": "n8n-nodes-base.respondToWebhook",
        "typeVersion": 1.1,
        "position": position,
        "parameters": {"respondWith": "json", "responseBody": "={{ JSON.stringify($json) }}", "options": {}},
    }


def embeddings_node(node_id, name, position):
    return {
        "id": node_id,
        "name": name,
        "type": "@n8n/n8n-nodes-langchain.embeddingsGoogleGemini",
        "typeVersion": 1,
        "position": position,
        "parameters": {"modelName": EMBEDDING_MODEL},
        "credentials": GEMINI_CREDENTIAL,
    }


def collection_ref():
    return {"__rl": True, "mode": "id", "value": COLLECTION}


workflow = {
    "id": WORKFLOW_ID,
    "name": "Arkon Customer Desk Knowledge Base v1",
    "nodes": [
        # -- ingest ------------------------------------------------------------
        {
            "id": "d1000000-0000-4000-8000-000000000001",
            "name": "Ingest Request",
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2,
            "position": [-1104, 0],
            "webhookId": INGEST_PATH,
            "parameters": {"httpMethod": "POST", "path": INGEST_PATH, "responseMode": "responseNode", "options": {}},
        },
        # Drop the collection before the insert: the insert node appends under
        # fresh point ids, so a rebuild without the drop doubles the store. A
        # collection that does not exist yet answers 404, which is not an error here.
        {
            "id": "d1000000-0000-4000-8000-000000000002",
            "name": "Reset Collection",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [-880, 0],
            "parameters": {
                "method": "DELETE",
                "url": "%s/collections/%s" % (QDRANT_URL, COLLECTION),
                "options": {"response": {"response": {"neverError": True, "fullResponse": True}}},
            },
        },
        code_node("d1000000-0000-4000-8000-000000000003", "Customer Documents", [-656, 0], CUSTOMER_DOCUMENTS_JS),
        {
            "id": "d1000000-0000-4000-8000-000000000004",
            "name": "Customer Desk Store",
            "type": "@n8n/n8n-nodes-langchain.vectorStoreQdrant",
            "typeVersion": 1.3,
            "position": [-432, 0],
            "parameters": {
                "mode": "insert",
                "qdrantCollection": collection_ref(),
                "embeddingBatchSize": 200,
                # The collection is created by the insert with the embedding's own
                # vector size (3072 for gemini-embedding-001) and Cosine distance;
                # the probe reads the created configuration back and asserts it.
                "options": {"contentPayloadKey": "content", "metadataPayloadKey": "metadata"},
            },
            "credentials": QDRANT_CREDENTIAL,
        },
        embeddings_node("d1000000-0000-4000-8000-000000000005", "Document Embeddings", [-560, 224]),
        {
            "id": "d1000000-0000-4000-8000-000000000006",
            "name": "Customer Document Loader",
            "type": "@n8n/n8n-nodes-langchain.documentDefaultDataLoader",
            "typeVersion": 1.1,
            "position": [-368, 224],
            "parameters": {
                "dataType": "json",
                "jsonMode": "expressionData",
                "jsonData": "={{ $json.text }}",
                "textSplittingMode": "custom",
                "options": {
                    "metadata": {
                        "metadataValues": [
                            {"name": "source", "value": "={{ $json.source }}"},
                            {"name": "title", "value": "={{ $json.title }}"},
                        ]
                    }
                },
            },
        },
        {
            "id": "d1000000-0000-4000-8000-000000000007",
            "name": "Chunker",
            "type": "@n8n/n8n-nodes-langchain.textSplitterRecursiveCharacterTextSplitter",
            "typeVersion": 1,
            "position": [-368, 432],
            "parameters": {"chunkSize": CHUNK_SIZE, "chunkOverlap": CHUNK_OVERLAP, "options": {}},
        },
        code_node("d1000000-0000-4000-8000-000000000008", "Count Ingested", [-16, 0], COUNT_INGESTED_JS),
        respond_node("d1000000-0000-4000-8000-000000000009", "Respond Ingest", [208, 0]),
        # -- search ------------------------------------------------------------
        {
            "id": "d1000000-0000-4000-8000-00000000000a",
            "name": "Search Request",
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2,
            "position": [-1104, 704],
            "webhookId": SEARCH_PATH,
            "parameters": {"httpMethod": "GET", "path": SEARCH_PATH, "responseMode": "responseNode", "options": {}},
        },
        {
            "id": "d1000000-0000-4000-8000-00000000000b",
            "name": "Customer Desk Search",
            "type": "@n8n/n8n-nodes-langchain.vectorStoreQdrant",
            "typeVersion": 1.3,
            "position": [-880, 704],
            "alwaysOutputData": True,
            "parameters": {
                "mode": "load",
                "qdrantCollection": collection_ref(),
                "prompt": "={{ $json.query.q }}",
                "topK": TOP_K,
                "includeDocumentMetadata": True,
                "options": {"contentPayloadKey": "content", "metadataPayloadKey": "metadata"},
            },
            "credentials": QDRANT_CREDENTIAL,
        },
        embeddings_node("d1000000-0000-4000-8000-00000000000c", "Query Embeddings", [-880, 928]),
        code_node("d1000000-0000-4000-8000-00000000000d", "Collect Passages", [-656, 704], COLLECT_PASSAGES_JS),
        respond_node("d1000000-0000-4000-8000-00000000000e", "Respond Search", [-432, 704]),
    ],
    "connections": {
        "Ingest Request": {"main": [[{"node": "Reset Collection", "type": "main", "index": 0}]]},
        "Reset Collection": {"main": [[{"node": "Customer Documents", "type": "main", "index": 0}]]},
        "Customer Documents": {"main": [[{"node": "Customer Desk Store", "type": "main", "index": 0}]]},
        "Document Embeddings": {"ai_embedding": [[{"node": "Customer Desk Store", "type": "ai_embedding", "index": 0}]]},
        "Customer Document Loader": {"ai_document": [[{"node": "Customer Desk Store", "type": "ai_document", "index": 0}]]},
        "Chunker": {"ai_textSplitter": [[{"node": "Customer Document Loader", "type": "ai_textSplitter", "index": 0}]]},
        "Customer Desk Store": {"main": [[{"node": "Count Ingested", "type": "main", "index": 0}]]},
        "Count Ingested": {"main": [[{"node": "Respond Ingest", "type": "main", "index": 0}]]},
        "Search Request": {"main": [[{"node": "Customer Desk Search", "type": "main", "index": 0}]]},
        "Query Embeddings": {"ai_embedding": [[{"node": "Customer Desk Search", "type": "ai_embedding", "index": 0}]]},
        "Customer Desk Search": {"main": [[{"node": "Collect Passages", "type": "main", "index": 0}]]},
        "Collect Passages": {"main": [[{"node": "Respond Search", "type": "main", "index": 0}]]},
    },
    "settings": {
        "executionOrder": "v1",
        "saveDataSuccessExecution": "all",
        "saveDataErrorExecution": "all",
        "saveManualExecutions": True,
    },
    "pinData": {},
}

OUT.write_text(json.dumps(workflow, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print("written", OUT, OUT.stat().st_size, "bytes;", len(DOCUMENTS), "documents injected")
