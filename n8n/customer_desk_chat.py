"""Send a scripted conversation through the Customer Quality Desk's chat webhook.

The validation runs of the desk are conversations whose expectations are
written before the run; this sends the turns of one such conversation in one
chat session and prints the transcript as returned, unedited, so it can be
pasted into the run log beside the expectations. Stdlib only.

    python n8n/customer_desk_chat.py --session desk-sprint1-a --turn "Hello, ..." --turn "..."
    python n8n/customer_desk_chat.py --session desk-sprint1-a --turns-file turns.json
    python n8n/customer_desk_chat.py --n8n http://AK2101:5678 --session desk-sprint1-b --turn "Which reference did I give you?"

A turns file is a JSON list of strings. The session id is the memory key: a
new id is a customer with no history, the same id continues one.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

CHAT = "/webhook/arkon-customer-desk/chat"


def send(n8n, session, text, timeout=180):
    body = json.dumps({"action": "sendMessage", "sessionId": session, "chatInput": text}).encode("utf-8")
    req = urllib.request.Request(n8n + CHAT, data=body, method="POST", headers={"Content-Type": "application/json"})
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            status = response.status
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8")
        status = error.code
    seconds = time.time() - started
    try:
        answer = json.loads(raw)
    except ValueError:
        answer = {"raw": raw}
    text_out = answer.get("output") if isinstance(answer, dict) else None
    return status, text_out if isinstance(text_out, str) else json.dumps(answer), seconds


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n8n", default="http://AK2101:5678")
    parser.add_argument("--session", required=True, help="the chat session id, the memory key")
    parser.add_argument("--turn", action="append", default=[], help="a message to send, in order; repeatable")
    parser.add_argument("--turns-file", default=None, help="a JSON list of messages")
    args = parser.parse_args()

    turns = list(args.turn)
    if args.turns_file:
        with open(args.turns_file, encoding="utf-8") as handle:
            turns.extend(json.load(handle))
    if not turns:
        sys.exit("nothing to send: pass --turn or --turns-file")

    print("session `%s` through %s%s, %d turns\n" % (args.session, args.n8n, CHAT, len(turns)))
    for number, text in enumerate(turns, 1):
        status, answer, seconds = send(args.n8n, args.session, text)
        print("### Turn %d (%s, %.1f s)\n\n**Sent:** %s\n\n**Answer:** %s\n" % (number, status, seconds, text, answer))
        sys.stdout.flush()


if __name__ == "__main__":
    main()
