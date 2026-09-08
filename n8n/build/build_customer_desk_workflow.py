"""Build the Arkon Customer Quality Desk n8n workflow JSON.

The customer-facing agent of the MSIT course project 2A (2026-09-08), built
sprint by sprint on the platform the plant already runs on. This file is
regenerated at every sprint and the git history keeps each sprint's shape;
`customer_desk_prompt.py` carries the prompt version it runs on.

Sprint 1 shape: the chat trigger (a hosted page, public so the chat webhook
answers outside the editor, no authentication until the public route of
sprint 4 puts Basic Auth in front of it), the agent with the sprint 1 prompt,
the OpenRouter chat model, and the buffer window memory keyed by the chat
session with the course's window of six.

    POST /webhook/arkon-customer-desk/chat   {"action": "sendMessage", "sessionId": "...", "chatInput": "..."}
    GET  /webhook/arkon-customer-desk/chat   the hosted chat page

The response mode is `lastNode`: the agent's `{output}` is the reply, which
is what the validation runs read back.
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
    SYSTEM_MESSAGE,
    TEMPERATURE,
)

OUT = pathlib.Path(__file__).resolve().parent.parent / "customer_desk_v1.json"

WORKFLOW_ID = "arkonCustDesk02"
# The chat trigger's URL is /webhook/<webhookId>/chat.
CHAT_ID = "arkon-customer-desk"

OPENROUTER_CREDENTIAL = {"openRouterApi": {"id": "oGwjduJ9ME1l2azw", "name": "OpenRouter account"}}

workflow = {
    "id": WORKFLOW_ID,
    "name": "Arkon Customer Quality Desk v1 (sprint %d)" % SPRINT,
    "nodes": [
        {
            "id": "e1000000-0000-4000-8000-000000000001",
            "name": "Customer Chat",
            "type": "@n8n/n8n-nodes-langchain.chatTrigger",
            "typeVersion": 1.4,
            "position": [-880, 0],
            "webhookId": CHAT_ID,
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
            "position": [-640, 240],
            "parameters": {"model": MODEL, "options": {"temperature": TEMPERATURE}},
            "credentials": OPENROUTER_CREDENTIAL,
        },
        {
            "id": "e1000000-0000-4000-8000-000000000004",
            "name": "Session Memory",
            "type": "@n8n/n8n-nodes-langchain.memoryBufferWindow",
            "typeVersion": 1.4,
            "position": [-480, 240],
            "parameters": {
                "sessionIdType": "fromInput",
                "sessionKey": "={{ $json.sessionId }}",
                "contextWindowLength": MEMORY_WINDOW,
            },
        },
    ],
    "connections": {
        "Customer Chat": {"main": [[{"node": "Desk Agent", "type": "main", "index": 0}]]},
        "Desk Model": {"ai_languageModel": [[{"node": "Desk Agent", "type": "ai_languageModel", "index": 0}]]},
        "Session Memory": {"ai_memory": [[{"node": "Desk Agent", "type": "ai_memory", "index": 0}]]},
    },
    # Every conversation is kept: the validation runs are read back from the
    # execution list, and a chat desk does not produce the volume the status API
    # did.
    "settings": {
        "executionOrder": "v1",
        "saveDataSuccessExecution": "all",
        "saveDataErrorExecution": "all",
        "saveManualExecutions": True,
    },
    "pinData": {},
}

OUT.write_text(json.dumps(workflow, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print("written", OUT, OUT.stat().st_size, "bytes; sprint", SPRINT)
