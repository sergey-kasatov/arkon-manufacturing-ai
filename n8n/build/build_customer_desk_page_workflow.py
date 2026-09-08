"""Build the Arkon Customer Quality Desk's page: one GET webhook that serves the chat page.

The public route of the desk (course project 2A, sprint 4) is Tailscale Funnel
on port 8443 mounting exactly two paths: this page and the desk's chat webhook.
n8n's own hosted chat page cannot be that page, because it embeds the
instance's `WEBHOOK_URL` as an absolute address, which is the tailnet name and
not the public one. This page builds the chat address from its own origin
(`location.origin + "/webhook/arkon-customer-desk/chat"`), so it works on the
LAN, on the tailnet and through the Funnel without knowing which one it is on.

    GET /webhook/arkon-desk      the page, Basic Auth (the same credential as the chat)

Both webhooks sit under `/webhook/` on the same origin and use the same
credential, so a browser that authenticated for the page reuses the header for
the chat POST (RFC 7617 protection space); measured through the Funnel on
2026-09-08. The page is served by the platform itself, so no second server and
no second certificate exist to keep alive.
"""

import json
import pathlib

from customer_desk_prompt import GREETING, INPUT_PLACEHOLDER, PAGE_SUBTITLE, PAGE_TITLE

OUT = pathlib.Path(__file__).resolve().parent.parent / "customer_desk_page_v1.json"

WORKFLOW_ID = "arkonCustDeskPg1"
PAGE_PATH = "arkon-desk"
CHAT_PATH = "/webhook/arkon-customer-desk/chat"

BASIC_AUTH_CREDENTIAL = {"httpBasicAuth": {"id": "arkonDeskBasic1", "name": "Arkon Customer Desk (basic auth)"}}

# Placeholders are replaced with str.replace, not % formatting: the page carries
# CSS percentages and JavaScript template braces of its own.
PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root { color-scheme: light; }
  body { margin: 0; background: #f2f4f8; color: #101330; font: 15px/1.5 -apple-system, "Segoe UI", Roboto, sans-serif; }
  header { background: #101330; color: #f2f4f8; padding: 14px 20px; }
  header h1 { margin: 0; font-size: 18px; }
  header p { margin: 4px 0 0; font-size: 13px; opacity: .8; }
  main { max-width: 760px; margin: 0 auto; padding: 16px; }
  #log { display: flex; flex-direction: column; gap: 10px; min-height: 50vh; }
  .msg { max-width: 82%; padding: 10px 14px; border-radius: 8px; white-space: pre-wrap; word-wrap: break-word; }
  .desk { background: #fff; align-self: flex-start; border: 1px solid #e6e9f1; }
  .you { background: #20b69e; color: #fff; align-self: flex-end; }
  .meta { font-size: 12px; color: #667; margin-top: 12px; }
  form { display: flex; gap: 8px; margin-top: 14px; }
  textarea { flex: 1; min-height: 52px; padding: 10px; border: 1px solid #c2c5cc; border-radius: 6px; font: inherit; resize: vertical; }
  button { padding: 0 18px; border: 0; border-radius: 6px; background: #20b69e; color: #fff; font: inherit; cursor: pointer; }
  button[disabled] { background: #81bbb1; cursor: default; }
</style>
</head>
<body>
<header>
  <h1>__TITLE__</h1>
  <p>__SUBTITLE__</p>
</header>
<main>
  <div id="log"></div>
  <form id="form">
    <textarea id="input" placeholder="__PLACEHOLDER__" required></textarea>
    <button id="send" type="submit">Send</button>
  </form>
  <p class="meta">Session <code id="session"></code>. The desk keeps this conversation for this session only. Arkon Manufacturing is a fictional company; this is a simulated quality process.</p>
</main>
<script>
  // The chat address is this page's own origin plus the desk's chat path, so
  // the same page works on the LAN, on the tailnet and through the Funnel.
  var CHAT = location.origin + "__CHAT_PATH__";
  var session = "desk-" + Math.random().toString(36).slice(2, 10) + "-" + Date.now().toString(36);
  var log = document.getElementById("log");
  var form = document.getElementById("form");
  var input = document.getElementById("input");
  var send = document.getElementById("send");
  document.getElementById("session").textContent = session;

  function show(text, who) {
    var node = document.createElement("div");
    node.className = "msg " + who;
    node.textContent = text;
    log.appendChild(node);
    node.scrollIntoView({ block: "end" });
  }

  show("__GREETING__", "desk");

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var text = input.value.trim();
    if (!text) { return; }
    show(text, "you");
    input.value = "";
    send.disabled = true;
    fetch(CHAT, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "sendMessage", sessionId: session, chatInput: text })
    }).then(function (response) {
      if (!response.ok) { throw new Error("HTTP " + response.status); }
      return response.json();
    }).then(function (answer) {
      show(typeof answer.output === "string" ? answer.output : JSON.stringify(answer), "desk");
    }).catch(function (error) {
      show("The desk did not answer (" + error.message + "). Please try again, or write to the Arkon Customer Quality Contact.", "desk");
    }).then(function () {
      send.disabled = false;
      input.focus();
    });
  });

  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
</script>
</body>
</html>
"""

html = (
    PAGE_HTML.replace("__TITLE__", PAGE_TITLE)
    .replace("__SUBTITLE__", PAGE_SUBTITLE)
    .replace("__PLACEHOLDER__", INPUT_PLACEHOLDER)
    .replace("__CHAT_PATH__", CHAT_PATH)
    .replace("__GREETING__", GREETING)
)

workflow = {
    "id": WORKFLOW_ID,
    "name": "Arkon Customer Quality Desk page v1",
    "nodes": [
        {
            "id": "f1000000-0000-4000-8000-000000000001",
            "name": "Desk Page Request",
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2,
            "position": [-880, 0],
            "webhookId": PAGE_PATH,
            "parameters": {
                "httpMethod": "GET",
                "path": PAGE_PATH,
                "authentication": "basicAuth",
                "responseMode": "responseNode",
                "options": {},
            },
            "credentials": BASIC_AUTH_CREDENTIAL,
        },
        {
            "id": "f1000000-0000-4000-8000-000000000002",
            "name": "Serve Desk Page",
            "type": "n8n-nodes-base.respondToWebhook",
            "typeVersion": 1.1,
            "position": [-656, 0],
            "parameters": {
                "respondWith": "text",
                "responseBody": html,
                "options": {
                    "responseHeaders": {
                        "entries": [
                            {"name": "Content-Type", "value": "text/html; charset=utf-8"},
                            {"name": "Cache-Control", "value": "no-store"},
                        ]
                    }
                },
            },
        },
    ],
    "connections": {
        "Desk Page Request": {"main": [[{"node": "Serve Desk Page", "type": "main", "index": 0}]]},
    },
    "settings": {"executionOrder": "v1", "saveDataSuccessExecution": "none", "saveDataErrorExecution": "all"},
    "pinData": {},
}

OUT.write_text(json.dumps(workflow, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print("written", OUT.name, OUT.stat().st_size, "bytes;", len(html), "characters of page")
