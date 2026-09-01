"""Build the n8n comparison slice: trigger, semantic routing, one retrieval, one HTTP call.

Deliberately small. It exists to make the platform comparison first-hand
rather than quoted: the same three capabilities the Langflow canvas uses, built
once on n8n, so the matrix can say what each platform costs from experience.

It is NOT a second Arkon assistant. It has no memory, no approval gate, no
sub-flow, no model-composed tool call, and one fixed HTTP request rather than an
agent holding a tool. Do not grow it.

Run it from the repository root:

    python n8n/build/build_comparison_slice.py
"""

import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
OUT = REPO / "n8n" / "comparison_slice_v1.json"

WORKFLOW_ID = "arkonSlice001"
WEBHOOK_PATH = "arkon-slice"
COLLECTION = "arkon-knowledge"
STATUS_API = "http://n8n.arkon.internal:5678/webhook/arkon-incident-status"
# The same model the Langflow canvas and the ingestion flow use, so the
# comparison is like for like.
CHAT_MODEL = "google/gemini-3.1-flash-lite"
# The collection was embedded through OpenRouter with google/gemini-embedding-001.
# n8n has no OpenRouter embedding node; this is the same model reached directly
# through Google AI Studio, which is a finding for the matrix rather than a
# workaround hidden in a config field.
EMBED_MODEL = "models/gemini-embedding-001"

# Credential ids read from the running instance. Names are kept beside them so a
# mismatch after a restore is visible rather than silent.
CRED_OPENROUTER = {"id": "oGwjduJ9ME1l2azw", "name": "OpenRouter account"}
CRED_GOOGLE = {"id": "GTyPBCXuMAicqhEB", "name": "Google Gemini(PaLM) Api account"}
CRED_QDRANT = {"id": "arkonQdrantLocal", "name": "Arkon Qdrant (local)"}

COLLECT_PASSAGES = """// Collapse the retrieved documents into one prompt context.
// The vector store in load mode emits one item per document, so a chain placed
// straight after it would run once per passage and answer four times. This node
// is what that difference costs; it has no counterpart on the Langflow canvas,
// where retrieval is a tool of one agent.
const question = $('Slice Request').first().json.body.message;
const passages = $input.all().map((item, index) => {
  const document = item.json.document ?? item.json;
  const text = document.pageContent ?? document.page_content ?? '';
  const source = document.metadata?.source ?? 'unknown source';
  return '[' + (index + 1) + '] (' + source + ')\\n' + text;
});
return [{ json: { question, context: passages.join('\\n\\n'), passage_count: passages.length } }];
"""

ANSWER_PROMPT = (
    "You answer questions about the Arkon quality process from the passages below "
    "and from nothing else.\n\n"
    "Rules:\n"
    "- If the passages do not settle the question, say so and name what is missing. "
    "Do not fill the gap from general quality-management knowledge.\n"
    "- Name the document each fact came from, using the source label in brackets.\n"
    "- Arkon's operational context is simulated; say so when it matters to the answer.\n\n"
    "Question: {{ $json.question }}\n\n"
    "Passages:\n{{ $json.context }}"
)

RESPOND_PROCEDURE = (
    "={{ JSON.stringify({route: \"quality_procedure\", answer: $json.text, "
    "passages: $('Collect Passages').first().json.passage_count}) }}"
)
RESPOND_STATUS = (
    "={{ JSON.stringify({route: \"incident_status\", upstream_code: $json.statusCode, "
    "store: $json.body?.store ?? null, "
    "message: $json.body?.message ?? \"the incident status API did not answer\"}) }}"
)
RESPOND_OTHER = (
    "={{ JSON.stringify({route: \"other\", answer: \"That is outside what this slice "
    "answers. It handles two things: how the Arkon quality process works, and what "
    "incidents are doing now.\"}) }}"
)


def node(index, name, type_name, version, position, parameters, **extra):
    entry = {
        "id": "b1000000-0000-4000-8000-%012d" % index,
        "name": name,
        "type": type_name,
        "typeVersion": version,
        "position": list(position),
        "parameters": parameters,
    }
    entry.update(extra)
    return entry


