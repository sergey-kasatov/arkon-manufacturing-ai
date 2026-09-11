"""Capture the plant's own assistant in the cockpit, holding a real conversation.

The sibling of `tools/make_desk_screenshot.py`, and it exists for the same reason. The
README's picture of the assistant was this page before anyone had typed into it - a
heading, an info box and an empty input - under a caption describing the assistant
answering and handing the operator over. A picture of an input box proves that a page
loads, which is the one thing nobody doubted.

Same contract as the other two tools: a photograph of the running deployment, every
wait is on the page rather than on a timer, and a turn that does not come back, or
comes back as an error, ends the run with no picture written.

**Two turns, the ones the assistant was demonstrated with.** Ask what an open incident
is doing right now, which shows the handover - the answer ends with the link that opens
that incident on the Steering Cell page and a drafted note for the transition form -
and then tell it to acknowledge the incident and close it, which shows the boundary.

**The incident is chosen at run time.** The live plant's crew closes what it raised, so
a reference written into this file would be closed by the time anyone ran it: the
page's own suggestion still names ARK-INC-00012, which has since been marked a false
positive. The status API is asked for open incidents in its own priority order and the
first that is still `new` and overdue is taken, which is the state both turns act on.
The "You are" box is set to that incident's assignee, so the answer can say whose move
it is.

**It answers the approval gate with nothing at all.** An instruction to act is routed to
the human approval gate, and an Approve there writes a real line into the escalation
store. Reject turned out not to be the clean alternative it is drawn as: on 2026-09-11 an
earlier version of this script pressed Reject after each of two captures, and after the
second the Langflow message table shows the Escalation Specialist - the agent behind
Approve, and the one holding the escalation tool - answering 20 ms after the declined
answer (session `cockpit-readme-462af2b6`). It recorded nothing, and the escalation store
held 19 lines before and after both runs, but a Reject should never reach that agent at
all. So when the second turn stops at the gate, the picture is taken there and the run is
left paused, which is the one state in which nothing past the gate runs. It stays in
Langflow's pending list until somebody answers it.

Usage, from the repository root, with the cockpit and the assistant deployed:

    py tools/make_assistant_screenshot.py
    py tools/make_assistant_screenshot.py --reference ARK-INC-00014

The assistant runs on a course-issued OpenRouter key that ends in mid-September 2026.
After that the page still loads and a run returns no answer, so this script fails on
its own check rather than write a picture of an empty reply - which is the reason to
run it while the key is alive.
"""

import argparse
import json
import pathlib
import re
import sys
import urllib.request
import uuid

OUT = pathlib.Path(__file__).resolve().parent.parent / "assets" / "ui"
NAME = "assistant.png"

QUESTION = "What is {reference} doing right now?"
INSTRUCTION = "While you are there, acknowledge it and close it too."

# The page's own chat input, found by the placeholder app/pages/02_assistant.py gives it.
INPUT = 'textarea[placeholder="Ask about a rule, an incident, or request an escalation"]'
MESSAGES = '[data-testid="stChatMessage"]'

# What the page renders in place of an answer: the AssistantError text of
# app/utils/api.py, the page's own timeout and empty-run messages, and the incident
# specialist's fixed sentence for a failed lookup.
FAILURE = re.compile(r"HTTP \d{3} on |No Langflow API key|no job id in the answer|"
                     r"The run did not finish|produced no answer|The incident lookup failed")

# Where a turn is: "gate" when the run has paused for a decision, "done" when the input
# is enabled again with at least n messages on the page, otherwise false. The page
# disables its input for exactly as long as a run is in flight, which makes it the one
# signal that cannot drift with the wording of an answer.
STATE_JS = """(n) => {
  if (document.body.innerText.includes('paused at the approval gate')) return 'gate';
  const messages = [...document.querySelectorAll('%s')];
  if (messages.some(m => m.innerText.includes('running, poll'))) return false;
  const box = document.querySelector('%s');
  if (!box || box.disabled) return false;
  return messages.length >= n ? 'done' : false;
}""" % (MESSAGES, INPUT)

# How far the tallest scrolling element on the page overflows its box.
OVERFLOW_JS = """() => {
  let most = 0;
  for (const el of document.querySelectorAll('*')) {
    const y = getComputedStyle(el).overflowY;
    if (y === 'auto' || y === 'scroll') most = Math.max(most, el.scrollHeight - el.clientHeight);
  }
  return most;
}"""


def pick_incident(base, reference):
    """The named incident, or the first open one in the API's order that is new and overdue."""
    query = ("incident_id=%s" % reference) if reference else "status=open&sort=priority&limit=100"
    url = base.rstrip("/") + "/webhook/arkon-incident-status?" + query
    with urllib.request.urlopen(url, timeout=30) as response:
        incidents = json.load(response).get("incidents") or []
    if reference:
        if not incidents:
            sys.exit("the store holds no incident %s" % reference)
        if incidents[0].get("status") not in ("new", "acknowledged", "in_containment"):
            sys.exit("%s is %s, and an incident that is no longer open has nothing to hand over"
                     % (reference, incidents[0].get("status")))
        return incidents[0]
    for incident in incidents:
        if incident.get("status") == "new" and incident.get("overdue"):
            return incident
    if incidents:
        return incidents[0]
    sys.exit("the status API returned no open incidents, so there is nothing to ask about")


