"""Build the Arkon Customer Quality Desk n8n workflow JSON.

The customer-facing agent of the MSIT course project 2A (2026-09-08), built
sprint by sprint on the platform the plant already runs on. This file is
regenerated at every sprint and the git history keeps each sprint's shape;
`customer_desk_prompt.py` carries the prompt version it runs on.

Sprint 3 shape: the sprint 1 chat trigger, agent, model and memory, plus the
three tools and the sprint 3 prompt that tells the agent when to reach for
each.

    POST /webhook/arkon-customer-desk/chat   {"action": "sendMessage", "sessionId": "...", "chatInput": "..."}
    GET  /webhook/arkon-customer-desk/chat   the hosted chat page

    arkon_customer_documents   the Qdrant collection `arkon-customer-desk`, retrieve-as-tool
    Calculator                 arithmetic on numbers the customer supplied
    complaint_status_lookup    GET /webhook/arkon-customer-status?reference=

The tool names are the NODE names: at typeVersion 1.3 the Qdrant node dropped
its `toolName` field and the HTTP request tool never had one, so n8n derives
the name the model sees from the node name (`nodeNameToToolName`). The three
node names below are therefore the three names quoted in the prompt, and
`tests/test_customer_desk.py` pins them to each other.

The retriever tool reads `contentPayloadKey` `content`, which is what the
knowledge base's insert wrote. The comparison slice over `arkon-knowledge` uses
Langflow's `page_content` instead: copying that setting here retrieves empty
passages with no error at all.

The response mode is `lastNode`: the agent's `{output}` is the reply, which
is what the validation runs read back.

Two files come out of one run. The second is the tool-failure fixture: the same
desk with the status endpoint's existing `simulate_failure` affordance switched
on, so element 6 of the prompt - what the agent says when the lookup itself
fails - can be tested through the agent instead of asserted. It is a separate
workflow id and a separate chat path, so the shipped desk carries no failure
switch at all.
"""

import json
import pathlib

from customer_desk_prompt import (
    GREETING,
    INPUT_PLACEHOLDER,
    MAX_ITERATIONS,
    MEMORY_WINDOW,
    MODEL,
    PAGE_SUBTITLE,
    PAGE_TITLE,
    SPRINT,
    STATUS_PARAMETER,
    STATUS_PARAMETER_DESCRIPTION,
    STATUS_URL,
    SYSTEM_MESSAGE,
    TEMPERATURE,
    TOOL_CALCULATOR,
    TOOL_DOCUMENTS,
    TOOL_DOCUMENTS_DESCRIPTION,
    TOOL_STATUS,
    TOOL_STATUS_DESCRIPTION,
)
from customer_documents import COLLECTION, EMBEDDING_MODEL, TOP_K

N8N = pathlib.Path(__file__).resolve().parent.parent
OUT = N8N / "customer_desk_v1.json"
FAILTEST_OUT = N8N / "customer_desk_failtest_v1.json"

WORKFLOW_ID = "arkonCustDesk02"
# The chat trigger's URL is /webhook/<webhookId>/chat.
CHAT_ID = "arkon-customer-desk"
FAILTEST_ID = "arkonCustDesk03"
FAILTEST_CHAT_ID = "arkon-customer-desk-failtest"

OPENROUTER_CREDENTIAL = {"openRouterApi": {"id": "oGwjduJ9ME1l2azw", "name": "OpenRouter account"}}
QDRANT_CREDENTIAL = {"qdrantApi": {"id": "arkonQdrantLocal", "name": "Arkon Qdrant (local)"}}
GEMINI_CREDENTIAL = {"googlePalmApi": {"id": "GTyPBCXuMAicqhEB", "name": "Google Gemini(PaLM) Api account"}}


def status_query(simulate_failure):
    """The status tool's query parameters. The reference is filled by the model
    through `$fromAI`, which makes it a required argument of the generated tool
    schema: the course's "supplies all identifying information" condition is
    enforced by the tool and not by the prompt alone. The fixture adds the
    endpoint's failure affordance as a fixed value, which the model can neither
    see nor set."""
    parameters = [
        {
            "name": STATUS_PARAMETER,
            "value": "={{ $fromAI('%s', '%s', 'string') }}"
            % (STATUS_PARAMETER, STATUS_PARAMETER_DESCRIPTION.replace("'", "")),
        }
    ]
    if simulate_failure:
        parameters.append({"name": "simulate_failure", "value": "true"})
    return {"parameters": parameters}


