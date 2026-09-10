"""Capture the deployed Customer Quality Desk answering a live quality notice.

The sibling of `tools/make_ui_screenshots.py`, and it exists for the same reason:
a README that describes an operational surface and shows none of it asks the
reader to take its word for the thing that is easiest to prove. The desk was the
one surface with no picture anywhere in this repository, which is a poor showing
for the agent the customer actually talks to.

Same contract as the cockpit tool: a photograph of a running system, the wait is
on content rather than on a timer, and a page that does not render fails loudly
instead of quietly producing a pretty picture.

Two things are different, and both are deliberate.

**The reference is chosen at run time, never hard-coded.** The live plant keeps
moving, so a notice that is open today is closed tomorrow: on 2026-09-10 the
reference printed on a submitted presentation had closed at 09:08 the same
morning, and a screenshot of "Closed, stage 5, no next step" is the weakest
possible picture of a process. This script reads the open incidents from the
status API and picks one that is mid-process, so the picture always shows a
stage, a next step and a committed date.

**The password comes from the environment and from nowhere else.** No default, no
prompt, no file: `ARKON_DESK_PASSWORD`, exactly as `n8n/customer_desk_validation.py`
takes it, because no credential of any deployment belongs in this repository.

It goes into the page's own login form, and that is the only route there is. Two
things were tried first and both are closed, which is worth writing down because
they look like they should work. n8n serves a webhook's HTML with
`Content-Security-Policy: sandbox ...` and **without `allow-same-origin`**, so
`sessionStorage` throws for every visitor, not just for automation - the page's
own reader is wrapped in a `try` for exactly that reason, and the practical
consequence is that the desk asks for its login on every single load. And the
chat POST is sent with `credentials: "omit"` behind an `if (!auth) return`
guard, so the browser's own Basic Auth handling never gets a request to attach
itself to. Filling `#user` and `#pw` and submitting is therefore not a shortcut
around the page, it is the page.

Usage, from the repository root, with the desk deployed:

    set ARKON_DESK_PASSWORD=...          (PowerShell: $env:ARKON_DESK_PASSWORD="...")
    py tools/make_desk_screenshot.py
    py tools/make_desk_screenshot.py --base https://ugreen-nas.tail90586f.ts.net:8443

Note that the demo runs on a course-issued OpenRouter key that ends in
mid-September 2026. After that the page still loads and the agent answers
nothing, so this script will fail on its own wait rather than write a picture of
an empty reply - which is the correct behaviour, and the reason to run it while
the key is alive.
"""

import argparse
import json
import os
import pathlib
import sys
import urllib.request

OUT = pathlib.Path(__file__).resolve().parent.parent / "assets" / "ui"
NAME = "customer_desk.png"

# A mid-process notice makes the picture: it carries a stage, a next step and a
# date Arkon has committed to. `new` would show stage 1 with nothing decided yet.
PREFERRED_STATES = ("in_containment", "acknowledged", "resolved")

QUESTION = (
    "What is the status of quality notice {reference}, and what happens next?"
)


def pick_reference(base, timeout):
    """Read the open incidents and return a mid-process reference, or any open one."""
    url = base.rstrip("/") + "/webhook/arkon-incident-status?status=open&sort=priority&limit=25"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        payload = json.load(response)
    incidents = payload.get("incidents") or payload.get("matches") or []
    if not incidents:
        sys.exit("the status API returned no open incidents, so there is nothing to ask about")
    for state in PREFERRED_STATES:
        for incident in incidents:
            if incident.get("status") == state:
                return incident["incident_id"], state
    first = incidents[0]
    return first["incident_id"], first.get("status", "unknown")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://AK2101:5678",
                        help="the n8n origin serving the desk")
    parser.add_argument("--user", default="arkon")
    parser.add_argument("--reference", default=None,
                        help="override the run-time pick with a specific ARK-INC reference")
    parser.add_argument("--timeout", type=int, default=90,
                        help="seconds to wait for the agent's reply; the model call is the slow part")
    args = parser.parse_args()

    password = os.environ.get("ARKON_DESK_PASSWORD")
    if not password:
        sys.exit("ARKON_DESK_PASSWORD is not set. This script takes the desk password from the "
                 "environment and from nowhere else; no credential of any deployment is in this "
                 "repository.")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("playwright is not installed in this interpreter: py -m pip install playwright "
                 "&& py -m playwright install chromium")

    reference, state = args.reference, "given on the command line"
    if reference is None:
        reference, state = pick_reference(args.base, args.timeout)
    print("  reference %s (%s)" % (reference, state))

    OUT.mkdir(parents=True, exist_ok=True)
    url = args.base.rstrip("/") + "/webhook/arkon-desk"
    question = QUESTION.format(reference=reference)

    with sync_playwright() as play:
        browser = play.chromium.launch()
        context = browser.new_context(
            # Short enough that a two-turn exchange fills the frame: the log area
            # grows to the viewport, so a tall shot of a short conversation is mostly
            # empty background. Measured on a probe run before this was set.
            viewport={"width": 1200, "height": 780},
            device_scale_factor=2,
            color_scheme="light",
        )
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)

            # The desk asks for its login on every load (see the sandbox note above),
            # so this is the page's normal path rather than a way around it.
            page.wait_for_selector("#pw", timeout=30000)
            page.fill("#user", args.user)
            page.fill("#pw", password)
            page.click("#signin")
            # The form hides itself and enables Send only when it has accepted both
            # fields; waiting on that is waiting on the page rather than on a timer.
            page.wait_for_selector("#login[hidden]", timeout=15000)

            # The page opens with one `.msg.desk` bubble, its welcome line.
            before = page.locator(".msg.desk").count()

            page.fill("#input", question)
            page.click("#send")

            # Wait for a NEW desk bubble rather than for a word in it: the reply is a
            # model call behind a retriever and a status lookup, so it is slower than any
            # fixed beat, and matching on wording would make the picture depend on a
            # phrasing the prompt is free to change. Counting bubbles cannot drift.
            page.wait_for_function(
                "n => document.querySelectorAll('.msg.desk').length > n",
                arg=before,
                timeout=args.timeout * 1000,
            )
            reply = page.locator(".msg.desk").last.inner_text()
            if "did not answer" in reply or "HTTP " in reply:
                sys.exit("the desk returned an error into the page, so no picture was written: "
                         + reply.strip()[:200])
            print("  replied with %d characters" % len(reply))
            page.wait_for_timeout(1200)

            page.screenshot(path=str(OUT / NAME), full_page=True)
            print("  %-22s %s" % (NAME, url))
        except Exception as err:
            sys.exit("the desk did not answer, and no picture was written: %s"
                     % str(err).splitlines()[0][:200])
        finally:
            context.close()
            browser.close()

    print("wrote to %s" % OUT)


if __name__ == "__main__":
    main()