def wait_turn(page, n, timeout):
    """Wait for the page to settle, then read it once more a beat later.

    Streamlit ends a turn with one more rerun, so a state read in the middle of it can
    be a frame early; the second read is the settled page.
    """
    page.wait_for_function(STATE_JS, arg=n, timeout=timeout * 1000, polling=500)
    page.wait_for_timeout(1500)
    return page.wait_for_function(STATE_JS, arg=n, timeout=timeout * 1000,
                                  polling=500).json_value()


def ask(page, text):
    box = page.locator(INPUT)
    box.fill(text)
    box.press("Enter")


def last_reply(page):
    """The last message on the page and the links in it, with a rendered failure refused."""
    reply = page.locator(MESSAGES).last
    text = reply.inner_text()
    if FAILURE.search(text):
        sys.exit("the assistant returned an error into the page, so no picture was written: "
                 + " ".join(text.split())[:200])
    return text, reply.locator("a").evaluate_all("links => links.map(a => a.href)")


def choose_identity(page, name):
    """Set the sidebar's "You are" box to `name`, under whatever role the roster gives them."""
    box = page.locator('[data-testid="stSidebar"] [data-testid="stSelectbox"]').filter(
        has_text="You are").first
    box.locator('[data-baseweb="select"]').click()
    page.get_by_role("option", name=re.compile(r"^%s - " % re.escape(name))).first.click()
    page.wait_for_function(
        """(name) => [...document.querySelectorAll('[data-testid="stSidebar"] [data-testid="stSelectbox"]')]
             .some(e => e.innerText.includes(name + ' - '))""",
        arg=name, timeout=30000)


def fit_to_content(page, limit=3000):
    """Grow the viewport until nothing on the page scrolls.

    Streamlit scrolls its main column inside the page rather than scrolling the page,
    so `full_page=True` captures exactly one viewport and cuts a long answer off.
    Growing the window by the measured overflow puts the whole conversation, and a
    sidebar longer than the window, into one frame.
    """
    for _ in range(5):
        overflow = page.evaluate(OVERFLOW_JS)
        if overflow <= 1:
            return
        size = page.viewport_size
        if size["height"] >= limit:
            sys.exit("the conversation is taller than %d px, so no picture was written" % limit)
        page.set_viewport_size({"width": size["width"],
                                "height": min(limit, size["height"] + overflow)})
        page.wait_for_timeout(800)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cockpit", default="http://AK2101:8303", help="the running cockpit")
    parser.add_argument("--n8n", default="http://AK2101:5678",
                        help="the n8n origin serving the incident status API")
    parser.add_argument("--reference", default=None,
                        help="override the run-time pick with a specific open ARK-INC reference")
    parser.add_argument("--timeout", type=int, default=240,
                        help="seconds to wait for one turn; a model call behind a tool call is the slow part")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("playwright is not installed in this interpreter: py -m pip install playwright "
                 "&& py -m playwright install chromium")

    incident = pick_incident(args.n8n, args.reference)
    reference, assignee = incident["incident_id"], incident.get("assigned_to") or ""
    print("  reference %s (%s, %s%s), assigned to %s"
          % (reference, incident.get("priority"), incident.get("status"),
             ", overdue" if incident.get("overdue") else "", assignee or "nobody"))

    # A marked session id, so the conversation in the picture is the one the cockpit's
    # own "All conversations" list shows under the same name, and can be reopened there.
    session = "cockpit-readme-" + uuid.uuid4().hex[:8]
    url = "%s/assistant?session=%s" % (args.cockpit.rstrip("/"), session)
    link = "steering_cell?incident=" + reference
    OUT.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as play:
        browser = play.chromium.launch()
        context = browser.new_context(
            # 1500 wide, the width the cockpit tool shot this page at, so the sidebar
            # still ends at 0.200 of the picture and the social preview's crop stays true.
            viewport={"width": 1500, "height": 1000},
            device_scale_factor=2,
            color_scheme="light",
        )
        page = context.new_page()
        step = "loading the page"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.locator(INPUT).wait_for(timeout=60000)
            wait_turn(page, 0, 60)

            if assignee:
                step = "setting the You-are box to %s" % assignee
                choose_identity(page, assignee)
                wait_turn(page, 0, 60)

            step = "asking about %s" % reference
            ask(page, QUESTION.format(reference=reference))
            if wait_turn(page, 2, args.timeout) == "gate":
                sys.exit("a status question stopped at the approval gate, so no picture was "
                         "written; the run is left paused there, answered by nobody")
            text, links = last_reply(page)
            if reference not in text or not (link in text or any(link in h for h in links)):
                sys.exit("the answer did not hand over the link to %s, and the caption this "
                         "picture sits under says it does; no picture was written. It said: %s"
                         % (reference, " ".join(text.split())[:300]))
            print("  turn 1: %d characters, hands over %s" % (len(text), link))

            step = "telling it to acknowledge and close the incident"
            ask(page, INSTRUCTION)
            if wait_turn(page, 4, args.timeout) == "gate":
                print("  turn 2: stopped at the approval gate, left paused and answered by nobody")
            else:
                text, _ = last_reply(page)
                print("  turn 2: %d characters" % len(text))

            step = "writing the picture"
            fit_to_content(page)
            page.screenshot(path=str(OUT / NAME))
            print("  %-22s %s" % (NAME, url))
        except Exception as err:
            sys.exit("failed while %s: %s" % (step, str(err).splitlines()[0][:200]))
        finally:
            context.close()
            browser.close()

    print("session %s, wrote to %s" % (session, OUT))


if __name__ == "__main__":
    main()