def build(workflow_id, chat_id, simulate_failure=False):
    return {
        "id": workflow_id,
        "name": "Arkon Customer Quality Desk v1 (sprint %d)%s"
        % (SPRINT, " - tool-failure fixture" if simulate_failure else ""),
        "nodes": [
            {
                "id": "e1000000-0000-4000-8000-000000000001",
                "name": "Customer Chat",
                "type": "@n8n/n8n-nodes-langchain.chatTrigger",
                "typeVersion": 1.4,
                "position": [-880, 0],
                "webhookId": chat_id,
                "parameters": {
                    "public": True,
                    "mode": "hostedChat",
                    "authentication": "none",
                    "initialMessages": GREETING,
                    "options": {
                        "title": PAGE_TITLE,
                        "subtitle": PAGE_SUBTITLE,
                        "inputPlaceholder": INPUT_PLACEHOLDER,
                        "allowedOrigins": "*",
                        "loadPreviousSession": "notSupported",
                        "showWelcomeScreen": False,
                        "responseMode": "lastNode",
                    },
                },
            },
            {
                "id": "e1000000-0000-4000-8000-000000000002",
                "name": "Desk Agent",
                "type": "@n8n/n8n-nodes-langchain.agent",
                "typeVersion": 3.1,
                "position": [-560, 0],
                "parameters": {
                    "promptType": "define",
                    "text": "={{ $json.chatInput }}",
                    "options": {"systemMessage": SYSTEM_MESSAGE, "maxIterations": MAX_ITERATIONS},
                },
            },
            {
                "id": "e1000000-0000-4000-8000-000000000003",
                "name": "Desk Model",
                "type": "@n8n/n8n-nodes-langchain.lmChatOpenRouter",
                "typeVersion": 1,
                "position": [-880, 240],
                "parameters": {"model": MODEL, "options": {"temperature": TEMPERATURE}},
                "credentials": OPENROUTER_CREDENTIAL,
            },
            {
                "id": "e1000000-0000-4000-8000-000000000004",
                "name": "Session Memory",
                "type": "@n8n/n8n-nodes-langchain.memoryBufferWindow",
                "typeVersion": 1.4,
                "position": [-720, 240],
                "parameters": {
                    "sessionIdType": "fromInput",
                    "sessionKey": "={{ $json.sessionId }}",
                    "contextWindowLength": MEMORY_WINDOW,
                },
            },
            # -- the three tools ------------------------------------------------
            # Named exactly as the model sees them, because the node name IS the
            # tool name at these type versions.
            {
                "id": "e1000000-0000-4000-8000-000000000005",
                "name": TOOL_DOCUMENTS,
                "type": "@n8n/n8n-nodes-langchain.vectorStoreQdrant",
                "typeVersion": 1.3,
                "position": [-560, 240],
                "parameters": {
                    "mode": "retrieve-as-tool",
                    "toolDescription": TOOL_DOCUMENTS_DESCRIPTION,
                    "qdrantCollection": {"__rl": True, "mode": "id", "value": COLLECTION},
                    "topK": TOP_K,
                    "includeDocumentMetadata": True,
                    # `content` is the key the knowledge base's insert wrote. The
                    # comparison slice's `page_content` returns empty passages here.
                    "options": {"contentPayloadKey": "content", "metadataPayloadKey": "metadata"},
                },
                "credentials": QDRANT_CREDENTIAL,
            },
            {
                "id": "e1000000-0000-4000-8000-000000000006",
                "name": "Desk Query Embeddings",
                "type": "@n8n/n8n-nodes-langchain.embeddingsGoogleGemini",
                "typeVersion": 1,
                "position": [-560, 448],
                "parameters": {"modelName": EMBEDDING_MODEL},
                "credentials": GEMINI_CREDENTIAL,
            },
            {
                "id": "e1000000-0000-4000-8000-000000000007",
                "name": TOOL_CALCULATOR,
                "type": "@n8n/n8n-nodes-langchain.toolCalculator",
                "typeVersion": 1,
                "position": [-400, 240],
                "parameters": {},
            },
            {
                "id": "e1000000-0000-4000-8000-000000000008",
                "name": TOOL_STATUS,
                # The base HTTP Request node used as a tool, NOT the langchain
                # `toolHttpRequest`: that one is `hidden: true` in n8n 2.29 and
                # carries no `execute` method, so the execution engine refuses it
                # with "has a supplyData method but no execute method" the moment
                # the agent calls it, and the agent reports a tool failure the
                # customer would read as an outage. Measured 2026-09-08.
                "type": "n8n-nodes-base.httpRequestTool",
                "typeVersion": 4.4,
                "position": [-240, 240],
                "parameters": {
                    "toolDescription": TOOL_STATUS_DESCRIPTION,
                    "method": "GET",
                    # n8n calls its own webhook from inside the container.
                    "url": STATUS_URL,
                    "sendQuery": True,
                    "specifyQuery": "keypair",
                    "queryParameters": status_query(simulate_failure),
                    # All four answers of the endpoint have to reach the model as
                    # data: found, no match, a rejected reference and the 503 are
                    # four different things to say, and an exception is only one.
                    "options": {"response": {"response": {"neverError": True}}},
                },
            },
        ],
        "connections": {
            "Customer Chat": {"main": [[{"node": "Desk Agent", "type": "main", "index": 0}]]},
            "Desk Model": {"ai_languageModel": [[{"node": "Desk Agent", "type": "ai_languageModel", "index": 0}]]},
            "Session Memory": {"ai_memory": [[{"node": "Desk Agent", "type": "ai_memory", "index": 0}]]},
            TOOL_DOCUMENTS: {"ai_tool": [[{"node": "Desk Agent", "type": "ai_tool", "index": 0}]]},
            "Desk Query Embeddings": {
                "ai_embedding": [[{"node": TOOL_DOCUMENTS, "type": "ai_embedding", "index": 0}]]
            },
            TOOL_CALCULATOR: {"ai_tool": [[{"node": "Desk Agent", "type": "ai_tool", "index": 0}]]},
            TOOL_STATUS: {"ai_tool": [[{"node": "Desk Agent", "type": "ai_tool", "index": 0}]]},
        },
        # Every conversation is kept: the validation runs are read back from the
        # execution list, and a chat desk does not produce the volume the status
        # API did.
        "settings": {
            "executionOrder": "v1",
            "saveDataSuccessExecution": "all",
            "saveDataErrorExecution": "all",
            "saveManualExecutions": True,
        },
        "pinData": {},
    }


for path, workflow in (
    (OUT, build(WORKFLOW_ID, CHAT_ID)),
    (FAILTEST_OUT, build(FAILTEST_ID, FAILTEST_CHAT_ID, simulate_failure=True)),
):
    path.write_text(json.dumps(workflow, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print("written", path.name, path.stat().st_size, "bytes; sprint", SPRINT, "with", len(workflow["nodes"]), "nodes")