def build():
    nodes = [
        node(1, "Slice Request", "n8n-nodes-base.webhook", 2, (-1120, 300), {
            "httpMethod": "POST",
            "path": WEBHOOK_PATH,
            "responseMode": "responseNode",
            "options": {},
        }, webhookId=WEBHOOK_PATH),

        # The whole reason the slice exists. One node, one output branch per
        # category, an explicit Other branch: a Condition Agent equivalent,
        # which the published platform comparison says n8n does not have.
        node(2, "Route Intent", "@n8n/n8n-nodes-langchain.textClassifier", 1.1, (-880, 300), {
            "inputText": "={{ $json.body.message }}",
            "categories": {"categories": [
                {
                    "category": "Quality procedure",
                    "description": (
                        "How the Arkon quality process works: priority levels and their response "
                        "windows, the CMAPSS risk thresholds, who owns which incident, the "
                        "escalation policy, what the model is and how accurate it is."
                    ),
                },
                {
                    "category": "Incident status",
                    "description": (
                        "The current state of incidents in the Steering Cell store: how many are "
                        "open, at what priority, which are overdue, what one particular incident "
                        "is doing right now."
                    ),
                },
            ]},
            "options": {"fallback": "other"},
        }),

        node(3, "Router Model", "@n8n/n8n-nodes-langchain.lmChatOpenRouter", 1, (-880, 540), {
            "model": CHAT_MODEL, "options": {},
        }, credentials={"openRouterApi": CRED_OPENROUTER}),

        node(4, "Arkon Knowledge", "@n8n/n8n-nodes-langchain.vectorStoreQdrant", 1, (-600, 60), {
            "mode": "load",
            "qdrantCollection": {"__rl": True, "mode": "id", "value": COLLECTION},
            "prompt": "={{ $('Slice Request').item.json.body.message }}",
            "topK": 4,
            "includeDocumentMetadata": True,
            "options": {
                # The collection was written by Langflow, whose Qdrant component
                # stores the chunk text under page_content. n8n defaults to
                # "content" and would retrieve empty passages without failing.
                "contentPayloadKey": "page_content",
                "metadataPayloadKey": "metadata",
            },
        }, credentials={"qdrantApi": CRED_QDRANT}),

        node(5, "Query Embeddings", "@n8n/n8n-nodes-langchain.embeddingsGoogleGemini", 1, (-600, 300), {
            "modelName": EMBED_MODEL,
        }, credentials={"googlePalmApi": CRED_GOOGLE}),

        node(6, "Collect Passages", "n8n-nodes-base.code", 2, (-360, 60), {
            "jsCode": COLLECT_PASSAGES,
        }),

        node(7, "Answer From Documents", "@n8n/n8n-nodes-langchain.chainLlm", 1.9, (-120, 60), {
            "promptType": "define",
            "text": "=" + ANSWER_PROMPT,
        }),

        node(8, "Answer Model", "@n8n/n8n-nodes-langchain.lmChatOpenRouter", 1, (-120, 300), {
            "model": CHAT_MODEL, "options": {},
        }, credentials={"openRouterApi": CRED_OPENROUTER}),

        node(9, "Respond Procedure", "n8n-nodes-base.respondToWebhook", 1.1, (140, 60), {
            "respondWith": "json",
            "responseBody": RESPOND_PROCEDURE,
            "options": {},
        }),

        # One fixed call, not a tool the model composes. Langflow's API Request
        # in tool mode lets the agent write the URL; here the URL is on the
        # canvas, which is the safer default and the less capable one.
        node(10, "Incident Lookup", "n8n-nodes-base.httpRequest", 4.2, (-600, 540), {
            "url": STATUS_API,
            "options": {"response": {"response": {"neverError": True, "fullResponse": True}}},
        }),

        node(11, "Respond Status", "n8n-nodes-base.respondToWebhook", 1.1, (-360, 540), {
            "respondWith": "json",
            "responseBody": RESPOND_STATUS,
            "options": {},
        }),

        node(12, "Respond Other", "n8n-nodes-base.respondToWebhook", 1.1, (-600, 780), {
            "respondWith": "json",
            "responseBody": RESPOND_OTHER,
            "options": {},
        }),
    ]

    connections = {
        "Slice Request": {"main": [[{"node": "Route Intent", "type": "main", "index": 0}]]},
        "Route Intent": {"main": [
            [{"node": "Arkon Knowledge", "type": "main", "index": 0}],
            [{"node": "Incident Lookup", "type": "main", "index": 0}],
            [{"node": "Respond Other", "type": "main", "index": 0}],
        ]},
        "Router Model": {"ai_languageModel": [[{"node": "Route Intent", "type": "ai_languageModel", "index": 0}]]},
        "Query Embeddings": {"ai_embedding": [[{"node": "Arkon Knowledge", "type": "ai_embedding", "index": 0}]]},
        "Arkon Knowledge": {"main": [[{"node": "Collect Passages", "type": "main", "index": 0}]]},
        "Collect Passages": {"main": [[{"node": "Answer From Documents", "type": "main", "index": 0}]]},
        "Answer Model": {"ai_languageModel": [[{"node": "Answer From Documents", "type": "ai_languageModel", "index": 0}]]},
        "Answer From Documents": {"main": [[{"node": "Respond Procedure", "type": "main", "index": 0}]]},
        "Incident Lookup": {"main": [[{"node": "Respond Status", "type": "main", "index": 0}]]},
    }

    return {
        "id": WORKFLOW_ID,
        "name": "Arkon Comparison Slice v1",
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1"},
        "pinData": {},
    }


if __name__ == "__main__":
    flow = build()
    OUT.write_text(json.dumps(flow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote %s: %d nodes" % (OUT.name, len(flow["nodes"])))
